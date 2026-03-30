"""
Simplified Trajectory Sampler for RAG synthesis

使用原生 MCP Resources + Tools 架构
与金融研投助手 MCP Server 保持完全一致
"""

import json
import hashlib
from typing import Dict, List, Optional, Any
import uuid
import bdb
import asyncio
from sandbox import format_tool_result
from .models import TrajectoryNode
from .config import SynthesisConfig
from .worker import SandboxWorker
from .utils import create_openai_client, parse_action_xml, async_chat_completion

from sandbox.tool_schemas import get_tool_schemas


class TrajectorySampler:
    """Samples trajectory trees by exploring with LLM + native MCP tools"""

    def __init__(self, worker: SandboxWorker, config: SynthesisConfig):
        """Initialize sampler"""
        self.worker = worker
        self.config = config

        # Initialize OpenAI client
        self.client = create_openai_client(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
        )

        # Tree storage
        self.nodes: Dict[str, TrajectoryNode] = {}
        self.root_id: Optional[str] = None

        # Available tools (will be populated after worker starts)
        self.available_tools: List[Dict[str, Any]] = []

        # Per-seed action de-duplication
        self._seed_used_action_signatures: set = set()
        self._seed_used_action_signatures_ordered: List[str] = []

    def _generate_node_id(self) -> str:
        """Generate unique node ID"""
        return f"node_{uuid.uuid4().hex[:8]}"

    async def sample_trajectory_tree(
        self,
        seed_data: str,
        seed_kwargs: Optional[Dict[str, Any]] = None
    ) -> Dict[str, TrajectoryNode]:
        """Sample a trajectory tree starting from seed data (async)"""
        if seed_kwargs is None:
            seed_kwargs = {}

        print(f"\n{'='*60}")
        print(f"Starting Trajectory Sampling")
        print(f"Seed: {seed_data[:100]}...")
        if seed_kwargs:
            print(f"Kwargs: {seed_kwargs}")
        print(f"{'='*60}\n")

        # Reset tree
        self.nodes = {}
        self.root_id = None
        self._seed_used_action_signatures.clear()
        self._seed_used_action_signatures_ordered.clear()

        # Store kwargs for use in action execution
        self.seed_kwargs = seed_kwargs

        # 提取工具执行用的 kwargs（排除 tags）
        self._execution_kwargs = {k: v for k, v in seed_kwargs.items() if k != "tags"}

        # Helper function to extract tool name from OpenAI format
        def _get_tool_name(t):
            if isinstance(t, dict):
                if 'function' in t and isinstance(t['function'], dict):
                    return t['function'].get('name', 'unknown')
                return t.get('name', 'unknown')
            return 'unknown'

        # ========== Server 健康检查和工具验证 ==========
        print("🔍 Checking server health and available tools...")
        try:
            # 从 Server 获取实际注册的工具列表
            server_tools = await self.worker.sandbox.client.list_tools(include_hidden=False)
            print(f"   Server returned {len(server_tools)} tools")
            
            if not server_tools:
                raise RuntimeError("Server 工具列表为空，请检查 Backend 是否加载成功")
            
            # 打印 Server 工具列表用于调试
            server_tool_names = []
            for t in server_tools:
                if isinstance(t, dict):
                    # 支持 OpenAI 格式: {"type": "function", "function": {"name": ...}}
                    if 'function' in t:
                        name = t['function'].get('name', 'unknown')
                    else:
                        name = t.get('full_name') or t.get('name') or 'unknown'
                    server_tool_names.append(name)
            print(f"   Server tools: {server_tool_names[:10]}...")  # 只打印前10个
            
        except Exception as e:
            print(f"   ⚠️ Warning: Failed to get tools from server: {e}")
            print("   Continuing with local tool schemas...")
            server_tools = []
        
        # Load tool schemas from local tools module
        # 优先使用配置中指定的工具过滤，如果没有则使用所有工具
        local_tools = get_tool_schemas(
            self.config.available_tools if self.config.available_tools else None
        )
        
        # 优先使用 Server 的工具列表（如果可用）
        if server_tools:
            print("   Using server tool schemas...")
            # 转换 Server 工具格式为 OpenAI 格式
            self.available_tools = []
            for t in server_tools:
                if isinstance(t, dict):
                    tool_name = t.get('full_name') or t.get('name')
                    tool_desc = t.get('description', '')
                    if tool_name:
                        self.available_tools.append({
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "description": tool_desc,
                                "parameters": {"type": "object", "properties": {}}
                            }
                        })
        elif local_tools:
            self.available_tools = local_tools
        else:
            self.available_tools = []
        
        # 最终验证
        if not self.available_tools:
            raise RuntimeError("❌ 没有可用的工具！请检查：\n" +
                             "1. Server 是否正常运行\n" +
                             "2. Backend 是否已加载\n" +
                             "3. tool_schemas 配置是否正确")
        
        tool_names = [_get_tool_name(t) for t in self.available_tools]
        print(f"✅ Final available tools ({len(self.available_tools)}): {tool_names}")

        # Create root node
        root_id = self._generate_node_id()
        root_node = TrajectoryNode(
            node_id=root_id,
            observation=f"Starting point: {seed_data}",
            intent="Initialize exploration",
            action=None,
            parent_id=None,
            children_ids=[],
            depth=0
        )
        self.nodes[root_id] = root_node
        self.root_id = root_id

        # Explore tree asynchronously
        await self._explore_node(root_node, seed_data)

        print(f"\n✅ Sampling complete. Total nodes: {len(self.nodes)}")
        return self.nodes

    async def _explore_node(self, node: TrajectoryNode, seed_data: str):
        """Explore from a node (async breadth-first for siblings)"""
        print(f"  [DEBUG] _explore_node called: node_id={node.node_id}, depth={node.depth}, max_depth={self.config.max_depth}")
        if node.depth >= self.config.max_depth:
            print(f"  [DEBUG] Reached max_depth, stopping exploration")
            return

        # Determine how many children to create
        num_children = self.config.branching_factor if node.depth < self.config.depth_threshold else 1
        print(f"  [DEBUG] Creating {num_children} children for node {node.node_id}")

        # Create tasks for all children at this level
        child_tasks = []
        for i in range(num_children):
            child_tasks.append(self._create_and_explore_child(node, seed_data))

        # Execute all children concurrently
        results = await asyncio.gather(*child_tasks, return_exceptions=True)
        print(f"  [DEBUG] Child tasks completed for node {node.node_id}: {results}")

    async def _create_and_explore_child(self, parent_node: TrajectoryNode, seed_data: str):
        """Create and explore a single child node"""
        max_retries = 3
        retry_wait = 0.5
        intent = ""
        action: Optional[Dict[str, Any]] = None
        observation = ""
        for attempt in range(max_retries + 1):
            try:
                # Generate next action
                print(f"  [DEBUG] _generate_next_action for parent {parent_node.node_id}, last_tool={parent_node.action.get('tool_name') if parent_node.action else 'None'}")
                intent, action = await self._generate_next_action(parent_node, seed_data)
                print(f"  [DEBUG] Generated intent={intent[:50] if intent else 'None'}..., action={action}")
                if not action:
                    print(f"  [DEBUG] No action generated, returning")
                    return

                # Execute action asynchronously
                observation = await self._execute_action(action)
                break
            except Exception as e:
                print(f"  [DEBUG] Exception in _create_and_explore_child: {e}")
                if attempt >= max_retries:
                    print(f"  ⚠️ Error exploring node: {e}")
                    return
                await asyncio.sleep(retry_wait * (2 ** attempt))

        # Create child node
        child_id = self._generate_node_id()
        child_node = TrajectoryNode(
            node_id=child_id,
            observation=observation,
            intent=intent,
            action=action,
            parent_id=parent_node.node_id,
            children_ids=[],
            depth=parent_node.depth + 1
        )

        self.nodes[child_id] = child_node
        parent_node.children_ids.append(child_id)

        node_index = len(self.nodes)
        action_data = action or {}
        print(
            f"\033[36m[#={node_index} Id={child_node.node_id} Depth={child_node.depth} "
            f"\033[33m{action_data.get('tool_name', 'unknown')}\033[36m]\033[0m:\n"
            f"{intent}"
        )
        print(f"\033[36m[params]:\n\033[0m {json.dumps(action_data.get('parameters', {}), ensure_ascii=False)}")
        preview = observation[:1000] + "...\n\n" if len(observation) > 1000 else observation
        print(f"\033[36m[output]:\n\033[0m {preview}")

        # Recursively explore this child
        await self._explore_node(child_node, seed_data)
        return

    async def _generate_next_action(self, node: TrajectoryNode, seed_data: str) -> tuple[str, Optional[Dict[str, Any]]]:
        """Generate next action using LLM - 与金融研投助手一致的3轮流程"""
        # Build context
        context = self._build_context(node, seed_data)
        
        # 检查当前处于哪一轮
        last_action = None
        current = node
        while current.parent_id:
            if current.action:
                last_action = current.action
                break
            current = self.nodes[current.parent_id]
        
        last_tool_name = last_action.get('tool_name', '') if last_action else ''
        
        try:
            # ========== Round 1: Skill选择 ==========
            if not last_action or last_tool_name == '':
                return await self._round1_select_skill(context, seed_data)
            
            # ========== Round 2: 执行skill后，获取工具列表并调用具体工具 ==========
            # 支持带前缀的 skill 工具名 (如 finance_research:skill)
            if last_tool_name in ('skill', 'finance_research:skill') or last_tool_name.endswith(':skill'):
                # 获取上一轮的skill名称
                skill_name = last_action.get('parameters', {}).get('name', '')
                if skill_name:
                    return await self._round2_call_tool(context, seed_data, skill_name)

            # 如果已经有工具调用历史，继续调用工具（可循环）
            # 支持带前缀的工具名 (如 finance_research:market_data.get_quote)
            if '.' in last_tool_name and not last_tool_name.endswith(':skill'):
                # 继续同一skill的其他工具调用
                # 处理带前缀的情况: finance_research:market_data.get_quote -> market_data
                tool_part = last_tool_name.split(':')[-1]  # 去掉前缀
                skill_name = tool_part.split('.')[0]
                return await self._round2_call_tool(context, seed_data, skill_name)
            
            # 默认情况：直接回答
            return "生成回答", None
            
        except Exception as e:
            if isinstance(e, bdb.BdbQuit):
                raise e
            print(f"  ⚠️ LLM generation failed: {e}")
            import traceback
            traceback.print_exc()
            return "", None
    
    async def _round1_select_skill(self, context: str, seed_data: str) -> tuple[str, Optional[Dict[str, Any]]]:
        """
        Round 1: 选择Skill
        只给LLM提供skill工具
        """
        # 构建只包含skill的tool schema
        skill_tool = {
            "type": "function",
            "function": {
                "name": "finance_research:skill",
                "description": "Round 1: 根据用户问题选择合适的 Skill。分析用户意图，选择最能满足需求的 Skill。可选 Skills: market_data(股价/估值/K线)、financial_analysis(财务指标/ROE/毛利率)、sector_analysis(行业分析/龙头)、risk_assessment(风险评估)、data_analysis(统计计算)、web_research(新闻公告)、deep_research(深度研报)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "选择的 Skill 名称",
                            "enum": ["market_data", "financial_analysis", "sector_analysis", "risk_assessment", "data_analysis", "web_research", "deep_research"]
                        }
                    },
                    "required": ["name"]
                }
            }
        }
        
        prompt = self._build_round1_prompt(context, seed_data)
        
        response = await async_chat_completion(
            self.client,
            model=self.config.model_name,
            messages=[{"role": "user", "content": prompt}],
            tools=[skill_tool],
            tool_choice="auto",
            temperature=0.7
        )
        
        message = response.choices[0].message
        if hasattr(message, 'tool_calls') and message.tool_calls:
            tool_call = message.tool_calls[0]
            tool_name = tool_call.function.name
            arguments = json.loads(tool_call.function.arguments)

            intent = f"选择Skill: {arguments.get('name', '')}"
            # 统一使用带前缀的工具名
            action = {
                "tool_name": "finance_research:skill",
                "parameters": arguments
            }

            # 记录action
            sig = self._action_signature(action, intent=intent)
            self._seed_used_action_signatures.add(sig)
            self._seed_used_action_signatures_ordered.append(sig)

            return intent, action

        # 尝试解析文本输出（qwen模型可能直接输出文本而不是tool_calls）
        content = message.content or ""
        parsed_action = self._parse_skill_call(content)
        if parsed_action:
            skill_name = parsed_action.get("name", "")
            intent = f"选择Skill: {skill_name}"
            action = {
                "tool_name": "finance_research:skill",
                "parameters": parsed_action
            }
            sig = self._action_signature(action, intent=intent)
            self._seed_used_action_signatures.add(sig)
            self._seed_used_action_signatures_ordered.append(sig)
            return intent, action

        # LLM直接回答
        return content or "直接回答", None

    def _parse_skill_call(self, text: str) -> Optional[Dict[str, Any]]:
        """解析 skill(name="xxx") 格式的文本调用"""
        if not text:
            return None
        import re
        # 匹配 skill(name="xxx") 或 skill(name='xxx') 格式
        pattern = r'skill\s*\(\s*name\s*=\s*["\'](\w+)["\']\s*\)'
        match = re.search(pattern, text)
        if match:
            return {"name": match.group(1)}
        return None
    
    async def _round2_call_tool(self, context: str, seed_data: str, skill_name: str) -> tuple[str, Optional[Dict[str, Any]]]:
        """
        Round 2: 调用具体工具
        【编排层自动处理 Round 1 的输出，生成 Round 2 的输入。即通过 get_skill_tools 获取该 Skill 的工具列表，只给 LLM 提供这些工具】
        """
        # 【编排层自动】获取该Skill的工具列表
        try:
            print(f"  [DEBUG] Calling get_skill_tools for {skill_name}")
            # 过滤 execution_kwargs，只保留必需参数
            clean_kwargs = {k: v for k, v in self._execution_kwargs.items()
                           if k not in ('entities', 'tags', 'quality_score')}
            tools_result = await self.worker.execute_tool(
                "get_skill_tools",
                {"name": skill_name},
                **clean_kwargs
            )
            print(f"  [DEBUG] get_skill_tools result type={type(tools_result)}, content={str(tools_result)[:200]}...")
            
            # 解析工具列表
            skill_tools = []
            if isinstance(tools_result, dict):
                # 检查是否是标准响应格式 (code, message, data)
                if 'data' in tools_result and isinstance(tools_result['data'], dict):
                    data = tools_result['data']
                    if data.get('success'):
                        skill_tools = data.get('tools', [])
                # 直接格式
                elif tools_result.get('success'):
                    skill_tools = tools_result.get('tools', [])
                elif 'tools' in tools_result:
                    skill_tools = tools_result['tools']
            
            print(f"  [DEBUG] Parsed {len(skill_tools)} tools")
            if not skill_tools:
                print(f"  [DEBUG] Full result: {tools_result}")
                return f"Skill {skill_name} 没有可用工具", None
            
        except Exception as e:
            print(f"  [DEBUG] 获取工具列表失败: {e}")
            import traceback
            traceback.print_exc()
            return f"获取 {skill_name} 工具列表失败", None
        
        # 构建该Skill的工具schemas
        tool_schemas = []
        for tool in skill_tools:
            tool_name = tool.get('name')
            tool_desc = tool.get('description', '')
            tool_params = tool.get('parameters', {})
            
            if tool_name:
                full_name = f"{skill_name}.{tool_name}"
                schema = {
                    "type": "function",
                    "function": {
                        "name": full_name,
                        "description": f"[{skill_name}] {tool_desc}",
                        "parameters": tool_params if tool_params else {"type": "object", "properties": {}}
                    }
                }
                tool_schemas.append(schema)
        
        prompt = self._build_round2_prompt(context, seed_data, skill_name, skill_tools)
        
        response = await async_chat_completion(
            self.client,
            model=self.config.model_name,
            messages=[{"role": "user", "content": prompt}],
            tools=tool_schemas,
            tool_choice="auto",
            temperature=0.7
        )
        
        message = response.choices[0].message
        if hasattr(message, 'tool_calls') and message.tool_calls:
            tool_call = message.tool_calls[0]
            tool_name = tool_call.function.name  # 格式: skill_name.tool_name
            arguments = json.loads(tool_call.function.arguments)

            intent = f"调用工具: {tool_name}"
            action = {
                "tool_name": tool_name,
                "parameters": arguments
            }

            # 检查重复
            sig = self._action_signature(action, intent=intent)
            if sig in self._seed_used_action_signatures:
                print(f"  ⚠️ Duplicate action detected, skipping: {sig}")
                return "", None

            self._seed_used_action_signatures.add(sig)
            self._seed_used_action_signatures_ordered.append(sig)

            return intent, action

        # 尝试解析文本输出（qwen模型可能直接输出文本而不是tool_calls）
        content = message.content or ""
        parsed_action = self._parse_tool_call(content, skill_name, skill_tools)
        if parsed_action:
            tool_name = parsed_action.get("tool_name", "")
            arguments = parsed_action.get("parameters", {})
            intent = f"调用工具: {tool_name}"
            action = {
                "tool_name": tool_name,
                "parameters": arguments
            }
            # 检查重复
            sig = self._action_signature(action, intent=intent)
            if sig in self._seed_used_action_signatures:
                print(f"  ⚠️ Duplicate action detected, skipping: {sig}")
                return "", None
            self._seed_used_action_signatures.add(sig)
            self._seed_used_action_signatures_ordered.append(sig)
            return intent, action

        # LLM直接回答
        return content or "生成回答", None

    def _parse_tool_call(self, text: str, skill_name: str, available_tools: list) -> Optional[Dict[str, Any]]:
        """解析 skill.tool_name(args) 格式的文本调用"""
        if not text:
            return None
        import re
        # 匹配 skill.tool_name(...) 格式，如 market_data.get_quote(ts_code="600519.SH")
        pattern = rf'{re.escape(skill_name)}\.(\w+)\s*\((.*?)\)'
        match = re.search(pattern, text, re.DOTALL)
        if match:
            tool_name = match.group(1)
            args_text = match.group(2)
            # 解析参数
            params = {}
            # 匹配 key="value" 或 key='value' 或 key=value 格式
            param_pattern = r'(\w+)\s*=\s*["\']([^"\']*)["\']|(\w+)\s*=\s*([^,\s]+)'
            for m in re.finditer(param_pattern, args_text):
                if m.group(1):
                    params[m.group(1)] = m.group(2)
                elif m.group(3):
                    params[m.group(3)] = m.group(4)
            full_tool_name = f"{skill_name}.{tool_name}"
            return {"tool_name": full_tool_name, "parameters": params}
        return None
    
    def _build_round1_prompt(self, context: str, seed_data: str) -> str:
        """构建Round 1的Prompt - 选择Skill"""
        return f"""你是专业的金融研投助手。

[任务]
{seed_data}

[当前探索历史]
{context}

请选择最合适的Skill来处理这个任务。

可用Skills:
- market_data: 股价、行情、PE/PB、K线、资金流向
- financial_analysis: ROE、营收、净利润、财务报表
- sector_analysis: 行业分析、龙头识别、行业对比
- risk_assessment: 风险、波动率、最大回撤
- data_analysis: 统计计算、对比分析
- web_research: 新闻、公告、舆情
- deep_research: 研报、深度分析

⚠️  CRITICAL: 你必须使用 skill(name) 函数选择Skill。

正确示例:
  skill(name="market_data")

❌ 错误示例:
  - 直接写 "market_data"
  - 调用 "get_skill_tools"
  - 调用其他函数名称
"""

    def _build_round2_prompt(self, context: str, seed_data: str, skill_name: str, skill_tools: list) -> str:
        """构建Round 2的Prompt - 调用具体工具"""
        tools_info = []
        for tool in skill_tools:
            tool_name = tool.get('name', '')
            tool_desc = tool.get('description', '')
            tools_info.append(f"- {skill_name}.{tool_name}: {tool_desc}")

        tools_str = "\n".join(tools_info)

        return f"""你是专业的金融研投助手。

[任务]
{seed_data}

[已选择Skill]
{skill_name}

[可用工具 - 直接调用格式]
{tools_str}

[当前探索历史]
{context}

请选择合适的工具来获取数据。

⚠️  CRITICAL: 工具调用格式
正确格式: 直接调用 {skill_name}.<tool_name>
  示例: {skill_name}.get_quote({{"ts_code": "600519.SH"}})

❌ 错误示例:
  - 只写 "get_quote" (缺少 skill 前缀)
  - 调用 "get_skill_tools" (这是系统内部工具)
  - 调用 "execute_skill_tool" (这是系统内部工具)

✅ 正确示例:
  - {skill_name}.get_quote({{"ts_code": "600519.SH"}})
  - {skill_name}.search_stock({{"keyword": "茅台"}})
"""

    async def _execute_action(self, action: Dict[str, Any]) -> str:
        """Execute an action via worker (async) - 与金融研投助手一致"""
        tool_name = action.get("tool_name", "")
        parameters = action.get("parameters", {})

        # 过滤 execution_kwargs，只保留必需参数，移除 entities/tags 等额外数据
        clean_kwargs = {k: v for k, v in self._execution_kwargs.items()
                       if k not in ('entities', 'tags', 'quality_score')}

        # 检查是否是直接工具调用 (格式: skill_name.tool_name)
        if "." in tool_name:
            # Round 2: 直接调用具体工具
            skill_name, actual_tool_name = tool_name.split(".", 1)
            try:
                result = await self.worker.execute_tool(
                    "execute_skill_tool",
                    {
                        "skill_name": skill_name,
                        "tool_name": actual_tool_name,
                        "arguments": parameters
                    },
                    **clean_kwargs
                )
                formatted_result = format_tool_result(result, verbose=False)
                return formatted_result
            except Exception as e:
                print(f"Error executing {tool_name}: {str(e)}")
                return f"Error executing {tool_name}: {str(e)}"

        # Round 1: skill 选择
        elif tool_name in ("skill", "finance_research:skill"):
            try:
                result = await self.worker.execute_tool(
                    "skill",
                    parameters,
                    **clean_kwargs
                )
                formatted_result = format_tool_result(result, verbose=False)
                return formatted_result
            except Exception as e:
                print(f"Error executing {tool_name}: {str(e)}")
                return f"Error executing {tool_name}: {str(e)}"

        else:
            error_msg = f"❌ ERROR: Tool '{tool_name}' is not available."
            print(f"  {error_msg}")
            return error_msg

    def _build_context(self, node: TrajectoryNode, seed_data: str) -> str:
        """Build context from current path"""
        context = f"Starting point: {seed_data}\n\n"

        # Trace back to root
        path = []
        current = node
        while current.parent_id:
            path.append(current)
            current = self.nodes[current.parent_id]
        path.reverse()

        # Format path
        for i, n in enumerate(path, 1):
            context += f"Step {i}:\n"
            context += f"  Intent: {n.intent}\n"
            if n.action:
                context += f"  Action: {n.action.get('tool_name', 'unknown')}\n"
                context += f"  Parameters: {json.dumps(n.action.get('parameters', {}), ensure_ascii=False)}\n"
            obs_preview = n.observation[:500] + "..." if len(n.observation) > 500 else n.observation
            context += f"  Observation: {obs_preview}\n\n"

        return context

    def _build_exploration_prompt(self, context: str, seed_data: str, used_actions_block: str = "") -> str:
        """Build prompt for exploration - 与金融研投助手一致的 3 轮流程"""
        from sandbox.tool_schemas import get_skills_info, ALL_SKILLS, SKILL_TOOLS
        
        # Build skills info block
        skills_info = []
        for skill_name, skill_data in ALL_SKILLS.items():
            skills_info.append(f"- {skill_name}: {skill_data['description']}\n  使用场景: {skill_data['use_when']}")
        skills_info_str = "\n".join(skills_info)

        # Build available tools info (直接暴露的具体工具)
        tools_info = []
        tools_info.append("Round 1: skill(name) - 选择 Skill")
        for skill_name, tools in SKILL_TOOLS.items():
            for tool in tools:
                params_str = ", ".join([f"{k}" for k in tool.get("parameters", {}).keys()])
                tools_info.append(f"  - {skill_name}.{tool['name']}({params_str}): {tool['description']}")
        tools_info_str = "\n".join(tools_info)

        prompt = f"""你是专业的金融研投助手，擅长使用工具查询金融数据并给出专业分析。

[Starting Point Information]
Content: {seed_data}"""

        if self.config.seed_description:
            prompt += f"\nDescription: {self.config.seed_description}"

        prompt += f"""

[Exploration Goal]:
Based on the starting point content, conduct systematic exploration to collect valuable information.
Finally, I will synthesize a question and answer based on your collected information.
"""
        if used_actions_block:
            prompt += f"""
[Already Explored Actions - Do NOT Repeat]:
The following tool calls have ALREADY been executed for this seed.
You MUST propose a NEW action that is NOT in this list.
{used_actions_block}
"""

        if self.config.sampling_tips:
            prompt += f"""[Exploration Strategy and Focus]:
{self.config.sampling_tips}

"""

        prompt += f"""[Current History Trajectory]:
{context}

[Available Skills]:
{skills_info_str}

[Available Tools - 3轮流程]:
{tools_info_str}

⚠️  CRITICAL INSTRUCTIONS - 与金融研投助手一致的 3 轮流程:

Round 1 - Skill选择:
  调用 skill(name) 选择合适的 Skill
  可选 Skills: market_data, financial_analysis, sector_analysis, risk_assessment, data_analysis, web_research, deep_research

Round 2 - 工具调用:
  【编排层自动处理】选择 Skill 后，系统会自动获取该 Skill 的工具列表
  然后直接调用具体工具: skill_name.tool_name(arguments)
  例如: market_data.get_quote({{"symbol": "600519"}})

Skill选择指南:
  - market_data: 股价、行情、PE/PB、K线、资金流向
  - financial_analysis: ROE、营收、净利润、财务报表
  - sector_analysis: 行业分析、龙头识别、行业对比
  - risk_assessment: 风险、波动率、最大回撤
  - data_analysis: 统计计算、对比分析
  - web_research: 新闻、公告、舆情
  - deep_research: 研报、深度分析

常见误区:
  ❌ PE/PB 属于 market_data，不是 financial_analysis
  ❌ "估值" 通常指 PE/PB/PS，选 market_data
  ✅ ROE/营收/利润 选 financial_analysis

[Current State]:
{context.split('Observation:')[-1] if 'Observation:' in context else 'Starting exploration'}

Based on the current state, decide which round you are in and generate the appropriate action.

Format:
<intent>Brief description of what you want to achieve in this step</intent>
<action>
<tool_name>skill|skill_name.tool_name</tool_name>
<parameters>{{"param1": "value1"}}</parameters>
</action>"""

        return prompt

    def _format_used_actions_for_prompt(self) -> str:
        """Format used actions for prompt to avoid duplicates"""
        if not self._seed_used_action_signatures_ordered:
            return "(No actions taken yet)"
        
        formatted = []
        for i, sig in enumerate(self._seed_used_action_signatures_ordered, 1):
            formatted.append(f"  {i}. {sig}")
        return "\n".join(formatted)

    def _action_signature(self, action: Dict[str, Any], intent: str = "") -> str:
        """Generate unique signature for an action to detect duplicates"""
        tool_name = action.get("tool_name", "")
        params = action.get("parameters", {})
        # Sort params to ensure consistent signature
        params_str = json.dumps(params, sort_keys=True, ensure_ascii=False)
        return f"{tool_name}:{params_str}"

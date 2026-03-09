# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""
MCP Chat Service - 三轮编排架构

三轮流程:
  Round 1（Skill 选择）: LLM 从 skill 元工具选择 skill，编排层获取 SKILL.md + 工具定义
  Round 2（工具调用）: LLM 使用 skill 的工具列表进行 function calling（可循环）
  Round 3（最终回答）: LLM 基于工具返回数据生成最终回答

消息流示例:
  [system] 你是金融研究助手...
  [user] 茅台股价多少？
  [assistant] tool_call: skill(name="market_data")              ← Round 1
  [tool] {SKILL.md 完整内容}                                     ← Round 1 结果
  [assistant] tool_call: market_data.get_quote(symbol="600519") ← Round 2
  [tool] {"success": true, "data": {"nowPri": "1850.50", ...}}  ← Round 2 结果
  [assistant] 贵州茅台(600519) 当前价格 ¥1,850.50...             ← Round 3
"""

import os
import json
import asyncio
import logging
from typing import Dict, Any, List, Optional, AsyncGenerator
from datetime import datetime

# DashScope (Qwen)
try:
    import dashscope
    from dashscope import Generation
    DASHSCOPE_AVAILABLE = True
except ImportError:
    DASHSCOPE_AVAILABLE = False
    Generation = None

# MCP Client
try:
    from app.mcp_client.client import MCPClient
    MCP_AVAILABLE = True
except ImportError:
    try:
        from mcp_client.client import MCPClient
        MCP_AVAILABLE = True
    except ImportError:
        MCP_AVAILABLE = False
        MCPClient = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MCPChatService")


class MCPChatService:
    """
    MCP Chat Service - 三轮编排架构

    Round 1: Skill 选择 — LLM 选择 skill，编排层获取 SKILL.md + 工具定义
    Round 2: 工具调用 — LLM 使用 skill 的工具列表进行 function calling（最多 5 次循环）
    Round 3: 最终回答 — LLM 基于工具返回数据生成最终回答
    """

    def __init__(
        self,
        mcp_server_path: str = None,
        model: str = "qwen-max",
        api_key: str = None,
        connect_timeout: float = 30.0,
        call_timeout: float = 30.0,
        max_iterations: int = 10
    ):
        if not DASHSCOPE_AVAILABLE:
            raise RuntimeError("dashscope 未安装。安装: pip install dashscope")

        if not MCP_AVAILABLE:
            raise RuntimeError("MCP Client 未安装")

        # 配置 DashScope
        self.model = model
        self.api_key = api_key or os.environ.get("DASHSCOPE_API_KEY")
        if not self.api_key:
            raise RuntimeError("未设置 DASHSCOPE_API_KEY")
        dashscope.api_key = self.api_key

        # 配置 MCP
        if mcp_server_path is None:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            backend_dir = os.path.dirname(current_dir)
            mcp_server_path = os.path.join(backend_dir, "app/mcp_server/server.py")

        self.mcp_server_path = mcp_server_path
        self.connect_timeout = connect_timeout
        self.call_timeout = call_timeout
        self.max_iterations = max_iterations

        # 运行时状态
        self.mcp_client: Optional[MCPClient] = None
        self.tools_list: List[Dict] = []  # 元工具列表
        self.is_connected = False

        logger.info(f"MCP Chat Service 初始化: model={model}, server={mcp_server_path}")

    async def connect(self) -> bool:
        """连接到 MCP Server 并获取元工具列表"""
        if self.is_connected:
            logger.info("MCP Client 已连接")
            return True

        try:
            logger.info(f"正在连接 MCP Server: {self.mcp_server_path}")
            self.mcp_client = MCPClient(
                server_script_path=self.mcp_server_path,
                connect_timeout=self.connect_timeout,
                call_timeout=self.call_timeout
            )

            connected = await self.mcp_client.connect()
            if not connected:
                logger.error("MCP Client 连接失败")
                return False

            # 获取元工具列表（skill, get_skill_tools, execute_skill_tool）
            tools_result = await self.mcp_client.list_tools()
            if not tools_result.get("success"):
                logger.error(f"获取工具列表失败: {tools_result.get('error')}")
                return False

            self.tools_list = tools_result.get("tools", [])
            self.is_connected = True

            logger.info(f"MCP Client 连接成功，发现 {len(self.tools_list)} 个元工具")
            for tool in self.tools_list:
                logger.debug(f"  - {tool['name']}: {tool.get('description', '')[:60]}...")

            return True

        except Exception as e:
            logger.error(f"连接 MCP Server 失败: {e}")
            return False

    async def disconnect(self):
        """断开 MCP Client 连接"""
        if self.mcp_client and self.is_connected:
            await self.mcp_client.disconnect()
            self.is_connected = False
            logger.info("MCP Client 已断开连接")

    def _mcp_tool_to_qwen(self, mcp_tool: Dict) -> Dict:
        """将 MCP 工具格式转换为 qwen function calling 格式"""
        # qwen 的 function name 不能有 "."，用 "__" 替代
        qwen_name = mcp_tool["name"].replace(".", "__")
        return {
            "type": "function",
            "function": {
                "name": qwen_name,
                "description": mcp_tool.get("description", ""),
                "parameters": mcp_tool.get("inputSchema", mcp_tool.get("parameters", {}))
            }
        }

    def _qwen_name_to_mcp(self, qwen_name: str) -> str:
        """将 qwen function name 转回 MCP tool name"""
        return qwen_name.replace("__", ".")

    async def _call_mcp_tool(self, tool_name: str, arguments: Dict) -> Any:
        """调用 MCP 工具，返回原始结果"""
        if not self.is_connected:
            return {"error": "MCP Client 未连接"}

        logger.info(f"调用 MCP 工具: {tool_name}")
        logger.debug(f"  参数: {json.dumps(arguments, ensure_ascii=False)}")

        result = await self.mcp_client.call_tool(tool_name, arguments)

        if result.get("success") is not None:
            if result.get("success"):
                logger.info(f"  工具调用成功")
                return result.get("data", result)
            else:
                error = result.get("error", "未知错误")
                logger.error(f"  工具调用失败: {error}")
                return {"error": error}
        else:
            # call_tool 返回的可能是直接的数据（非标准格式）
            return result

    async def _call_mcp_tool_raw(self, tool_name: str, arguments: Dict) -> str:
        """
        调用 MCP 工具，返回原始文本（不做 JSON 解析）。

        用于 skill 工具返回 SKILL.md 等非 JSON 内容。
        """
        if not self.is_connected or not self.mcp_client._session:
            return json.dumps({"error": "MCP Client 未连接"})

        try:
            result = await asyncio.wait_for(
                self.mcp_client._session.call_tool(tool_name, arguments),
                timeout=self.call_timeout
            )

            if result.content and len(result.content) > 0:
                first_content = result.content[0]
                if hasattr(first_content, 'text'):
                    return first_content.text

            return json.dumps({"error": "工具返回为空"})

        except asyncio.TimeoutError:
            return json.dumps({"error": f"工具调用超时 ({self.call_timeout}s)"})
        except Exception as e:
            return json.dumps({"error": str(e)})

    def _build_messages(
        self,
        user_question: str,
        system_prompt: Optional[str] = None,
        conversation_history: Optional[List[Dict]] = None
    ) -> List[Dict]:
        """构建消息列表"""
        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        else:
            messages.append({
                "role": "system",
                "content": "你是一个专业的金融投资分析师。你可以使用提供的工具来查询股票数据、分析财务指标和评估风险。请基于真实数据给出专业、客观的投资建议。"
            })

        if conversation_history:
            messages.extend(conversation_history)

        messages.append({"role": "user", "content": user_question})
        return messages

    def _extract_tool_calls(self, assistant_message) -> Optional[List]:
        """从 assistant 消息中提取 tool_calls"""
        tool_calls = None
        if hasattr(assistant_message, 'get'):
            tool_calls = assistant_message.get('tool_calls')
        elif hasattr(assistant_message, 'tool_calls'):
            try:
                tool_calls = assistant_message.tool_calls
            except (AttributeError, KeyError):
                tool_calls = None
        return tool_calls

    def _get_assistant_content(self, assistant_message) -> str:
        """从 assistant 消息中提取 content"""
        if hasattr(assistant_message, 'get'):
            return assistant_message.get('content', '') or ''
        return (assistant_message.content or '') if hasattr(assistant_message, 'content') else ''

    def _get_assistant_role(self, assistant_message) -> str:
        """从 assistant 消息中提取 role"""
        if hasattr(assistant_message, 'get'):
            return assistant_message.get('role', 'assistant')
        return assistant_message.role if hasattr(assistant_message, 'role') else 'assistant'

    def _parse_tool_call(self, tool_call) -> tuple:
        """解析单个 tool_call，返回 (function_name, function_args)"""
        if isinstance(tool_call, dict):
            function_name = tool_call['function']['name']
            function_args = json.loads(tool_call['function']['arguments'])
        else:
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)
        return function_name, function_args

    def _call_llm(self, messages: List[Dict], tools: List[Dict]):
        """调用 LLM"""
        response = Generation.call(
            model=self.model,
            messages=messages,
            tools=tools if tools else None,
            result_format='message'
        )
        if response.status_code != 200:
            raise RuntimeError(f"qwen API 调用失败: {response.code} - {response.message}")
        return response.output.choices[0].message

    async def _round1_select_skill(self, messages: List[Dict]) -> tuple:
        """
        Round 1: Skill 选择

        只给 LLM 提供 skill 元工具，让 LLM 决定是否需要调用 skill。

        Returns:
            (skill_name, skill_md, skill_tools) 或 (None, None, None) 如果 LLM 直接回答
        """
        logger.info("=== Round 1: Skill 选择 ===")

        # 只保留 skill 元工具
        skill_tool = None
        for t in self.tools_list:
            if t["name"] == "skill":
                skill_tool = t
                break

        if not skill_tool:
            logger.error("未找到 skill 元工具")
            return None, None, None

        qwen_tools = [self._mcp_tool_to_qwen(skill_tool)]

        # 调用 LLM
        assistant_msg = self._call_llm(messages, qwen_tools)
        tool_calls = self._extract_tool_calls(assistant_msg)

        # 将 assistant 消息追加到 messages
        messages.append({
            "role": self._get_assistant_role(assistant_msg),
            "content": self._get_assistant_content(assistant_msg),
            "tool_calls": tool_calls
        })

        if not tool_calls:
            # LLM 直接回答，不需要 skill
            logger.info("Round 1: LLM 直接回答，无需 skill")
            return None, None, None

        # 解析 LLM 选择的 skill
        function_name, function_args = self._parse_tool_call(tool_calls[0])
        mcp_tool_name = self._qwen_name_to_mcp(function_name)

        logger.info(f"Round 1: LLM tool_call: name={function_name}, args={function_args}")

        if mcp_tool_name != "skill":
            logger.warning(f"Round 1: LLM 调用了非 skill 工具: {mcp_tool_name}，尝试作为 skill name 处理")
            # qwen 有时会把 skill name 直接作为 function name 返回
            # 将其视为对该 skill 的选择
            skill_name = mcp_tool_name
        else:
            skill_name = function_args.get("name")
        logger.info(f"Round 1: LLM 选择了 skill: {skill_name}")

        # 通过 MCP 获取 SKILL.md（原始文本）
        skill_md = await self._call_mcp_tool_raw("skill", {"name": skill_name})

        # 将 SKILL.md 内容作为 tool result 追加到 messages
        messages.append({
            "role": "tool",
            "name": function_name,
            "content": skill_md
        })

        # 通过 MCP 获取工具定义
        tools_result = await self._call_mcp_tool("get_skill_tools", {"name": skill_name})

        # get_skill_tools 返回 JSON，需要解析
        if isinstance(tools_result, str):
            try:
                tools_result = json.loads(tools_result)
            except json.JSONDecodeError:
                logger.error(f"解析 get_skill_tools 结果失败")
                return skill_name, skill_md, []

        # 从返回结果中提取工具定义
        if isinstance(tools_result, dict):
            skill_tools = tools_result.get("tools", [])
        else:
            skill_tools = []

        logger.info(f"Round 1 完成: skill={skill_name}, 获取 {len(skill_tools)} 个工具定义")
        return skill_name, skill_md, skill_tools

    async def _round2_execute_tools(
        self,
        messages: List[Dict],
        skill_name: str,
        skill_tools: List[Dict],
        max_rounds: int = 5
    ):
        """
        Round 2: 工具调用（可循环）

        给 LLM 提供 skill 的工具列表，让 LLM 进行 function calling。
        通过 execute_skill_tool 元工具执行。
        """
        logger.info(f"=== Round 2: 工具调用 (skill={skill_name}, {len(skill_tools)} 个工具) ===")

        # 将 skill 工具定义转为 qwen function calling 格式
        qwen_tools = []
        for tool_def in skill_tools:
            qwen_tools.append({
                "type": "function",
                "function": {
                    "name": tool_def["name"].replace(".", "__"),
                    "description": tool_def.get("description", ""),
                    "parameters": tool_def.get("parameters", {})
                }
            })

        # function calling 循环
        for round_num in range(max_rounds):
            logger.info(f"Round 2 - 迭代 {round_num + 1}/{max_rounds}")

            assistant_msg = self._call_llm(messages, qwen_tools)
            tool_calls = self._extract_tool_calls(assistant_msg)

            messages.append({
                "role": self._get_assistant_role(assistant_msg),
                "content": self._get_assistant_content(assistant_msg),
                "tool_calls": tool_calls
            })

            if not tool_calls:
                # 没有 tool_call，LLM 已生成回答
                logger.info(f"Round 2 完成: LLM 生成回答 (迭代 {round_num + 1} 次)")
                return

            # 处理所有 tool_calls
            for tool_call in tool_calls:
                function_name, function_args = self._parse_tool_call(tool_call)
                # 转回 MCP 格式: market_data__get_quote -> market_data.get_quote
                mcp_tool_name = self._qwen_name_to_mcp(function_name)

                logger.info(f"  工具调用: {mcp_tool_name}, 参数: {function_args}")

                # 解析 skill_name.tool_name
                parts = mcp_tool_name.split(".", 1)
                if len(parts) == 2:
                    call_skill_name, call_tool_name = parts
                else:
                    call_skill_name = skill_name
                    call_tool_name = mcp_tool_name

                # 通过 execute_skill_tool 执行
                tool_result = await self._call_mcp_tool("execute_skill_tool", {
                    "skill_name": call_skill_name,
                    "tool_name": call_tool_name,
                    "arguments": function_args
                })

                # 将工具结果追加到 messages
                result_str = json.dumps(tool_result, ensure_ascii=False) if not isinstance(tool_result, str) else tool_result
                messages.append({
                    "role": "tool",
                    "name": function_name,
                    "content": result_str
                })

        logger.warning(f"Round 2: 达到最大迭代次数 {max_rounds}")

    def _get_last_assistant_content(self, messages: List[Dict]) -> str:
        """获取 messages 中最后一条 assistant 消息的 content"""
        for msg in reversed(messages):
            if msg.get("role") == "assistant" and msg.get("content"):
                return msg["content"]
        return ""

    async def chat(
        self,
        user_question: str,
        system_prompt: Optional[str] = None,
        conversation_history: Optional[List[Dict]] = None
    ) -> str:
        """
        三轮编排对话

        Args:
            user_question: 用户问题
            system_prompt: 系统提示词（可选）
            conversation_history: 对话历史（可选）

        Returns:
            LLM 的最终回答
        """
        if not self.is_connected:
            await self.connect()

        messages = self._build_messages(user_question, system_prompt, conversation_history)

        try:
            # Round 1: Skill 选择
            skill_name, skill_md, skill_tools = await self._round1_select_skill(messages)

            if skill_name is None:
                # LLM 直接回答，无需 skill
                return self._get_last_assistant_content(messages)

            # Round 2: 工具调用（可循环）
            await self._round2_execute_tools(messages, skill_name, skill_tools)

            # Round 3: 最终回答
            # Round 2 退出时 messages 中最后一条 assistant 消息就是最终回答
            final_answer = self._get_last_assistant_content(messages)
            if final_answer:
                logger.info("Round 3: 返回最终回答")
                return final_answer

            # 如果 Round 2 结束后 messages 最后是 tool 结果，再调一次 LLM 生成回答
            logger.info("=== Round 3: 生成最终回答 ===")
            assistant_msg = self._call_llm(messages, [])
            content = self._get_assistant_content(assistant_msg)
            messages.append({
                "role": "assistant",
                "content": content
            })
            return content

        except Exception as e:
            logger.error(f"chat 流程出错: {e}")
            raise

    async def chat_stream(
        self,
        user_question: str,
        system_prompt: Optional[str] = None,
        conversation_history: Optional[List[Dict]] = None
    ) -> AsyncGenerator[str, None]:
        """
        流式对话（暂不支持 function calling 流式，先返回完整结果）
        """
        result = await self.chat(user_question, system_prompt, conversation_history)
        yield result

    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.disconnect()


# 便捷函数
async def mcp_chat(
    question: str,
    model: str = "qwen-max",
    system_prompt: Optional[str] = None
) -> str:
    """
    便捷函数：快速调用 MCP Chat Service

    Example:
        >>> answer = await mcp_chat("查一下茅台近期的股市表现，值不值得买")
    """
    async with MCPChatService(model=model) as service:
        return await service.chat(question, system_prompt=system_prompt)

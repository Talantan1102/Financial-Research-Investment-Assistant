#!/usr/bin/env python3
"""
金融研投助手 MCP Server 端到端测试执行器
用于测试 GLM5 模型的工具调用和推理能力

调用方式: 使用阿里云 DashScope 调用 GLM5 模型
"""

import json
import asyncio
import time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from datetime import datetime
import sys
import os
import re

# 添加 benchmark 目录到路径（用于导入 evaluator）
sys.path.insert(0, os.path.dirname(__file__))

# 添加 backend 路径（用于导入 MCP Client）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend', 'app'))

# 加载 .env 文件
try:
    from dotenv import load_dotenv
    env_path = os.path.join(os.path.dirname(__file__), '..', 'backend', '.env')
    if os.path.exists(env_path):
        load_dotenv(env_path, override=False)
        print(f"[OK] 已加载 .env: {env_path}")
except ImportError:
    # 如果没有 dotenv，手动解析
    env_path = os.path.join(os.path.dirname(__file__), '..', 'backend', '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, _, value = line.partition('=')
                    os.environ.setdefault(key.strip(), value.strip())

# 设置 PYTHON 路径（MCP Server 需要）
if not os.environ.get('PYTHON'):
    venv_python = os.path.join(os.path.dirname(__file__), '..', 'venv', 'bin', 'python3')
    if os.path.exists(venv_python):
        os.environ['PYTHON'] = venv_python
    else:
        os.environ['PYTHON'] = sys.executable

# DashScope (阿里云百炼)
try:
    import dashscope
    from dashscope import Generation
    DASHSCOPE_AVAILABLE = True
except ImportError:
    DASHSCOPE_AVAILABLE = False
    Generation = None

# ZhipuAI (智谱)
try:
    from zhipuai import ZhipuAI
    ZHIPUAI_AVAILABLE = True
except ImportError:
    ZHIPUAI_AVAILABLE = False
    ZhipuAI = None

# OpenAI
try:
    from openai import AsyncOpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    AsyncOpenAI = None

# 导入 MCP Client
from app.mcp_client.client import MCPClient


@dataclass
class TestResult:
    """单个测试结果"""
    test_id: str
    query: str
    expected_skill: str
    predicted_skill: str
    skill_correct: bool
    expected_tools: List[str]
    predicted_tools: List[str]
    tools_correct: bool
    execution_success: bool
    output_quality_score: float
    latency_ms: int
    tool_call_count: int
    error_occurred: bool
    error_type: Optional[str]
    reasoning_quality: str
    raw_response: str
    timestamp: str
    tool_calls_detail: List[Dict] = None  # 工具调用详细信息
    evaluation_mode: str = "simple"  # 评估模式：exact/equivalent/functional/simple
    evaluation_notes: List[str] = None  # 评估备注
    tool_calls_detail: List[Dict] = None  # 工具调用详细信息，包含输入和输出


class GLM5MCPRunner:
    """GLM5 + MCP Server 端到端测试执行器"""
    
    def __init__(
        self,
        model: str = "glm-4-plus",
        api_key: Optional[str] = None,
        provider: str = "auto"  # auto, zhipu, dashscope, openai
    ):
        """
        Args:
            model: 模型名称，默认 glm-4-plus
                   GLM系列: glm-4-plus, glm-4-air, glm-4-flash
                   Qwen系列: qwen-max, qwen-plus, qwen-turbo
            api_key: API Key（根据 provider 自动选择环境变量）
            provider: API 提供商 (auto, zhipu, dashscope, openai)
                     auto 会根据模型名自动选择
        """
        self.model = model
        self.provider = self._detect_provider(model, provider)
        self.api_key = api_key or self._get_api_key()
        
        if not self.api_key:
            raise RuntimeError(
                f"请设置 {self._get_env_var_name()} 环境变量或传入 api_key"
            )
        
        # 初始化客户端
        self._init_client()
        
        self.results: List[TestResult] = []
        self.test_cases: List[Dict] = []
        self.mcp_client: Optional[MCPClient] = None
        
        # MCP Server 配置
        backend_dir = os.path.join(os.path.dirname(__file__), '..', 'backend')
        self.server_path = os.path.join(backend_dir, 'app', 'mcp_server', 'server.py')
        
    def _detect_provider(self, model: str, provider: str) -> str:
        """自动检测 API 提供商"""
        if provider != "auto":
            return provider
        
        # 根据模型名判断
        model_lower = model.lower()
        if model_lower.startswith("glm-"):
            return "zhipu" if ZHIPUAI_AVAILABLE else "dashscope"
        elif model_lower.startswith("qwen"):
            return "dashscope"
        else:
            return "dashscope"  # 默认
    
    def _get_env_var_name(self) -> str:
        """获取环境变量名"""
        if self.provider == "zhipu":
            return "ZHIPUAI_API_KEY"
        elif self.provider == "dashscope":
            return "DASHSCOPE_API_KEY"
        elif self.provider == "openai":
            return "OPENAI_API_KEY"
        return "API_KEY"
    
    def _get_api_key(self) -> Optional[str]:
        """获取 API Key"""
        if self.provider == "zhipu":
            return os.environ.get("ZHIPUAI_API_KEY")
        elif self.provider == "dashscope":
            return os.environ.get("DASHSCOPE_API_KEY")
        elif self.provider == "openai":
            return os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
        return None
    
    def _init_client(self):
        """初始化 LLM 客户端"""
        if self.provider == "zhipu":
            if not ZHIPUAI_AVAILABLE:
                raise RuntimeError("zhipuai 未安装。请运行: pip install zhipuai")
            self.zhipu_client = ZhipuAI(api_key=self.api_key)
            self.dashscope = None
            self.openai_client = None
            print(f"[OK] 使用智谱 API，模型: {self.model}")
            
        elif self.provider == "dashscope":
            if not DASHSCOPE_AVAILABLE:
                raise RuntimeError("dashscope 未安装。请运行: pip install dashscope")
            dashscope.api_key = self.api_key
            self.zhipu_client = None
            self.dashscope = dashscope
            self.openai_client = None
            print(f"[OK] 使用 DashScope API，模型: {self.model}")
            
        elif self.provider == "openai":
            if not OPENAI_AVAILABLE:
                raise RuntimeError("openai 未安装。请运行: pip install openai")
            base_url = os.environ.get("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
            self.openai_client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=base_url
            )
            self.zhipu_client = None
            self.dashscope = None
            print(f"[OK] 使用 OpenAI 兼容 API，模型: {self.model}")
        
    async def init_mcp(self):
        """初始化 MCP Client"""
        self.mcp_client = MCPClient(
            server_script_path=self.server_path,
            connect_timeout=30.0,
            call_timeout=60.0
        )
        connected = await self.mcp_client.connect()
        if not connected:
            raise RuntimeError("MCP Server 连接失败")
        print(f"[OK] MCP Client 连接成功")
        
    async def close_mcp(self):
        """关闭 MCP Client"""
        if self.mcp_client:
            await self.mcp_client.disconnect()
            print("[OK] MCP Client 已关闭")
    
    def load_test_cases(self, filepath: str) -> List[Dict]:
        """加载测试用例 (支持 JSON 数组、JSONL 和多行 JSON 格式)"""
        test_cases = []
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 首先尝试解析为 JSON 数组
        json_pattern = r'\[\s*\{.*?\}\s*\]'
        matches = re.findall(json_pattern, content, re.DOTALL)
        
        for match in matches:
            try:
                data = json.loads(match)
                if isinstance(data, list):
                    test_cases.extend(data)
            except json.JSONDecodeError:
                continue
        
        # 如果没有找到 JSON 数组，尝试解析多行 JSON 对象
        if not test_cases:
            # 移除注释行
            lines = [line for line in content.split('\n') if not line.strip().startswith('#')]
            clean_content = '\n'.join(lines)
            
            # 使用大括号匹配解析 JSON 对象
            buffer = ""
            bracket_count = 0
            for char in clean_content:
                if char == '{':
                    if bracket_count == 0:
                        buffer = ""
                    bracket_count += 1
                elif char == '}':
                    bracket_count -= 1
                    if bracket_count == 0:
                        buffer += char
                        try:
                            data = json.loads(buffer)
                            if isinstance(data, dict) and 'id' in data:
                                test_cases.append(data)
                        except json.JSONDecodeError:
                            pass
                        buffer = ""
                        continue
                if bracket_count > 0:
                    buffer += char
                
        self.test_cases = test_cases
        return test_cases
    
    def _build_system_prompt(self) -> str:
        """构建系统提示词"""
        return """你是专业的金融研投助手，擅长使用工具查询金融数据并给出专业分析。

## 重要：Skill 选择指南

1. **market_data** - 市场数据（必选当问题涉及以下概念）
   - 股价、行情、涨跌幅、成交量
   - 市盈率(PE)、市净率(PB)、市值
   - K线、历史走势、资金流向
   - 股票代码查询

2. **financial_analysis** - 财务报表分析（必选当问题涉及）
   - ROE(净资产收益率)、ROA
   - 营收、净利润、毛利率
   - 资产负债表、现金流量表
   - 同比/环比增长率

3. **risk_assessment** - 风险评估
   - 波动率、最大回撤、夏普比率

4. **deep_research** - 深度研究
   - 研报生成、综合分析

5. **web_research** - 网络搜索
   - 新闻、公告、舆情

6. **data_analysis** - 数据分析
   - 统计计算、对比分析

7. **sector_analysis** - 行业分析
   - 行业板块、产业链

## 常见误区提醒

❌ PE/PB 属于 **market_data**，不是 financial_analysis
❌ "估值" 通常指 PE/PB/PS，选 market_data
✅ ROE/营收/利润 选 financial_analysis

## 工作流程
1. 分析用户问题中的关键词
2. 根据上述指南选择正确的 Skill
3. 调用工具获取数据
4. 给出专业分析

请确保选择正确的 Skill，否则无法获取所需数据。"""

    def _call_llm(self, messages: List[Dict], tools: Optional[List[Dict]] = None):
        """调用 LLM（支持多种 provider）"""
        if self.provider == "zhipu":
            return self._call_zhipu(messages, tools)
        else:
            return self._call_dashscope(messages, tools)
    
    def _call_zhipu(self, messages: List[Dict], tools: Optional[List[Dict]] = None):
        """调用智谱 API"""
        try:
            if tools:
                response = self.zhipu_client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    temperature=0.7,
                    max_tokens=2000
                )
            else:
                response = self.zhipu_client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.7,
                    max_tokens=2000
                )
            return response.choices[0].message
        except Exception as e:
            raise RuntimeError(f"智谱 API 调用失败: {e}")
    
    def _call_dashscope(self, messages: List[Dict], tools: Optional[List[Dict]] = None):
        """调用 DashScope API"""
        response = Generation.call(
            model=self.model,
            messages=messages,
            tools=tools if tools else None,
            result_format='message'
        )
        
        if response.status_code != 200:
            raise RuntimeError(f"API 调用失败: {response.code} - {response.message}")
        
        return response.output.choices[0].message
    
    async def _execute_skill(
        self,
        skill_name: str,
        tool_name: str,
        arguments: Dict
    ) -> Any:
        """通过 MCP 执行 Skill 工具"""
        try:
            result = await self.mcp_client.call_tool(
                "execute_skill_tool",
                {
                    "skill_name": skill_name,
                    "tool_name": tool_name,
                    "arguments": arguments
                }
            )
            return result
        except Exception as e:
            return {"error": str(e)}
    
    async def _get_skill_md(self, skill_name: str) -> str:
        """获取 Skill 的 SKILL.md 内容"""
        try:
            result = await self.mcp_client.call_tool(
                "skill",
                {"name": skill_name}
            )
            if isinstance(result, dict) and result.get("success"):
                return result.get("data", "")
            return str(result)
        except Exception as e:
            return f"获取 SKILL.md 失败: {e}"
    
    async def _get_skill_tools(self, skill_name: str) -> List[Dict]:
        """获取 Skill 的工具列表"""
        try:
            result = await self.mcp_client.call_tool(
                "get_skill_tools",
                {"name": skill_name}
            )
            if isinstance(result, dict) and result.get("success"):
                return result.get("tools", [])
            return []
        except Exception as e:
            print(f"[WARN] 获取工具列表失败: {e}")
            return []
    
    def _convert_to_dashscope_tools(self, skill_tools: List[Dict]) -> List[Dict]:
        """将 Skill 工具转换为 DashScope function calling 格式"""
        tools = []
        for tool in skill_tools:
            # DashScope 使用 qwen 格式: name 不能有 "."，用 "__" 替代
            qwen_name = tool["name"].replace(".", "__")
            tools.append({
                "type": "function",
                "function": {
                    "name": qwen_name,
                    "description": tool.get("description", ""),
                    "parameters": tool.get("parameters", {})
                }
            })
        return tools
    
    def _extract_tool_calls(self, message) -> List:
        """从消息中提取 tool_calls"""
        # DashScope Message 类重载了 __getattr__，当 key 不存在时会抛出 KeyError
        # 所以不能使用 hasattr，需要直接尝试访问并捕获异常
        try:
            tool_calls = message.tool_calls
            if tool_calls is None:
                return []
            return list(tool_calls)
        except (AttributeError, KeyError):
            return []
    
    async def _run_conversation(
        self,
        query: str,
        expected_skill: str
    ) -> Dict:
        """
        执行完整对话流程
        
        Returns:
            {
                "skill": str,
                "tools": List[str],
                "answer": str,
                "tool_calls": List[Dict]
            }
        """
        messages = [
            {"role": "system", "content": self._build_system_prompt()},
            {"role": "user", "content": query}
        ]
        
        tool_calls_history = []
        predicted_skill = None
        
        # Round 1: Skill 选择
        print("  [1] Skill选择...", end=" ", flush=True)
        
        # 构建元工具（用于选择 skill）
        meta_tools = [{
            "type": "function",
            "function": {
                "name": "select_skill",
                "description": "选择合适的 Skill 来处理用户问题",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "skill_name": {
                            "type": "string",
                            "enum": ["market_data", "financial_analysis", "risk_assessment", 
                                    "deep_research", "web_research", "data_analysis", "sector_analysis"],
                            "description": "要使用的 Skill 名称"
                        },
                        "reason": {
                            "type": "string",
                            "description": "选择该 Skill 的原因"
                        }
                    },
                    "required": ["skill_name", "reason"]
                }
            }
        }]
        
        try:
            assistant_msg = self._call_llm(messages, meta_tools)
        except Exception as e:
            return {"error": f"LLM 调用失败: {e}"}
        
        tool_calls = self._extract_tool_calls(assistant_msg)
        
        # 将 assistant 消息添加到 messages
        msg_dict = {
            "role": "assistant",
            "content": assistant_msg.content if hasattr(assistant_msg, 'content') else ""
        }
        if tool_calls:
            msg_dict["tool_calls"] = []
            for tc in tool_calls:
                msg_dict["tool_calls"].append({
                    "id": tc.id if hasattr(tc, 'id') else "call_1",
                    "type": "function",
                    "function": {
                        "name": tc.function.name if hasattr(tc, 'function') else tc.get('function', {}).get('name'),
                        "arguments": tc.function.arguments if hasattr(tc, 'function') else tc.get('function', {}).get('arguments')
                    }
                })
        messages.append(msg_dict)
        
        if not tool_calls:
            # LLM 直接回答
            predicted_skill = self._infer_skill_from_answer(assistant_msg.content or "", query)
            print(f"直接回答 → {predicted_skill}")
            return {
                "skill": predicted_skill,
                "tools": [],
                "tool_calls": []
            }
        
        # 解析选择的 skill
        tc = tool_calls[0]
        func_args = json.loads(tc.function.arguments if hasattr(tc, 'function') else tc.get('function', {}).get('arguments'))
        predicted_skill = func_args.get("skill_name")
        
        print(f"✓ {predicted_skill}")
        
        # 添加 tool 结果
        messages.append({
            "role": "tool",
            "tool_call_id": tc.id if hasattr(tc, 'id') else "call_1",
            "content": f"已选择 Skill: {predicted_skill}"
        })
        
        # Round 2: 获取工具列表并调用
        print("  [2] 获取工具...", end=" ", flush=True)
        skill_tools = await self._get_skill_tools(predicted_skill)
        
        if not skill_tools:
            print(f"无工具")
            return {
                "skill": predicted_skill,
                "tools": [],
                "tool_calls": tool_calls_history
            }
        
        print(f"✓ {len(skill_tools)}个工具")
        
        # 转换工具格式
        dashscope_tools = self._convert_to_dashscope_tools(skill_tools)
        
        # 让 LLM 选择工具
        print("  [3] 调用工具...", end=" ", flush=True)
        try:
            assistant_msg = self._call_llm(messages, dashscope_tools)
        except Exception as e:
            return {"error": f"工具选择失败: {e}"}
        
        tool_calls = self._extract_tool_calls(assistant_msg)
        
        # 添加 assistant 消息
        msg_dict = {
            "role": "assistant",
            "content": assistant_msg.content if hasattr(assistant_msg, 'content') else ""
        }
        if tool_calls:
            msg_dict["tool_calls"] = []
            for tc in tool_calls:
                msg_dict["tool_calls"].append({
                    "id": tc.id if hasattr(tc, 'id') else f"call_{len(msg_dict['tool_calls']) + 1}",
                    "type": "function",
                    "function": {
                        "name": tc.function.name if hasattr(tc, 'function') else tc.get('function', {}).get('name'),
                        "arguments": tc.function.arguments if hasattr(tc, 'function') else tc.get('function', {}).get('arguments')
                    }
                })
        messages.append(msg_dict)
        
        # 执行工具调用
        if tool_calls:
            for tc in tool_calls:
                func_name = tc.function.name if hasattr(tc, 'function') else tc.get('function', {}).get('name')
                func_args = json.loads(tc.function.arguments if hasattr(tc, 'function') else tc.get('function', {}).get('arguments'))
                
                # 转回原始格式: market_data__get_quote -> market_data.get_quote
                original_tool_name = func_name.replace("__", ".")
                
                # 解析 skill_name 和 tool_name
                if "." in original_tool_name:
                    skill, tname = original_tool_name.split(".", 1)
                else:
                    skill = predicted_skill
                    tname = original_tool_name
                
                # 执行工具
                tool_result = await self._execute_skill(skill, tname, func_args)
                
                print(f"{tname}", end=" ")
                
                # 只记录 tool_name（不含 skill 前缀）以匹配测试用例格式
                tool_calls_history.append({
                    "tool": tname,  # 只记录 get_quote 而不是 market_data.get_quote
                    "full_tool": f"{skill}.{tname}",
                    "arguments": func_args,
                    "result": tool_result
                })
                
                # 添加 tool 结果
                result_content = json.dumps(tool_result, ensure_ascii=False) if not isinstance(tool_result, str) else tool_result
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id if hasattr(tc, 'id') else f"call_{len(messages)}",
                    "content": result_content[:2000]  # 限制长度
                })
        
        # Round 3: 生成最终回答
        print("✓ 生成回答")
        try:
            assistant_msg = self._call_llm(messages)
            answer = assistant_msg.content if hasattr(assistant_msg, 'content') else str(assistant_msg)
            # 添加最终回答到 messages
            messages.append({
                "role": "assistant",
                "content": answer
            })
        except Exception as e:
            return {"error": f"生成回答失败: {e}"}
        
        return {
            "skill": predicted_skill,
            "tools": [tc["tool"] for tc in tool_calls_history],
            "tool_calls": tool_calls_history
        }
    
    async def run_single_test(self, test_case: Dict) -> TestResult:
        """执行单个测试用例"""
        test_id = test_case.get('id', 'unknown')
        query = test_case.get('query', '')
        expected_skill = test_case.get('expected_skill', '')
        expected_tools = test_case.get('expected_tools', [])
        
        # 简化的测试开始日志（并发安全）
        print(f"\n📝 [{test_id}] {query[:50]}...")
        
        start_time = time.time()
        
        try:
            # 执行对话流程
            result = await self._run_conversation(query, expected_skill)
            
            latency_ms = int((time.time() - start_time) * 1000)
            
            if "error" in result:
                raise Exception(result["error"])
            
            predicted_skill = result["skill"]
            predicted_tools = result["tools"]
            
            # 简化评估：只关心工具调用是否正确
            skill_correct = (predicted_skill == expected_skill) if expected_skill else (predicted_skill == '' or predicted_skill is None)
            tools_correct = set(predicted_tools) == set(expected_tools) if expected_tools else (len(predicted_tools) == 0)
            execution_success = True  # 能执行到这里就是成功
            
            # 简化记录：只记录工具调用信息，不记录完整对话
            tool_calls_summary = []
            for tc in result.get("tool_calls", []):
                tool_calls_summary.append({
                    "tool": tc.get("tool"),
                    "arguments": tc.get("arguments")
                })
            
            test_result = TestResult(
                test_id=test_id,
                query=query,
                expected_skill=expected_skill,
                predicted_skill=predicted_skill,
                skill_correct=skill_correct,
                expected_tools=expected_tools,
                predicted_tools=predicted_tools,
                tools_correct=tools_correct,
                execution_success=execution_success,
                output_quality_score=10.0 if (skill_correct and tools_correct) else 0.0,
                latency_ms=latency_ms,
                tool_call_count=len(predicted_tools),
                error_occurred=False,
                error_type=None,
                reasoning_quality='good' if (skill_correct and tools_correct) else 'poor',
                raw_response=json.dumps(tool_calls_summary, ensure_ascii=False) if tool_calls_summary else "无工具调用",
                timestamp=datetime.now().isoformat(),
                tool_calls_detail=result.get("tool_calls", []),
                evaluation_mode='simple',
                evaluation_notes=[]
            )
            
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            
            test_result = TestResult(
                test_id=test_id,
                query=query,
                expected_skill=expected_skill,
                predicted_skill='',
                skill_correct=False,
                expected_tools=expected_tools,
                predicted_tools=[],
                tools_correct=False,
                execution_success=False,
                output_quality_score=0.0,
                latency_ms=latency_ms,
                tool_call_count=0,
                error_occurred=True,
                error_type=str(type(e).__name__),
                reasoning_quality='poor',
                raw_response=str(e)[:500],
                timestamp=datetime.now().isoformat(),
                tool_calls_detail=[],
                evaluation_mode='error',
                evaluation_notes=[str(e)]
            )
        
        self._print_result(test_result)
        return test_result
    
    def _infer_skill_from_answer(self, answer: str, query: str) -> str:
        """从回答内容推断使用的 Skill"""
        skill_keywords = {
            'market_data': ['股价', '行情', 'K线', '涨跌', '市值', 'PE', 'PB', '成交量', '股票'],
            'financial_analysis': ['财务', 'ROE', '营收', '净利润', '资产负债', '现金流', '毛利率'],
            'risk_assessment': ['风险', '波动', '回撤', '夏普', '贝塔', 'VaR'],
            'deep_research': ['研报', '研究', '深度', '分析', '竞争格局'],
            'web_research': ['新闻', '资讯', '公告', '舆情', '热点'],
            'data_analysis': ['统计', '计算', '对比', '趋势', '相关性'],
            'sector_analysis': ['行业', '板块', '赛道', '产业链']
        }
        
        scores = {}
        text = answer + query
        for skill, keywords in skill_keywords.items():
            score = sum(1 for kw in keywords if kw in text)
            if score > 0:
                scores[skill] = score
                
        if scores:
            return max(scores, key=scores.get)
        
        return 'unknown'
    
    def _print_result(self, result: TestResult):
        """打印测试结果"""
        status = "✅" if result.execution_success else "❌"
        skill_status = "✅" if result.skill_correct else "❌"
        tool_status = "✅" if result.tools_correct else "❌"
        
        # 单行输出关键结果
        mode_tag = f"[{result.evaluation_mode[:3].upper()}]" if result.evaluation_mode else ""
        print(f"  [{status}] {mode_tag} {result.test_id}: "
              f"Skill{skill_status} {result.predicted_skill} | "
              f"Tool{tool_status} {result.predicted_tools} | "
              f"质量{result.output_quality_score:.1f} | "
              f"耗时{result.latency_ms}ms")
        
        # 如果有评估备注，显示前2条
        if result.evaluation_notes and len(result.evaluation_notes) > 0:
            for note in result.evaluation_notes[:2]:
                print(f"    📝 {note[:80]}...")
        
        # 如果有错误，显示错误信息
        if result.error_occurred:
            print(f"    ⚠️ 错误: {result.error_type} - {result.raw_response[:100]}")
    
    async def run_all_tests(self, test_cases: List[Dict]) -> Dict[str, Any]:
        """运行所有测试用例（串行执行）
        
        Args:
            test_cases: 测试用例列表
        """
        print("\n" + "="*60)
        print("开始运行 MCP Server Benchmark")
        print(f"模型: {self.model}")
        print(f"总测试数: {len(test_cases)}")
        print("="*60)
        
        # 串行执行测试
        for i, test_case in enumerate(test_cases, 1):
            # 每个测试用例独立初始化 MCP Client
            await self.init_mcp()
            try:
                result = await self.run_single_test(test_case)
                self.results.append(result)
            finally:
                await self.close_mcp()
            
            print(f"\n📊 进度: {i}/{len(test_cases)} 完成")
        
        return self._generate_report()
    
    def _generate_report(self) -> Dict[str, Any]:
        """生成测试报告（简化版）"""
        total = len(self.results)
        if total == 0:
            return {"error": "No test results"}
        
        skill_correct = sum(1 for r in self.results if r.skill_correct)
        tools_correct = sum(1 for r in self.results if r.tools_correct)
        execution_success = sum(1 for r in self.results if r.execution_success)
        error_count = sum(1 for r in self.results if r.error_occurred)
        
        return {
            "timestamp": datetime.now().isoformat(),
            "model": self.model,
            "total_tests": total,
            "summary": {
                "skill_selection_accuracy": skill_correct / total,
                "tool_selection_accuracy": tools_correct / total,
                "execution_success_rate": execution_success / total,
                "error_rate": error_count / total,
            },
            "metrics": {
                "skill_correct": skill_correct,
                "tools_correct": tools_correct,
                "execution_success": execution_success,
                "errors": error_count,
            },
            "results": [asdict(r) for r in self.results]
        }
    
    def save_report(self, report: Dict[str, Any], filepath: str):
        """保存测试报告"""
        # 确保目录存在
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\n✅ 报告已保存: {filepath}")
    
    def print_summary(self, report: Dict[str, Any]):
        """打印汇总报告"""
        summary = report['summary']
        
        print("\n" + "="*60)
        print("📊 测试报告汇总")
        print("="*60)
        print(f"模型: {report.get('model', 'unknown')}")
        print(f"总测试数: {report['total_tests']}")
        
        print(f"\n核心指标:")
        print(f"  Skill选择准确率: {summary['skill_selection_accuracy']*100:.1f}%")
        print(f"  Tool选择准确率: {summary['tool_selection_accuracy']*100:.1f}%")
        print(f"  执行成功率: {summary['execution_success_rate']*100:.1f}%")
        print(f"  错误率: {summary['error_rate']*100:.1f}%")
        
        # 打印失败测试的详细分析
        failed_results = [r for r in self.results if not r.skill_correct or not r.tools_correct or r.error_occurred]
        if failed_results:
            print(f"\n{'='*60}")
            print(f"🔍 失败/不匹配测试详细分析 ({len(failed_results)}个)")
            print(f"{'='*60}")
            for r in failed_results:
                print(f"\n测试ID: {r.test_id}")
                print(f"查询: {r.query}")
                print(f"期望Skill: {r.expected_skill} | 实际: {r.predicted_skill} {'✅' if r.skill_correct else '❌'}")
                print(f"期望Tools: {r.expected_tools} | 实际: {r.predicted_tools} {'✅' if r.tools_correct else '❌'}")
                
                if r.tool_calls_detail:
                    print("工具调用链:")
                    for i, tc in enumerate(r.tool_calls_detail, 1):
                        tool_name = tc.get('full_tool', tc.get('tool', 'unknown'))
                        print(f"  [{i}] {tool_name}")
                else:
                    print("工具调用链: 无")
                print("-" * 60)
        
        print("="*60)


async def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='GLM5 MCP Server Benchmark')
    parser.add_argument('--model', default='glm-4-plus',
                        help='模型名称 (默认: glm-4-plus)')
    parser.add_argument('--provider', default='auto',
                        choices=['auto', 'zhipu', 'dashscope', 'openai'],
                        help='API 提供商 (默认: auto 自动检测)')
    parser.add_argument('--test-file', default=None,
                        help='测试用例文件路径')
    parser.add_argument('--max-tests', type=int, default=None,
                        help='最大测试数量')
    parser.add_argument('--api-key', default=None,
                        help='API Key (默认从环境变量读取)')
    args = parser.parse_args()
    
    # 测试用例文件路径
    if args.test_file:
        test_cases_file = args.test_file
    else:
        # 默认使用 testcases 目录下的测试用例
        test_cases_file = os.path.join(
            os.path.dirname(__file__),
            'testcases',
            'phase1_single_tool_calls.jsonl'
        )
    
    # 创建 runner
    runner = GLM5MCPRunner(
        model=args.model,
        api_key=args.api_key,
        provider=args.provider
    )
    
    # 加载测试用例
    if not os.path.exists(test_cases_file):
        print(f"❌ 错误: 测试用例文件不存在: {test_cases_file}")
        return
    
    test_cases = runner.load_test_cases(test_cases_file)
    print(f"✅ 加载了 {len(test_cases)} 个测试用例")
    
    # 限制测试数量
    if args.max_tests and args.max_tests > 0:
        test_cases = test_cases[:args.max_tests]
        print(f"⚠️  限制测试数量: {len(test_cases)}")
    
    # 运行测试
    report = await runner.run_all_tests(test_cases)
    
    # 打印汇总
    runner.print_summary(report)
    
    # 保存报告
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_file = os.path.join(
        os.path.dirname(__file__),
        'reports',
        f'benchmark_{args.model}_{timestamp}.json'
    )
    runner.save_report(report, report_file)
    print(f"\n🎉 测试完成！")


if __name__ == '__main__':
    asyncio.run(main())

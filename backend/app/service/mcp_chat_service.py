# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""
MCP Chat Service - 基于 MCP Tools 的聊天服务

提供 qwen LLM + MCP Tools 的完整 function calling 集成。
参考 test_real_e2e.py 的实现，封装为可重用的服务。
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
    MCP Chat Service - 基于 MCP Tools 的对话服务

    功能：
    1. 连接 MCP Server，获取所有可用工具
    2. 将 MCP 工具转换为 qwen function calling 格式
    3. 调用 qwen 模型，支持完整的 function calling 流程
    4. 自动处理工具调用和结果返回
    5. 支持流式输出
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
        """
        初始化 MCP Chat Service

        Args:
            mcp_server_path: MCP Server 脚本路径（默认自动推断）
            model: qwen 模型名称（默认 qwen-max）
            api_key: DashScope API Key（默认从环境变量读取）
            connect_timeout: MCP 连接超时时间（秒）
            call_timeout: MCP 工具调用超时时间（秒）
            max_iterations: 最大 function calling 迭代次数
        """
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
            # 自动推断 MCP Server 路径
            current_dir = os.path.dirname(os.path.abspath(__file__))
            backend_dir = os.path.dirname(current_dir)
            mcp_server_path = os.path.join(backend_dir, "app/mcp_server/server.py")

        self.mcp_server_path = mcp_server_path
        self.connect_timeout = connect_timeout
        self.call_timeout = call_timeout
        self.max_iterations = max_iterations

        # 运行时状态
        self.mcp_client: Optional[MCPClient] = None
        self.tools_list: List[Dict] = []
        self.is_connected = False

        logger.info(f"MCP Chat Service 初始化: model={model}, server={mcp_server_path}")

    async def connect(self) -> bool:
        """
        连接到 MCP Server 并获取工具列表

        Returns:
            bool: 连接是否成功
        """
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

            # 获取工具列表
            tools_result = await self.mcp_client.list_tools()
            if not tools_result.get("success"):
                logger.error(f"获取工具列表失败: {tools_result.get('error')}")
                return False

            self.tools_list = tools_result.get("tools", [])
            self.is_connected = True

            logger.info(f"✅ MCP Client 连接成功，发现 {len(self.tools_list)} 个工具")
            for tool in self.tools_list:
                logger.debug(f"  - {tool['name']}: {tool['description'][:60]}...")

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

    def mcp_tool_to_qwen_function(self, mcp_tool: Dict) -> Dict:
        """
        将 MCP 工具格式转换为 qwen function calling 格式

        Args:
            mcp_tool: MCP 工具定义

        Returns:
            qwen function 格式
        """
        # qwen 的 function name 不能有 "."，用 "__" 替代
        qwen_name = mcp_tool["name"].replace(".", "__")

        return {
            "type": "function",
            "function": {
                "name": qwen_name,
                "description": mcp_tool["description"],
                "parameters": mcp_tool["inputSchema"]
            }
        }

    def qwen_function_to_mcp_tool(self, qwen_name: str) -> str:
        """将 qwen function name 转回 MCP tool name"""
        return qwen_name.replace("__", ".")

    async def call_mcp_tool(self, tool_name: str, arguments: Dict) -> Any:
        """
        调用 MCP 工具

        Args:
            tool_name: MCP 工具名称
            arguments: 工具参数

        Returns:
            工具执行结果
        """
        if not self.is_connected:
            logger.error("MCP Client 未连接")
            return {"error": "MCP Client 未连接"}

        logger.info(f"调用 MCP 工具: {tool_name}")
        logger.debug(f"  参数: {json.dumps(arguments, ensure_ascii=False)}")

        result = await self.mcp_client.call_tool(tool_name, arguments)

        if result.get("success"):
            logger.info(f"  ✅ 成功")
            return result["data"]
        else:
            error = result.get("error", "未知错误")
            logger.error(f"  ❌ 失败: {error}")
            return {"error": error}

    async def chat(
        self,
        user_question: str,
        system_prompt: Optional[str] = None,
        conversation_history: Optional[List[Dict]] = None
    ) -> str:
        """
        发送问题给 qwen，使用 MCP Tools

        Args:
            user_question: 用户问题
            system_prompt: 系统提示词（可选）
            conversation_history: 对话历史（可选）

        Returns:
            qwen 的最终回答
        """
        if not self.is_connected:
            await self.connect()

        # 准备工具列表
        qwen_tools = [self.mcp_tool_to_qwen_function(tool) for tool in self.tools_list]

        # 准备消息
        messages = []

        # 添加系统提示词
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        else:
            messages.append({
                "role": "system",
                "content": "你是一个专业的金融投资分析师。你可以使用提供的工具来查询股票数据、分析财务指标和评估风险。请基于真实数据给出专业、客观的投资建议。"
            })

        # 添加对话历史
        if conversation_history:
            messages.extend(conversation_history)

        # 添加用户问题
        messages.append({"role": "user", "content": user_question})

        # 开始 function calling 循环
        iteration = 0
        while iteration < self.max_iterations:
            iteration += 1
            logger.info(f"迭代 {iteration}: 调用 qwen-{self.model}...")

            try:
                response = Generation.call(
                    model=self.model,
                    messages=messages,
                    tools=qwen_tools,
                    result_format='message'
                )

                if response.status_code != 200:
                    raise RuntimeError(f"qwen API 调用失败: {response.code} - {response.message}")

                assistant_message = response.output.choices[0].message

                # 检查是否有 tool_calls
                tool_calls = None
                if hasattr(assistant_message, 'get'):
                    tool_calls = assistant_message.get('tool_calls')
                elif hasattr(assistant_message, 'tool_calls'):
                    try:
                        tool_calls = assistant_message.tool_calls
                    except (AttributeError, KeyError):
                        tool_calls = None

                # 将 assistant 消息加入对话历史
                messages.append({
                    "role": assistant_message.get('role', 'assistant') if hasattr(assistant_message, 'get') else assistant_message.role,
                    "content": assistant_message.get('content', '') if hasattr(assistant_message, 'get') else (assistant_message.content or ''),
                    "tool_calls": tool_calls
                })

                # 处理 tool_calls
                if tool_calls:
                    logger.info(f"qwen 请求调用 {len(tool_calls)} 个工具")

                    for tool_call in tool_calls:
                        # 解析 tool_call
                        if isinstance(tool_call, dict):
                            function_name = tool_call['function']['name']
                            function_args = json.loads(tool_call['function']['arguments'])
                        else:
                            function_name = tool_call.function.name
                            function_args = json.loads(tool_call.function.arguments)

                        # 转换为 MCP tool name
                        mcp_tool_name = self.qwen_function_to_mcp_tool(function_name)

                        logger.info(f"  工具: {mcp_tool_name}")
                        logger.debug(f"  参数: {json.dumps(function_args, ensure_ascii=False)}")

                        # 调用 MCP 工具
                        tool_result = await self.call_mcp_tool(mcp_tool_name, function_args)

                        # 将工具结果加入消息历史
                        messages.append({
                            "role": "tool",
                            "name": function_name,
                            "content": json.dumps(tool_result, ensure_ascii=False)
                        })

                    # 继续下一轮迭代
                    continue

                else:
                    # 没有 tool_calls，生成了最终回答
                    final_content = assistant_message.get('content', '') if hasattr(assistant_message, 'get') else (assistant_message.content or '')
                    logger.info(f"✅ qwen 生成最终回答 (迭代 {iteration} 次)")
                    return final_content

            except Exception as e:
                logger.error(f"调用 qwen 时出错: {e}")
                raise

        # 达到最大迭代次数
        logger.warning(f"达到最大迭代次数 {self.max_iterations}")
        return "抱歉，分析过程超时，请稍后重试。"

    async def chat_stream(
        self,
        user_question: str,
        system_prompt: Optional[str] = None,
        conversation_history: Optional[List[Dict]] = None
    ) -> AsyncGenerator[str, None]:
        """
        流式对话（暂不支持 function calling 流式）

        Args:
            user_question: 用户问题
            system_prompt: 系统提示词
            conversation_history: 对话历史

        Yields:
            流式输出的文本片段
        """
        # 注意：qwen 的 function calling 暂不支持流式输出
        # 这里先返回完整结果
        result = await self.chat(user_question, system_prompt, conversation_history)
        yield result

    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.disconnect()


# 便捷函数：快速调用
async def mcp_chat(
    question: str,
    model: str = "qwen-max",
    system_prompt: Optional[str] = None
) -> str:
    """
    便捷函数：快速调用 MCP Chat Service

    Args:
        question: 用户问题
        model: qwen 模型名称
        system_prompt: 系统提示词

    Returns:
        qwen 的回答

    Example:
        >>> answer = await mcp_chat("查一下茅台近期的股市表现，值不值得买")
        >>> print(answer)
    """
    async with MCPChatService(model=model) as service:
        return await service.chat(question, system_prompt=system_prompt)

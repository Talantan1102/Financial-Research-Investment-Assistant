"""
MCP Client - 连接到 MCP Server 的 STDIO 客户端

提供与 MCP Server 的连接管理、工具列表和工具调用功能。
支持异步操作、超时控制和完善的错误处理。
"""

import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPClient:
    """
    MCP Client - 通过 STDIO 连接到 MCP Server

    特性：
    - 异步连接管理
    - 工具列表查询
    - 工具调用（带超时控制）
    - 线程安全（使用 asyncio.Lock）
    - 详细的错误处理和日志记录

    使用示例：
        client = MCPClient("backend/app/mcp_server/server.py")
        await client.connect()

        result = await client.call_tool(
            "market_data.get_quote",
            {"symbol": "600519"}
        )

        await client.disconnect()
    """

    def __init__(
        self,
        server_script_path: str,
        python_executable: str = "python3",
        connect_timeout: float = 30.0,
        call_timeout: float = 30.0
    ):
        """
        初始化 MCP Client

        Args:
            server_script_path: MCP Server 脚本路径（server.py）
            python_executable: Python 解释器路径（默认 "python3"）
            connect_timeout: 连接超时时间（秒，默认 30.0）
            call_timeout: 工具调用超时时间（秒，默认 30.0）
        """
        self.server_script_path = os.path.abspath(server_script_path)
        self.python_executable = python_executable
        self.connect_timeout = connect_timeout
        self.call_timeout = call_timeout

        # 连接状态
        self._session: Optional[ClientSession] = None
        self._stdio_context = None
        self._connected = False
        self._lock = asyncio.Lock()

        # 日志
        self.logger = logging.getLogger("MCPClient")

    async def connect(self) -> bool:
        """
        连接到 MCP Server

        使用 STDIO 传输启动 MCP Server 进程并建立会话。
        如果已连接，直接返回 True。

        Returns:
            bool: 连接是否成功
        """
        async with self._lock:
            if self._connected:
                self.logger.info("MCP Client 已连接，跳过重复连接")
                return True

            try:
                self.logger.info(f"正在连接 MCP Server: {self.server_script_path}")

                # 检查服务器脚本是否存在
                if not os.path.exists(self.server_script_path):
                    self.logger.error(f"MCP Server 脚本不存在: {self.server_script_path}")
                    return False

                # 配置 STDIO 服务器参数
                server_params = StdioServerParameters(
                    command=self.python_executable,
                    args=[self.server_script_path],
                    env=None  # 继承当前环境变量
                )

                # 启动 STDIO 客户端
                self._stdio_context = stdio_client(server_params)
                read_stream, write_stream = await self._stdio_context.__aenter__()

                # 创建会话并初始化
                self._session = ClientSession(read_stream, write_stream)
                await asyncio.wait_for(
                    self._session.initialize(),
                    timeout=self.connect_timeout
                )

                self._connected = True
                self.logger.info("MCP Client 连接成功")
                return True

            except asyncio.TimeoutError:
                self.logger.error(
                    f"MCP Server 连接超时 ({self.connect_timeout}s)"
                )
                await self._cleanup_failed_connection()
                return False

            except FileNotFoundError as e:
                self.logger.error(f"找不到 Python 解释器或脚本: {e}")
                await self._cleanup_failed_connection()
                return False

            except Exception as e:
                self.logger.error(f"MCP Client 连接失败: {type(e).__name__}: {e}")
                await self._cleanup_failed_connection()
                return False

    async def _cleanup_failed_connection(self):
        """清理失败的连接尝试"""
        try:
            if self._stdio_context:
                await self._stdio_context.__aexit__(None, None, None)
        except Exception as e:
            self.logger.warning(f"清理失败连接时出错: {e}")
        finally:
            self._stdio_context = None
            self._session = None
            self._connected = False

    async def disconnect(self):
        """
        断开与 MCP Server 的连接

        关闭 STDIO 连接并释放资源。
        """
        async with self._lock:
            if not self._connected:
                self.logger.debug("MCP Client 未连接，跳过断开")
                return

            try:
                self.logger.info("正在断开 MCP Server 连接")

                if self._stdio_context:
                    await self._stdio_context.__aexit__(None, None, None)

                self._connected = False
                self._session = None
                self._stdio_context = None
                self.logger.info("MCP Client 已断开连接")

            except Exception as e:
                self.logger.error(f"断开连接时出错: {e}")
                # 强制重置状态
                self._connected = False
                self._session = None
                self._stdio_context = None

    @property
    def is_connected(self) -> bool:
        """
        检查连接状态

        Returns:
            bool: 是否已连接到 MCP Server
        """
        return self._connected

    async def list_tools(self) -> Dict[str, Any]:
        """
        列出 MCP Server 提供的所有工具

        Returns:
            Dict[str, Any]: 格式为 {"success": bool, "tools": [...], "error": str}
            - success: 是否成功
            - tools: 工具列表（成功时）
            - error: 错误信息（失败时）
        """
        if not self._connected:
            return {
                "success": False,
                "error": "未连接到 MCP Server",
                "tools": []
            }

        try:
            self.logger.debug("正在列出 MCP 工具")

            response = await asyncio.wait_for(
                self._session.list_tools(),
                timeout=self.call_timeout
            )

            tools = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.inputSchema
                }
                for tool in response.tools
            ]

            self.logger.info(f"成功列出 {len(tools)} 个 MCP 工具")
            return {
                "success": True,
                "tools": tools,
                "error": None
            }

        except asyncio.TimeoutError:
            error_msg = f"列出工具超时 ({self.call_timeout}s)"
            self.logger.error(error_msg)
            return {
                "success": False,
                "error": error_msg,
                "tools": []
            }

        except Exception as e:
            error_msg = f"列出工具失败: {type(e).__name__}: {e}"
            self.logger.error(error_msg)
            return {
                "success": False,
                "error": str(e),
                "tools": []
            }

    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        调用 MCP 工具

        Args:
            tool_name: 工具名称（格式: "skill_name.tool_name"，如 "market_data.get_quote"）
            arguments: 工具参数（字典格式）

        Returns:
            Dict[str, Any]: 工具返回结果，格式为 {"success": bool, "data": Any, "error": str}
            - success: 是否成功
            - data: 返回数据（成功时）
            - error: 错误信息（失败时）
        """
        if not self._connected:
            return {
                "success": False,
                "data": None,
                "error": "未连接到 MCP Server"
            }

        try:
            self.logger.info(f"调用 MCP 工具: {tool_name}")
            self.logger.debug(f"工具参数: {arguments}")

            # 调用工具（带超时）
            result = await asyncio.wait_for(
                self._session.call_tool(tool_name, arguments),
                timeout=self.call_timeout
            )

            # 解析返回内容
            # MCP 返回格式: CallToolResult with content: List[TextContent | ImageContent | ...]
            if not result.content or len(result.content) == 0:
                self.logger.warning(f"工具 {tool_name} 返回为空")
                return {
                    "success": False,
                    "data": None,
                    "error": "工具返回为空"
                }

            # 获取第一个内容块（通常是文本）
            first_content = result.content[0]

            # 检查是否有文本内容
            if not hasattr(first_content, 'text'):
                self.logger.error(f"工具返回不包含文本内容: {type(first_content)}")
                return {
                    "success": False,
                    "data": None,
                    "error": "工具返回格式错误（无文本内容）"
                }

            response_text = first_content.text

            # 尝试解析 JSON
            try:
                response_data = json.loads(response_text)
            except json.JSONDecodeError as e:
                self.logger.error(f"解析工具返回 JSON 失败: {e}")
                self.logger.debug(f"原始返回: {response_text}")
                return {
                    "success": False,
                    "data": None,
                    "error": f"解析返回数据失败: {e}"
                }

            # 验证返回格式
            if not isinstance(response_data, dict):
                self.logger.error(f"工具返回不是字典: {type(response_data)}")
                return {
                    "success": False,
                    "data": None,
                    "error": "工具返回格式错误（非字典）"
                }

            # 记录成功日志
            if response_data.get("success"):
                self.logger.info(f"工具 {tool_name} 调用成功")
            else:
                self.logger.warning(
                    f"工具 {tool_name} 返回失败: {response_data.get('error')}"
                )

            return response_data

        except asyncio.TimeoutError:
            error_msg = f"工具调用超时 ({self.call_timeout}s)"
            self.logger.error(f"{error_msg}: {tool_name}")
            return {
                "success": False,
                "data": None,
                "error": error_msg
            }

        except Exception as e:
            error_msg = f"工具调用失败: {type(e).__name__}: {e}"
            self.logger.error(f"{error_msg} - 工具: {tool_name}")
            return {
                "success": False,
                "data": None,
                "error": str(e)
            }

    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.disconnect()

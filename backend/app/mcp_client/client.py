"""
MCP Client - 连接到 MCP Server 的 STDIO 客户端

提供与 MCP Server 的连接管理、工具列表和工具调用功能。
支持异步操作、超时控制和完善的错误处理。
"""

import asyncio
import json
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MCPClient")


@asynccontextmanager
async def mcp_client_context(
    server_script_path: str, python_executable: str = "python3", connect_timeout: float = 30.0
) -> AsyncGenerator[ClientSession, None]:
    """
    MCP Client 异步上下文管理器

    使用示例：
        async with mcp_client_context("backend/app/mcp_server/server.py") as session:
            tools = await session.list_tools()
            result = await session.call_tool("market_data.get_quote", {"symbol": "600519"})
    """
    server_script_path = os.path.abspath(server_script_path)

    if not os.path.exists(server_script_path):
        raise FileNotFoundError(f"MCP Server 脚本不存在: {server_script_path}")

    # 计算正确的工作目录
    # server_script_path = .../backend/app/mcp_server/server.py
    # server_dir = .../backend/app/mcp_server
    # app_dir = .../backend/app
    # backend_dir = .../backend
    # cwd = .../项目根目录
    server_dir = os.path.dirname(server_script_path)  # backend/app/mcp_server
    app_dir = os.path.dirname(server_dir)  # backend/app
    backend_dir = os.path.dirname(app_dir)  # backend
    cwd = os.path.dirname(backend_dir)  # 项目根目录

    env_vars = os.environ.copy()

    # 确保 PYTHONPATH 包含 backend 目录
    if "PYTHONPATH" in env_vars:
        env_vars["PYTHONPATH"] = f"{backend_dir}:{env_vars['PYTHONPATH']}"
    else:
        env_vars["PYTHONPATH"] = backend_dir

    server_params = StdioServerParameters(
        command=python_executable, args=[server_script_path], env=env_vars, cwd=cwd
    )

    logger.info(f"正在连接 MCP Server: {server_script_path}")

    async with stdio_client(server_params) as (read_stream, write_stream):  # noqa: SIM117 — inline comment describes inner ctx
        # 关键：ClientSession 需要在 async with 上下文中使用，才能启动 _receive_loop
        async with ClientSession(read_stream, write_stream) as session:
            logger.info("正在初始化会话...")
            await asyncio.wait_for(session.initialize(), timeout=connect_timeout)
            logger.info("✅ MCP Client 连接成功")

            yield session


class MCPClient:
    """
    MCP Client - 通过 STDIO 连接到 MCP Server

    注意：此类现在只是 mcp_client_context 的包装器，建议使用上下文管理器方式。

    推荐使用方式：
        async with mcp_client_context(server_path) as session:
            tools = await session.list_tools()
            result = await session.call_tool(tool_name, arguments)
    """

    def __init__(
        self,
        server_script_path: str,
        python_executable: str = "python3",
        connect_timeout: float = 30.0,
        call_timeout: float = 30.0,
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
        self._session: ClientSession | None = None
        self._context_stack = None
        self._connected = False
        self._lock = asyncio.Lock()

    async def connect(self) -> bool:
        """
        连接到 MCP Server

        注意：此方法现在会启动一个内部上下文管理器来保持连接。
        建议使用 async with mcp_client_context() 方式替代。

        Returns:
            bool: 连接是否成功
        """
        async with self._lock:
            if self._connected:
                return True

            try:
                # 创建上下文管理器
                self._client_context = mcp_client_context(
                    self.server_script_path, self.python_executable, self.connect_timeout
                )
                # 手动进入上下文
                self._session = await self._client_context.__aenter__()
                self._connected = True
                return True

            except Exception as e:
                logger.error(f"MCP Client 连接失败: {e}")
                self._connected = False
                self._session = None
                return False

    async def disconnect(self):
        """
        断开与 MCP Server 的连接
        """
        async with self._lock:
            if not self._connected:
                return

            try:
                if self._client_context:
                    await self._client_context.__aexit__(None, None, None)
            except Exception as e:
                logger.error(f"断开连接时出错: {e}")
            finally:
                self._connected = False
                self._session = None
                self._client_context = None

    @property
    def is_connected(self) -> bool:
        """
        检查连接状态

        Returns:
            bool: 是否已连接到 MCP Server
        """
        return self._connected

    async def list_tools(self) -> dict[str, Any]:
        """
        列出 MCP Server 提供的所有工具

        Returns:
            Dict[str, Any]: 格式为 {"success": bool, "tools": [...], "error": str}
        """
        if not self._connected or not self._session:
            return {"success": False, "error": "未连接到 MCP Server", "tools": []}

        try:
            response = await asyncio.wait_for(self._session.list_tools(), timeout=self.call_timeout)

            tools = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.inputSchema,
                }
                for tool in response.tools
            ]

            return {"success": True, "tools": tools, "error": None}

        except Exception as e:
            return {"success": False, "error": str(e), "tools": []}

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """
        调用 MCP 工具

        Args:
            tool_name: 工具名称（格式: "skill_name.tool_name"）
            arguments: 工具参数（字典格式）

        Returns:
            Dict[str, Any]: 工具返回结果
        """
        if not self._connected or not self._session:
            return {"success": False, "data": None, "error": "未连接到 MCP Server"}

        try:
            result = await asyncio.wait_for(
                self._session.call_tool(tool_name, arguments), timeout=self.call_timeout
            )

            if not result.content or len(result.content) == 0:
                return {"success": False, "data": None, "error": "工具返回为空"}

            first_content = result.content[0]

            if not hasattr(first_content, "text"):
                return {"success": False, "data": None, "error": "工具返回格式错误（无文本内容）"}

            response_text = first_content.text

            try:
                response_data = json.loads(response_text)
            except json.JSONDecodeError as e:
                return {"success": False, "data": None, "error": f"解析返回数据失败: {e}"}

            return response_data

        except TimeoutError:
            return {"success": False, "data": None, "error": f"工具调用超时 ({self.call_timeout}s)"}

        except Exception as e:
            return {"success": False, "data": None, "error": str(e)}

    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.disconnect()


# 向后兼容
__all__ = ["MCPClient", "mcp_client_context"]

"""
MCP Client 单元测试

测试 MCPClient 的连接、断开、工具列表和工具调用功能。
"""

import asyncio
import os
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from app.mcp_client.client import MCPClient


class TestMCPClient:
    """MCP Client 单元测试"""

    @pytest.fixture
    def mock_session(self):
        """创建模拟的 ClientSession"""
        session = AsyncMock()
        session.initialize = AsyncMock()
        session.list_tools = AsyncMock()
        session.call_tool = AsyncMock()
        return session

    @pytest.fixture
    def mock_stdio_context(self, mock_session):
        """创建模拟的 STDIO 上下文"""
        context = AsyncMock()
        context.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
        context.__aexit__ = AsyncMock()
        return context

    @pytest.fixture
    def client(self):
        """创建 MCPClient 实例"""
        return MCPClient(
            server_script_path="backend/app/mcp_server/server.py",
            connect_timeout=5.0,
            call_timeout=5.0
        )

    @pytest.mark.asyncio
    async def test_init(self, client):
        """测试初始化"""
        assert client.server_script_path.endswith("server.py")
        assert client.python_executable == "python"
        assert client.connect_timeout == 5.0
        assert client.call_timeout == 5.0
        assert not client.is_connected

    @pytest.mark.asyncio
    async def test_connect_success(self, client, mock_stdio_context, mock_session):
        """测试成功连接"""
        with patch('app.mcp_client.client.stdio_client', return_value=mock_stdio_context):
            with patch('app.mcp_client.client.ClientSession', return_value=mock_session):
                # 模拟服务器脚本存在
                with patch('os.path.exists', return_value=True):
                    result = await client.connect()

                    assert result is True
                    assert client.is_connected
                    mock_session.initialize.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_file_not_found(self, client):
        """测试连接失败 - 文件不存在"""
        with patch('os.path.exists', return_value=False):
            result = await client.connect()

            assert result is False
            assert not client.is_connected

    @pytest.mark.asyncio
    async def test_connect_timeout(self, client, mock_stdio_context, mock_session):
        """测试连接超时"""
        # 模拟初始化超时
        mock_session.initialize.side_effect = asyncio.TimeoutError()

        with patch('app.mcp_client.client.stdio_client', return_value=mock_stdio_context):
            with patch('app.mcp_client.client.ClientSession', return_value=mock_session):
                with patch('os.path.exists', return_value=True):
                    result = await client.connect()

                    assert result is False
                    assert not client.is_connected

    @pytest.mark.asyncio
    async def test_connect_duplicate(self, client, mock_stdio_context, mock_session):
        """测试重复连接"""
        with patch('app.mcp_client.client.stdio_client', return_value=mock_stdio_context):
            with patch('app.mcp_client.client.ClientSession', return_value=mock_session):
                with patch('os.path.exists', return_value=True):
                    # 第一次连接
                    await client.connect()

                    # 第二次连接应该直接返回成功
                    result = await client.connect()
                    assert result is True

                    # initialize 只应该调用一次
                    assert mock_session.initialize.call_count == 1

    @pytest.mark.asyncio
    async def test_disconnect(self, client, mock_stdio_context, mock_session):
        """测试断开连接"""
        with patch('app.mcp_client.client.stdio_client', return_value=mock_stdio_context):
            with patch('app.mcp_client.client.ClientSession', return_value=mock_session):
                with patch('os.path.exists', return_value=True):
                    # 先连接
                    await client.connect()
                    assert client.is_connected

                    # 断开连接
                    await client.disconnect()
                    assert not client.is_connected
                    mock_stdio_context.__aexit__.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_not_connected(self, client):
        """测试断开未连接的客户端"""
        # 不应该抛出异常
        await client.disconnect()
        assert not client.is_connected

    @pytest.mark.asyncio
    async def test_list_tools_not_connected(self, client):
        """测试未连接时列出工具"""
        result = await client.list_tools()

        assert result["success"] is False
        assert "未连接" in result["error"]
        assert result["tools"] == []

    @pytest.mark.asyncio
    async def test_list_tools_success(self, client, mock_stdio_context, mock_session):
        """测试成功列出工具"""
        # 模拟工具列表返回
        mock_tool1 = MagicMock()
        mock_tool1.name = "market_data.get_quote"
        mock_tool1.description = "获取股票行情"
        mock_tool1.inputSchema = {"type": "object"}

        mock_tool2 = MagicMock()
        mock_tool2.name = "market_data.search_stock"
        mock_tool2.description = "搜索股票"
        mock_tool2.inputSchema = {"type": "object"}

        mock_response = MagicMock()
        mock_response.tools = [mock_tool1, mock_tool2]
        mock_session.list_tools.return_value = mock_response

        with patch('app.mcp_client.client.stdio_client', return_value=mock_stdio_context):
            with patch('app.mcp_client.client.ClientSession', return_value=mock_session):
                with patch('os.path.exists', return_value=True):
                    # 连接
                    await client.connect()

                    # 列出工具
                    result = await client.list_tools()

                    assert result["success"] is True
                    assert len(result["tools"]) == 2
                    assert result["tools"][0]["name"] == "market_data.get_quote"
                    assert result["tools"][1]["name"] == "market_data.search_stock"

    @pytest.mark.asyncio
    async def test_call_tool_not_connected(self, client):
        """测试未连接时调用工具"""
        result = await client.call_tool("market_data.get_quote", {"symbol": "600519"})

        assert result["success"] is False
        assert "未连接" in result["error"]
        assert result["data"] is None

    @pytest.mark.asyncio
    async def test_call_tool_success(self, client, mock_stdio_context, mock_session):
        """测试成功调用工具"""
        # 模拟工具返回
        mock_content = MagicMock()
        mock_content.text = '{"success": true, "data": {"name": "贵州茅台", "price": "1800.00"}}'

        mock_result = MagicMock()
        mock_result.content = [mock_content]
        mock_session.call_tool.return_value = mock_result

        with patch('app.mcp_client.client.stdio_client', return_value=mock_stdio_context):
            with patch('app.mcp_client.client.ClientSession', return_value=mock_session):
                with patch('os.path.exists', return_value=True):
                    # 连接
                    await client.connect()

                    # 调用工具
                    result = await client.call_tool(
                        "market_data.get_quote",
                        {"symbol": "600519"}
                    )

                    assert result["success"] is True
                    assert result["data"]["name"] == "贵州茅台"
                    assert result["data"]["price"] == "1800.00"

    @pytest.mark.asyncio
    async def test_call_tool_timeout(self, client, mock_stdio_context, mock_session):
        """测试工具调用超时"""
        mock_session.call_tool.side_effect = asyncio.TimeoutError()

        with patch('app.mcp_client.client.stdio_client', return_value=mock_stdio_context):
            with patch('app.mcp_client.client.ClientSession', return_value=mock_session):
                with patch('os.path.exists', return_value=True):
                    # 连接
                    await client.connect()

                    # 调用工具
                    result = await client.call_tool(
                        "market_data.get_quote",
                        {"symbol": "600519"}
                    )

                    assert result["success"] is False
                    assert "超时" in result["error"]

    @pytest.mark.asyncio
    async def test_call_tool_empty_response(self, client, mock_stdio_context, mock_session):
        """测试工具返回空内容"""
        mock_result = MagicMock()
        mock_result.content = []
        mock_session.call_tool.return_value = mock_result

        with patch('app.mcp_client.client.stdio_client', return_value=mock_stdio_context):
            with patch('app.mcp_client.client.ClientSession', return_value=mock_session):
                with patch('os.path.exists', return_value=True):
                    # 连接
                    await client.connect()

                    # 调用工具
                    result = await client.call_tool(
                        "market_data.get_quote",
                        {"symbol": "600519"}
                    )

                    assert result["success"] is False
                    assert "返回为空" in result["error"]

    @pytest.mark.asyncio
    async def test_call_tool_invalid_json(self, client, mock_stdio_context, mock_session):
        """测试工具返回无效 JSON"""
        mock_content = MagicMock()
        mock_content.text = 'invalid json {'

        mock_result = MagicMock()
        mock_result.content = [mock_content]
        mock_session.call_tool.return_value = mock_result

        with patch('app.mcp_client.client.stdio_client', return_value=mock_stdio_context):
            with patch('app.mcp_client.client.ClientSession', return_value=mock_session):
                with patch('os.path.exists', return_value=True):
                    # 连接
                    await client.connect()

                    # 调用工具
                    result = await client.call_tool(
                        "market_data.get_quote",
                        {"symbol": "600519"}
                    )

                    assert result["success"] is False
                    assert "解析" in result["error"]

    @pytest.mark.asyncio
    async def test_context_manager(self, client, mock_stdio_context, mock_session):
        """测试上下文管理器"""
        with patch('app.mcp_client.client.stdio_client', return_value=mock_stdio_context):
            with patch('app.mcp_client.client.ClientSession', return_value=mock_session):
                with patch('os.path.exists', return_value=True):
                    async with client as c:
                        assert c.is_connected

                    # 退出后应该断开连接
                    assert not client.is_connected


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

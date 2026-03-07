"""
MCP 集成测试

测试 MCP Client、ToolAdapter 和 DeepScout 的完整集成流程。
"""

import asyncio
import os
import sys
import pytest

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from app.mcp_client.client import MCPClient
from app.mcp_client.adapter import ToolAdapter


class TestMCPIntegration:
    """MCP 集成测试（需要 MCP Server 运行）"""

    @pytest.fixture
    def server_script_path(self):
        """MCP Server 脚本路径"""
        return os.path.abspath(
            os.path.join(
                os.path.dirname(__file__),
                "../mcp_server/server.py"
            )
        )

    @pytest.fixture
    async def mcp_client(self, server_script_path):
        """创建并连接 MCP Client"""
        client = MCPClient(
            server_script_path=server_script_path,
            connect_timeout=10.0,
            call_timeout=10.0
        )
        await client.connect()
        yield client
        await client.disconnect()

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_mcp_server_connection(self, server_script_path):
        """测试 MCP Server 连接"""
        client = MCPClient(server_script_path)

        # 连接
        success = await client.connect()
        assert success, "MCP Server 连接失败"
        assert client.is_connected

        # 断开
        await client.disconnect()
        assert not client.is_connected

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_list_tools(self, mcp_client):
        """测试列出工具"""
        result = await mcp_client.list_tools()

        assert result["success"] is True
        assert len(result["tools"]) > 0

        # 验证工具格式
        tool = result["tools"][0]
        assert "name" in tool
        assert "description" in tool
        assert "inputSchema" in tool

        # 验证 MarketData 工具存在
        tool_names = [t["name"] for t in result["tools"]]
        assert "market_data.get_quote" in tool_names

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_call_get_quote(self, mcp_client):
        """测试调用 get_quote 工具"""
        result = await mcp_client.call_tool(
            "market_data.get_quote",
            {"symbol": "600519"}
        )

        assert result["success"] is True
        assert result["data"] is not None

        # 验证返回数据结构
        data = result["data"]
        assert "gid" in data
        assert "name" in data
        assert "nowPri" in data

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_call_search_stock(self, mcp_client):
        """测试调用 search_stock 工具"""
        result = await mcp_client.call_tool(
            "market_data.search_stock",
            {"keyword": "茅台"}
        )

        assert result["success"] is True
        assert isinstance(result["data"], list)
        assert len(result["data"]) > 0

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_call_get_market_list(self, mcp_client):
        """测试调用 get_market_list 工具"""
        result = await mcp_client.call_tool(
            "market_data.get_market_list",
            {"market": "shanghai", "page": 1}
        )

        assert result["success"] is True
        assert isinstance(result["data"], list)

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_tool_adapter_with_mcp(self, mcp_client):
        """测试 ToolAdapter 使用 MCP"""
        adapter = ToolAdapter(mcp_client=mcp_client, fallback_enabled=True)

        # 验证正在使用 MCP
        assert adapter.is_using_mcp

        # 调用 get_stock_by_code
        result = await adapter.get_stock_by_code("600519")

        assert result["success"] is True
        assert result["data"]["name"] is not None
        assert not adapter.is_degraded

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_tool_adapter_fallback(self):
        """测试 ToolAdapter 降级到 StockService"""
        # 不提供 MCP Client，应该直接使用降级
        adapter = ToolAdapter(mcp_client=None, fallback_enabled=True)

        # 验证不使用 MCP
        assert not adapter.is_using_mcp

        # 调用应该使用 StockService
        result = await adapter.get_stock_by_code("600519")

        # 根据 StockService 是否可用判断结果
        if result["success"]:
            assert result["data"] is not None
        else:
            # StockService 不可用时应该返回错误
            assert "不可用" in result["error"]

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_mcp_server_invalid_tool(self, mcp_client):
        """测试调用不存在的工具"""
        result = await mcp_client.call_tool(
            "market_data.invalid_tool",
            {}
        )

        assert result["success"] is False
        assert "不存在" in result["error"]

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_mcp_server_invalid_arguments(self, mcp_client):
        """测试使用无效参数调用工具"""
        result = await mcp_client.call_tool(
            "market_data.get_quote",
            {}  # 缺少 symbol 参数
        )

        assert result["success"] is False

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_context_manager(self, server_script_path):
        """测试使用上下文管理器"""
        async with MCPClient(server_script_path) as client:
            assert client.is_connected

            # 调用工具
            result = await client.call_tool(
                "market_data.get_quote",
                {"symbol": "600519"}
            )
            assert result["success"] is True

        # 退出后应该断开连接
        assert not client.is_connected

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_concurrent_calls(self, mcp_client):
        """测试并发调用"""
        symbols = ["600519", "000858", "600036"]

        # 并发调用
        tasks = [
            mcp_client.call_tool("market_data.get_quote", {"symbol": symbol})
            for symbol in symbols
        ]
        results = await asyncio.gather(*tasks)

        # 验证所有调用都成功
        for result in results:
            assert result["success"] is True
            assert result["data"] is not None


class TestDeepScoutIntegration:
    """DeepScout 集成 ToolAdapter 测试"""

    @pytest.fixture
    def server_script_path(self):
        """MCP Server 脚本路径"""
        return os.path.abspath(
            os.path.join(
                os.path.dirname(__file__),
                "../mcp_server/server.py"
            )
        )

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_deep_scout_with_tool_adapter(self, server_script_path):
        """测试 DeepScout 使用 ToolAdapter 获取股票数据"""
        # 创建 MCP Client
        mcp_client = MCPClient(server_script_path)
        await mcp_client.connect()

        try:
            # 创建 ToolAdapter
            tool_adapter = ToolAdapter(mcp_client=mcp_client, fallback_enabled=True)

            # 模拟 DeepScout 调用
            result = await tool_adapter.get_stock_by_code("600519")

            assert result["success"] is True
            assert result["data"] is not None
            assert "name" in result["data"]

            # 验证使用的是 MCP
            assert tool_adapter.is_using_mcp

        finally:
            await mcp_client.disconnect()

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_deep_scout_mcp_degradation(self):
        """测试 DeepScout 在 MCP 不可用时的降级"""
        # 使用不存在的路径创建 MCP Client
        mcp_client = MCPClient("invalid/path/to/server.py")
        connected = await mcp_client.connect()

        # 连接应该失败
        assert not connected

        # 创建 ToolAdapter（启用降级）
        tool_adapter = ToolAdapter(mcp_client=mcp_client, fallback_enabled=True)

        # 调用应该降级到 StockService
        result = await tool_adapter.get_stock_by_code("600519")

        # 根据 StockService 是否可用判断结果
        if result["success"]:
            # 降级成功
            assert result["data"] is not None
        else:
            # 降级也失败
            assert "不可用" in result["error"]


if __name__ == "__main__":
    # 只运行集成测试
    pytest.main([__file__, "-v", "-s", "-m", "integration"])

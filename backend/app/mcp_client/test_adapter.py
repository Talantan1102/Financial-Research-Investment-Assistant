"""
ToolAdapter 单元测试

测试 ToolAdapter 的自动降级功能和与 StockService 的兼容性。
"""

import asyncio
import os
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from app.mcp_client.adapter import ToolAdapter


class TestToolAdapter:
    """ToolAdapter 单元测试"""

    @pytest.fixture
    def mock_mcp_client(self):
        """创建模拟的 MCPClient"""
        client = AsyncMock()
        client.is_connected = True
        client.call_tool = AsyncMock()
        return client

    @pytest.fixture
    def mock_stock_service(self):
        """创建模拟的 StockService"""
        service = AsyncMock()
        service.get_stock_by_code = AsyncMock()
        service.search_stock = AsyncMock()
        service.get_market_stocks = AsyncMock()
        return service

    @pytest.fixture
    def adapter_with_mcp(self, mock_mcp_client):
        """创建带 MCP 的 ToolAdapter"""
        return ToolAdapter(mcp_client=mock_mcp_client, fallback_enabled=True)

    @pytest.fixture
    def adapter_without_mcp(self):
        """创建不带 MCP 的 ToolAdapter"""
        return ToolAdapter(mcp_client=None, fallback_enabled=True)

    @pytest.mark.asyncio
    async def test_init_with_mcp(self, mock_mcp_client):
        """测试初始化（带 MCP）"""
        adapter = ToolAdapter(mcp_client=mock_mcp_client, fallback_enabled=True)

        assert adapter.mcp_client is mock_mcp_client
        assert adapter.fallback_enabled is True
        assert not adapter.is_degraded

    @pytest.mark.asyncio
    async def test_init_without_mcp(self):
        """测试初始化（不带 MCP）"""
        adapter = ToolAdapter(mcp_client=None, fallback_enabled=True)

        assert adapter.mcp_client is None
        assert adapter.fallback_enabled is True

    @pytest.mark.asyncio
    async def test_get_stock_by_code_mcp_success(self, adapter_with_mcp, mock_mcp_client):
        """测试 get_stock_by_code - MCP 成功"""
        mock_mcp_client.call_tool.return_value = {
            "success": True,
            "data": {
                "gid": "sh600519",
                "name": "贵州茅台",
                "nowPri": "1800.00",
                "increase": "10.00",
                "increPer": "0.56"
            }
        }

        result = await adapter_with_mcp.get_stock_by_code("600519")

        assert result["success"] is True
        assert result["data"]["name"] == "贵州茅台"
        mock_mcp_client.call_tool.assert_called_once_with(
            "market_data.get_quote",
            {"symbol": "600519"}
        )

    @pytest.mark.asyncio
    async def test_get_stock_by_code_mcp_fail_fallback_success(
        self, adapter_with_mcp, mock_mcp_client, mock_stock_service
    ):
        """测试 get_stock_by_code - MCP 失败，降级成功"""
        # MCP 返回失败
        mock_mcp_client.call_tool.return_value = {
            "success": False,
            "error": "API 错误"
        }

        # 模拟 StockService
        mock_stock_service.get_stock_by_code.return_value = {
            "success": True,
            "data": {
                "gid": "sh600519",
                "name": "贵州茅台",
                "nowPri": "1800.00"
            }
        }

        with patch.object(adapter_with_mcp, '_get_fallback_service', return_value=mock_stock_service):
            result = await adapter_with_mcp.get_stock_by_code("600519")

            assert result["success"] is True
            assert result["data"]["name"] == "贵州茅台"
            mock_stock_service.get_stock_by_code.assert_called_once_with("600519")

    @pytest.mark.asyncio
    async def test_get_stock_by_code_mcp_exception_degraded(
        self, adapter_with_mcp, mock_mcp_client, mock_stock_service
    ):
        """测试 get_stock_by_code - MCP 异常，触发降级模式"""
        # MCP 抛出异常
        mock_mcp_client.call_tool.side_effect = Exception("连接超时")

        # 模拟 StockService
        mock_stock_service.get_stock_by_code.return_value = {
            "success": True,
            "data": {"name": "贵州茅台"}
        }

        with patch.object(adapter_with_mcp, '_get_fallback_service', return_value=mock_stock_service):
            result = await adapter_with_mcp.get_stock_by_code("600519")

            # 应该触发降级
            assert adapter_with_mcp.is_degraded
            assert result["success"] is True

            # 第二次调用应该直接使用 StockService
            result2 = await adapter_with_mcp.get_stock_by_code("000858")
            assert result2["success"] is True
            # MCP 只调用一次（第二次直接降级）
            assert mock_mcp_client.call_tool.call_count == 1

    @pytest.mark.asyncio
    async def test_get_stock_by_code_no_mcp_no_fallback(self):
        """测试 get_stock_by_code - 没有 MCP，没有降级"""
        adapter = ToolAdapter(mcp_client=None, fallback_enabled=False)

        result = await adapter.get_stock_by_code("600519")

        assert result["success"] is False
        assert "都不可用" in result["error"]

    @pytest.mark.asyncio
    async def test_get_stock_by_code_mcp_disconnected_fallback(
        self, mock_mcp_client, mock_stock_service
    ):
        """测试 get_stock_by_code - MCP 未连接，使用降级"""
        mock_mcp_client.is_connected = False

        adapter = ToolAdapter(mcp_client=mock_mcp_client, fallback_enabled=True)

        mock_stock_service.get_stock_by_code.return_value = {
            "success": True,
            "data": {"name": "平安银行"}
        }

        with patch.object(adapter, '_get_fallback_service', return_value=mock_stock_service):
            result = await adapter.get_stock_by_code("000001")

            assert result["success"] is True
            assert result["data"]["name"] == "平安银行"
            # MCP 未调用（因为未连接）
            mock_mcp_client.call_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_search_stock_mcp_success(self, adapter_with_mcp, mock_mcp_client):
        """测试 search_stock - MCP 成功"""
        mock_mcp_client.call_tool.return_value = {
            "success": True,
            "data": [
                {"code": "600519", "name": "贵州茅台"},
                {"code": "000858", "name": "五粮液"}
            ]
        }

        result = await adapter_with_mcp.search_stock("茅台")

        assert result["success"] is True
        assert len(result["data"]) == 2
        mock_mcp_client.call_tool.assert_called_once_with(
            "market_data.search_stock",
            {"keyword": "茅台"}
        )

    @pytest.mark.asyncio
    async def test_get_market_stocks_mcp_success(self, adapter_with_mcp, mock_mcp_client):
        """测试 get_market_stocks - MCP 成功"""
        mock_mcp_client.call_tool.return_value = {
            "success": True,
            "data": [
                {"code": "600519", "name": "贵州茅台"},
                {"code": "600036", "name": "招商银行"}
            ]
        }

        result = await adapter_with_mcp.get_market_stocks("shanghai", 1)

        assert result["success"] is True
        assert len(result["data"]) == 2
        mock_mcp_client.call_tool.assert_called_once_with(
            "market_data.get_market_list",
            {"market": "shanghai", "page": 1}
        )

    @pytest.mark.asyncio
    async def test_is_using_mcp(self, adapter_with_mcp, mock_mcp_client):
        """测试 is_using_mcp 属性"""
        assert adapter_with_mcp.is_using_mcp is True

        # 断开 MCP
        mock_mcp_client.is_connected = False
        assert adapter_with_mcp.is_using_mcp is False

    @pytest.mark.asyncio
    async def test_reset_degraded_state(self, adapter_with_mcp, mock_mcp_client):
        """测试重置降级状态"""
        # 触发降级
        mock_mcp_client.call_tool.side_effect = Exception("错误")

        with patch.object(adapter_with_mcp, '_get_fallback_service', return_value=AsyncMock()):
            await adapter_with_mcp.get_stock_by_code("600519")

        assert adapter_with_mcp.is_degraded

        # 重置降级状态
        adapter_with_mcp.reset_degraded_state()
        assert not adapter_with_mcp.is_degraded

    @pytest.mark.asyncio
    async def test_fallback_service_import_error(self, adapter_with_mcp):
        """测试降级服务导入失败"""
        # 模拟导入失败
        with patch('app.mcp_client.adapter.get_stock_service', side_effect=ImportError("模块不存在")):
            service = adapter_with_mcp._get_fallback_service()
            assert service is None

    @pytest.mark.asyncio
    async def test_fallback_service_lazy_load(self, adapter_with_mcp, mock_stock_service):
        """测试降级服务延迟加载"""
        assert adapter_with_mcp._fallback_service is None

        with patch('app.service.stock_service.get_stock_service', return_value=mock_stock_service):
            service1 = adapter_with_mcp._get_fallback_service()
            service2 = adapter_with_mcp._get_fallback_service()

            # 应该返回同一个实例（缓存）
            assert service1 is service2
            assert service1 is mock_stock_service


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

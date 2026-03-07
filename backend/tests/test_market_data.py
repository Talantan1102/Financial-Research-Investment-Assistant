# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""
MarketDataSkill 单元测试

测试 MarketDataSkill 的市场行情功能，包括：
- get_quote: 获取股票实时行情
- search_stock: 搜索股票

运行方式：
    cd backend
    python -m pytest tests/test_market_data.py -v
"""

import pytest
from unittest.mock import Mock, patch
from app.mcp_server.skills.market_data import MarketDataSkill
from app.mcp_server.skills.base import ToolResult


@pytest.fixture
def mock_tushare_client():
    """创建 Mock 的 TushareClient"""
    client = Mock()
    client.get_quote = Mock()
    client.get_cache_info = Mock(return_value={'cache_size': 0})
    client.clear_cache = Mock()
    return client


@pytest.fixture
def market_skill(mock_tushare_client):
    """创建 MarketDataSkill 实例"""
    with patch('app.mcp_server.skills.market_data.get_tushare_client', return_value=mock_tushare_client):
        skill = MarketDataSkill()
    return skill


class TestMarketDataSkill:
    """MarketDataSkill 测试类"""

    def test_skill_initialization(self, market_skill):
        """测试 Skill 初始化"""
        assert market_skill.name == "market_data"
        assert market_skill.description == "股票市场行情数据查询，支持A股实时行情获取"
        assert market_skill.tool_count == 2
        assert market_skill.has_tool("get_quote")
        assert market_skill.has_tool("search_stock")


class TestGetQuote:
    """测试 get_quote 方法"""

    @pytest.mark.asyncio
    async def test_get_quote_success(self, market_skill, mock_tushare_client):
        """测试成功获取股票行情"""
        # 准备 Mock 数据
        mock_quote_data = {
            "success": True,
            "data": {
                "gid": "sh600519",
                "ts_code": "600519.SH",
                "name": "贵州茅台",
                "nowPri": "1850.50",
                "increase": "25.30",
                "increPer": "1.39",
                "todayStartPri": "1840.00",
                "yestodEndPri": "1825.20",
                "todayMax": "1865.00",
                "todayMin": "1835.00",
                "traAmount": "125000",
                "traNumber": "231250000",
                "update_time": "20260308"
            }
        }

        mock_tushare_client.get_quote.return_value = mock_quote_data

        # 执行测试
        result = await market_skill.get_quote(symbol="600519")

        # 验证结果
        assert isinstance(result, ToolResult)
        assert result.success is True
        assert result.data is not None
        assert result.data['ts_code'] == '600519.SH'
        assert result.data['name'] == '贵州茅台'
        assert result.data['nowPri'] == '1850.50'

        # 验证 Mock 被调用
        mock_tushare_client.get_quote.assert_called_once_with("600519")

    @pytest.mark.asyncio
    async def test_get_quote_with_prefix(self, market_skill, mock_tushare_client):
        """测试带市场前缀的股票代码"""
        mock_quote_data = {
            "success": True,
            "data": {
                "gid": "sh600519",
                "ts_code": "600519.SH",
                "name": "贵州茅台",
                "nowPri": "1850.50"
            }
        }

        mock_tushare_client.get_quote.return_value = mock_quote_data

        result = await market_skill.get_quote(symbol="sh600519")

        assert result.success is True
        assert result.data['ts_code'] == '600519.SH'

    @pytest.mark.asyncio
    async def test_get_quote_empty_symbol(self, market_skill):
        """测试空的股票代码"""
        result = await market_skill.get_quote(symbol="")

        assert result.success is False
        assert "股票代码不能为空" in result.error

    @pytest.mark.asyncio
    async def test_get_quote_not_found(self, market_skill, mock_tushare_client):
        """测试股票不存在"""
        mock_tushare_client.get_quote.return_value = {
            "success": False,
            "error": "未找到股票"
        }

        result = await market_skill.get_quote(symbol="999999")

        assert result.success is False
        assert "未找到股票" in result.error

    @pytest.mark.asyncio
    async def test_get_quote_exception(self, market_skill, mock_tushare_client):
        """测试异常情况"""
        mock_tushare_client.get_quote.side_effect = Exception("网络错误")

        result = await market_skill.get_quote(symbol="600519")

        assert result.success is False
        assert "获取股票行情失败" in result.error


class TestSearchStock:
    """测试 search_stock 方法"""

    @pytest.mark.asyncio
    async def test_search_by_code(self, market_skill, mock_tushare_client):
        """测试通过股票代码搜索"""
        mock_quote_data = {
            "success": True,
            "data": {
                "gid": "sh600519",
                "ts_code": "600519.SH",
                "name": "贵州茅台"
            }
        }

        mock_tushare_client.get_quote.return_value = mock_quote_data

        result = await market_skill.search_stock(keyword="600519")

        assert result.success is True
        assert result.data['count'] == 1
        assert len(result.data['results']) == 1
        assert result.data['results'][0]['ts_code'] == '600519.SH'

    @pytest.mark.asyncio
    async def test_search_with_prefix(self, market_skill, mock_tushare_client):
        """测试带市场前缀的搜索"""
        mock_quote_data = {
            "success": True,
            "data": {
                "gid": "sh600519",
                "ts_code": "600519.SH",
                "name": "贵州茅台"
            }
        }

        mock_tushare_client.get_quote.return_value = mock_quote_data

        result = await market_skill.search_stock(keyword="sh600519")

        assert result.success is True
        assert result.data['count'] == 1

    @pytest.mark.asyncio
    async def test_search_empty_keyword(self, market_skill):
        """测试空的搜索关键词"""
        result = await market_skill.search_stock(keyword="")

        assert result.success is False
        assert "搜索关键词不能为空" in result.error

    @pytest.mark.asyncio
    async def test_search_not_found(self, market_skill, mock_tushare_client):
        """测试搜索不到结果"""
        mock_tushare_client.get_quote.return_value = {
            "success": False,
            "error": "未找到股票"
        }

        result = await market_skill.search_stock(keyword="999999")

        assert result.success is False
        assert "未找到匹配的股票" in result.error

    @pytest.mark.asyncio
    async def test_search_exception(self, market_skill, mock_tushare_client):
        """测试搜索异常"""
        mock_tushare_client.get_quote.side_effect = Exception("数据库错误")

        result = await market_skill.search_stock(keyword="600519")

        assert result.success is False
        assert "搜索股票失败" in result.error


class TestCacheManagement:
    """测试缓存管理"""

    def test_get_cache_info(self, market_skill, mock_tushare_client):
        """测试获取缓存信息"""
        mock_tushare_client.get_cache_info.return_value = {'cache_size': 100}

        info = market_skill.get_cache_info()
        assert info == {'cache_size': 100}
        mock_tushare_client.get_cache_info.assert_called_once()

    def test_clear_cache(self, market_skill, mock_tushare_client):
        """测试清空缓存"""
        market_skill.clear_cache()
        mock_tushare_client.clear_cache.assert_called_once()

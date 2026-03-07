#!/usr/bin/env python3
"""
MarketDataSkill 扩展功能单元测试
测试新增的历史数据、龙虎榜、资金流向等功能
"""

import sys
import os
import unittest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
import pandas as pd

# 添加项目路径
backend_dir = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, backend_dir)

from app.mcp_server.skills.market_data import MarketDataSkill
from app.mcp_server.skills.base import ToolResult
from app.data.tushare_client import TushareClient

# 设置环境变量
os.environ['TUSHARE_API_TOKEN'] = 'test_token'
os.environ['TUSHARE_API_URL'] = 'http://test.url'


class AsyncTestCase(unittest.TestCase):
    """异步测试基类"""

    def get_event_loop(self):
        """获取或创建事件循环"""
        try:
            return asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop

    def run_async(self, coro):
        """运行异步协程"""
        return self.get_event_loop().run_until_complete(coro)


class TestMarketDataSkillExtended(AsyncTestCase):
    """MarketDataSkill 扩展功能测试"""

    def setUp(self):
        """测试前准备"""
        # 重置 TushareClient 单例
        TushareClient._instance = None

        # Mock Tushare API
        self.mock_api = MagicMock()

        with patch('tushare.pro_api', return_value=self.mock_api):
            self.skill = MarketDataSkill()

    def test_tool_registration(self):
        """测试新工具是否正确注册"""
        expected_tools = [
            'get_quote',
            'search_stock',
            'get_history',
            'get_stock_basic_info',
            'get_top_list',
            'get_money_flow',
            'get_limit_list',
            'get_company_info'
        ]

        for tool_name in expected_tools:
            self.assertTrue(
                self.skill.has_tool(tool_name),
                f"工具 {tool_name} 应该已注册"
            )

        self.assertEqual(self.skill.tool_count, 8, "应该注册8个工具")

    def test_get_history_daily(self):
        """测试获取日线历史数据"""
        mock_result = {
            "success": True,
            "data": [
                {
                    "trade_date": "20260307",
                    "open": 1800.0,
                    "high": 1850.0,
                    "low": 1790.0,
                    "close": 1825.0,
                    "pre_close": 1800.0,
                    "change": 25.0,
                    "pct_chg": 1.39,
                    "vol": 125000.0,
                    "amount": 231250.0
                }
            ],
            "meta": {"symbol": "600519.SH", "period": "daily", "count": 1}
        }

        with patch.object(self.skill.tushare_client, 'get_history', return_value=mock_result):
            result = self.run_async(self.skill.get_history("600519", "daily"))

        self.assertTrue(result.success)
        self.assertEqual(len(result.data["records"]), 1)
        self.assertEqual(result.data["records"][0]["close"], 1825.0)

    def test_get_history_weekly(self):
        """测试获取周线历史数据"""
        mock_result = {
            "success": True,
            "data": [],
            "meta": {"symbol": "000001.SZ", "period": "weekly", "count": 0}
        }

        with patch.object(self.skill.tushare_client, 'get_history', return_value=mock_result):
            result = self.run_async(self.skill.get_history("000001", "weekly"))

        self.assertTrue(result.success)
        self.assertEqual(len(result.data["records"]), 0)

    def test_get_history_error(self):
        """测试获取历史数据失败"""
        mock_result = {
            "success": False,
            "data": None,
            "error": "股票代码不存在"
        }

        with patch.object(self.skill.tushare_client, 'get_history', return_value=mock_result):
            result = self.run_async(self.skill.get_history("999999"))

        self.assertFalse(result.success)
        self.assertIn("股票代码不存在", result.error)

    def test_get_stock_basic_info(self):
        """测试获取股票基础信息"""
        mock_result = {
            "success": True,
            "data": {
                "ts_code": "600519.SH",
                "symbol": "600519",
                "name": "贵州茅台",
                "area": "贵州",
                "industry": "白酒",
                "list_date": "20010827"
            },
            "error": None
        }

        with patch.object(self.skill.tushare_client, 'get_stock_basic', return_value=mock_result):
            result = self.run_async(self.skill.get_stock_basic_info("600519"))

        self.assertTrue(result.success)
        self.assertEqual(result.data["name"], "贵州茅台")
        self.assertEqual(result.data["industry"], "白酒")

    def test_get_top_list(self):
        """测试获取龙虎榜数据"""
        mock_result = {
            "success": True,
            "data": [
                {
                    "trade_date": "20260307",
                    "ts_code": "000001.SZ",
                    "name": "平安银行",
                    "close": 10.5,
                    "pct_chg": 10.02,
                    "net_amount": 53000000.0,
                    "reason": "日涨幅偏离值达到7%的前5只证券"
                }
            ],
            "meta": {"trade_date": "20260307", "count": 1}
        }

        with patch.object(self.skill.tushare_client, 'get_top_list', return_value=mock_result):
            result = self.run_async(self.skill.get_top_list("20260307", 10))

        self.assertTrue(result.success)
        self.assertEqual(len(result.data["records"]), 1)
        self.assertEqual(result.data["records"][0]["name"], "平安银行")

    def test_get_money_flow(self):
        """测试获取资金流向"""
        mock_result = {
            "success": True,
            "data": [
                {
                    "trade_date": "20260307",
                    "ts_code": "600519.SH",
                    "name": "贵州茅台",
                    "net_mf_amount": 3700000.0,
                    "buy_elg_amount": 5000000.0,
                    "sell_elg_amount": 3000000.0
                }
            ],
            "meta": {"symbol": "600519.SH", "count": 1}
        }

        with patch.object(self.skill.tushare_client, 'get_money_flow', return_value=mock_result):
            result = self.run_async(self.skill.get_money_flow("600519"))

        self.assertTrue(result.success)
        self.assertEqual(result.data["records"][0]["net_mf_amount"], 3700000.0)

    def test_get_limit_list(self):
        """测试获取涨跌停统计"""
        mock_result = {
            "success": True,
            "data": [
                {
                    "trade_date": "20260307",
                    "ts_code": "600519.SH",
                    "name": "贵州茅台",
                    "close": 1850.5,
                    "pct_chg": 10.0,
                    "up_stat": "U",
                    "limit_type": "T"
                }
            ],
            "meta": {
                "trade_date": "20260307",
                "limit_type": "all",
                "count": 1,
                "limit_up_count": 1,
                "limit_down_count": 0
            }
        }

        with patch.object(self.skill.tushare_client, 'get_limit_list', return_value=mock_result):
            result = self.run_async(self.skill.get_limit_list("20260307"))

        self.assertTrue(result.success)
        self.assertEqual(len(result.data["records"]), 1)
        self.assertEqual(result.data["meta"]["limit_up_count"], 1)

    def test_get_company_info(self):
        """测试获取公司详细信息"""
        mock_result = {
            "success": True,
            "data": {
                "ts_code": "600519.SH",
                "symbol": "600519",
                "name": "贵州茅台",
                "fullname": "贵州茅台酒股份有限公司",
                "enname": "Kweichow Moutai Co., Ltd.",
                "industry": "白酒",
                "area": "贵州",
                "city": "遵义",
                "introduction": "公司是国内白酒行业的标志性企业"
            },
            "error": None
        }

        with patch.object(self.skill.tushare_client, 'get_stock_company_info', return_value=mock_result):
            result = self.run_async(self.skill.get_company_info("600519"))

        self.assertTrue(result.success)
        self.assertEqual(result.data["fullname"], "贵州茅台酒股份有限公司")
        self.assertEqual(result.data["city"], "遵义")


class TestTushareClientExtended(unittest.TestCase):
    """TushareClient 扩展功能测试"""

    def setUp(self):
        """测试前准备"""
        TushareClient._instance = None
        self.mock_api = MagicMock()

        with patch('tushare.pro_api', return_value=self.mock_api):
            with patch.object(TushareClient, '__init__', lambda x: None):
                self.client = TushareClient.__new__(TushareClient)
                self.client.api = self.mock_api
                self.client._cache = {}
                self.client._cache_lock = MagicMock()
                self.client._cache_lock.__enter__ = MagicMock(return_value=None)
                self.client._cache_lock.__exit__ = MagicMock(return_value=None)
                self.client.CACHE_TTL = 300
                self.client._initialized = True

    def test_get_history_params(self):
        """测试历史数据参数处理"""
        mock_df = pd.DataFrame({
            'trade_date': ['20260307'],
            'open': [1800.0],
            'high': [1850.0],
            'low': [1790.0],
            'close': [1825.0],
            'pre_close': [1800.0],
            'change': [25.0],
            'pct_chg': [1.39],
            'vol': [125000.0],
            'amount': [231250.0]
        })
        self.mock_api.daily.return_value = mock_df

        result = self.client.get_history("600519", "daily", "20260101", "20260307")

        self.assertTrue(result["success"])
        self.assertEqual(len(result["data"]), 1)
        self.mock_api.daily.assert_called_with(
            ts_code="600519.SH",
            start_date="20260101",
            end_date="20260307"
        )

    def test_get_history_invalid_period(self):
        """测试无效周期类型"""
        result = self.client.get_history("600519", "invalid")

        self.assertFalse(result["success"])
        self.assertIn("不支持的周期类型", result["error"])

    def test_get_top_list_insufficient_points(self):
        """测试积分不足时的龙虎榜查询"""
        self.mock_api.top_list.side_effect = Exception("积分不足")

        result = self.client.get_top_list("20260307")

        self.assertFalse(result["success"])


class TestParameterValidation(AsyncTestCase):
    """参数验证测试"""

    def setUp(self):
        TushareClient._instance = None
        with patch('tushare.pro_api', return_value=MagicMock()):
            self.skill = MarketDataSkill()

    def test_empty_symbol_get_history(self):
        """测试空股票代码获取历史数据"""
        result = self.run_async(self.skill.get_history(""))

        self.assertFalse(result.success)
        self.assertIn("不能为空", result.error)

    def test_empty_symbol_get_company_info(self):
        """测试空股票代码获取公司信息"""
        result = self.run_async(self.skill.get_company_info(""))

        self.assertFalse(result.success)
        self.assertIn("不能为空", result.error)

    def test_empty_symbol_get_money_flow(self):
        """测试空股票代码获取资金流向"""
        result = self.run_async(self.skill.get_money_flow(""))

        self.assertFalse(result.success)
        self.assertIn("不能为空", result.error)


def run_tests():
    """运行所有测试"""
    print("=" * 60)
    print("🧪 MarketDataSkill 扩展功能单元测试")
    print("=" * 60)

    # 创建测试套件
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # 添加测试类
    suite.addTests(loader.loadTestsFromTestCase(TestMarketDataSkillExtended))
    suite.addTests(loader.loadTestsFromTestCase(TestTushareClientExtended))
    suite.addTests(loader.loadTestsFromTestCase(TestParameterValidation))

    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # 打印汇总
    print("\n" + "=" * 60)
    print("📋 测试结果汇总")
    print("=" * 60)
    print(f"   测试总数: {result.testsRun}")
    print(f"   通过: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"   失败: {len(result.failures)}")
    print(f"   错误: {len(result.errors)}")

    if result.wasSuccessful():
        print("\n   ✅ 所有测试通过!")
    else:
        print("\n   ❌ 部分测试失败")

    print("=" * 60)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)

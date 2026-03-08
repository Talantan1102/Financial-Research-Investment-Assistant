#!/usr/bin/env python3
# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""
三个 Anthropic Skill 的端到端测试脚本

测试内容：
1. MarketDataSkill - search_stock 工具
2. FinancialAnalysisSkill - get_financial_report 工具
3. RiskAssessmentSkill - generate_risk_report 工具

使用 mock 数据避免依赖真实 TUSHARE_API_TOKEN
"""

import asyncio
import sys
import os
from unittest.mock import Mock, patch, MagicMock
import pandas as pd
import numpy as np

# 添加 backend 目录到 Python 路径（从 skills -> mcp_server -> app -> backend）
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
sys.path.insert(0, backend_dir)


def print_section(title: str):
    """打印测试章节标题"""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_test_result(test_name: str, success: bool, details: str = ""):
    """打印测试结果"""
    status = "✅ 成功" if success else "❌ 失败"
    print(f"\n[{status}] {test_name}")
    if details:
        print(f"    详情: {details}")


def create_mock_tushare_client():
    """创建模拟的 TushareClient"""
    mock_client = Mock()
    mock_client.api = Mock()

    # Mock _normalize_stock_code 方法
    def normalize_code(symbol: str) -> str:
        """模拟代码标准化"""
        symbol = symbol.strip().upper()
        if symbol.startswith('SH') or symbol.startswith('SZ'):
            symbol = symbol[2:]
        if '.' in symbol:
            return symbol
        if symbol.startswith('6'):
            return f"{symbol}.SH"
        elif symbol.startswith(('0', '3')):
            return f"{symbol}.SZ"
        return symbol

    mock_client._normalize_stock_code = normalize_code

    return mock_client


def create_mock_quote_data(symbol: str):
    """创建模拟的股票行情数据"""
    return {
        "gid": f"sh{symbol}",
        "ts_code": f"{symbol}.SH",
        "name": "测试股票",
        "nowPri": "100.50",
        "increase": "2.50",
        "increPer": "2.55",
        "todayStartPri": "98.00",
        "yestodEndPri": "98.00",
        "todayMax": "101.00",
        "todayMin": "97.50",
        "traAmount": "50000",
        "traNumber": "5025000",
        "update_time": "20260308"
    }


def create_mock_financial_data():
    """创建模拟的财务报表数据"""
    return pd.DataFrame([
        {
            "ts_code": "600519.SH",
            "end_date": "20231231",
            "ann_date": "20240331",
            "f_ann_date": "20240331",
            "report_type": "1",
            "comp_type": "1",
            "total_revenue": 1500000.0,
            "revenue": 1480000.0,
            "operate_profit": 750000.0,
            "total_profit": 760000.0,
            "n_income": 620000.0,
            "n_income_attr_p": 615000.0,
            "basic_eps": 12.50,
            "diluted_eps": 12.48
        }
    ])


def create_mock_price_data():
    """创建模拟的历史价格数据"""
    dates = pd.date_range(end='20260308', periods=252, freq='D')
    prices = 100 + np.random.randn(252).cumsum()

    return pd.DataFrame({
        'trade_date': [d.strftime('%Y%m%d') for d in dates],
        'close': prices,
        'ts_code': ['600519.SH'] * 252
    })


def create_mock_stock_basic():
    """创建模拟的股票基本信息"""
    return pd.DataFrame([
        {
            'ts_code': '600519.SH',
            'name': '贵州茅台'
        }
    ])


async def test_market_data_skill():
    """测试 MarketDataSkill - search_stock 工具"""
    print_section("测试 MarketDataSkill")

    try:
        # 1. 测试导入
        print("\n1. 测试导入 MarketDataSkill...")
        from app.mcp_server.skills.market_data import MarketDataSkill
        print_test_result("导入 MarketDataSkill", True)

        # 2. 创建 mock TushareClient
        print("\n2. 创建 MarketDataSkill 实例（使用 mock）...")
        mock_client = create_mock_tushare_client()

        # Mock get_quote 方法
        def mock_get_quote(symbol: str):
            return {
                "success": True,
                "data": create_mock_quote_data(symbol)
            }

        mock_client.get_quote = mock_get_quote

        # 使用 patch 替换 get_tushare_client
        with patch('app.mcp_server.skills.market_data.get_tushare_client', return_value=mock_client):
            skill = MarketDataSkill()
            print_test_result("创建 MarketDataSkill 实例", True)

            # 3. 测试 search_stock 工具
            print("\n3. 测试 search_stock 工具...")
            result = await skill.search_stock(keyword="600519")

            if result.success:
                data = result.data
                assert "results" in data, "返回数据应包含 'results' 字段"
                assert "count" in data, "返回数据应包含 'count' 字段"
                assert data["count"] == 1, "搜索结果数量应为 1"
                assert len(data["results"]) == 1, "结果列表长度应为 1"

                stock_data = data["results"][0]
                assert "name" in stock_data, "股票数据应包含 'name' 字段"
                assert "ts_code" in stock_data, "股票数据应包含 'ts_code' 字段"
                assert "nowPri" in stock_data, "股票数据应包含 'nowPri' 字段"

                print_test_result(
                    "search_stock 工具测试",
                    True,
                    f"成功获取股票: {stock_data['name']} ({stock_data['ts_code']})"
                )
                return True
            else:
                print_test_result("search_stock 工具测试", False, result.error)
                return False

    except Exception as e:
        print_test_result("MarketDataSkill 测试", False, str(e))
        import traceback
        traceback.print_exc()
        return False


async def test_financial_analysis_skill():
    """测试 FinancialAnalysisSkill - get_financial_report 工具"""
    print_section("测试 FinancialAnalysisSkill")

    try:
        # 1. 测试导入
        print("\n1. 测试导入 FinancialAnalysisSkill...")
        from app.mcp_server.skills.financial_analysis import FinancialAnalysisSkill
        print_test_result("导入 FinancialAnalysisSkill", True)

        # 2. 创建 mock TushareClient
        print("\n2. 创建 FinancialAnalysisSkill 实例（使用 mock）...")
        mock_client = create_mock_tushare_client()

        # Mock income API
        mock_client.api.income = Mock(return_value=create_mock_financial_data())

        # 使用 patch 替换 get_tushare_client
        with patch('app.mcp_server.skills.financial_analysis.get_tushare_client', return_value=mock_client):
            skill = FinancialAnalysisSkill()
            print_test_result("创建 FinancialAnalysisSkill 实例", True)

            # 3. 测试 get_financial_report 工具
            print("\n3. 测试 get_financial_report 工具（利润表）...")
            result = await skill.get_financial_report(
                symbol="600519",
                report_type="income",
                report_count=1
            )

            if result.success:
                data = result.data
                assert "symbol" in data, "返回数据应包含 'symbol' 字段"
                assert "report_type" in data, "返回数据应包含 'report_type' 字段"
                assert "reports" in data, "返回数据应包含 'reports' 字段"
                assert data["report_type"] == "利润表", "报表类型应为 '利润表'"
                assert len(data["reports"]) > 0, "报表数据不应为空"

                report = data["reports"][0]
                assert "total_revenue" in report, "报表应包含 'total_revenue' 字段"
                assert "net_income" in report, "报表应包含 'net_income' 字段"
                assert "basic_eps" in report, "报表应包含 'basic_eps' 字段"

                print_test_result(
                    "get_financial_report 工具测试",
                    True,
                    f"成功获取财报: {data['symbol']}, 营收: {report['total_revenue']}万元"
                )
                return True
            else:
                print_test_result("get_financial_report 工具测试", False, result.error)
                return False

    except Exception as e:
        print_test_result("FinancialAnalysisSkill 测试", False, str(e))
        import traceback
        traceback.print_exc()
        return False


async def test_risk_assessment_skill():
    """测试 RiskAssessmentSkill - generate_risk_report 工具"""
    print_section("测试 RiskAssessmentSkill")

    try:
        # 1. 测试导入
        print("\n1. 测试导入 RiskAssessmentSkill...")
        from app.mcp_server.skills.risk_assessment import RiskAssessmentSkill
        print_test_result("导入 RiskAssessmentSkill", True)

        # 2. 创建 mock TushareClient
        print("\n2. 创建 RiskAssessmentSkill 实例（使用 mock）...")
        mock_client = create_mock_tushare_client()

        # Mock daily API (历史价格数据)
        mock_client.api.daily = Mock(return_value=create_mock_price_data())

        # Mock stock_basic API
        mock_client.api.stock_basic = Mock(return_value=create_mock_stock_basic())

        # 使用 patch 替换 get_tushare_client
        with patch('app.mcp_server.skills.risk_assessment.get_tushare_client', return_value=mock_client):
            skill = RiskAssessmentSkill()
            print_test_result("创建 RiskAssessmentSkill 实例", True)

            # 3. 测试 generate_risk_report 工具
            print("\n3. 测试 generate_risk_report 工具...")
            result = await skill.generate_risk_report(
                symbol="600519",
                days=100,
                is_portfolio=False
            )

            if result.success:
                data = result.data
                assert "title" in data, "返回数据应包含 'title' 字段"
                assert "risk_rating" in data, "返回数据应包含 'risk_rating' 字段"
                assert "key_metrics" in data, "返回数据应包含 'key_metrics' 字段"
                assert "recommendations" in data, "返回数据应包含 'recommendations' 字段"
                assert "risk_warnings" in data, "返回数据应包含 'risk_warnings' 字段"

                risk_rating = data["risk_rating"]
                assert "level" in risk_rating, "风险评级应包含 'level' 字段"
                assert "score" in risk_rating, "风险评级应包含 'score' 字段"
                assert "description" in risk_rating, "风险评级应包含 'description' 字段"

                key_metrics = data["key_metrics"]
                assert "预期年化收益率" in key_metrics, "关键指标应包含 '预期年化收益率'"
                assert "波动率(年化)" in key_metrics, "关键指标应包含 '波动率(年化)'"
                assert "夏普比率" in key_metrics, "关键指标应包含 '夏普比率'"
                assert "最大回撤" in key_metrics, "关键指标应包含 '最大回撤'"

                print_test_result(
                    "generate_risk_report 工具测试",
                    True,
                    f"成功生成风险报告: 风险等级={risk_rating['level']}, 评分={risk_rating['score']}"
                )
                return True
            else:
                print_test_result("generate_risk_report 工具测试", False, result.error)
                return False

    except Exception as e:
        print_test_result("RiskAssessmentSkill 测试", False, str(e))
        import traceback
        traceback.print_exc()
        return False


async def main():
    """主测试函数"""
    print("\n")
    print("╔" + "=" * 68 + "╗")
    print("║" + " " * 15 + "Anthropic Skills 端到端测试" + " " * 25 + "║")
    print("╚" + "=" * 68 + "╝")

    # 设置空的环境变量（避免使用真实 token）
    os.environ["TUSHARE_API_TOKEN"] = ""

    # 运行所有测试
    results = {
        "MarketDataSkill": await test_market_data_skill(),
        "FinancialAnalysisSkill": await test_financial_analysis_skill(),
        "RiskAssessmentSkill": await test_risk_assessment_skill(),
    }

    # 打印测试总结
    print_section("测试总结")

    total = len(results)
    passed = sum(1 for r in results.values() if r)
    failed = total - passed

    print(f"\n总测试数: {total}")
    print(f"通过: {passed} ✅")
    print(f"失败: {failed} ❌")

    if failed == 0:
        print("\n🎉 所有测试通过！")
        return 0
    else:
        print("\n⚠️  部分测试失败，请检查详情")
        print("\n失败的测试:")
        for name, result in results.items():
            if not result:
                print(f"  - {name}")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

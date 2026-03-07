# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""
FinancialAnalysisSkill 单元测试

测试 FinancialAnalysisSkill 的财务分析功能，包括：
- get_financial_report: 获取财务报表
- calculate_financial_ratios: 计算财务指标
- compare_financial_data: 对比财务数据

运行方式：
    cd backend
    python -m pytest tests/test_financial_analysis_skill.py -v
"""

import pytest
import pandas as pd
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from app.mcp_server.skills.financial_analysis import FinancialAnalysisSkill
from app.mcp_server.skills.base import ToolResult


@pytest.fixture
def mock_tushare_client():
    """创建 Mock 的 TushareClient"""
    client = Mock()
    client.api = Mock()
    client._normalize_stock_code = Mock(return_value="600519.SH")
    return client


@pytest.fixture
def financial_skill(mock_tushare_client):
    """创建 FinancialAnalysisSkill 实例"""
    with patch('app.mcp_server.skills.financial_analysis.get_tushare_client', return_value=mock_tushare_client):
        skill = FinancialAnalysisSkill()
    return skill


class TestFinancialAnalysisSkill:
    """FinancialAnalysisSkill 测试类"""

    def test_skill_initialization(self, financial_skill):
        """测试 Skill 初始化"""
        assert financial_skill.name == "financial_analysis"
        assert financial_skill.description == "A股上市公司财务分析，支持财报查询、财务指标计算、财报对比分析"
        assert financial_skill.tool_count == 3
        assert financial_skill.has_tool("get_financial_report")
        assert financial_skill.has_tool("calculate_financial_ratios")
        assert financial_skill.has_tool("compare_financial_data")


class TestGetFinancialReport:
    """测试 get_financial_report 方法"""

    @pytest.mark.asyncio
    async def test_get_income_report_success(self, financial_skill, mock_tushare_client):
        """测试成功获取利润表"""
        # 准备 Mock 数据
        mock_df = pd.DataFrame([{
            'ts_code': '600519.SH',
            'ann_date': '20231231',
            'f_ann_date': '20240101',
            'end_date': '20231231',
            'report_type': 1,
            'comp_type': 1,
            'total_revenue': 150000.0,
            'revenue': 148000.0,
            'operate_profit': 75000.0,
            'total_profit': 76000.0,
            'n_income': 60000.0,
            'n_income_attr_p': 59000.0,
            'basic_eps': 48.5,
            'diluted_eps': 48.3
        }])

        mock_tushare_client.api.income = Mock(return_value=mock_df)

        # 执行测试
        result = await financial_skill.get_financial_report(
            symbol="600519",
            report_type="income",
            period=None,
            report_count=1
        )

        # 验证结果
        assert isinstance(result, ToolResult)
        assert result.success is True
        assert result.data is not None
        assert result.data['symbol'] == '600519.SH'
        assert result.data['report_type'] == '利润表'
        assert result.data['report_count'] == 1
        assert len(result.data['reports']) == 1

        report = result.data['reports'][0]
        assert report['ts_code'] == '600519.SH'
        assert report['end_date'] == '20231231'
        assert report['report_type'] == '年报'

    @pytest.mark.asyncio
    async def test_get_balance_report_success(self, financial_skill, mock_tushare_client):
        """测试成功获取资产负债表"""
        mock_df = pd.DataFrame([{
            'ts_code': '600519.SH',
            'ann_date': '20231231',
            'f_ann_date': '20240101',
            'end_date': '20231231',
            'report_type': 1,
            'comp_type': 1,
            'total_assets': 300000.0,
            'total_cur_assets': 150000.0,
            'total_nca': 150000.0,
            'total_liab': 100000.0,
            'total_cur_liab': 60000.0,
            'total_ncl': 40000.0,
            'total_hldr_eqy_exc_min_int': 200000.0,
            'total_hldr_eqy_inc_min_int': 205000.0
        }])

        mock_tushare_client.api.balancesheet = Mock(return_value=mock_df)

        result = await financial_skill.get_financial_report(
            symbol="600519",
            report_type="balance"
        )

        assert result.success is True
        assert result.data['report_type'] == '资产负债表'
        assert 'total_assets' in result.data['reports'][0]

    @pytest.mark.asyncio
    async def test_get_cashflow_report_success(self, financial_skill, mock_tushare_client):
        """测试成功获取现金流量表"""
        mock_df = pd.DataFrame([{
            'ts_code': '600519.SH',
            'ann_date': '20231231',
            'f_ann_date': '20240101',
            'end_date': '20231231',
            'report_type': 1,
            'comp_type': 1,
            'n_cashflow_act': 70000.0,
            'n_cashflow_inv_act': -20000.0,
            'n_cashflow_fnc_act': -10000.0,
            'c_cash_equ_end_period': 100000.0,
            'c_cash_equ_beg_period': 60000.0
        }])

        mock_tushare_client.api.cashflow = Mock(return_value=mock_df)

        result = await financial_skill.get_financial_report(
            symbol="600519",
            report_type="cashflow"
        )

        assert result.success is True
        assert result.data['report_type'] == '现金流量表'
        assert 'operating_cashflow' in result.data['reports'][0]

    @pytest.mark.asyncio
    async def test_empty_symbol(self, financial_skill):
        """测试空的股票代码"""
        result = await financial_skill.get_financial_report(
            symbol="",
            report_type="income"
        )

        assert result.success is False
        assert "股票代码不能为空" in result.error

    @pytest.mark.asyncio
    async def test_invalid_report_type(self, financial_skill):
        """测试无效的报表类型"""
        result = await financial_skill.get_financial_report(
            symbol="600519",
            report_type="invalid_type"
        )

        assert result.success is False
        assert "不支持的报表类型" in result.error

    @pytest.mark.asyncio
    async def test_invalid_report_count(self, financial_skill):
        """测试无效的报告期数量"""
        # 测试小于1
        result = await financial_skill.get_financial_report(
            symbol="600519",
            report_type="income",
            report_count=0
        )
        assert result.success is False
        assert "报告期数量必须在 1-10 之间" in result.error

        # 测试大于10
        result = await financial_skill.get_financial_report(
            symbol="600519",
            report_type="income",
            report_count=11
        )
        assert result.success is False
        assert "报告期数量必须在 1-10 之间" in result.error

    @pytest.mark.asyncio
    async def test_api_not_initialized(self, financial_skill, mock_tushare_client):
        """测试 API 未初始化的情况"""
        mock_tushare_client.api = None

        result = await financial_skill.get_financial_report(
            symbol="600519",
            report_type="income"
        )

        assert result.success is False
        assert "Tushare API 未初始化" in result.error

    @pytest.mark.asyncio
    async def test_no_data_found(self, financial_skill, mock_tushare_client):
        """测试未找到数据的情况"""
        # 返回空 DataFrame
        mock_tushare_client.api.income = Mock(return_value=pd.DataFrame())

        result = await financial_skill.get_financial_report(
            symbol="600519",
            report_type="income"
        )

        assert result.success is False
        assert "未找到股票" in result.error

    @pytest.mark.asyncio
    async def test_api_exception(self, financial_skill, mock_tushare_client):
        """测试 API 调用异常"""
        mock_tushare_client.api.income = Mock(side_effect=Exception("API 调用失败"))

        result = await financial_skill.get_financial_report(
            symbol="600519",
            report_type="income"
        )

        assert result.success is False
        assert "获取财务报表失败" in result.error


class TestCalculateFinancialRatios:
    """测试 calculate_financial_ratios 方法"""

    @pytest.mark.asyncio
    async def test_calculate_ratios_success(self, financial_skill, mock_tushare_client):
        """测试成功计算财务指标"""
        mock_df = pd.DataFrame([{
            'ts_code': '600519.SH',
            'ann_date': '20231231',
            'end_date': '20231231',
            'eps': 48.5,
            'roe': 25.5,
            'roe_waa': 25.3,
            'roe_dt': 25.1,
            'roa': 18.5,
            'grossprofit_margin': 91.2,
            'netprofit_margin': 51.3,
            'debt_to_assets': 22.5,
            'current_ratio': 4.2,
            'quick_ratio': 3.8,
            'ocf_to_or': 95.5,
            'or_last_year': 18.2,
            'op_yoy': 17.8,
            'ebt_yoy': 18.5,
            'netprofit_yoy': 18.0,
            'dt_netprofit_yoy': 17.9
        }])

        mock_tushare_client.api.fina_indicator = Mock(return_value=mock_df)

        result = await financial_skill.calculate_financial_ratios(
            symbol="600519",
            period=None
        )

        assert result.success is True
        assert result.data is not None
        assert result.data['symbol'] == '600519.SH'

        ratios = result.data['ratios']
        assert ratios['eps'] == "48.5000"
        assert ratios['roe'] == "25.50%"
        assert ratios['roa'] == "18.50%"
        assert '摘要' in result.data or 'summary' in result.data

    @pytest.mark.asyncio
    async def test_empty_symbol_ratios(self, financial_skill):
        """测试空股票代码"""
        result = await financial_skill.calculate_financial_ratios(symbol="")

        assert result.success is False
        assert "股票代码不能为空" in result.error

    @pytest.mark.asyncio
    async def test_api_not_initialized_ratios(self, financial_skill, mock_tushare_client):
        """测试 API 未初始化"""
        mock_tushare_client.api = None

        result = await financial_skill.calculate_financial_ratios(symbol="600519")

        assert result.success is False
        assert "Tushare API 未初始化" in result.error

    @pytest.mark.asyncio
    async def test_no_data_found_ratios(self, financial_skill, mock_tushare_client):
        """测试未找到数据"""
        mock_tushare_client.api.fina_indicator = Mock(return_value=pd.DataFrame())

        result = await financial_skill.calculate_financial_ratios(symbol="600519")

        assert result.success is False
        assert "未找到股票" in result.error

    @pytest.mark.asyncio
    async def test_api_exception_ratios(self, financial_skill, mock_tushare_client):
        """测试 API 异常"""
        mock_tushare_client.api.fina_indicator = Mock(side_effect=Exception("网络错误"))

        result = await financial_skill.calculate_financial_ratios(symbol="600519")

        assert result.success is False
        assert "计算财务指标失败" in result.error


class TestCompareFinancialData:
    """测试 compare_financial_data 方法"""

    @pytest.mark.asyncio
    async def test_compare_revenue_success(self, financial_skill, mock_tushare_client):
        """测试成功对比营收数据"""
        # 准备多期数据
        mock_df = pd.DataFrame([
            {'ts_code': '600519.SH', 'end_date': '20231231', 'total_revenue': 150000.0, 'n_income_attr_p': 75000.0},
            {'ts_code': '600519.SH', 'end_date': '20230930', 'total_revenue': 140000.0, 'n_income_attr_p': 70000.0},
            {'ts_code': '600519.SH', 'end_date': '20230630', 'total_revenue': 130000.0, 'n_income_attr_p': 65000.0},
            {'ts_code': '600519.SH', 'end_date': '20230331', 'total_revenue': 120000.0, 'n_income_attr_p': 60000.0},
        ])

        mock_tushare_client.api.income = Mock(return_value=mock_df)

        result = await financial_skill.compare_financial_data(
            symbol="600519",
            indicator="revenue",
            periods=4
        )

        assert result.success is True
        assert result.data is not None
        assert result.data['indicator'] == '营业总收入'
        assert result.data['unit'] == '万元'
        assert len(result.data['data_points']) == 4
        assert len(result.data['qoq_comparisons']) == 3  # 4期数据有3个环比
        assert 'summary' in result.data

    @pytest.mark.asyncio
    async def test_compare_net_profit_success(self, financial_skill, mock_tushare_client):
        """测试成功对比净利润数据"""
        mock_df = pd.DataFrame([
            {'ts_code': '600519.SH', 'end_date': '20231231', 'total_revenue': 150000.0, 'n_income_attr_p': 75000.0},
            {'ts_code': '600519.SH', 'end_date': '20230930', 'total_revenue': 140000.0, 'n_income_attr_p': 70000.0},
        ])

        mock_tushare_client.api.income = Mock(return_value=mock_df)

        result = await financial_skill.compare_financial_data(
            symbol="600519",
            indicator="net_profit",
            periods=2
        )

        assert result.success is True
        assert result.data['indicator'] == '归母净利润'

    @pytest.mark.asyncio
    async def test_compare_roe_success(self, financial_skill, mock_tushare_client):
        """测试成功对比 ROE 数据"""
        mock_df = pd.DataFrame([
            {'ts_code': '600519.SH', 'end_date': '20231231', 'roe': 25.5, 'roa': 18.5},
            {'ts_code': '600519.SH', 'end_date': '20230930', 'roe': 24.8, 'roa': 18.0},
        ])

        mock_tushare_client.api.fina_indicator = Mock(return_value=mock_df)

        result = await financial_skill.compare_financial_data(
            symbol="600519",
            indicator="roe",
            periods=2
        )

        assert result.success is True
        assert result.data['indicator'] == 'ROE'
        assert result.data['unit'] == '%'

    @pytest.mark.asyncio
    async def test_empty_symbol_compare(self, financial_skill):
        """测试空股票代码"""
        result = await financial_skill.compare_financial_data(
            symbol="",
            indicator="revenue"
        )

        assert result.success is False
        assert "股票代码不能为空" in result.error

    @pytest.mark.asyncio
    async def test_invalid_indicator(self, financial_skill):
        """测试无效的指标"""
        result = await financial_skill.compare_financial_data(
            symbol="600519",
            indicator="invalid_indicator"
        )

        assert result.success is False
        assert "不支持的指标" in result.error

    @pytest.mark.asyncio
    async def test_invalid_periods(self, financial_skill):
        """测试无效的期数"""
        # 测试小于2
        result = await financial_skill.compare_financial_data(
            symbol="600519",
            indicator="revenue",
            periods=1
        )
        assert result.success is False
        assert "对比期数必须在 2-20 之间" in result.error

        # 测试大于20
        result = await financial_skill.compare_financial_data(
            symbol="600519",
            indicator="revenue",
            periods=21
        )
        assert result.success is False
        assert "对比期数必须在 2-20 之间" in result.error

    @pytest.mark.asyncio
    async def test_insufficient_data(self, financial_skill, mock_tushare_client):
        """测试数据不足的情况"""
        # 只返回1期数据
        mock_df = pd.DataFrame([
            {'ts_code': '600519.SH', 'end_date': '20231231', 'total_revenue': 150000.0, 'n_income_attr_p': 75000.0}
        ])

        mock_tushare_client.api.income = Mock(return_value=mock_df)

        result = await financial_skill.compare_financial_data(
            symbol="600519",
            indicator="revenue",
            periods=4
        )

        assert result.success is False
        assert "数据不足" in result.error

    @pytest.mark.asyncio
    async def test_api_exception_compare(self, financial_skill, mock_tushare_client):
        """测试 API 异常"""
        mock_tushare_client.api.income = Mock(side_effect=Exception("数据库错误"))

        result = await financial_skill.compare_financial_data(
            symbol="600519",
            indicator="revenue"
        )

        assert result.success is False
        assert "对比财务数据失败" in result.error


class TestHelperMethods:
    """测试辅助方法"""

    def test_format_number(self, financial_skill):
        """测试数字格式化"""
        assert financial_skill._format_number(123.456) == "123.46"
        assert financial_skill._format_number(123.456, precision=1) == "123.5"
        assert financial_skill._format_number(None) == "N/A"
        assert financial_skill._format_number("") == "N/A"
        assert financial_skill._format_number("invalid") == "N/A"

    def test_format_percentage(self, financial_skill):
        """测试百分比格式化"""
        assert financial_skill._format_percentage(25.5) == "25.50%"
        assert financial_skill._format_percentage(None) == "N/A"
        assert financial_skill._format_percentage("") == "N/A"

    def test_format_report_type(self, financial_skill):
        """测试报告类型格式化"""
        assert financial_skill._format_report_type("1") == "年报"
        assert financial_skill._format_report_type(1) == "年报"
        assert financial_skill._format_report_type("2") == "半年报"
        assert financial_skill._format_report_type(2) == "半年报"
        assert financial_skill._format_report_type("3") == "一季报"
        assert financial_skill._format_report_type(3) == "一季报"
        assert financial_skill._format_report_type("4") == "三季报"
        assert financial_skill._format_report_type(4) == "三季报"
        assert financial_skill._format_report_type("9") == "未知"

    def test_generate_ratio_summary(self, financial_skill):
        """测试财务指标摘要生成"""
        ratios = {
            'roe': '25.50%',
            'gross_profit_margin': '91.20%',
            'net_profit_margin': '51.30%',
            'debt_to_assets': '22.50%'
        }

        summary = financial_skill._generate_ratio_summary(ratios)
        assert isinstance(summary, str)
        assert "ROE" in summary
        assert "优秀" in summary or "良好" in summary
        assert "毛利率" in summary
        assert "净利率" in summary
        assert "资产负债率" in summary

    def test_generate_comparison_summary(self, financial_skill):
        """测试对比分析摘要生成"""
        data_points = [
            {'end_date': '20231231', 'value': 150000.0, 'formatted_value': '150000.00'},
            {'end_date': '20230930', 'value': 140000.0, 'formatted_value': '140000.00'}
        ]

        comparisons = [
            {
                'current_period': '20231231',
                'previous_period': '20230930',
                'change_rate': '7.14%',
                'trend': '上升'
            }
        ]

        summary = financial_skill._generate_comparison_summary(
            '营业总收入',
            data_points,
            comparisons
        )

        assert isinstance(summary, str)
        assert '营业总收入' in summary
        assert '150000.00' in summary


class TestCacheManagement:
    """测试缓存管理"""

    def test_get_cache_info(self, financial_skill, mock_tushare_client):
        """测试获取缓存信息"""
        mock_tushare_client.get_cache_info = Mock(return_value={'cache_size': 100})

        info = financial_skill.get_cache_info()
        assert info == {'cache_size': 100}
        mock_tushare_client.get_cache_info.assert_called_once()

    def test_clear_cache(self, financial_skill, mock_tushare_client):
        """测试清空缓存"""
        mock_tushare_client.clear_cache = Mock()

        financial_skill.clear_cache()
        mock_tushare_client.clear_cache.assert_called_once()

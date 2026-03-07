# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""
RiskAssessmentSkill 单元测试

测试 RiskAssessmentSkill 的风险评估功能，包括：
- assess_portfolio_risk: 评估投资组合风险
- calculate_risk_metrics: 计算风险指标
- generate_risk_report: 生成风险报告

运行方式：
    cd backend
    python -m pytest tests/test_risk_assessment_skill.py -v
"""

import pytest
import numpy as np
import pandas as pd
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from datetime import datetime, timedelta
from app.mcp_server.skills.risk_assessment import RiskAssessmentSkill
from app.mcp_server.skills.base import ToolResult


@pytest.fixture
def mock_tushare_client():
    """创建 Mock 的 TushareClient"""
    client = Mock()
    client.api = Mock()
    client._normalize_stock_code = Mock(side_effect=lambda x: f"{x}.SH" if not x.endswith(('.SH', '.SZ')) else x)
    return client


@pytest.fixture
def risk_skill(mock_tushare_client):
    """创建 RiskAssessmentSkill 实例"""
    with patch('app.mcp_server.skills.risk_assessment.get_tushare_client', return_value=mock_tushare_client):
        skill = RiskAssessmentSkill()
    return skill


@pytest.fixture
def sample_price_data():
    """生成样本价格数据"""
    # 生成100个交易日的模拟价格数据
    dates = pd.date_range(end=datetime.now(), periods=100, freq='B')
    prices = 100 + np.cumsum(np.random.randn(100) * 2)  # 随机游走
    prices = np.maximum(prices, 50)  # 确保价格为正

    df = pd.DataFrame({
        'trade_date': dates.strftime('%Y%m%d').tolist(),
        'close': prices
    })
    return df


class TestRiskAssessmentSkill:
    """RiskAssessmentSkill 测试类"""

    def test_skill_initialization(self, risk_skill):
        """测试 Skill 初始化"""
        assert risk_skill.name == "risk_assessment"
        assert risk_skill.description == "投资组合风险评估,支持风险指标计算、投资组合分析、风险报告生成"
        assert risk_skill.tool_count == 3
        assert risk_skill.has_tool("assess_portfolio_risk")
        assert risk_skill.has_tool("calculate_risk_metrics")
        assert risk_skill.has_tool("generate_risk_report")
        assert risk_skill.risk_free_rate == 0.03

    def test_risk_free_rate(self, risk_skill):
        """测试无风险收益率设置"""
        assert risk_skill.risk_free_rate == 0.03


class TestCalculateRiskMetrics:
    """测试 calculate_risk_metrics 方法"""

    @pytest.mark.asyncio
    async def test_calculate_metrics_success(self, risk_skill, mock_tushare_client, sample_price_data):
        """测试成功计算风险指标"""
        # Mock 返回价格数据
        mock_tushare_client.api.daily = Mock(return_value=sample_price_data)

        # Mock 股票名称
        mock_stock_basic = pd.DataFrame([{'ts_code': '600519.SH', 'name': '贵州茅台'}])
        mock_tushare_client.api.stock_basic = Mock(return_value=mock_stock_basic)

        result = await risk_skill.calculate_risk_metrics(
            symbol="600519",
            days=252
        )

        assert result.success is True
        assert result.data is not None
        assert result.data['symbol'] == '600519'
        assert result.data['name'] == '贵州茅台'

        metrics = result.data['metrics']
        assert 'expected_return' in metrics
        assert 'volatility' in metrics
        assert 'sharpe_ratio' in metrics
        assert 'max_drawdown' in metrics
        assert 'var_95' in metrics
        assert 'cvar_95' in metrics
        assert 'downside_deviation' in metrics

        # 验证指标合理性
        assert isinstance(metrics['expected_return'], (int, float))
        assert isinstance(metrics['volatility'], (int, float))
        assert metrics['volatility'] >= 0

    @pytest.mark.asyncio
    async def test_calculate_metrics_with_benchmark(self, risk_skill, mock_tushare_client, sample_price_data):
        """测试带基准的风险指标计算"""
        # Mock 股票和基准数据
        mock_tushare_client.api.daily = Mock(return_value=sample_price_data)

        mock_stock_basic = pd.DataFrame([
            {'ts_code': '600519.SH', 'name': '贵州茅台'},
            {'ts_code': '000001.SH', 'name': '上证指数'}
        ])
        mock_tushare_client.api.stock_basic = Mock(return_value=mock_stock_basic)

        result = await risk_skill.calculate_risk_metrics(
            symbol="600519",
            days=252,
            benchmark="000001"
        )

        assert result.success is True
        metrics = result.data['metrics']

        # 验证基准相关指标
        if 'beta' in metrics:
            assert isinstance(metrics['beta'], (int, float, type(None)))
        if 'correlation' in metrics:
            assert -1 <= metrics['correlation'] <= 1
        if 'benchmark' in metrics:
            assert 'name' in metrics['benchmark']
            assert 'return' in metrics['benchmark']

    @pytest.mark.asyncio
    async def test_empty_symbol(self, risk_skill):
        """测试空的股票代码"""
        result = await risk_skill.calculate_risk_metrics(symbol="")

        assert result.success is False
        assert "股票代码不能为空" in result.error

    @pytest.mark.asyncio
    async def test_api_not_initialized(self, risk_skill, mock_tushare_client):
        """测试 API 未初始化"""
        mock_tushare_client.api = None

        result = await risk_skill.calculate_risk_metrics(symbol="600519")

        assert result.success is False
        assert "获取历史数据失败" in result.error

    @pytest.mark.asyncio
    async def test_insufficient_data(self, risk_skill, mock_tushare_client):
        """测试数据不足的情况"""
        # 返回少于30天的数据
        dates = pd.date_range(end=datetime.now(), periods=20, freq='B')
        small_df = pd.DataFrame({
            'trade_date': dates.strftime('%Y%m%d').tolist(),
            'close': np.random.randn(20) * 10 + 100
        })

        mock_tushare_client.api.daily = Mock(return_value=small_df)

        result = await risk_skill.calculate_risk_metrics(symbol="600519", days=252)

        assert result.success is False
        assert "历史数据不足" in result.error or "数据不足" in result.error


class TestAssessPortfolioRisk:
    """测试 assess_portfolio_risk 方法"""

    @pytest.mark.asyncio
    async def test_assess_portfolio_success(self, risk_skill, mock_tushare_client, sample_price_data):
        """测试成功评估投资组合风险"""
        # Mock 多个股票的价格数据
        def mock_daily(ts_code, start_date, end_date):
            # 为不同股票返回略有不同的数据
            df = sample_price_data.copy()
            if '000001' in ts_code:
                df['close'] = df['close'] * 0.9
            elif '600036' in ts_code:
                df['close'] = df['close'] * 1.1
            return df

        mock_tushare_client.api.daily = Mock(side_effect=mock_daily)

        # Mock 股票名称
        def mock_stock_basic(ts_code, fields):
            name_map = {
                '600519.SH': '贵州茅台',
                '000001.SZ': '平安银行',
                '600036.SH': '招商银行'
            }
            name = name_map.get(ts_code, '未知')
            return pd.DataFrame([{'ts_code': ts_code, 'name': name}])

        mock_tushare_client.api.stock_basic = Mock(side_effect=mock_stock_basic)

        result = await risk_skill.assess_portfolio_risk(
            portfolio="600519:0.4,000001:0.3,600036:0.3",
            days=252
        )

        assert result.success is True
        assert result.data is not None

        # 验证投资组合信息
        portfolio = result.data['portfolio']
        assert len(portfolio['holdings']) == 3
        assert portfolio['holdings'][0]['symbol'] == '600519'
        assert portfolio['holdings'][0]['weight'] == '40.00%'

        # 验证风险指标
        metrics = result.data['metrics']
        assert 'expected_return' in metrics
        assert 'volatility' in metrics
        assert 'sharpe_ratio' in metrics

        # 验证风险评估
        risk_assessment = result.data['risk_assessment']
        assert 'level' in risk_assessment
        assert 'score' in risk_assessment
        assert 'description' in risk_assessment

    @pytest.mark.asyncio
    async def test_empty_portfolio(self, risk_skill):
        """测试空的投资组合描述"""
        result = await risk_skill.assess_portfolio_risk(portfolio="")

        assert result.success is False
        assert "投资组合描述不能为空" in result.error

    @pytest.mark.asyncio
    async def test_invalid_portfolio_format(self, risk_skill):
        """测试无效的投资组合格式"""
        result = await risk_skill.assess_portfolio_risk(
            portfolio="invalid format"
        )

        assert result.success is False
        assert "投资组合格式错误" in result.error

    @pytest.mark.asyncio
    async def test_invalid_weight_sum(self, risk_skill):
        """测试权重和不为1的情况"""
        # 权重和大于1
        result = await risk_skill.assess_portfolio_risk(
            portfolio="600519:0.6,000001:0.6"
        )
        assert result.success is False
        assert "权重之和必须为1" in result.error

        # 权重和小于1
        result = await risk_skill.assess_portfolio_risk(
            portfolio="600519:0.3,000001:0.3"
        )
        assert result.success is False
        assert "权重之和必须为1" in result.error

    @pytest.mark.asyncio
    async def test_portfolio_with_benchmark(self, risk_skill, mock_tushare_client, sample_price_data):
        """测试带基准的投资组合评估"""
        mock_tushare_client.api.daily = Mock(return_value=sample_price_data)

        def mock_stock_basic(ts_code, fields):
            return pd.DataFrame([{'ts_code': ts_code, 'name': '测试股票'}])
        mock_tushare_client.api.stock_basic = Mock(side_effect=mock_stock_basic)

        result = await risk_skill.assess_portfolio_risk(
            portfolio="600519:0.5,000001:0.5",
            days=252,
            benchmark="000001"
        )

        # 如果成功，验证基准相关数据
        if result.success:
            metrics = result.data['metrics']
            if 'benchmark' in metrics:
                assert 'name' in metrics['benchmark']
                assert 'return' in metrics['benchmark']


class TestGenerateRiskReport:
    """测试 generate_risk_report 方法"""

    @pytest.mark.asyncio
    async def test_generate_report_for_single_stock(self, risk_skill, mock_tushare_client, sample_price_data):
        """测试为单只股票生成风险报告"""
        mock_tushare_client.api.daily = Mock(return_value=sample_price_data)
        mock_stock_basic = pd.DataFrame([{'ts_code': '600519.SH', 'name': '贵州茅台'}])
        mock_tushare_client.api.stock_basic = Mock(return_value=mock_stock_basic)

        result = await risk_skill.generate_risk_report(
            symbol="600519",
            days=252,
            is_portfolio=False
        )

        assert result.success is True
        assert result.data is not None

        report = result.data
        assert report['title'] == "资产风险评估报告"
        assert report['subject'] == "600519"
        assert 'generated_at' in report
        assert 'risk_rating' in report
        assert 'key_metrics' in report
        assert 'recommendations' in report
        assert 'risk_warnings' in report

        # 验证风险评级
        risk_rating = report['risk_rating']
        assert 'level' in risk_rating
        assert 'score' in risk_rating
        assert 'description' in risk_rating

        # 验证关键指标
        key_metrics = report['key_metrics']
        assert '预期年化收益率' in key_metrics
        assert '波动率(年化)' in key_metrics
        assert '夏普比率' in key_metrics

        # 验证投资建议和风险提示
        assert isinstance(report['recommendations'], list)
        assert isinstance(report['risk_warnings'], list)
        assert len(report['risk_warnings']) > 0

    @pytest.mark.asyncio
    async def test_generate_report_for_portfolio(self, risk_skill, mock_tushare_client, sample_price_data):
        """测试为投资组合生成风险报告"""
        mock_tushare_client.api.daily = Mock(return_value=sample_price_data)

        def mock_stock_basic(ts_code, fields):
            return pd.DataFrame([{'ts_code': ts_code, 'name': '测试股票'}])
        mock_tushare_client.api.stock_basic = Mock(side_effect=mock_stock_basic)

        result = await risk_skill.generate_risk_report(
            symbol="600519:0.5,000001:0.5",
            days=252,
            is_portfolio=True
        )

        if result.success:
            report = result.data
            assert report['title'] == "投资风险评估报告"
            if 'portfolio_holdings' in report:
                assert len(report['portfolio_holdings']) == 2

    @pytest.mark.asyncio
    async def test_empty_symbol_report(self, risk_skill):
        """测试空的股票代码或投资组合描述"""
        result = await risk_skill.generate_risk_report(symbol="")

        assert result.success is False
        assert "股票代码或投资组合描述不能为空" in result.error


class TestHelperMethods:
    """测试辅助方法"""

    def test_parse_portfolio_valid(self, risk_skill):
        """测试解析有效的投资组合"""
        holdings = risk_skill._parse_portfolio("600519:0.4,000001:0.3,600036:0.3")

        assert len(holdings) == 3
        assert holdings['600519'] == 0.4
        assert holdings['000001'] == 0.3
        assert holdings['600036'] == 0.3

    def test_parse_portfolio_invalid(self, risk_skill):
        """测试解析无效的投资组合"""
        holdings = risk_skill._parse_portfolio("invalid format")
        assert len(holdings) == 0

        holdings = risk_skill._parse_portfolio("600519:abc")
        assert len(holdings) == 0

    def test_parse_portfolio_with_spaces(self, risk_skill):
        """测试带空格的投资组合解析"""
        holdings = risk_skill._parse_portfolio(" 600519 : 0.5 , 000001 : 0.5 ")

        assert len(holdings) == 2
        assert holdings['600519'] == 0.5
        assert holdings['000001'] == 0.5

    def test_parse_portfolio_invalid_weight(self, risk_skill):
        """测试无效的权重值"""
        # 负权重
        holdings = risk_skill._parse_portfolio("600519:-0.5")
        assert len(holdings) == 0

        # 权重大于1
        holdings = risk_skill._parse_portfolio("600519:1.5")
        assert len(holdings) == 0

        # 权重为0
        holdings = risk_skill._parse_portfolio("600519:0")
        assert len(holdings) == 0

    def test_calculate_annualized_return(self, risk_skill):
        """测试年化收益率计算"""
        # 正收益
        returns = np.array([0.01, 0.02, -0.01, 0.03] * 63)  # 252个交易日
        annual_return = risk_skill._calculate_annualized_return(returns)
        assert isinstance(annual_return, float)

        # 空数组
        empty_returns = np.array([])
        annual_return = risk_skill._calculate_annualized_return(empty_returns)
        assert annual_return == 0.0

    def test_calculate_volatility(self, risk_skill):
        """测试波动率计算"""
        returns = np.array([0.01, -0.02, 0.015, -0.01] * 63)  # 252个交易日
        volatility = risk_skill._calculate_volatility(returns)

        assert isinstance(volatility, float)
        assert volatility > 0

        # 数据不足
        small_returns = np.array([0.01])
        volatility = risk_skill._calculate_volatility(small_returns)
        assert volatility == 0.0

    def test_calculate_sharpe_ratio(self, risk_skill):
        """测试夏普比率计算"""
        # 正收益
        returns = np.array([0.01, 0.02, 0.015, 0.012] * 63)
        sharpe = risk_skill._calculate_sharpe_ratio(returns)
        assert isinstance(sharpe, float)

        # 负收益
        negative_returns = np.array([-0.01, -0.02, -0.015, -0.012] * 63)
        sharpe = risk_skill._calculate_sharpe_ratio(negative_returns)
        assert sharpe < 0

    def test_calculate_max_drawdown(self, risk_skill):
        """测试最大回撤计算"""
        # 价格先上升后下跌
        prices = [100, 110, 120, 110, 100, 90]
        max_dd = risk_skill._calculate_max_drawdown(prices)

        assert isinstance(max_dd, float)
        assert max_dd < 0  # 回撤应该是负数

        # 价格持续上升
        rising_prices = [100, 110, 120, 130, 140]
        max_dd = risk_skill._calculate_max_drawdown(rising_prices)
        assert max_dd == 0.0

        # 数据不足
        small_prices = [100]
        max_dd = risk_skill._calculate_max_drawdown(small_prices)
        assert max_dd == 0.0

    def test_calculate_var(self, risk_skill):
        """测试 VaR 计算"""
        returns = np.random.randn(252) * 0.02  # 标准正态分布，标准差2%
        var_95 = risk_skill._calculate_var(returns, 0.95)

        assert isinstance(var_95, float)
        assert var_95 < 0  # VaR 应该是负数

        # 数据不足
        small_returns = np.array([0.01])
        var = risk_skill._calculate_var(small_returns, 0.95)
        assert var == 0.0

    def test_calculate_cvar(self, risk_skill):
        """测试 CVaR 计算"""
        returns = np.random.randn(252) * 0.02
        cvar_95 = risk_skill._calculate_cvar(returns, 0.95)

        assert isinstance(cvar_95, float)

        # CVaR 应该小于等于 VaR（更极端）
        var_95 = risk_skill._calculate_var(returns, 0.95)
        assert cvar_95 <= var_95

    def test_calculate_downside_deviation(self, risk_skill):
        """测试下行标准差计算"""
        returns = np.array([0.02, -0.01, 0.015, -0.02, 0.01, -0.015] * 42)
        downside_dev = risk_skill._calculate_downside_deviation(returns)

        assert isinstance(downside_dev, float)
        assert downside_dev >= 0

        # 全是正收益
        positive_returns = np.array([0.01, 0.02, 0.015] * 84)
        downside_dev = risk_skill._calculate_downside_deviation(positive_returns)
        assert downside_dev == 0.0

    def test_assess_risk_level(self, risk_skill):
        """测试风险等级评估"""
        # 低风险指标
        low_risk_metrics = {
            'volatility': 0.1,
            'sharpe_ratio': 2.0,
            'max_drawdown': -0.05
        }
        assessment = risk_skill._assess_risk_level(low_risk_metrics)
        assert assessment['level'] in ['低风险', '中低风险']

        # 高风险指标
        high_risk_metrics = {
            'volatility': 0.5,
            'sharpe_ratio': 0.2,
            'max_drawdown': -0.4
        }
        assessment = risk_skill._assess_risk_level(high_risk_metrics)
        assert assessment['level'] in ['中高风险', '高风险']
        assert assessment['score'] > 50

    def test_generate_recommendations(self, risk_skill):
        """测试投资建议生成"""
        metrics = {
            'sharpe_ratio': 1.5,
            'max_drawdown': -0.15,
            'volatility': 0.25,
            'beta': 1.3
        }
        risk_assessment = {
            'level': '中等风险',
            'score': 50
        }

        recommendations = risk_skill._generate_recommendations(metrics, risk_assessment)

        assert isinstance(recommendations, list)
        assert len(recommendations) > 0

    def test_generate_risk_warnings(self, risk_skill):
        """测试风险提示生成"""
        metrics = {
            'expected_return': -0.05,
            'var_95': -0.08,
            'cvar_95': -0.12,
            'max_drawdown': -0.55
        }
        risk_assessment = {
            'level': '高风险',
            'score': 85
        }

        warnings = risk_skill._generate_risk_warnings(metrics, risk_assessment)

        assert isinstance(warnings, list)
        assert len(warnings) > 0
        # 应该包含通用风险提示
        assert any('投资有风险' in w for w in warnings)

    def test_align_returns(self, risk_skill):
        """测试收益率对齐"""
        returns_data = {
            'stock1': [0.01, 0.02, 0.015, 0.01, 0.02] * 20,  # 100个数据点
            'stock2': [0.015, 0.01, 0.02, 0.012] * 20,  # 80个数据点
            'stock3': [-0.01, 0.02, 0.01] * 40  # 120个数据点
        }

        aligned = risk_skill._align_returns(returns_data)

        assert len(aligned) == 3
        assert len(aligned['stock1']) == len(aligned['stock2']) == len(aligned['stock3'])
        assert len(aligned['stock1']) == 80  # 应该对齐到最短的长度

    def test_align_returns_insufficient_data(self, risk_skill):
        """测试数据不足时的对齐"""
        returns_data = {
            'stock1': [0.01, 0.02] * 10,  # 20个数据点
        }

        aligned = risk_skill._align_returns(returns_data)
        assert len(aligned) == 0  # 数据少于30个，返回空字典

    def test_calculate_portfolio_returns(self, risk_skill):
        """测试投资组合收益率计算"""
        aligned_returns = {
            'stock1': np.array([0.01, 0.02, -0.01, 0.015]),
            'stock2': np.array([0.015, -0.01, 0.02, 0.01])
        }
        holdings = {
            'stock1': 0.6,
            'stock2': 0.4
        }

        portfolio_returns = risk_skill._calculate_portfolio_returns(
            aligned_returns, holdings
        )

        assert isinstance(portfolio_returns, np.ndarray)
        assert len(portfolio_returns) == 4
        # 验证加权计算
        expected_first = 0.01 * 0.6 + 0.015 * 0.4
        assert np.isclose(portfolio_returns[0], expected_first)


class TestCacheManagement:
    """测试缓存管理"""

    def test_get_cache_info(self, risk_skill, mock_tushare_client):
        """测试获取缓存信息"""
        mock_tushare_client.get_cache_info = Mock(return_value={'cache_size': 200})

        info = risk_skill.get_cache_info()
        assert info == {'cache_size': 200}
        mock_tushare_client.get_cache_info.assert_called_once()

    def test_clear_cache(self, risk_skill, mock_tushare_client):
        """测试清空缓存"""
        mock_tushare_client.clear_cache = Mock()

        risk_skill.clear_cache()
        mock_tushare_client.clear_cache.assert_called_once()

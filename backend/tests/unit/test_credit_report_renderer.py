"""Unit tests for investment_dd_renderer (v0.8.4).

Replaces the former test_credit_report_renderer.py (render_credit_report_markdown).
"""

from __future__ import annotations

from datetime import datetime

from app.agents.investment_dd_renderer import (
    _RECOMMENDATION_ZH,
    _RISK_LEVEL_ZH,
    _SEVERITY_ZH,
    render_investment_dd_report_markdown,
)
from app.agents.investment_dd_schema import (
    FinancialAnalysis,
    FinancialMetric,
    IndustryAnalysis,
    InvestmentDueDiligenceReport,
    InvestmentRecommendation,
    LegalQualification,
    PriceRange,
    RiskAssessment,
    RiskItem,
    TargetOverview,
    ValuationAnalysis,
)


def _full_report() -> InvestmentDueDiligenceReport:
    return InvestmentDueDiligenceReport(
        target_name="贵州茅台酒股份有限公司",
        target_ts_code="600519.SH",
        request_id="req-test-002",
        generated_at=datetime(2026, 5, 4, 12, 0, 0),
        target_overview=TargetOverview(
            narrative="贵州茅台是国内白酒龙头。",
            registered_capital="12.56 亿元",
            main_business="白酒生产销售",
            controlling_shareholder="贵州省国资委",
            listing_status="A 股主板",
            current_pe=25.0,
            current_pb=8.5,
            current_market_cap=22000.0,
            dividend_yield=2.0,
            evidence=["maotai_2024_h1::3", "maotai_2024_h1::5"],
        ),
        legal_qualification=LegalQualification(
            narrative="主体合规,无重大不良。",
            legal_status="合规",
            business_qualifications=["白酒生产许可"],
            adverse_records=[],
            evidence=["maotai_2024_h1::10"],
        ),
        financial_analysis=FinancialAnalysis(
            narrative="财务稳健,盈利能力突出。",
            key_metrics=[
                FinancialMetric(
                    name="营业收入", value="819 亿元", period="2024 H1", yoy_change="+17%"
                ),
                FinancialMetric(
                    name="净利润", value="417 亿元", period="2024 H1", yoy_change="+15%"
                ),
            ],
            profitability_analysis="毛利率 91%,行业第一。",
            growth_analysis="营收同比 +17%,净利同比 +15%。",
            return_analysis="ROE 33.5%,高于行业均值。",
            cash_flow_analysis="经营性现金流持续为正。",
            valuation_analysis=ValuationAnalysis(
                narrative="当前估值处于历史中低位。",
                pe_historical_percentile="近 5 年 30 分位",
                dcf_valuation="DCF 内在价值 2100 元",
                peer_comparison="五粮液 PE 22x,茅台溢价合理",
            ),
            year_over_year_summary="同比双位数增长。",
            evidence=["maotai_2024_h1::20", "maotai_2024_h1::25"],
        ),
        industry_analysis=IndustryAnalysis(
            narrative="白酒行业景气度温和。",
            industry_name="白酒",
            industry_outlook="稳定增长",
            competitive_position="高端龙头",
            key_competitors=["五粮液", "泸州老窖"],
            policy_impact="消费税政策无重大变化。",
            evidence=["maotai_2024_h1::40"],
        ),
        risk_assessment=RiskAssessment(
            narrative="整体风险低。",
            market_risk=[
                RiskItem(
                    title="市场流动性",
                    description="大盘下跌带动回调风险。",
                    severity="low",
                    mitigations=["分批建仓"],
                ),
            ],
            growth_risk=[],
            event_risk=[],
            valuation_risk=[],
            overall_risk_level="low",
            evidence=["maotai_2024_h1::50"],
        ),
        investment_recommendation=InvestmentRecommendation(
            narrative="建议增持,中期持有。",
            recommendation="recommend_overweight",
            recommended_position_size_pct=5.0,
            recommended_holding_period="medium_term",
            recommended_entry_price_range=PriceRange(low=1700.0, high=1800.0),
            recommended_stop_loss_price=1600.0,
            estimated_target_price_range=PriceRange(low=2000.0, high=2200.0),
            position_management_conditions=["回调 5% 时加仓"],
            evidence=["maotai_2024_h1::60"],
        ),
    )


def test_renders_all_six_sections() -> None:
    md = render_investment_dd_report_markdown(_full_report())
    assert "# 投资标的尽调报告 — 贵州茅台酒股份有限公司 (600519.SH)" in md
    assert "## § 1 标的基本信息" in md
    assert "## § 2 主体资格" in md
    assert "## § 3 财务分析" in md
    assert "## § 4 行业分析" in md
    assert "## § 5 风险评估" in md
    assert "## § 6 投资建议" in md


def test_includes_metric_table() -> None:
    md = render_investment_dd_report_markdown(_full_report())
    assert "营业收入" in md
    assert "819 亿元" in md


def test_includes_evidence_footnotes_per_section() -> None:
    md = render_investment_dd_report_markdown(_full_report())
    assert "maotai_2024_h1::3" in md  # target_overview evidence
    assert "maotai_2024_h1::20" in md  # financial_analysis evidence
    assert "maotai_2024_h1::60" in md  # investment_recommendation evidence


def test_idempotent() -> None:
    r = _full_report()
    assert render_investment_dd_report_markdown(r) == render_investment_dd_report_markdown(r)


def test_recommendation_label_zh() -> None:
    md = render_investment_dd_report_markdown(_full_report())
    assert "增持" in md  # recommend_overweight → 增持


def test_recommendation_zh_covers_all_literals() -> None:
    """Meta-guard: _RECOMMENDATION_ZH must cover every Literal value."""
    from typing import get_args

    decision_field = InvestmentRecommendation.model_fields["recommendation"]
    literal_values = set(get_args(decision_field.annotation))
    assert literal_values == set(_RECOMMENDATION_ZH.keys()), (
        f"_RECOMMENDATION_ZH out of sync with schema: "
        f"missing={literal_values - set(_RECOMMENDATION_ZH.keys())}, "
        f"extra={set(_RECOMMENDATION_ZH.keys()) - literal_values}"
    )


def test_risk_level_zh_covers_all_literals() -> None:
    from typing import get_args

    field = RiskAssessment.model_fields["overall_risk_level"]
    literal_values = set(get_args(field.annotation))
    assert literal_values == set(_RISK_LEVEL_ZH.keys())


def test_severity_zh_covers_all_literals() -> None:
    from typing import get_args

    field = RiskItem.model_fields["severity"]
    literal_values = set(get_args(field.annotation))
    assert literal_values == set(_SEVERITY_ZH.keys())


def test_empty_key_metrics_renders_placeholder() -> None:
    """FinancialAnalysis.key_metrics=[] should render a placeholder, not crash."""
    r = _full_report()
    r.financial_analysis.key_metrics = []
    md = render_investment_dd_report_markdown(r)
    assert "_暂无关键财务指标_" in md
    assert "## § 3 财务分析" in md  # section still rendered


def test_disclaimer_appears_in_output() -> None:
    md = render_investment_dd_report_markdown(_full_report())
    assert "AI 模型" in md
    assert "投资决策" in md

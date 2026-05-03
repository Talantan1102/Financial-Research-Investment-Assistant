"""Unit test for credit_report_renderer."""

from __future__ import annotations

from datetime import datetime

from app.agents.credit_report_renderer import render_credit_report_markdown
from app.agents.credit_report_schema import (
    CompanyOverview,
    CreditInvestigationReport,
    CreditRecommendation,
    FinancialAnalysis,
    FinancialMetric,
    IndustryAnalysis,
    LegalQualification,
    RiskAssessment,
    RiskItem,
)


def _full_report() -> CreditInvestigationReport:
    return CreditInvestigationReport(
        company_name="贵州茅台",
        request_id="req-test-002",
        generated_at=datetime(2026, 5, 3, 12, 0, 0),
        company_overview=CompanyOverview(
            narrative="贵州茅台是国内白酒龙头。",
            unified_credit_code="91520000215123456X",
            registered_capital="12.56 亿元",
            main_business="白酒生产销售",
            controlling_shareholder="贵州省国资委",
            listing_status="A 股主板",
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
            solvency_analysis="偿债能力优异,现金充裕。",
            profitability_analysis="毛利率 91%,行业第一。",
            cash_flow_analysis="经营性现金流持续为正。",
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
            operational_risks=[
                RiskItem(
                    title="渠道库存",
                    description="经销商压货。",
                    severity="low",
                    mitigations=["渠道优化"],
                ),
            ],
            financial_risks=[],
            industry_risks=[],
            compliance_risks=[],
            overall_risk_level="low",
            evidence=["maotai_2024_h1::50"],
        ),
        credit_recommendation=CreditRecommendation(
            narrative="建议批准 50 亿元 3 年期流动资金贷款。",
            decision="approve",
            recommended_credit_limit="50 亿元",
            recommended_term="3 年",
            recommended_rate_range="LPR + 0bp ~ LPR + 30bp",
            guarantee_requirements=[],
            conditions=[],
            evidence=["maotai_2024_h1::60"],
        ),
    )


def test_renders_all_six_sections() -> None:
    md = render_credit_report_markdown(_full_report())
    assert "# 信贷调查报告 — 贵州茅台" in md
    assert "## § 1 基本信息" in md
    assert "## § 2 主体资格" in md
    assert "## § 3 财务分析" in md
    assert "## § 4 行业分析" in md
    assert "## § 5 风险评估" in md
    assert "## § 6 信贷建议" in md


def test_includes_metric_table() -> None:
    md = render_credit_report_markdown(_full_report())
    assert "营业收入" in md
    assert "819 亿元" in md


def test_includes_evidence_footer_per_section() -> None:
    md = render_credit_report_markdown(_full_report())
    assert "maotai_2024_h1::3" in md  # company_overview evidence
    assert "maotai_2024_h1::20" in md  # financial_analysis evidence
    assert "maotai_2024_h1::60" in md  # credit_recommendation evidence


def test_idempotent() -> None:
    r = _full_report()
    assert render_credit_report_markdown(r) == render_credit_report_markdown(r)


def test_decision_label_zh() -> None:
    md = render_credit_report_markdown(_full_report())
    assert "批准" in md  # approve → 批准


def test_decision_zh_covers_all_literals() -> None:
    """Meta-guard: _DECISION_ZH must cover every Literal value in CreditRecommendation.decision."""
    from typing import get_args

    from app.agents.credit_report_renderer import _DECISION_ZH
    from app.agents.credit_report_schema import CreditRecommendation

    decision_field = CreditRecommendation.model_fields["decision"]
    literal_values = set(get_args(decision_field.annotation))
    assert literal_values == set(_DECISION_ZH.keys()), (
        f"_DECISION_ZH out of sync with schema: "
        f"missing={literal_values - set(_DECISION_ZH.keys())}, "
        f"extra={set(_DECISION_ZH.keys()) - literal_values}"
    )


def test_risk_level_zh_covers_all_literals() -> None:
    """Meta-guard: _RISK_LEVEL_ZH must cover every Literal value in RiskAssessment.overall_risk_level."""
    from typing import get_args

    from app.agents.credit_report_renderer import _RISK_LEVEL_ZH
    from app.agents.credit_report_schema import RiskAssessment

    field = RiskAssessment.model_fields["overall_risk_level"]
    literal_values = set(get_args(field.annotation))
    assert literal_values == set(_RISK_LEVEL_ZH.keys())


def test_severity_zh_covers_all_literals() -> None:
    """Meta-guard: _SEVERITY_ZH must cover every Literal value in RiskItem.severity."""
    from typing import get_args

    from app.agents.credit_report_renderer import _SEVERITY_ZH
    from app.agents.credit_report_schema import RiskItem

    field = RiskItem.model_fields["severity"]
    literal_values = set(get_args(field.annotation))
    assert literal_values == set(_SEVERITY_ZH.keys())


def test_empty_key_metrics_renders_placeholder() -> None:
    """FinancialAnalysis.key_metrics=[] should render a placeholder, not crash."""
    r = _full_report()
    r.financial_analysis.key_metrics = []
    md = render_credit_report_markdown(r)
    assert "_暂无关键财务指标_" in md
    assert "## § 3 财务分析" in md  # section still rendered


def test_all_empty_risk_categories_render_placeholders() -> None:
    """All risk categories empty should render '_无' placeholders for each, not crash."""
    r = _full_report()
    r.risk_assessment.operational_risks = []
    r.risk_assessment.financial_risks = []
    r.risk_assessment.industry_risks = []
    r.risk_assessment.compliance_risks = []
    md = render_credit_report_markdown(r)
    # Each category renders an empty placeholder
    assert "_经营风险:无_" in md
    assert "_财务风险:无_" in md
    assert "_行业风险:无_" in md
    assert "_合规风险:无_" in md

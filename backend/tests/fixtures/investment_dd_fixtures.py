"""Fixtures for InvestmentDueDiligenceReport unit tests (v0.8.4)."""

from __future__ import annotations

from datetime import datetime

from app.agents.investment_dd_schema import (
    FinancialAnalysis,
    FinancialMetric,
    IndustryAnalysis,
    InvestmentDueDiligenceReport,
    InvestmentSynthesis,
    LegalQualification,
    RiskAssessment,
    TargetOverview,
    ValuationAnalysis,
)


def minimal_valid_report() -> InvestmentDueDiligenceReport:
    """Minimal valid InvestmentDueDiligenceReport — all required fields filled."""
    return InvestmentDueDiligenceReport(
        target_name="贵州茅台酒股份有限公司",
        target_ts_code="600519.SH",
        request_id="req-test-001",
        generated_at=datetime(2026, 5, 4, 12, 0, 0),
        target_overview=TargetOverview(
            narrative="贵州茅台是国内白酒行业龙头。",
            main_business="高端白酒生产与销售",
            evidence=["maotai_2024::0"],
        ),
        legal_qualification=LegalQualification(
            narrative="主体合规,无重大不良记录。",
            legal_status="合规",
            business_qualifications=[],
            adverse_records=[],
            evidence=["maotai_2024::1"],
        ),
        financial_analysis=FinancialAnalysis(
            narrative="财务稳健,盈利能力突出。",
            key_metrics=[
                FinancialMetric(name="营业收入", value="1782 亿元", period="2024 全年"),
            ],
            profitability_analysis="毛利率 91.8%,行业第一。",
            growth_analysis="营收同比 +15.4%,净利同比 +14.8%。",
            return_analysis="ROE 33.5%,ROIC 高于行业均值。",
            cash_flow_analysis="经营现金流净额 910 亿元,质量高。",
            valuation_analysis=ValuationAnalysis(
                narrative="当前估值处于历史中低位。",
            ),
            evidence=["maotai_2024::2"],
        ),
        industry_analysis=IndustryAnalysis(
            narrative="白酒行业景气度高,高端化趋势延续。",
            industry_name="白酒",
            industry_outlook="稳定增长",
            competitive_position="高端市场绝对龙头",
            key_competitors=["五粮液", "泸州老窖"],
            policy_impact="无重大不利政策。",
            evidence=["maotai_2024::3"],
        ),
        risk_assessment=RiskAssessment(
            narrative="整体风险可控,估值风险需关注。",
            market_risk=[],
            growth_risk=[],
            event_risk=[],
            valuation_risk=[],
            overall_risk_level="low",
            evidence=["maotai_2024::4"],
        ),
        investment_synthesis=InvestmentSynthesis(
            narrative="综合研判:基本面稳健、估值处历史中低位;需关注高端需求与估值消化。",
            key_judgment_factors=["高端白酒需求景气度", "估值能否消化"],
            valuation_context="当前价位于内在价值区间下沿。",
            bull_case=["高端龙头护城河深", "现金流质量高"],
            bear_case=["估值对需求波动敏感"],
            evidence=["maotai_2024::5"],
        ),
    )

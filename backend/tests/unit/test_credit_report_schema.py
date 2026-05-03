"""Unit test for CreditInvestigationReport Pydantic schema."""

from __future__ import annotations

from datetime import datetime

import pytest
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
from pydantic import ValidationError


def _minimal_report() -> CreditInvestigationReport:
    """Minimal valid report — all required fields filled, all optionals empty."""
    return CreditInvestigationReport(
        company_name="测试公司",
        request_id="req-test-001",
        generated_at=datetime(2026, 5, 3, 12, 0, 0),
        company_overview=CompanyOverview(
            narrative="测试综述。",
            main_business="测试主营。",
            evidence=["c1::0"],
        ),
        legal_qualification=LegalQualification(
            narrative="主体合规。",
            legal_status="合规",
            business_qualifications=[],
            adverse_records=[],
            evidence=["c1::1"],
        ),
        financial_analysis=FinancialAnalysis(
            narrative="财务稳定。",
            key_metrics=[
                FinancialMetric(name="营业收入", value="100 亿元", period="2024 H1"),
            ],
            solvency_analysis="偿债能力强。",
            profitability_analysis="盈利稳定。",
            cash_flow_analysis="现金流健康。",
            evidence=["c1::2"],
        ),
        industry_analysis=IndustryAnalysis(
            narrative="行业景气。",
            industry_name="白酒",
            industry_outlook="稳定增长",
            competitive_position="龙头",
            key_competitors=[],
            policy_impact="无重大不利政策。",
            evidence=["c1::3"],
        ),
        risk_assessment=RiskAssessment(
            narrative="整体风险可控。",
            operational_risks=[],
            financial_risks=[],
            industry_risks=[],
            compliance_risks=[],
            overall_risk_level="low",
            evidence=["c1::4"],
        ),
        credit_recommendation=CreditRecommendation(
            narrative="建议批准。",
            decision="approve",
            guarantee_requirements=[],
            conditions=[],
            evidence=["c1::5"],
        ),
    )


def test_minimal_valid_report() -> None:
    r = _minimal_report()
    assert r.company_name == "测试公司"
    assert r.credit_recommendation.decision == "approve"


def test_empty_evidence_rejected() -> None:
    """每个 section evidence 至少 1 个 chunk_id(min_length=1)。"""
    with pytest.raises(ValidationError):
        CompanyOverview(narrative="x", main_business="y", evidence=[])


def test_decision_enum_strict() -> None:
    """decision 必须是三值之一。"""
    with pytest.raises(ValidationError):
        CreditRecommendation(
            narrative="x",
            decision="maybe",  # type: ignore[arg-type]
            guarantee_requirements=[],
            conditions=[],
            evidence=["c1::0"],
        )


def test_overall_risk_level_enum_strict() -> None:
    with pytest.raises(ValidationError):
        RiskAssessment(
            narrative="x",
            operational_risks=[],
            financial_risks=[],
            industry_risks=[],
            compliance_risks=[],
            overall_risk_level="catastrophic",  # type: ignore[arg-type]
            evidence=["c1::0"],
        )


def test_risk_item_severity_enum_strict() -> None:
    with pytest.raises(ValidationError):
        RiskItem(
            title="x",
            description="y",
            severity="moderate",  # type: ignore[arg-type]
        )


def test_required_field_missing_rejected() -> None:
    """company_overview 缺 main_business 必拒。"""
    with pytest.raises(ValidationError):
        CompanyOverview(narrative="x", evidence=["c1::0"])  # type: ignore[call-arg]


def test_json_roundtrip() -> None:
    r = _minimal_report()
    j = r.model_dump_json()
    r2 = CreditInvestigationReport.model_validate_json(j)
    assert r2 == r


def test_json_schema_generation() -> None:
    """`model_json_schema()` 不抛异常,作为 LLMService.chat schema= 入参形态。"""
    schema = CreditInvestigationReport.model_json_schema()
    assert schema["type"] == "object"
    assert "company_name" in schema["properties"]

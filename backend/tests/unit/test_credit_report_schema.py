"""Unit tests for InvestmentDueDiligenceReport Pydantic schema (v0.8.4).

Replaces the former test_credit_report_schema.py (CreditInvestigationReport).
"""

from __future__ import annotations

import pytest
from app.agents.investment_dd_schema import (
    InvestmentDueDiligenceReport,
    InvestmentRecommendation,
    PriceRange,
    RiskAssessment,
    RiskItem,
    TargetOverview,
)
from pydantic import ValidationError


def _minimal_report() -> InvestmentDueDiligenceReport:
    """Minimal valid report — all required fields filled, all optionals empty."""
    from tests.fixtures.investment_dd_fixtures import minimal_valid_report

    return minimal_valid_report()


def test_minimal_valid_report() -> None:
    r = _minimal_report()
    assert r.target_name == "贵州茅台酒股份有限公司"
    assert r.investment_recommendation.recommendation == "recommend_overweight"


def test_empty_evidence_rejected() -> None:
    """每个 section evidence 至少 1 个 chunk_id(min_length=1)。"""
    with pytest.raises(ValidationError):
        TargetOverview(narrative="x", main_business="y", evidence=[])


def test_recommendation_enum_strict() -> None:
    """recommendation 必须是 5 档之一。"""
    with pytest.raises(ValidationError):
        InvestmentRecommendation(
            narrative="x",
            recommendation="maybe",  # type: ignore[arg-type]
            recommended_position_size_pct=5.0,
            recommended_holding_period="medium_term",
            recommended_entry_price_range=PriceRange(low=100.0, high=110.0),
            recommended_stop_loss_price=90.0,
            estimated_target_price_range=PriceRange(low=120.0, high=140.0),
            position_management_conditions=[],
            evidence=["c1::0"],
        )


def test_overall_risk_level_enum_strict() -> None:
    with pytest.raises(ValidationError):
        RiskAssessment(
            narrative="x",
            market_risk=[],
            growth_risk=[],
            event_risk=[],
            valuation_risk=[],
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
    """target_overview 缺 main_business 必拒。"""
    with pytest.raises(ValidationError):
        TargetOverview(narrative="x", evidence=["c1::0"])  # type: ignore[call-arg]


def test_json_roundtrip() -> None:
    r = _minimal_report()
    j = r.model_dump_json()
    r2 = InvestmentDueDiligenceReport.model_validate_json(j)
    assert r2 == r


def test_json_schema_generation() -> None:
    """`model_json_schema()` 不抛异常,作为 LLMService.chat schema= 入参形态。"""
    schema = InvestmentDueDiligenceReport.model_json_schema()
    assert schema["type"] == "object"
    assert "target_name" in schema["properties"]


def test_disclaimer_has_default() -> None:
    """disclaimer 字段必须有非空默认值包含 'AI 模型'。"""
    r = _minimal_report()
    assert r.disclaimer
    assert "AI 模型" in r.disclaimer

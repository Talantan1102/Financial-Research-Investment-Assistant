"""Unit tests for InvestmentDueDiligenceReport Pydantic schema (v0.8.4)."""

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


def test_recommendation_enum_values() -> None:
    """recommendation 枚举必须是 5 档卖方研报标准化术语。"""
    valid = [
        "recommend_buy",
        "recommend_overweight",
        "recommend_hold",
        "recommend_underweight",
        "recommend_sell",
    ]
    for v in valid:
        rec = InvestmentRecommendation(
            narrative="...",
            recommendation=v,  # type: ignore[arg-type]
            recommended_position_size_pct=5.0,
            recommended_holding_period="medium_term",
            recommended_entry_price_range=PriceRange(low=100.0, high=110.0),
            recommended_stop_loss_price=90.0,
            estimated_target_price_range=PriceRange(low=120.0, high=140.0),
            position_management_conditions=["市场系统性回调 5% 时加仓"],
            evidence=["chunk_001"],
        )
        assert rec.recommendation == v


def test_evidence_min_length_enforced() -> None:
    """每个 section evidence 至少 1 chunk_id。"""
    with pytest.raises(ValidationError):
        InvestmentRecommendation(
            narrative="...",
            recommendation="recommend_hold",
            recommended_position_size_pct=5.0,
            recommended_holding_period="medium_term",
            recommended_entry_price_range=PriceRange(low=100.0, high=110.0),
            recommended_stop_loss_price=90.0,
            estimated_target_price_range=PriceRange(low=120.0, high=140.0),
            position_management_conditions=[],
            evidence=[],  # ← empty,必须 fail
        )


def test_main_report_has_disclaimer_field() -> None:
    """主报告必须含 disclaimer 字段(默认值非空)。"""
    from tests.fixtures.investment_dd_fixtures import minimal_valid_report

    report = minimal_valid_report()
    assert report.disclaimer
    assert "AI 模型" in report.disclaimer
    assert "辅助生成" in report.disclaimer
    assert "投资决策" in report.disclaimer


def test_minimal_valid_report() -> None:
    from tests.fixtures.investment_dd_fixtures import minimal_valid_report

    r = minimal_valid_report()
    assert r.target_name == "贵州茅台酒股份有限公司"
    assert r.investment_recommendation.recommendation == "recommend_overweight"


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
    from tests.fixtures.investment_dd_fixtures import minimal_valid_report

    r = minimal_valid_report()
    j = r.model_dump_json()
    r2 = InvestmentDueDiligenceReport.model_validate_json(j)
    assert r2 == r


def test_json_schema_generation() -> None:
    """`model_json_schema()` 不抛异常,作为 LLMService.chat schema= 入参形态。"""
    schema = InvestmentDueDiligenceReport.model_json_schema()
    assert schema["type"] == "object"
    assert "target_name" in schema["properties"]


def test_empty_evidence_in_target_overview_rejected() -> None:
    """TargetOverview evidence 至少 1 chunk_id(独立于 InvestmentRecommendation 的校验)。"""
    with pytest.raises(ValidationError):
        TargetOverview(narrative="x", main_business="y", evidence=[])


def test_recommendation_enum_strict() -> None:
    """recommendation 必须是 5 档之一,非法值必拒。"""
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


def test_price_range_accepts_valid_low_high() -> None:
    """PriceRange: low < high 是业务约束 — 只验证类型可实例化。"""
    pr = PriceRange(low=100.0, high=200.0)
    assert pr.low < pr.high


def test_investment_report_target_ts_code_stored() -> None:
    """target_ts_code 字段存储并可查询。"""
    from tests.fixtures.investment_dd_fixtures import minimal_valid_report

    r = minimal_valid_report()
    assert r.target_ts_code == "600519.SH"


def test_risk_assessment_optional_risk_items_default_empty() -> None:
    """market_risk / growth_risk / event_risk / valuation_risk 可为空列表。"""
    ra = RiskAssessment(
        narrative="低风险",
        market_risk=[],
        growth_risk=[],
        event_risk=[],
        valuation_risk=[],
        overall_risk_level="low",
        evidence=["c1::0"],
    )
    assert ra.market_risk == []
    assert ra.overall_risk_level == "low"

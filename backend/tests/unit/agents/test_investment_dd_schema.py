"""Unit tests for InvestmentDueDiligenceReport Pydantic schema (v0.8.4)."""

from __future__ import annotations

import pytest
from app.agents.investment_dd_schema import (
    InvestmentRecommendation,
    PriceRange,
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

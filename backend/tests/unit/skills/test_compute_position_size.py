"""Unit tests for compute_position_size_pct (pure deterministic helper)."""

from __future__ import annotations

import pytest
from app.skills.financial_research.scripts.compute_position_size import (
    compute_position_size_pct,
)


def test_buy_moderate_large_cap_yields_base_15() -> None:
    pct = compute_position_size_pct(
        recommendation="recommend_buy",
        risk_tolerance="moderate",
        market_cap_cny=200_000_000_000.0,  # 2000 亿, large
    )
    assert pct == pytest.approx(15.0)


def test_buy_aggressive_small_cap_applies_haircut() -> None:
    # base 15 * aggressive 1.6 * haircut 0.7 = 16.8
    pct = compute_position_size_pct(
        recommendation="recommend_buy",
        risk_tolerance="aggressive",
        market_cap_cny=10_000_000_000.0,  # 100 亿, small
    )
    assert pct == pytest.approx(16.8)


def test_capped_at_max_position_pct() -> None:
    # base 15 * very_aggressive 2.0 * 1.0 = 30, equals cap
    pct = compute_position_size_pct(
        recommendation="recommend_buy",
        risk_tolerance="very_aggressive",
        market_cap_cny=200_000_000_000.0,
    )
    assert pct == pytest.approx(30.0)
    assert pct <= 30.0


def test_recommend_sell_yields_zero() -> None:
    pct = compute_position_size_pct(
        recommendation="recommend_sell",
        risk_tolerance="aggressive",
        market_cap_cny=200_000_000_000.0,
    )
    assert pct == pytest.approx(0.0)


def test_deterministic_across_repeated_calls() -> None:
    results = [
        compute_position_size_pct(
            recommendation="recommend_overweight",
            risk_tolerance="balanced",
            market_cap_cny=80_000_000_000.0,
        )
        for _ in range(5)
    ]
    assert len(set(results)) == 1

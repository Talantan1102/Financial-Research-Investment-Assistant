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


def test_buy_conservative_large_cap_yields_7_5() -> None:
    """conservative multiplier=0.5 explicit numeric: 15 * 0.5 * 1.0 = 7.5%."""
    pct = compute_position_size_pct(
        recommendation="recommend_buy",
        risk_tolerance="conservative",
        market_cap_cny=200_000_000_000.0,  # large cap
    )
    assert pct == pytest.approx(7.5)


def test_hold_between_buy_and_sell_position() -> None:
    """hold position 应在 buy 和 sell 之间 (defensive ordering)."""
    buy = compute_position_size_pct(
        recommendation="recommend_buy",
        risk_tolerance="moderate",
        market_cap_cny=200_000_000_000.0,
    )
    hold = compute_position_size_pct(
        recommendation="recommend_hold",
        risk_tolerance="moderate",
        market_cap_cny=200_000_000_000.0,
    )
    sell = compute_position_size_pct(
        recommendation="recommend_sell",
        risk_tolerance="moderate",
        market_cap_cny=200_000_000_000.0,
    )
    assert sell <= hold <= buy
    # 防止 hold 改 0%: hold 应该是 5.0% (5 * 1.0 * 1.0)
    assert hold == pytest.approx(5.0)

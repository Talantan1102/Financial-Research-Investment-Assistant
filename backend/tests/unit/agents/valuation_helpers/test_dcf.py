"""L0 — DCF valuation helper (growth_trajectory + WACC + main + sensitivity).

Task 6 (本 commit): growth_trajectory only.
Task 7 (后): WACC + compute_dcf_value 主入口.
Task 8 (后): sensitivity matrix.
"""

from __future__ import annotations

import math

import pytest

# ── compute_growth_trajectory ─────────────────────────────────────────────────


def test_growth_trajectory_base_uses_forecast_if_available() -> None:
    """base 场景:forecast 优先于 historical avg(管理层 guidance 第一手)"""
    from app.agents.valuation_helpers.dcf import compute_growth_trajectory

    rates = compute_growth_trajectory(
        historical_growth=[0.05, 0.08, 0.06, 0.07, 0.05],  # avg 6.2%
        forecast_growth=0.10,  # 管理层指引 10%
        industry_terminal=0.025,
        scenario="base",
        n_years=10,
    )
    assert len(rates) == 10
    assert rates[0] == pytest.approx(0.10, rel=0.01)  # 启动 = forecast
    assert rates[-1] == pytest.approx(0.025, rel=0.05)  # 最后年 ≈ terminal
    # 单调 decay (允许 noise)
    for i in range(len(rates) - 1):
        assert rates[i] >= rates[i + 1] - 0.001


def test_growth_trajectory_base_falls_back_historical_avg() -> None:
    """base 场景:无 forecast 时用 historical avg"""
    from app.agents.valuation_helpers.dcf import compute_growth_trajectory

    rates = compute_growth_trajectory(
        historical_growth=[0.05, 0.08, 0.06, 0.07, 0.05],
        forecast_growth=None,
        industry_terminal=0.025,
        scenario="base",
        n_years=10,
    )
    assert rates[0] == pytest.approx(0.062, rel=0.05)  # avg 6.2%
    assert rates[-1] == pytest.approx(0.025, rel=0.05)


def test_growth_trajectory_bull_scenario() -> None:
    """bull = max(historical, forecast) × 1.2"""
    from app.agents.valuation_helpers.dcf import compute_growth_trajectory

    rates = compute_growth_trajectory(
        historical_growth=[0.05, 0.08, 0.06, 0.07, 0.05],
        forecast_growth=0.10,
        industry_terminal=0.025,
        scenario="bull",
        n_years=10,
    )
    # max(0.062, 0.10) × 1.2 = 0.12
    assert rates[0] == pytest.approx(0.12, rel=0.05)


def test_growth_trajectory_bear_scenario() -> None:
    """bear = min(historical, forecast) × 0.8"""
    from app.agents.valuation_helpers.dcf import compute_growth_trajectory

    rates = compute_growth_trajectory(
        historical_growth=[0.05, 0.08, 0.06, 0.07, 0.05],
        forecast_growth=0.10,
        industry_terminal=0.025,
        scenario="bear",
        n_years=10,
    )
    # min(0.062, 0.10) × 0.8 = 0.0496
    assert rates[0] == pytest.approx(0.0496, rel=0.05)


def test_growth_trajectory_raises_for_empty_historical_and_no_forecast() -> None:
    from app.agents.valuation_helpers.dcf import compute_growth_trajectory
    from app.agents.valuation_helpers.exceptions import InsufficientDataForModelError

    with pytest.raises(InsufficientDataForModelError):
        compute_growth_trajectory(
            historical_growth=[],
            forecast_growth=None,
            industry_terminal=0.025,
            scenario="base",
        )


def test_growth_trajectory_clamps_below_terminal() -> None:
    """启动值 ≤ industry_terminal → 全 clamp 至 terminal(防衰减成负数)."""
    from app.agents.valuation_helpers.dcf import compute_growth_trajectory

    rates = compute_growth_trajectory(
        historical_growth=[0.01, 0.01, 0.01],  # avg 1% < terminal 2.5%
        forecast_growth=None,
        industry_terminal=0.025,
        scenario="bear",  # bear 还要 ×0.8,更低
        n_years=5,
    )
    assert all(r >= 0.025 - 0.001 for r in rates)


def test_growth_trajectory_raises_on_nan_input() -> None:
    """forecast_growth=NaN / industry_terminal=NaN / historical 含 NaN → raise"""
    from app.agents.valuation_helpers.dcf import compute_growth_trajectory
    from app.agents.valuation_helpers.exceptions import InsufficientDataForModelError

    with pytest.raises(InsufficientDataForModelError):
        compute_growth_trajectory(
            historical_growth=[0.05, 0.08],
            forecast_growth=math.nan,
            industry_terminal=0.025,
            scenario="base",
        )
    with pytest.raises(InsufficientDataForModelError):
        compute_growth_trajectory(
            historical_growth=[0.05, math.nan, 0.07],
            forecast_growth=None,
            industry_terminal=0.025,
            scenario="base",
        )
    with pytest.raises(InsufficientDataForModelError):
        compute_growth_trajectory(
            historical_growth=[0.05, 0.08],
            forecast_growth=None,
            industry_terminal=math.nan,
            scenario="base",
        )


def test_growth_trajectory_raises_on_inf_input() -> None:
    from app.agents.valuation_helpers.dcf import compute_growth_trajectory
    from app.agents.valuation_helpers.exceptions import InsufficientDataForModelError

    with pytest.raises(InsufficientDataForModelError):
        compute_growth_trajectory(
            historical_growth=[0.05, 0.08],
            forecast_growth=math.inf,
            industry_terminal=0.025,
            scenario="base",
        )


def test_growth_trajectory_invalid_scenario_raises() -> None:
    """非 base/bull/bear → ValueError(by Literal enforcement + explicit raise)"""
    from app.agents.valuation_helpers.dcf import compute_growth_trajectory

    with pytest.raises((ValueError, TypeError)):
        compute_growth_trajectory(
            historical_growth=[0.05],
            forecast_growth=None,
            industry_terminal=0.025,
            scenario="moderate",  # type: ignore[arg-type]
        )


def test_growth_trajectory_n_years_1() -> None:
    """n_years=1 → 单元素 [start]"""
    from app.agents.valuation_helpers.dcf import compute_growth_trajectory

    rates = compute_growth_trajectory(
        historical_growth=[0.05],
        forecast_growth=0.10,
        industry_terminal=0.025,
        scenario="base",
        n_years=1,
    )
    assert rates == [pytest.approx(0.10, rel=0.01)]


def test_growth_trajectory_n_years_2_collapses_to_start_terminal() -> None:
    """n_years=2 → [start, terminal] (最小非平凡 decay)"""
    from app.agents.valuation_helpers.dcf import compute_growth_trajectory

    rates = compute_growth_trajectory(
        historical_growth=[0.05],
        forecast_growth=0.10,
        industry_terminal=0.025,
        scenario="base",
        n_years=2,
    )
    assert len(rates) == 2
    assert rates[0] == pytest.approx(0.10, rel=0.01)
    assert rates[1] == pytest.approx(0.025, rel=0.01)


def test_growth_trajectory_n_years_below_1_raises() -> None:
    """n_years < 1 → ValueError (programming error, not data error)"""
    from app.agents.valuation_helpers.dcf import compute_growth_trajectory

    with pytest.raises(ValueError):
        compute_growth_trajectory(
            historical_growth=[0.05],
            forecast_growth=0.10,
            industry_terminal=0.025,
            scenario="base",
            n_years=0,
        )
    with pytest.raises(ValueError):
        compute_growth_trajectory(
            historical_growth=[0.05],
            forecast_growth=0.10,
            industry_terminal=0.025,
            scenario="base",
            n_years=-3,
        )


def test_growth_trajectory_negative_historical_base_clamps() -> None:
    """萎缩公司 base case: historical avg < 0 < terminal → clamp 全 terminal"""
    from app.agents.valuation_helpers.dcf import compute_growth_trajectory

    rates = compute_growth_trajectory(
        historical_growth=[-0.02, -0.03, -0.01],
        forecast_growth=None,
        industry_terminal=0.025,
        scenario="base",
        n_years=5,
    )
    # avg = -0.02 < terminal 0.025 → 全 clamp
    assert all(r == pytest.approx(0.025) for r in rates)

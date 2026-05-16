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


# ── compute_company_wacc ──────────────────────────────────────────────────────


def test_wacc_neutral_beta_low_leverage() -> None:
    """β=1.0, d/e=0.3, baseline 8% → wacc = 8% + 0 + 0 = 8%"""
    from app.agents.valuation_helpers.dcf import compute_company_wacc

    wacc = compute_company_wacc(industry_baseline_wacc=0.08, company_beta=1.0, debt_to_equity=0.3)
    assert wacc == pytest.approx(0.08, rel=0.01)


def test_wacc_high_beta_high_leverage() -> None:
    """β=1.5, d/e=1.5, baseline 8% → wacc = 8% + 1% + 1% = 10%"""
    from app.agents.valuation_helpers.dcf import compute_company_wacc

    wacc = compute_company_wacc(industry_baseline_wacc=0.08, company_beta=1.5, debt_to_equity=1.5)
    assert wacc == pytest.approx(0.10, rel=0.01)


def test_wacc_low_beta_low_leverage() -> None:
    """β=0.5, d/e=0.1, baseline 10% → wacc = 10% + (-1%) + 0 = 9%"""
    from app.agents.valuation_helpers.dcf import compute_company_wacc

    wacc = compute_company_wacc(industry_baseline_wacc=0.10, company_beta=0.5, debt_to_equity=0.1)
    assert wacc == pytest.approx(0.09, rel=0.01)


def test_wacc_missing_beta_uses_baseline() -> None:
    """缺 β → β_adj = 0, 只走 leverage_adj"""
    from app.agents.valuation_helpers.dcf import compute_company_wacc

    wacc = compute_company_wacc(industry_baseline_wacc=0.10, company_beta=None, debt_to_equity=0.2)
    assert wacc == pytest.approx(0.10, rel=0.01)


def test_wacc_raises_on_nan_input() -> None:
    """baseline / beta / d/e 任一 NaN → raise"""
    from app.agents.valuation_helpers.dcf import compute_company_wacc
    from app.agents.valuation_helpers.exceptions import InsufficientDataForModelError

    with pytest.raises(InsufficientDataForModelError):
        compute_company_wacc(industry_baseline_wacc=math.nan, company_beta=1.0, debt_to_equity=0.5)
    with pytest.raises(InsufficientDataForModelError):
        compute_company_wacc(industry_baseline_wacc=0.08, company_beta=math.nan, debt_to_equity=0.5)
    with pytest.raises(InsufficientDataForModelError):
        compute_company_wacc(industry_baseline_wacc=0.08, company_beta=1.0, debt_to_equity=math.nan)


def test_wacc_raises_on_inf_input() -> None:
    from app.agents.valuation_helpers.dcf import compute_company_wacc
    from app.agents.valuation_helpers.exceptions import InsufficientDataForModelError

    with pytest.raises(InsufficientDataForModelError):
        compute_company_wacc(industry_baseline_wacc=math.inf, company_beta=1.0, debt_to_equity=0.5)


def test_wacc_raises_on_negative_baseline() -> None:
    """baseline_wacc ≤ 0 是数据 corruption(实际 WACC 都 > 0)→ raise"""
    from app.agents.valuation_helpers.dcf import compute_company_wacc
    from app.agents.valuation_helpers.exceptions import InsufficientDataForModelError

    with pytest.raises(InsufficientDataForModelError):
        compute_company_wacc(industry_baseline_wacc=0, company_beta=1.0, debt_to_equity=0.5)
    with pytest.raises(InsufficientDataForModelError):
        compute_company_wacc(industry_baseline_wacc=-0.05, company_beta=1.0, debt_to_equity=0.5)


# ── compute_dcf_value ─────────────────────────────────────────────────────────


def test_dcf_value_stable_growth_sanity_range() -> None:
    """成熟公司:FCF=100亿, 增速 [5%]*10, terminal 2.5%, WACC 8%, 股本 10亿
    粗校验:price > 0,合理数量级(几十到几百)
    """
    from app.agents.valuation_helpers.dcf import compute_dcf_value

    price = compute_dcf_value(
        free_cash_flow_base=100e8,
        shares_outstanding=10e8,
        growth_trajectory=[0.05] * 10,
        terminal_growth=0.025,
        wacc=0.08,
    )
    assert 50 < price < 500


def test_dcf_value_terminal_ge_wacc_raises() -> None:
    """terminal_growth ≥ wacc → Gordon Growth 数学发散 → raise"""
    from app.agents.valuation_helpers.dcf import compute_dcf_value
    from app.agents.valuation_helpers.exceptions import InsufficientDataForModelError

    with pytest.raises(InsufficientDataForModelError):
        compute_dcf_value(
            free_cash_flow_base=100e8,
            shares_outstanding=10e8,
            growth_trajectory=[0.05] * 10,
            terminal_growth=0.08,  # == wacc, 发散
            wacc=0.08,
        )
    with pytest.raises(InsufficientDataForModelError):
        compute_dcf_value(
            free_cash_flow_base=100e8,
            shares_outstanding=10e8,
            growth_trajectory=[0.05] * 10,
            terminal_growth=0.10,  # > wacc
            wacc=0.08,
        )


def test_dcf_value_raises_for_zero_shares() -> None:
    from app.agents.valuation_helpers.dcf import compute_dcf_value
    from app.agents.valuation_helpers.exceptions import InsufficientDataForModelError

    with pytest.raises(InsufficientDataForModelError):
        compute_dcf_value(
            free_cash_flow_base=100e8,
            shares_outstanding=0,
            growth_trajectory=[0.05] * 10,
            terminal_growth=0.025,
            wacc=0.08,
        )


def test_dcf_value_raises_for_negative_fcf() -> None:
    """当前 FCF ≤ 0 → DCF 不适用亏损 / 烧钱公司 → raise"""
    from app.agents.valuation_helpers.dcf import compute_dcf_value
    from app.agents.valuation_helpers.exceptions import InsufficientDataForModelError

    with pytest.raises(InsufficientDataForModelError):
        compute_dcf_value(
            free_cash_flow_base=-10e8,
            shares_outstanding=10e8,
            growth_trajectory=[0.05] * 10,
            terminal_growth=0.025,
            wacc=0.08,
        )


def test_dcf_value_higher_wacc_gives_lower_price() -> None:
    """灵敏度直觉:WACC ↑ → 折现率 ↑ → 现值 ↓"""
    from app.agents.valuation_helpers.dcf import compute_dcf_value

    price_8 = compute_dcf_value(
        free_cash_flow_base=100e8,
        shares_outstanding=10e8,
        growth_trajectory=[0.05] * 10,
        terminal_growth=0.025,
        wacc=0.08,
    )
    price_10 = compute_dcf_value(
        free_cash_flow_base=100e8,
        shares_outstanding=10e8,
        growth_trajectory=[0.05] * 10,
        terminal_growth=0.025,
        wacc=0.10,
    )
    assert price_8 > price_10


def test_dcf_value_higher_terminal_gives_higher_price() -> None:
    """灵敏度直觉:terminal ↑ → 终值 ↑ → 现值 ↑ (前提 terminal < wacc)"""
    from app.agents.valuation_helpers.dcf import compute_dcf_value

    price_2 = compute_dcf_value(
        free_cash_flow_base=100e8,
        shares_outstanding=10e8,
        growth_trajectory=[0.05] * 10,
        terminal_growth=0.02,
        wacc=0.08,
    )
    price_3 = compute_dcf_value(
        free_cash_flow_base=100e8,
        shares_outstanding=10e8,
        growth_trajectory=[0.05] * 10,
        terminal_growth=0.03,
        wacc=0.08,
    )
    assert price_3 > price_2


def test_dcf_value_raises_on_nan_input() -> None:
    from app.agents.valuation_helpers.dcf import compute_dcf_value
    from app.agents.valuation_helpers.exceptions import InsufficientDataForModelError

    # fcf NaN
    with pytest.raises(InsufficientDataForModelError):
        compute_dcf_value(
            free_cash_flow_base=math.nan,
            shares_outstanding=10e8,
            growth_trajectory=[0.05] * 10,
            terminal_growth=0.025,
            wacc=0.08,
        )
    # growth_trajectory 含 NaN
    with pytest.raises(InsufficientDataForModelError):
        compute_dcf_value(
            free_cash_flow_base=100e8,
            shares_outstanding=10e8,
            growth_trajectory=[0.05, math.nan, 0.05],
            terminal_growth=0.025,
            wacc=0.08,
        )
    # wacc NaN
    with pytest.raises(InsufficientDataForModelError):
        compute_dcf_value(
            free_cash_flow_base=100e8,
            shares_outstanding=10e8,
            growth_trajectory=[0.05] * 10,
            terminal_growth=0.025,
            wacc=math.nan,
        )


def test_dcf_value_empty_growth_trajectory_raises() -> None:
    """growth_trajectory 空 → raise(无法算 FCF projection)"""
    from app.agents.valuation_helpers.dcf import compute_dcf_value
    from app.agents.valuation_helpers.exceptions import InsufficientDataForModelError

    with pytest.raises(InsufficientDataForModelError):
        compute_dcf_value(
            free_cash_flow_base=100e8,
            shares_outstanding=10e8,
            growth_trajectory=[],
            terminal_growth=0.025,
            wacc=0.08,
        )

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
    """C8: bear = terminal + (min(signals) - terminal) × 0.8 (deviation-from-terminal).

    The old `min(signals) × 0.8` inverted ordering for negative-growth firms; the new
    deviation scaling keeps bull > base > bear for any sign.
    """
    from app.agents.valuation_helpers.dcf import compute_growth_trajectory

    rates = compute_growth_trajectory(
        historical_growth=[0.05, 0.08, 0.06, 0.07, 0.05],
        forecast_growth=0.10,
        industry_terminal=0.025,
        scenario="bear",
        n_years=10,
    )
    # historical_avg=0.062, min(signals)=0.062; 0.025 + (0.062 - 0.025) × 0.8 = 0.0546
    assert rates[0] == pytest.approx(0.0546, rel=0.01)


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


# ── C8 regression: negative-growth bull/bear ordering ────────────────────────


def test_growth_trajectory_negative_growth_bull_bear_distinct() -> None:
    """C8 regression: 负增速公司 bull/bear 三场景应不同而非全 clamp 到 terminal。

    原 bug: max(signals)*1.2 对 negative rate 使 bull < base (倒置)。
    修复后 deviation scaling: bull[0] > base[0] > bear[0]。
    """
    from app.agents.valuation_helpers.dcf import compute_growth_trajectory

    # historical_avg=-0.05, forecast=-0.03, terminal=0.02
    # base: forecast = -0.03
    # bull: terminal + (max(-0.05,-0.03) - 0.02)*1.2 = 0.02 + (-0.03-0.02)*1.2 = 0.02 - 0.06 = -0.04
    #   → still < terminal → clamp, but ABOVE bear start
    # bear: terminal + (min(-0.05,-0.03) - 0.02)*0.8 = 0.02 + (-0.05-0.02)*0.8 = 0.02 - 0.056 = -0.036
    # Both below terminal → clamp. The key: bear deviation is more negative than bull.
    # After clamp all are terminal, but the pre-clamp ordering is correct.
    # Use a case where bull does NOT clamp: historical_avg=-0.02, forecast=-0.01, terminal=-0.05
    base_rates = compute_growth_trajectory(
        historical_growth=[-0.02],
        forecast_growth=-0.01,
        industry_terminal=-0.05,
        scenario="base",
        n_years=5,
    )
    bull_rates = compute_growth_trajectory(
        historical_growth=[-0.02],
        forecast_growth=-0.01,
        industry_terminal=-0.05,
        scenario="bull",
        n_years=5,
    )
    bear_rates = compute_growth_trajectory(
        historical_growth=[-0.02],
        forecast_growth=-0.01,
        industry_terminal=-0.05,
        scenario="bear",
        n_years=5,
    )
    # All start above terminal (terminal=-0.05), so should not clamp
    # bull[0] > base[0] > bear[0]
    assert bull_rates[0] > base_rates[0], "bull start must exceed base start"
    assert base_rates[0] > bear_rates[0], "base start must exceed bear start"


def test_growth_trajectory_positive_growth_bull_bear_ordering_preserved() -> None:
    """C8 regression guard: 正增速公司 bull/bear 排序不变。"""
    from app.agents.valuation_helpers.dcf import compute_growth_trajectory

    bull_rates = compute_growth_trajectory(
        historical_growth=[0.05, 0.08, 0.06],
        forecast_growth=0.10,
        industry_terminal=0.025,
        scenario="bull",
        n_years=5,
    )
    base_rates = compute_growth_trajectory(
        historical_growth=[0.05, 0.08, 0.06],
        forecast_growth=0.10,
        industry_terminal=0.025,
        scenario="base",
        n_years=5,
    )
    bear_rates = compute_growth_trajectory(
        historical_growth=[0.05, 0.08, 0.06],
        forecast_growth=0.10,
        industry_terminal=0.025,
        scenario="bear",
        n_years=5,
    )
    assert bull_rates[0] > base_rates[0], "positive: bull start > base start"
    assert base_rates[0] > bear_rates[0], "positive: base start > bear start"


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


# ── compute_dcf_sensitivity ───────────────────────────────────────────────────


def test_sensitivity_shape_5x5() -> None:
    """default 5×5 matrix"""
    from app.agents.valuation_helpers.dcf import compute_dcf_sensitivity

    matrix = compute_dcf_sensitivity(
        free_cash_flow_base=100e8,
        shares_outstanding=10e8,
        growth_trajectory=[0.05] * 10,
        base_terminal_growth=0.025,
        base_wacc=0.08,
    )
    assert len(matrix) == 5
    assert all(len(row) == 5 for row in matrix)


def test_sensitivity_center_matches_base_dcf() -> None:
    """matrix[2][2] (base wacc, base terminal) == 直接调 compute_dcf_value 的结果"""
    from app.agents.valuation_helpers.dcf import compute_dcf_sensitivity, compute_dcf_value

    matrix = compute_dcf_sensitivity(
        free_cash_flow_base=100e8,
        shares_outstanding=10e8,
        growth_trajectory=[0.05] * 10,
        base_terminal_growth=0.025,
        base_wacc=0.08,
    )
    expected = compute_dcf_value(
        free_cash_flow_base=100e8,
        shares_outstanding=10e8,
        growth_trajectory=[0.05] * 10,
        terminal_growth=0.025,
        wacc=0.08,
    )
    assert matrix[2][2] == pytest.approx(expected, rel=0.001)


def test_sensitivity_lower_wacc_higher_value() -> None:
    """同一列(同 terminal)low wacc 给更高 value(row 0 wacc -2% > row 4 wacc +2%)"""
    from app.agents.valuation_helpers.dcf import compute_dcf_sensitivity

    matrix = compute_dcf_sensitivity(
        free_cash_flow_base=100e8,
        shares_outstanding=10e8,
        growth_trajectory=[0.05] * 10,
        base_terminal_growth=0.025,
        base_wacc=0.08,
    )
    for col in range(5):
        assert matrix[0][col] > matrix[4][col]


def test_sensitivity_higher_terminal_higher_value() -> None:
    """同一行(同 wacc)higher terminal 给更高 value(col 4 terminal+1% > col 0 terminal-1%)"""
    from app.agents.valuation_helpers.dcf import compute_dcf_sensitivity

    matrix = compute_dcf_sensitivity(
        free_cash_flow_base=100e8,
        shares_outstanding=10e8,
        growth_trajectory=[0.05] * 10,
        base_terminal_growth=0.025,
        base_wacc=0.08,
    )
    for row in range(5):
        # 跳过 divergent cells (value=0); 其它必单调
        nonzero = [matrix[row][c] for c in range(5) if matrix[row][c] > 0]
        if len(nonzero) >= 2:
            # 单调递增(higher terminal → higher value)
            for c in range(len(nonzero) - 1):
                assert nonzero[c] <= nonzero[c + 1] + 1e-6


def test_sensitivity_divergent_cells_are_zero() -> None:
    """terminal ≥ wacc 的 cell → 0.0(数学发散 fallback)"""
    from app.agents.valuation_helpers.dcf import compute_dcf_sensitivity

    # base wacc 6%, base terminal 4%: 当 wacc -2% (=4%) 且 terminal +1% (=5%) → terminal > wacc → 0
    matrix = compute_dcf_sensitivity(
        free_cash_flow_base=100e8,
        shares_outstanding=10e8,
        growth_trajectory=[0.05] * 10,
        base_terminal_growth=0.04,
        base_wacc=0.06,
    )
    # row 0 (wacc 4%), col 4 (terminal 5%) → 发散 → 0
    assert matrix[0][4] == 0.0


def test_sensitivity_custom_deltas() -> None:
    """custom wacc/terminal deltas 也工作(non-default 5×5 not assumed)"""
    from app.agents.valuation_helpers.dcf import compute_dcf_sensitivity

    matrix = compute_dcf_sensitivity(
        free_cash_flow_base=100e8,
        shares_outstanding=10e8,
        growth_trajectory=[0.05] * 10,
        base_terminal_growth=0.025,
        base_wacc=0.08,
        wacc_deltas=(0.0, 0.01),
        terminal_deltas=(0.0, 0.005, 0.01),
    )
    assert len(matrix) == 2
    assert all(len(row) == 3 for row in matrix)


def test_sensitivity_propagates_non_divergent_errors() -> None:
    """non-divergent compute_dcf_value 错误(NaN, neg FCF)不该 swallow,直接上抛"""
    from app.agents.valuation_helpers.dcf import compute_dcf_sensitivity
    from app.agents.valuation_helpers.exceptions import InsufficientDataForModelError

    with pytest.raises(InsufficientDataForModelError):
        compute_dcf_sensitivity(
            free_cash_flow_base=-100e8,  # 亏损 → raise,不是 divergent
            shares_outstanding=10e8,
            growth_trajectory=[0.05] * 10,
            base_terminal_growth=0.025,
            base_wacc=0.08,
        )


def test_wacc_boundary_d_e_exactly_1_no_premium() -> None:
    """Task 7 review M1 fold:d/e == 1.0 (strict > threshold) → no leverage premium"""
    from app.agents.valuation_helpers.dcf import compute_company_wacc

    wacc = compute_company_wacc(
        industry_baseline_wacc=0.08,
        company_beta=1.0,
        debt_to_equity=1.0,  # boundary
    )
    # β neutral + d/e at boundary → 8% + 0 + 0 = 8%
    assert wacc == pytest.approx(0.08, rel=0.001)

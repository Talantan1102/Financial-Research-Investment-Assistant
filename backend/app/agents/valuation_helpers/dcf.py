"""v1.x A5a: DCF 估值 helper.

本模块分 3 部分:
1. compute_growth_trajectory  — 10 年增速序列(3 场景 base/bull/bear)         [Task 6 / 本 commit]
2. compute_company_wacc        — 简化 CAPM + β/leverage 调整                  [Task 7]
3. compute_dcf_value           — 主入口,产 base/bull/bear 三个理论价             [Task 7]
4. compute_dcf_sensitivity     — 5×5 矩阵 (WACC × Terminal Growth)            [Task 8]

设计 anchor(spec § 6):
- 数字 Python deterministic / judgment LLM 局部 override(增长率 base 场景 LLM 可调)
- WACC / terminal growth 不让 LLM 改(金融学公式锚 + team view 范式)
- 强制 base/bull/bear 三场景 + sensitivity 表(行业实践)
- 增长率来源优先级:管理层 guidance (get_forecast) > 历史外推

spec ref: 2026-05-16-v1.x-multi-valuation-cross-check-design.md § 6
"""

from __future__ import annotations

import math
from typing import Literal

from app.agents.valuation_helpers.exceptions import InsufficientDataForModelError

__all__ = [
    "compute_growth_trajectory",
    "compute_company_wacc",
    "compute_dcf_value",
    "compute_dcf_sensitivity",
]

# Bull/bear scenario multipliers (spec § 6.3 defaults; calibrate post-dogfood).
_BULL_MULTIPLIER = 1.2
_BEAR_MULTIPLIER = 0.8

# CAPM-style WACC adjustment coefficients (spec § 6.6; calibrate post-dogfood).
_BETA_ADJUSTMENT_PER_UNIT = 0.02  # β 偏离 1.0 每单位调整 ±2%
_LEVERAGE_THRESHOLD = 1.0  # d/e > 1.0 视为高杠杆
_LEVERAGE_RISK_PREMIUM = 0.01  # 高杠杆 +1% 风险溢价


def compute_growth_trajectory(
    *,
    historical_growth: list[float],
    forecast_growth: float | None,
    industry_terminal: float,
    scenario: Literal["base", "bull", "bear"],
    n_years: int = 10,
) -> list[float]:
    """生成 n 年增速序列,从启动值线性 decay 到 industry_terminal。

    启动值(spec § 6 优先级:管理层 > 共识 > 历史外推):
      - base: forecast_growth if available else avg(historical_growth)
      - bull: max(historical_avg, forecast) × 1.2
      - bear: min(historical_avg, forecast) × 0.8

    若启动值 ≤ industry_terminal,全序列 clamp 至 terminal(防衰减成负数)。

    Raises:
        InsufficientDataForModelError:
            - historical_growth 空 + forecast_growth None (无 growth signal)
            - 任一输入为 NaN / inf
        ValueError: scenario 非 base/bull/bear (defensive,Literal 已守一层)
    """
    # NaN/inf guard — forecast_growth
    if forecast_growth is not None and not math.isfinite(forecast_growth):
        raise InsufficientDataForModelError(
            model="dcf",
            missing_field="forecast_growth",
            reason=f"forecast_growth={forecast_growth} not finite",
        )
    # NaN/inf guard — industry_terminal
    if not math.isfinite(industry_terminal):
        raise InsufficientDataForModelError(
            model="dcf",
            missing_field="industry_terminal",
            reason=f"industry_terminal={industry_terminal} not finite",
        )
    # NaN/inf guard — historical_growth elements
    if any(not math.isfinite(g) for g in historical_growth):
        raise InsufficientDataForModelError(
            model="dcf",
            missing_field="historical_growth",
            reason=f"historical_growth contains non-finite: {historical_growth}",
        )

    # n_years boundary guard (programming error, not data error)
    if n_years < 1:
        raise ValueError(f"n_years must be >= 1, got {n_years}")

    # Both signals empty
    if not historical_growth and forecast_growth is None:
        raise InsufficientDataForModelError(
            model="dcf",
            missing_field="growth_signal",
            reason="historical_growth empty + forecast_growth=None, 无 growth signal",
        )

    historical_avg: float | None = (
        sum(historical_growth) / len(historical_growth) if historical_growth else None
    )

    start: float
    if scenario == "base":
        # forecast 优先(管理层 guidance);否则 historical_avg
        if forecast_growth is not None:
            start = forecast_growth
        else:
            assert historical_avg is not None
            start = historical_avg
    elif scenario == "bull":
        # C8: 原 max(signals)*1.2 对负增速倒置 — bull 会 worse than base。
        # 改为偏离 terminal 的 deviation scaling:
        # start = terminal + deviation_from_terminal * _BULL_MULTIPLIER
        # 保证 bull[0] > base[0] > bear[0] 无论增速正负。
        signals = [g for g in (historical_avg, forecast_growth) if g is not None]
        deviation = max(signals) - industry_terminal
        start = industry_terminal + deviation * _BULL_MULTIPLIER
    elif scenario == "bear":
        # C8: 同上，bear 用 min deviation。
        signals = [g for g in (historical_avg, forecast_growth) if g is not None]
        deviation = min(signals) - industry_terminal
        start = industry_terminal + deviation * _BEAR_MULTIPLIER
    else:
        # Literal 已收口,但 runtime defensive
        raise ValueError(f"invalid scenario: {scenario!r}")

    # Clamp 启动值 ≤ terminal 的 case
    if start <= industry_terminal:
        return [industry_terminal] * n_years

    # 线性 decay from start → terminal across n_years
    if n_years <= 1:
        return [start]
    step = (start - industry_terminal) / (n_years - 1)
    return [max(start - step * i, industry_terminal) for i in range(n_years)]


def compute_company_wacc(
    *,
    industry_baseline_wacc: float,
    company_beta: float | None,
    debt_to_equity: float,
) -> float:
    """简化 CAPM 调整:WACC = industry_baseline + β_adj + leverage_adj

    - β_adj = (β - 1.0) × _BETA_ADJUSTMENT_PER_UNIT (β 偏离 1.0 → 风险 ±2%)
    - leverage_adj = _LEVERAGE_RISK_PREMIUM if d/e > _LEVERAGE_THRESHOLD else 0
    - 缺 β 时 β_adj = 0 (行业 baseline fallback,跟 team-view 范式一致)

    Raises:
        InsufficientDataForModelError:
            - industry_baseline_wacc ≤ 0 (实际 WACC 都正,≤ 0 是数据 corruption)
            - 任一 float 输入为 NaN/inf
    """
    if not math.isfinite(industry_baseline_wacc):
        raise InsufficientDataForModelError(
            model="dcf",
            missing_field="industry_baseline_wacc",
            reason=f"industry_baseline_wacc={industry_baseline_wacc} not finite",
        )
    if company_beta is not None and not math.isfinite(company_beta):
        raise InsufficientDataForModelError(
            model="dcf",
            missing_field="company_beta",
            reason=f"company_beta={company_beta} not finite",
        )
    if not math.isfinite(debt_to_equity):
        raise InsufficientDataForModelError(
            model="dcf",
            missing_field="debt_to_equity",
            reason=f"debt_to_equity={debt_to_equity} not finite",
        )
    if industry_baseline_wacc <= 0:
        raise InsufficientDataForModelError(
            model="dcf",
            missing_field="industry_baseline_wacc",
            reason=f"industry_baseline_wacc={industry_baseline_wacc} <= 0",
        )

    beta_adj = (company_beta - 1.0) * _BETA_ADJUSTMENT_PER_UNIT if company_beta is not None else 0.0
    leverage_adj = _LEVERAGE_RISK_PREMIUM if debt_to_equity > _LEVERAGE_THRESHOLD else 0.0
    return industry_baseline_wacc + beta_adj + leverage_adj


def compute_dcf_value(
    *,
    free_cash_flow_base: float,
    shares_outstanding: float,
    growth_trajectory: list[float],
    terminal_growth: float,
    wacc: float,
) -> float:
    """单场景 DCF 主入口。

    1. FCF_t = FCF_base × Π_{i=0..t-1} (1 + g_i)
    2. PV_t = FCF_t / (1+wacc)^t
    3. Terminal Value = FCF_{n+1} / (wacc - terminal_growth)  [Gordon Growth]
    4. PV_Terminal = TV / (1+wacc)^n
    5. EV = Σ PV_t + PV_Terminal
    6. implied_price = EV / shares_outstanding

    Raises:
        InsufficientDataForModelError:
            - free_cash_flow_base <= 0 (DCF 不适用亏损 / 烧钱公司)
            - shares_outstanding <= 0
            - terminal_growth >= wacc (Gordon Growth 发散)
            - growth_trajectory 空
            - 任一 float / list 元素为 NaN/inf
    """
    # NaN/inf guard (含 list 元素)
    scalars = (free_cash_flow_base, shares_outstanding, terminal_growth, wacc)
    if not all(math.isfinite(x) for x in scalars):
        raise InsufficientDataForModelError(
            model="dcf",
            missing_field="numeric_finite",
            reason=(
                f"non-finite scalar input: fcf={free_cash_flow_base}, "
                f"shares={shares_outstanding}, terminal={terminal_growth}, wacc={wacc}"
            ),
        )
    if any(not math.isfinite(g) for g in growth_trajectory):
        raise InsufficientDataForModelError(
            model="dcf",
            missing_field="growth_trajectory",
            reason=f"growth_trajectory contains non-finite: {growth_trajectory}",
        )

    if not growth_trajectory:
        raise InsufficientDataForModelError(
            model="dcf",
            missing_field="growth_trajectory",
            reason="growth_trajectory empty, 无法做 FCF projection",
        )
    if shares_outstanding <= 0:
        raise InsufficientDataForModelError(
            model="dcf",
            missing_field="shares_outstanding",
            reason=f"shares_outstanding={shares_outstanding} <= 0",
        )
    if free_cash_flow_base <= 0:
        raise InsufficientDataForModelError(
            model="dcf",
            missing_field="free_cash_flow_base",
            reason=f"FCF base={free_cash_flow_base} <= 0 (DCF 不适用亏损 / 烧钱公司)",
        )
    if terminal_growth >= wacc:
        raise InsufficientDataForModelError(
            model="dcf",
            missing_field="terminal_growth_vs_wacc",
            reason=f"terminal_growth={terminal_growth} >= wacc={wacc} (Gordon Growth 发散)",
        )

    n = len(growth_trajectory)

    # 1. 算每年 FCF (compound from base)
    fcf_t: list[float] = []
    fcf_prev = free_cash_flow_base
    for g in growth_trajectory:
        fcf_prev = fcf_prev * (1.0 + g)
        fcf_t.append(fcf_prev)

    # 2. 折现各年 FCF
    pv_fcf_total = 0.0
    for t, fcf in enumerate(fcf_t, start=1):
        pv_fcf_total += fcf / ((1.0 + wacc) ** t)

    # 3. Terminal value (Gordon Growth) + 折现
    fcf_n_plus_1 = fcf_t[-1] * (1.0 + terminal_growth)
    terminal_value = fcf_n_plus_1 / (wacc - terminal_growth)
    pv_terminal = terminal_value / ((1.0 + wacc) ** n)

    # 4. EV → implied price
    enterprise_value = pv_fcf_total + pv_terminal
    return enterprise_value / shares_outstanding


def compute_dcf_sensitivity(
    *,
    free_cash_flow_base: float,
    shares_outstanding: float,
    growth_trajectory: list[float],
    base_terminal_growth: float,
    base_wacc: float,
    wacc_deltas: tuple[float, ...] = (-0.02, -0.01, 0.0, 0.01, 0.02),
    terminal_deltas: tuple[float, ...] = (-0.01, -0.005, 0.0, 0.005, 0.01),
) -> list[list[float]]:
    """生成 sensitivity matrix:matrix[i][j] = DCF at (wacc=base+wacc_deltas[i], terminal=base+terminal_deltas[j])

    Default 5×5 (deltas 数组长度决定 shape)。
    Divergent cell (terminal ≥ wacc) → 0.0 不 raise(caller 看到 0 知道是发散,narrative flag)。
    其它输入错(NaN / 负 FCF / 空 trajectory 等)→ propagate compute_dcf_value 的 raise。

    spec ref: 2026-05-16-v1.x-multi-valuation-cross-check-design.md § 6.5(灵敏度表必做)
    """
    matrix: list[list[float]] = []
    for wacc_d in wacc_deltas:
        row: list[float] = []
        wacc = base_wacc + wacc_d
        for terminal_d in terminal_deltas:
            terminal = base_terminal_growth + terminal_d
            try:
                v = compute_dcf_value(
                    free_cash_flow_base=free_cash_flow_base,
                    shares_outstanding=shares_outstanding,
                    growth_trajectory=growth_trajectory,
                    terminal_growth=terminal,
                    wacc=wacc,
                )
                row.append(v)
            except InsufficientDataForModelError as exc:
                # 只 swallow Gordon-divergence 错(terminal ≥ wacc),其它 propagate
                if exc.missing_field == "terminal_growth_vs_wacc":
                    row.append(0.0)
                else:
                    raise
        matrix.append(row)
    return matrix

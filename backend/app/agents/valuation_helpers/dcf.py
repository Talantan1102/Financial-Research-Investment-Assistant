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
    # compute_company_wacc / compute_dcf_value / compute_dcf_sensitivity — added in Task 7/8
]

# Bull/bear scenario multipliers (spec § 6.3 defaults; calibrate post-dogfood).
_BULL_MULTIPLIER = 1.2
_BEAR_MULTIPLIER = 0.8


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
        signals = [g for g in (historical_avg, forecast_growth) if g is not None]
        start = max(signals) * _BULL_MULTIPLIER
    elif scenario == "bear":
        signals = [g for g in (historical_avg, forecast_growth) if g is not None]
        start = min(signals) * _BEAR_MULTIPLIER
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

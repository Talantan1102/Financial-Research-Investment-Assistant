"""v1.x A5a: EV/EBITDA 估值 helper.

EV/EBITDA = (market_cap + net_debt) / EBITDA. implied_price 反推:
1. target_ev = ebitda × industry_ev_ebitda_target
2. implied_market_cap = target_ev - net_debt    (debt 占 EV 的一部分,股权部分 = EV - 净负债)
3. implied_price = implied_market_cap / shares_outstanding

适用跨负债结构对比(并购 / 重资本)。对零负债公司,信号跟 PE 高度相关 — IndustryModelRouter
决定何时激活本 helper(轻资本不激活,重资本 / 高负债激活)。

边界 case: 若 debt 远超 target_ev → implied_market_cap < 0 → return 0.0 (clamp).
narrative 层应 flag "高负债吞噬全部企业价值 — 估值意义存疑"。

spec ref: 2026-05-16-v1.x-multi-valuation-cross-check-design.md § 4
"""

from __future__ import annotations

import math

from app.agents.valuation_helpers.exceptions import InsufficientDataForModelError

__all__ = ["compute_ev_ebitda_value"]


def compute_ev_ebitda_value(
    *,
    ebitda: float,
    net_debt: float,
    shares_outstanding: float,
    industry_ev_ebitda_avg: float,
    industry_ev_ebitda_median: float,
) -> float:
    """计算 EV/EBITDA 理论价。

    Args:
        ebitda: 必须 > 0
        net_debt: total_debt - cash;负值表示净现金,允许
        shares_outstanding: 必须 > 0
        industry_ev_ebitda_avg / median: 任一 ≤ 0 raise

    Returns:
        implied_price (元/股),clamp 至 0.0 if implied_market_cap < 0

    Raises:
        InsufficientDataForModelError on:
            - ebitda ≤ 0 (negative EBITDA, 模型失效)
            - shares_outstanding ≤ 0
            - industry multiple 任一 ≤ 0
            - 任一输入为 NaN / inf
    """
    if not all(
        math.isfinite(x)
        for x in (
            ebitda,
            net_debt,
            shares_outstanding,
            industry_ev_ebitda_avg,
            industry_ev_ebitda_median,
        )
    ):
        raise InsufficientDataForModelError(
            model="ev_ebitda",
            missing_field="numeric_finite",
            reason=(
                f"non-finite input: ebitda={ebitda}, net_debt={net_debt}, "
                f"shares={shares_outstanding}, avg={industry_ev_ebitda_avg}, "
                f"median={industry_ev_ebitda_median}"
            ),
        )
    if ebitda <= 0:
        raise InsufficientDataForModelError(
            model="ev_ebitda",
            missing_field="ebitda",
            reason=f"ebitda={ebitda} ≤ 0 (负 EBITDA, 模型失效)",
        )
    if shares_outstanding <= 0:
        raise InsufficientDataForModelError(
            model="ev_ebitda",
            missing_field="shares_outstanding",
            reason=f"shares_outstanding={shares_outstanding} ≤ 0",
        )
    if industry_ev_ebitda_avg <= 0 or industry_ev_ebitda_median <= 0:
        raise InsufficientDataForModelError(
            model="ev_ebitda",
            missing_field="industry_ev_ebitda",
            reason=(
                f"industry_ev_ebitda_avg={industry_ev_ebitda_avg} "
                f"or median={industry_ev_ebitda_median} ≤ 0"
            ),
        )

    industry_target = (industry_ev_ebitda_avg + industry_ev_ebitda_median) / 2
    target_ev = ebitda * industry_target
    implied_market_cap = target_ev - net_debt
    implied_price = implied_market_cap / shares_outstanding

    return max(implied_price, 0.0)

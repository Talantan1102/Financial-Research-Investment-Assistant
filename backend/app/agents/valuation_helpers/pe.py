"""v1.x A5a: PE 估值 helper.

PE = price / eps. implied_price = eps × industry_pe_target.

industry_pe_target = (industry_pe_avg + industry_pe_median) / 2,弱化极端可比公司影响。
spec ref: 2026-05-16-v1.x-multi-valuation-cross-check-design.md § 4
"""

from __future__ import annotations

from app.agents.valuation_helpers.exceptions import InsufficientDataForModelError

__all__ = ["compute_pe_value"]


def compute_pe_value(
    *,
    eps: float,
    industry_pe_avg: float,
    industry_pe_median: float,
) -> float:
    """计算 PE 理论价。

    industry_pe_target 取 avg 和 median 的均值,弱化极端可比公司影响。
    若仅一方为正则用正的一方(容错单侧缺失)。

    Raises:
        InsufficientDataForModelError: eps ≤ 0(亏损/无盈利)or 行业 PE 全部 ≤ 0
    """
    if eps <= 0:
        raise InsufficientDataForModelError(
            model="pe",
            missing_field="eps",
            reason=f"eps={eps} ≤ 0 (亏损或零利润, PE 失效)",
        )
    if industry_pe_avg <= 0 or industry_pe_median <= 0:
        raise InsufficientDataForModelError(
            model="pe",
            missing_field="industry_pe",
            reason=(
                f"industry_pe_avg={industry_pe_avg} or industry_pe_median={industry_pe_median} ≤ 0"
            ),
        )

    industry_pe_target = (industry_pe_avg + industry_pe_median) / 2
    return eps * industry_pe_target

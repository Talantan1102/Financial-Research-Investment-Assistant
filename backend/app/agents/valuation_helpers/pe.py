"""v1.x A5a: PE 估值 helper.

PE = price / eps. implied_price = eps × industry_pe_target.

industry_pe_target = (industry_pe_avg + industry_pe_median) / 2,弱化极端可比公司影响。
spec ref: 2026-05-16-v1.x-multi-valuation-cross-check-design.md § 4
"""

from __future__ import annotations

import math

from app.agents.valuation_helpers.exceptions import InsufficientDataForModelError

__all__ = ["compute_pe_value"]


def compute_pe_value(
    *,
    eps: float,
    industry_pe_avg: float,
    industry_pe_median: float,
) -> float:
    """计算 PE 理论价: implied_price = eps * (industry_pe_avg + industry_pe_median) / 2

    industry_pe_target 取 avg 和 median 的均值(中位数已抗 outlier,均值保留中心信号)。

    Raises:
        InsufficientDataForModelError: eps ≤ 0 (亏损公司 PE 失效),
            或 industry_pe_avg / industry_pe_median 任一 ≤ 0 (可比集合数据 corrupt signal),
            或任一为 NaN / inf (数值异常)
    """
    if not all(math.isfinite(x) for x in (eps, industry_pe_avg, industry_pe_median)):
        raise InsufficientDataForModelError(
            model="pe",
            missing_field="numeric_finite",
            reason=f"non-finite input: eps={eps}, avg={industry_pe_avg}, median={industry_pe_median}",
        )
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

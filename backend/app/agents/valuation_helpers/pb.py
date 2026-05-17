"""v1.x A5a: PB 估值 helper.

PB = price / book_value_per_share. implied_price = bvps × industry_pb_target.
适用资产驱动型(银行/地产/重工业);轻资产(消费/科技)信号密度低 — 由 IndustryModelRouter
决定何时激活本 helper。

industry_pb_target = (avg + median) / 2(中位数抗 outlier,均值保留中心信号)。

spec ref: 2026-05-16-v1.x-multi-valuation-cross-check-design.md § 4
"""

from __future__ import annotations

import math

from app.agents.valuation_helpers.exceptions import InsufficientDataForModelError

__all__ = ["compute_pb_value"]


def compute_pb_value(
    *,
    book_value_per_share: float,
    industry_pb_avg: float,
    industry_pb_median: float,
) -> float:
    """计算 PB 理论价: implied_price = bvps * (industry_pb_avg + industry_pb_median) / 2

    Raises:
        InsufficientDataForModelError:
            - book_value_per_share ≤ 0 (负净资产 / 数据缺失)
            - industry_pb_avg / industry_pb_median 任一 ≤ 0 (可比集合数据 corrupt signal)
            - 任一为 NaN / inf (数值异常)
    """
    if not all(
        math.isfinite(x) for x in (book_value_per_share, industry_pb_avg, industry_pb_median)
    ):
        raise InsufficientDataForModelError(
            model="pb",
            missing_field="numeric_finite",
            reason=f"non-finite input: bvps={book_value_per_share}, avg={industry_pb_avg}, median={industry_pb_median}",
        )
    if book_value_per_share <= 0:
        raise InsufficientDataForModelError(
            model="pb",
            missing_field="book_value_per_share",
            reason=f"bvps={book_value_per_share} ≤ 0 (负净资产 / 数据缺失)",
        )
    if industry_pb_avg <= 0 or industry_pb_median <= 0:
        raise InsufficientDataForModelError(
            model="pb",
            missing_field="industry_pb",
            reason=f"industry_pb_avg={industry_pb_avg} or median={industry_pb_median} ≤ 0",
        )

    industry_pb_target = (industry_pb_avg + industry_pb_median) / 2
    return book_value_per_share * industry_pb_target

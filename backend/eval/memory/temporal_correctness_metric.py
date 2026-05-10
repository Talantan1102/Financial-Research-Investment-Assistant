"""Metric 2: Temporal Correctness.

spec § 10 Metric 2: 给定 expected_time_range = (start, end),
检查 retrieved_fact 的 valid_from ≤ end AND (valid_to IS NULL OR valid_to ≥ start).

确定性 check, 不用 LLM. 目标 ≥ 0.95.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def fact_overlaps_range(
    fact: dict[str, Any],
    time_range: tuple[datetime, datetime],
) -> bool:
    """fact 的有效期是否跟 time_range 有重叠.

    bi-temporal valid-time 重叠判断:
      - valid_from > end → 整个 fact 在窗口之后, 不重叠
      - valid_to IS NOT NULL AND valid_to < start → 整个 fact 在窗口之前, 不重叠
      - 其余 → 重叠
    """
    start, end = time_range
    valid_from = fact["valid_from"]
    valid_to = fact.get("valid_to")
    if valid_from > end:
        return False
    return not (valid_to is not None and valid_to < start)


def temporal_correctness(
    retrieved_facts: list[dict[str, Any]],
    expected_time_range: tuple[datetime, datetime] | None,
) -> float:
    """Return [0.0, 1.0] — 落入 expected_time_range 的 fact 比例.

    expected_time_range=None → query 不带时间, 返 1.0 (vacuously correct).
    空集 → 0.0 (无 fact 可校验, 视为 fail).
    """
    if expected_time_range is None:
        return 1.0
    if not retrieved_facts:
        return 0.0
    correct = sum(1 for f in retrieved_facts if fact_overlaps_range(f, expected_time_range))
    return correct / len(retrieved_facts)

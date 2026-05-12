"""DeepCard 完成度计算 — spec § 5.1。

完成度 = (what + why + alternatives + tradeoff 4 个必填字段中非空数) / 4。
- 0 → empty;> 0 且 < 1 → partial;= 1 → full
- lessons_learned / metrics 是 optional,不计入完成度分母
"""

from __future__ import annotations

from typing import Literal

from dashboard.derive.deep_card_types import DeepCard

CompletionLevel = Literal["empty", "partial", "full"]

REQUIRED_FIELDS = ("what", "why", "alternatives", "tradeoff")


def completion_ratio(card: DeepCard) -> float:
    """填充字段数 / 4。"""
    filled = 0
    for f in REQUIRED_FIELDS:
        v = getattr(card, f, None)
        if v is None:
            continue
        if isinstance(v, list) and not v:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        filled += 1
    return filled / len(REQUIRED_FIELDS)


def completion_level(card: DeepCard) -> CompletionLevel:
    r = completion_ratio(card)
    if r == 0.0:
        return "empty"
    if r >= 1.0:
        return "full"
    return "partial"


def completion_level_or_none(card: DeepCard | None) -> CompletionLevel | None:
    if card is None:
        return None
    return completion_level(card)

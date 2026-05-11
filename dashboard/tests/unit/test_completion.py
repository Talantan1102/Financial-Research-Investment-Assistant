"""DeepCard 完成度计算 — spec § 5.1。Plan 1 Task 10。"""

from __future__ import annotations

from dashboard.derive.completion import (
    completion_level,
    completion_level_or_none,
    completion_ratio,
)
from dashboard.derive.deep_card_types import AlternativeItem, DeepCard


def test_empty_card_ratio_zero() -> None:
    assert completion_ratio(DeepCard(cap_id="x")) == 0.0
    assert completion_level(DeepCard(cap_id="x")) == "empty"


def test_partial_one_field() -> None:
    c = DeepCard(cap_id="x", what="something")
    assert 0 < completion_ratio(c) < 1
    assert completion_level(c) == "partial"


def test_full_card() -> None:
    c = DeepCard(
        cap_id="x",
        what="w",
        why="why",
        alternatives=[AlternativeItem(name="A", brief_tradeoff="a")],
        tradeoff="t",
    )
    assert completion_ratio(c) == 1.0
    assert completion_level(c) == "full"


def test_optional_fields_not_counted() -> None:
    """lessons_learned 和 metrics 不计入完成度分母。"""
    c = DeepCard(cap_id="x", lessons_learned="L", metrics={"k": "v"})
    assert completion_level(c) == "empty"


def test_no_deep_card_returns_none() -> None:
    """completion_level_or_none(None) → None"""
    assert completion_level_or_none(None) is None


def test_empty_string_not_counted() -> None:
    """空字符串 / whitespace-only 不算填。"""
    c = DeepCard(cap_id="x", what="", why="   ")
    assert completion_level(c) == "empty"

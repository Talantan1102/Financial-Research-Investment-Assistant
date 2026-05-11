"""L0 unit: temporal_correctness metric — 确定性 check 不用 LLM."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from eval.memory.temporal_correctness_metric import (
    fact_overlaps_range,
    temporal_correctness,
)


def _utc(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


def test_fact_overlaps_range_active_in_window() -> None:
    """valid_from 在窗口前, valid_to=None (当前仍有效) → 重叠."""
    fact = {"valid_from": _utc("2024-08-01"), "valid_to": None}
    assert fact_overlaps_range(fact, time_range=(_utc("2024-09-01"), _utc("2024-12-01")))


def test_fact_overlaps_range_historical_in_window() -> None:
    """valid_from + valid_to 都落入窗口 → 重叠."""
    fact = {"valid_from": _utc("2024-08-01"), "valid_to": _utc("2024-10-01")}
    assert fact_overlaps_range(fact, time_range=(_utc("2024-09-01"), _utc("2024-12-01")))


def test_fact_overlaps_range_before_window() -> None:
    fact = {"valid_from": _utc("2023-01-01"), "valid_to": _utc("2023-06-01")}
    assert not fact_overlaps_range(fact, time_range=(_utc("2024-01-01"), _utc("2024-12-01")))


def test_fact_overlaps_range_after_window() -> None:
    fact = {"valid_from": _utc("2025-01-01"), "valid_to": None}
    assert not fact_overlaps_range(fact, time_range=(_utc("2024-01-01"), _utc("2024-12-01")))


def test_temporal_correctness_all_in_range() -> None:
    facts: list[dict[str, Any]] = [
        {"valid_from": _utc("2024-08-01"), "valid_to": None},
        {"valid_from": _utc("2024-08-01"), "valid_to": _utc("2024-10-01")},
    ]
    p = temporal_correctness(
        retrieved_facts=facts,
        expected_time_range=(_utc("2024-09-01"), _utc("2024-12-01")),
    )
    assert p == 1.0


def test_temporal_correctness_partial() -> None:
    facts: list[dict[str, Any]] = [
        {"valid_from": _utc("2024-08-01"), "valid_to": None},  # ok
        {"valid_from": _utc("2023-01-01"), "valid_to": _utc("2023-06-01")},  # not ok
    ]
    p = temporal_correctness(
        retrieved_facts=facts,
        expected_time_range=(_utc("2024-09-01"), _utc("2024-12-01")),
    )
    assert p == 0.5


def test_temporal_correctness_no_range_returns_one() -> None:
    """golden_query.expected_time_range = None → 不验证, 返 1.0."""
    p = temporal_correctness(retrieved_facts=[{}, {}], expected_time_range=None)
    assert p == 1.0


def test_temporal_correctness_empty_facts_with_range_returns_zero() -> None:
    """空 facts + 有 range → 0.0 (无 fact 可校验, 视为 fail)."""
    p = temporal_correctness(
        retrieved_facts=[],
        expected_time_range=(_utc("2024-01-01"), _utc("2024-12-31")),
    )
    assert p == 0.0

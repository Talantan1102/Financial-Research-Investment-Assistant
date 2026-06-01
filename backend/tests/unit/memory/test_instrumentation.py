"""L0 unit tests for instrumentation._compute_p90_valid_from_age_days (C49 regression).

Finding C49: idx = int(len(sorted_ages) * 0.9) overshoots — computes P91/P100.
Fix: idx = int((len(sorted_ages) - 1) * 0.9).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.memory.instrumentation import _compute_p90_valid_from_age_days


def _make_edges_meta(ages_days: Sequence[float], now: datetime) -> tuple[list[str], dict]:
    """Build edge_ids / edges_meta for the given age list (in days)."""
    edge_ids: list[str] = []
    edges_meta: dict = {}
    for age in ages_days:
        eid = str(uuid4())
        edge_ids.append(eid)
        edges_meta[eid] = {"valid_from": now - timedelta(days=age)}
    return edge_ids, edges_meta


def test_p90_ten_elements_index_eight() -> None:
    """C49: n=10 → idx = int(9 * 0.9) = 8 (0-based), i.e. the 9th-smallest element.

    ages 0..9 sorted → [0,1,2,3,4,5,6,7,8,9].
    Correct P90 (0-indexed idx 8) = 8.0 days.
    Old buggy code: idx = int(10 * 0.9) = 9 → ages[9] = 9.0 (P100).
    """
    now = datetime.now(UTC)
    ages_days = list(range(10))  # 0,1,2,...,9
    edge_ids, edges_meta = _make_edges_meta(ages_days, now)

    result = _compute_p90_valid_from_age_days(edge_ids, edges_meta, now)

    assert result is not None
    # idx = int((10-1) * 0.9) = int(8.1) = 8 → sorted_ages[8] = 8.0
    assert abs(result - 8.0) < 0.01, f"expected ~8.0 days, got {result}"


def test_p90_hundred_elements_index_89() -> None:
    """C49: n=100 → idx = int(99 * 0.9) = 89 (0-based), i.e. the 90th element.

    ages 1..100 sorted → [1,2,...,100].
    Correct P90 (idx 89) = 90.0 days.
    Old buggy code: idx = int(100 * 0.9) = 90 → ages[90] = 91.0 (91st element).
    """
    now = datetime.now(UTC)
    ages_days = list(range(1, 101))  # 1,2,...,100
    edge_ids, edges_meta = _make_edges_meta(ages_days, now)

    result = _compute_p90_valid_from_age_days(edge_ids, edges_meta, now)

    assert result is not None
    # idx = int((100-1) * 0.9) = int(89.1) = 89 → sorted_ages[89] = 90.0
    assert abs(result - 90.0) < 0.01, f"expected ~90.0 days, got {result}"


def test_p90_single_element_returns_that_element() -> None:
    """n=1 → idx = int(0 * 0.9) = 0 → returns the only element."""
    now = datetime.now(UTC)
    edge_ids, edges_meta = _make_edges_meta([42.0], now)

    result = _compute_p90_valid_from_age_days(edge_ids, edges_meta, now)

    assert result is not None
    assert abs(result - 42.0) < 0.01


def test_p90_empty_returns_none() -> None:
    """Empty sample → None."""
    now = datetime.now(UTC)
    result = _compute_p90_valid_from_age_days([], {}, now)
    assert result is None


def test_p90_two_elements_returns_first_not_last() -> None:
    """C49 regression: n=2 → idx=0 (not idx=1 as old code produced).

    Verifies the off-by-one is fixed: ages [10, 20] → P90 = 10.0, not 20.0.
    """
    now = datetime.now(UTC)
    edge_ids, edges_meta = _make_edges_meta([10.0, 20.0], now)

    result = _compute_p90_valid_from_age_days(edge_ids, edges_meta, now)

    assert result is not None
    # idx = int((2-1) * 0.9) = int(0.9) = 0 → sorted[0] = 10.0
    assert abs(result - 10.0) < 0.01, f"expected ~10.0 days (idx=0), got {result}"

"""L0 unit: backend/eval/memory/long_tail_monitor.py (eval-pipeline 接入层).

区别于 test_long_tail_monitor.py (Plan 3 ship, app.memory.long_tail_monitor 测).
本 module 测 Plan 8 ship 的 long_tail_recall_check + weekly_report_sql.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from eval.memory.long_tail_monitor import (
    long_tail_recall_check,
    weekly_report_sql,
)


def _now() -> datetime:
    return datetime.now(UTC)


def test_long_tail_recall_check_all_recent_violates() -> None:
    """所有 query 的 top-5 facts 都集中近 3-5 天 → P90 < 7 → violated."""
    now = _now()
    sample = [
        {
            "query": f"q{i}",
            "top5_facts": [
                {"valid_from": now - timedelta(days=3)},
                {"valid_from": now - timedelta(days=5)},
            ],
        }
        for i in range(10)
    ]
    result = long_tail_recall_check(sample, p90_floor_days=7)
    assert result["violated"] is True


def test_long_tail_recall_check_diverse_passes() -> None:
    """top-5 含近期 + 老 fact, 老 fact 拉高 max-age → P90 ≥ 7 → pass."""
    now = _now()
    sample = [
        {
            "query": f"q{i}",
            "top5_facts": [
                {"valid_from": now - timedelta(days=3)},
                {"valid_from": now - timedelta(days=200)},
            ],
        }
        for i in range(10)
    ]
    result = long_tail_recall_check(sample, p90_floor_days=7)
    assert result["violated"] is False
    assert result["p90_min_age_days"] >= 7


def test_long_tail_recall_check_empty_samples_violates() -> None:
    result = long_tail_recall_check([], p90_floor_days=7)
    assert result["violated"] is True
    assert result["samples"] == 0


def test_long_tail_recall_check_iso_string_valid_from() -> None:
    """valid_from 可以是 ISO string."""
    sample = [
        {
            "query": "q1",
            "top5_facts": [
                {"valid_from": "2023-01-01T00:00:00+00:00"},  # 老 fact
            ],
        }
    ]
    result = long_tail_recall_check(sample, p90_floor_days=7)
    assert result["violated"] is False
    assert result["p90_min_age_days"] > 365


def test_long_tail_recall_check_facts_without_valid_from_skipped() -> None:
    """fact 缺 valid_from 跳过, 整 query 都没 valid_from → 不计入."""
    sample = [
        {"query": "q1", "top5_facts": [{"edge_id": "e1"}]},
        {"query": "q2", "top5_facts": [{"valid_from": _now() - timedelta(days=100)}]},
    ]
    result = long_tail_recall_check(sample, p90_floor_days=7)
    # 只有 q2 计入 → samples=2 但 min_age_days_per_query = [100]
    assert result["violated"] is False


def test_weekly_report_sql_returns_select() -> None:
    sql = weekly_report_sql()
    assert "SELECT" in sql
    assert "chat_memory_retrieval_logs" in sql
    assert "PERCENTILE_CONT" in sql


def test_weekly_report_sql_filters_7_days() -> None:
    sql = weekly_report_sql()
    assert "INTERVAL '7 day'" in sql

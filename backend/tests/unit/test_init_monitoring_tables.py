"""Unit tests for init_monitoring_tables — verifies 5 tables created with correct schema."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from app.scripts.init_monitoring_tables import init_monitoring_tables


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.sqlite"


def test_init_creates_5_tables(db_path: Path) -> None:
    init_monitoring_tables(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name LIKE 'monitoring_%' OR name = 'notifications'"
        ).fetchall()
    names = {r[0] for r in rows}
    assert names == {
        "monitoring_customers",
        "monitoring_runs",
        "monitoring_signals",
        "monitoring_alerts",
        "notifications",
    }


def test_init_idempotent(db_path: Path) -> None:
    init_monitoring_tables(db_path)
    init_monitoring_tables(db_path)  # 重复跑不应抛错


@pytest.mark.parametrize(
    "table,required_cols",
    [
        (
            "monitoring_customers",
            {"id", "ts_code", "name", "industry", "enabled", "thresholds_override"},
        ),
        ("monitoring_runs", {"id", "customer_id", "trigger_type", "started_at", "status"}),
        (
            "monitoring_signals",
            {"id", "run_id", "rule_name", "level", "detected_value", "threshold"},
        ),
        (
            "monitoring_alerts",
            {"id", "run_id", "customer_id", "alert_level", "report_json", "escalated"},
        ),
        ("notifications", {"id", "alert_id", "channel", "recipient", "send_status"}),
    ],
)
def test_table_required_columns(db_path: Path, table: str, required_cols: set[str]) -> None:
    init_monitoring_tables(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    cols = {r[1] for r in rows}
    assert required_cols.issubset(cols), f"{table} missing: {required_cols - cols}"

"""Create monitoring + notifications tables. Idempotent (CREATE TABLE IF NOT EXISTS)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS monitoring_customers (
    id TEXT PRIMARY KEY,
    ts_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    industry TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    thresholds_override TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS monitoring_runs (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES monitoring_customers(id),
    trigger_type TEXT NOT NULL,
    started_at TIMESTAMP NOT NULL,
    finished_at TIMESTAMP,
    status TEXT NOT NULL,
    error_message TEXT,
    cost_cny REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS monitoring_signals (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES monitoring_runs(id),
    rule_name TEXT NOT NULL,
    level TEXT NOT NULL,
    detected_value TEXT,
    threshold TEXT,
    explanation TEXT,
    raw_data_ref TEXT
);

CREATE TABLE IF NOT EXISTS monitoring_alerts (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES monitoring_runs(id),
    customer_id TEXT NOT NULL REFERENCES monitoring_customers(id),
    alert_level TEXT NOT NULL,
    report_json TEXT NOT NULL,
    report_markdown TEXT,
    escalated INTEGER DEFAULT 0,
    escalation_status TEXT,
    deep_dive_text TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notifications (
    id TEXT PRIMARY KEY,
    alert_id TEXT NOT NULL REFERENCES monitoring_alerts(id),
    channel TEXT NOT NULL,
    recipient TEXT,
    sent_at TIMESTAMP,
    send_status TEXT NOT NULL,
    error_message TEXT,
    read_at TIMESTAMP
);
"""


def init_monitoring_tables(db_path: Path) -> None:
    """Create all 5 monitoring tables in the sqlite DB at *db_path*.

    Safe to call multiple times — uses CREATE TABLE IF NOT EXISTS throughout.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_SCHEMA_SQL)

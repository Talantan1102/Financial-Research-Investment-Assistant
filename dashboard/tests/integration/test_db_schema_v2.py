"""v2 schema migration — deep_cards 表幂等创建。Plan 1 Task 2。"""

from __future__ import annotations

from pathlib import Path

from dashboard.state.db import open_db


def test_deep_cards_table_created(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    conn = open_db(db)
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='deep_cards'")
    assert cur.fetchone() is not None


def test_schema_idempotent(tmp_path: Path) -> None:
    """open_db 跑两次不抛"""
    db = tmp_path / "test.db"
    open_db(db).close()
    conn = open_db(db)
    assert conn is not None

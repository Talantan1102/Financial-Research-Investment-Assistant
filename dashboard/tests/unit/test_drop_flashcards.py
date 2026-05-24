"""Plan 1 — DROP flashcards / prefill_log 脚本幂等测试。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from dashboard.scripts.drop_flashcards_tables import drop_legacy_tables


@pytest.fixture
def db_with_legacy(tmp_path: Path) -> Path:
    """构造一个含 flashcards / prefill_log 的旧 db。"""
    db_path = tmp_path / "harness_board.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE flashcards (id TEXT PRIMARY KEY, cap_id TEXT);
        CREATE INDEX idx_flashcards_cap_id ON flashcards(cap_id);
        CREATE TABLE prefill_log (id INTEGER PRIMARY KEY, cap_id TEXT);
        CREATE TABLE deep_cards (cap_id TEXT PRIMARY KEY, payload TEXT);
        INSERT INTO flashcards VALUES ('f1', 'cap_a');
        INSERT INTO prefill_log VALUES (1, 'cap_a');
        INSERT INTO deep_cards VALUES ('cap_a', '{}');
        """
    )
    conn.commit()
    conn.close()
    return db_path


def _table_names(db_path: Path) -> set[str]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    conn.close()
    return {r[0] for r in rows}


def test_drop_removes_legacy_tables(db_with_legacy: Path) -> None:
    drop_legacy_tables(db_with_legacy)
    names = _table_names(db_with_legacy)
    assert "flashcards" not in names
    assert "prefill_log" not in names
    assert "deep_cards" in names  # 不动其他表


def test_drop_preserves_deep_cards_rows(db_with_legacy: Path) -> None:
    drop_legacy_tables(db_with_legacy)
    conn = sqlite3.connect(db_with_legacy)
    rows = conn.execute("SELECT cap_id FROM deep_cards").fetchall()
    conn.close()
    assert rows == [("cap_a",)]


def test_drop_idempotent(db_with_legacy: Path) -> None:
    """跑两遍不报错 — 第二遍发现表已不在,静默通过。"""
    drop_legacy_tables(db_with_legacy)
    drop_legacy_tables(db_with_legacy)  # 第二次:幂等
    names = _table_names(db_with_legacy)
    assert "flashcards" not in names


def test_drop_on_clean_db(tmp_path: Path) -> None:
    """从来没有这些表的新 db 也不报错。"""
    db_path = tmp_path / "clean.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("CREATE TABLE foo (x INTEGER);")
    conn.commit()
    conn.close()
    drop_legacy_tables(db_path)  # 不抛
    names = _table_names(db_path)
    assert names == {"foo"}

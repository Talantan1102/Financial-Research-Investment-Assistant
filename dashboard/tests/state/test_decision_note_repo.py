from pathlib import Path

from dashboard.state.db import open_db
from dashboard.state.repositories import DecisionNoteRepo


def test_empty_returns_empty_dict(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "board.db")
    repo = DecisionNoteRepo(conn)
    assert repo.get_all() == {}


def test_upsert_then_get(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "board.db")
    repo = DecisionNoteRepo(conn)
    repo.upsert("a1b2c3d4e5f6", "回头看 plan_correctness 是否真的够好")
    assert repo.get_all() == {"a1b2c3d4e5f6": "回头看 plan_correctness 是否真的够好"}


def test_upsert_overwrites_existing(tmp_path: Path) -> None:
    """upsert overwrites — 行数 ≤ 1。"""
    conn = open_db(tmp_path / "board.db")
    repo = DecisionNoteRepo(conn)
    repo.upsert("a1b2c3d4e5f6", "first note")
    repo.upsert("a1b2c3d4e5f6", "second note")
    assert repo.get_all() == {"a1b2c3d4e5f6": "second note"}
    cur = conn.execute("SELECT COUNT(*) AS n FROM decision_note")
    assert cur.fetchone()["n"] == 1  # upsert 不累积


def test_delete_clears(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "board.db")
    repo = DecisionNoteRepo(conn)
    repo.upsert("a1b2c3d4e5f6", "test")
    repo.delete("a1b2c3d4e5f6")
    assert repo.get_all() == {}


def test_multi_decision_isolation(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "board.db")
    repo = DecisionNoteRepo(conn)
    repo.upsert("aaaaaaaaaaaa", "决策 A note")
    repo.upsert("bbbbbbbbbbbb", "决策 B note")
    repo.delete("aaaaaaaaaaaa")
    assert repo.get_all() == {"bbbbbbbbbbbb": "决策 B note"}

from pathlib import Path

from dashboard.state.db import open_db
from dashboard.state.repositories import OverrideRepo


def test_empty_returns_empty_dict(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "board.db")
    repo = OverrideRepo(conn)
    assert repo.get_all() == {}


def test_upsert_then_get(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "board.db")
    repo = OverrideRepo(conn)
    repo.upsert("memory.long_term_memory", "wip", reason="正在做 mem0 接入")
    out = repo.get_all()
    assert out == {"memory.long_term_memory": "wip"}


def test_upsert_overwrites_existing(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "board.db")
    repo = OverrideRepo(conn)
    repo.upsert("memory.long_term_memory", "wip")
    repo.upsert("memory.long_term_memory", "lit")
    assert repo.get_all() == {"memory.long_term_memory": "lit"}
    cur = conn.execute("SELECT COUNT(*) AS n FROM capability_override")
    assert cur.fetchone()["n"] == 1  # upsert 不累积


def test_delete_clears(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "board.db")
    repo = OverrideRepo(conn)
    repo.upsert("memory.long_term_memory", "wip")
    repo.delete("memory.long_term_memory")
    assert repo.get_all() == {}


def test_multi_capability_isolation(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "board.db")
    repo = OverrideRepo(conn)
    repo.upsert("memory.long_term_memory", "wip")
    repo.upsert("rag_knowledge.reranker", "lit")
    repo.delete("memory.long_term_memory")
    assert repo.get_all() == {"rag_knowledge.reranker": "lit"}

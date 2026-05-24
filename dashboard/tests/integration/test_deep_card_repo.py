"""DeepCardRepo CRUD + prefill_source 自动转换。Plan 1 Task 3。"""

from __future__ import annotations

from pathlib import Path

from dashboard.derive.deep_card_types import AlternativeItem, DeepCard
from dashboard.state.db import open_db
from dashboard.state.repositories import DeepCardRepo


def test_upsert_and_get(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "t.db")
    repo = DeepCardRepo(conn)
    card = DeepCard(
        cap_id="01.constrained_schema",
        what="LLM JSON 强制",
        alternatives=[AlternativeItem(name="A", brief_tradeoff="a")],
        chosen_alternative="A",
        prefill_source="manual",
    )
    repo.upsert(card)
    got = repo.get("01.constrained_schema")
    assert got is not None
    assert got.cap_id == card.cap_id
    assert got.what == "LLM JSON 强制"
    assert got.alternatives[0].name == "A"


def test_get_missing_returns_none(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "t.db")
    repo = DeepCardRepo(conn)
    assert repo.get("nope") is None


def test_upsert_overwrites(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "t.db")
    repo = DeepCardRepo(conn)
    repo.upsert(DeepCard(cap_id="x", what="v1"))
    repo.upsert(DeepCard(cap_id="x", what="v2"))
    got = repo.get("x")
    assert got is not None and got.what == "v2"


def test_update_field_partial(tmp_path: Path) -> None:
    """update_field 只改一个字段,其他不动 + 自动转 prefill_source。"""
    conn = open_db(tmp_path / "t.db")
    repo = DeepCardRepo(conn)
    repo.upsert(DeepCard(cap_id="x", what="seed", prefill_source="llm"))
    repo.update_field("x", "what", "edited")
    got = repo.get("x")
    assert got is not None
    assert got.what == "edited"
    assert got.prefill_source == "hybrid"  # llm 后人改 → hybrid


def test_update_field_manual_to_manual(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "t.db")
    repo = DeepCardRepo(conn)
    repo.upsert(DeepCard(cap_id="x", prefill_source="manual"))  # what=None
    repo.update_field("x", "what", "first manual fill")
    got = repo.get("x")
    assert got is not None and got.prefill_source == "manual"


def test_update_field_unknown_raises(tmp_path: Path) -> None:
    import pytest

    conn = open_db(tmp_path / "t.db")
    repo = DeepCardRepo(conn)
    repo.upsert(DeepCard(cap_id="x"))
    with pytest.raises(KeyError):
        repo.update_field("x", "bogus_field", "v")


def test_get_all_returns_all(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "t.db")
    repo = DeepCardRepo(conn)
    repo.upsert(DeepCard(cap_id="a"))
    repo.upsert(DeepCard(cap_id="b"))
    cards = repo.get_all()
    assert {c.cap_id for c in cards} == {"a", "b"}

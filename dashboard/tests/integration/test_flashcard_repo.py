"""FlashcardRepo CRUD skeleton。Plan 1 Task 4。"""

from __future__ import annotations

from pathlib import Path

from dashboard.derive.deep_card_types import Flashcard, SrsState
from dashboard.state.db import open_db
from dashboard.state.repositories import FlashcardRepo


def test_upsert_and_get(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "t.db")
    repo = FlashcardRepo(conn)
    fc = Flashcard(
        id="x::tradeoff",
        cap_id="x",
        template_kind="tradeoff",
        question="q?",
        answer="a",
    )
    repo.upsert(fc)
    got = repo.get("x::tradeoff")
    assert got is not None and got.question == "q?"


def test_get_by_cap_id(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "t.db")
    repo = FlashcardRepo(conn)
    repo.upsert(
        Flashcard(
            id="x::tradeoff",
            cap_id="x",
            template_kind="tradeoff",
            question="q1",
            answer="a1",
        )
    )
    repo.upsert(
        Flashcard(
            id="x::lessons",
            cap_id="x",
            template_kind="lessons",
            question="q2",
            answer="a2",
        )
    )
    cards = repo.get_by_cap_id("x")
    assert len(cards) == 2


def test_srs_state_roundtrip(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "t.db")
    repo = FlashcardRepo(conn)
    repo.upsert(
        Flashcard(
            id="x::tradeoff",
            cap_id="x",
            template_kind="tradeoff",
            question="q",
            answer="a",
            srs_state=SrsState(confidence=3, ef=2.6, interval=6, repetition=2),
        )
    )
    got = repo.get("x::tradeoff")
    assert got is not None
    assert got.srs_state.confidence == 3
    assert got.srs_state.ef == 2.6
    assert got.srs_state.interval == 6


def test_delete_by_cap_id(tmp_path: Path) -> None:
    """DeepCard 重生成闪卡时,需要先删旧的(template kind 没了)。"""
    conn = open_db(tmp_path / "t.db")
    repo = FlashcardRepo(conn)
    repo.upsert(
        Flashcard(
            id="x::tradeoff",
            cap_id="x",
            template_kind="tradeoff",
            question="q",
            answer="a",
        )
    )
    repo.delete_by_cap_id("x")
    assert repo.get_by_cap_id("x") == []

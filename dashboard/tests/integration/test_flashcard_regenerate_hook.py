"""DeepCard 编辑触发闪卡重生成 — 保留 srs_state。Plan 3 Task 3。"""

from __future__ import annotations

from pathlib import Path

from dashboard.derive.deep_card_types import DeepCard, SrsState
from dashboard.state.db import open_db
from dashboard.state.repositories import DeepCardRepo, FlashcardRepo, regenerate_flashcards_for


def test_upsert_first_time_generates_flashcards(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "t.db")
    dc_repo = DeepCardRepo(conn)
    fc_repo = FlashcardRepo(conn)
    dc_repo.upsert(DeepCard(cap_id="x.a", tradeoff="选 schema", lessons_learned="撞过 escape"))
    regenerate_flashcards_for("x.a", dc_repo=dc_repo, fc_repo=fc_repo, cap_name_cn="X.A")
    fcs = fc_repo.get_by_cap_id("x.a")
    assert len(fcs) == 2  # tradeoff + lessons


def test_regenerate_preserves_srs_state(tmp_path: Path) -> None:
    """DeepCard 编辑后重生成 — 保留旧闪卡的 srs_state,只 overwrite Q/A 文本。"""
    conn = open_db(tmp_path / "t.db")
    dc_repo = DeepCardRepo(conn)
    fc_repo = FlashcardRepo(conn)
    dc_repo.upsert(DeepCard(cap_id="x.a", tradeoff="V1 tradeoff"))
    regenerate_flashcards_for("x.a", dc_repo=dc_repo, fc_repo=fc_repo, cap_name_cn="X.A")
    # 模拟用户复习过 → srs_state 有积累
    fc = fc_repo.get("x.a::tradeoff")
    assert fc is not None
    fc_with_state = fc.model_copy(
        update={"srs_state": SrsState(repetition=3, interval=10, ef=2.6, confidence=4)}
    )
    fc_repo.upsert(fc_with_state)

    # DeepCard 改 tradeoff,re-generate
    dc_repo.upsert(DeepCard(cap_id="x.a", tradeoff="V2 改写后的 tradeoff"))
    regenerate_flashcards_for("x.a", dc_repo=dc_repo, fc_repo=fc_repo, cap_name_cn="X.A")
    fc_after = fc_repo.get("x.a::tradeoff")
    assert fc_after is not None
    assert fc_after.answer == "V2 改写后的 tradeoff"  # 文本变
    assert fc_after.srs_state.repetition == 3  # SRS 保留
    assert fc_after.srs_state.ef == 2.6


def test_regenerate_deletes_obsolete_kinds(tmp_path: Path) -> None:
    """DeepCard 删掉 lessons_learned → 对应闪卡应该消失。"""
    conn = open_db(tmp_path / "t.db")
    dc_repo = DeepCardRepo(conn)
    fc_repo = FlashcardRepo(conn)
    dc_repo.upsert(DeepCard(cap_id="x", tradeoff="t", lessons_learned="l"))
    regenerate_flashcards_for("x", dc_repo=dc_repo, fc_repo=fc_repo, cap_name_cn="X")
    assert len(fc_repo.get_by_cap_id("x")) == 2

    # 删 lessons
    dc_repo.upsert(DeepCard(cap_id="x", tradeoff="t"))
    regenerate_flashcards_for("x", dc_repo=dc_repo, fc_repo=fc_repo, cap_name_cn="X")
    fcs = fc_repo.get_by_cap_id("x")
    assert len(fcs) == 1
    assert fcs[0].template_kind == "tradeoff"

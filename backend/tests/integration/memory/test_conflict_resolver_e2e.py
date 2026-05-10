"""L1 integration: archival_memory_insert with existing edges → conflict resolver.

Tests 4-action end-to-end:
- update_validity (用户买了又卖, valid_to set)
- contradict_existing (用户澄清记错, invalidated_at set)
- no_op (重复)
- append_new (独立共存) — 已在 test_extractor_e2e 覆盖, 此处补强 multi-edge 形态

AGE 不可用时 monkeypatch age_create_edge / age_merge_node 为 no-op.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from app.memory.conflict_resolver import ConflictResolver
from app.memory.extractor import LLMExtractor
from app.memory.hierarchical import HierarchicalMemory
from app.memory.models import ChatMemoryEdge, ChatMemoryEpisode, ChatMemoryNode
from sqlalchemy import select, text

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_PG_TESTS") == "1",
    reason="PG container required",
)


def _patch_age_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.memory import age_sync, hierarchical

    def _noop(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(age_sync, "age_create_edge", _noop)
    monkeypatch.setattr(age_sync, "age_merge_node", _noop)
    if hasattr(hierarchical, "age_create_edge"):
        monkeypatch.setattr(hierarchical, "age_create_edge", _noop, raising=False)
    if hasattr(hierarchical, "age_merge_node"):
        monkeypatch.setattr(hierarchical, "age_merge_node", _noop, raising=False)


def _seed_user_session(pg_memory_fixture: dict[str, Any]) -> tuple[UUID, UUID]:
    engine = pg_memory_fixture["engine"]
    user_uuid = uuid4()
    session_uuid = uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, username, email, hashed_password, is_active) "
                "VALUES (:id, :u, :e, :p, true)"
            ),
            {
                "id": str(user_uuid),
                "u": f"cre_{user_uuid.hex[:8]}",
                "e": f"{user_uuid.hex[:8]}@test.local",
                "p": "x",
            },
        )
        conn.execute(
            text("INSERT INTO chat_sessions (id, user_id, title) VALUES (:id, :uid, :title)"),
            {"id": str(session_uuid), "uid": str(user_uuid), "title": "cre"},
        )
    return user_uuid, session_uuid


def _make_judge_returning(action: str) -> AsyncMock:
    """Build mock LLM client whose chat() returns canned action verdict."""
    fake = AsyncMock()
    fake.chat.return_value = json.dumps({"action": action, "reasoning": f"test {action}"})
    return fake


def _build_memory(
    pg_memory_session_factory: Callable[[], Any],
    *,
    judge_action: str,
    milvus: Any | None = None,
) -> HierarchicalMemory:
    embed = AsyncMock()
    embed.embed.return_value = [0.1] * 1024
    return HierarchicalMemory(
        pg_session_factory=pg_memory_session_factory,
        age_executor=None,
        milvus_client=milvus or MagicMock(),
        embed_service=embed,
        llm_extractor=LLMExtractor(llm_client=AsyncMock()),
        llm_judge=ConflictResolver(llm_client=_make_judge_returning(judge_action)),
    )


@pytest.mark.integration
async def test_e2e_update_validity_holds_to_sold(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """场景: 用户先持有 600519, 后说 3-31 卖了 → existing.valid_to 设为 new.valid_from."""
    _patch_age_noop(monkeypatch)
    uid, sid = _seed_user_session(pg_memory_fixture)

    sess = pg_memory_session_factory()
    try:
        un = ChatMemoryNode(user_id=uid, entity_type="User", entity_label="User")
        sn = ChatMemoryNode(user_id=uid, entity_type="Stock", entity_label="600519.SH")
        ep1 = ChatMemoryEpisode(
            user_id=uid,
            session_id=sid,
            episode_index=0,
            user_message_text="买了茅台",
            source_kind="chat_turn",
        )
        ep2 = ChatMemoryEpisode(
            user_id=uid,
            session_id=sid,
            episode_index=1,
            user_message_text="同 target 卖了",
            source_kind="chat_turn",
        )
        sess.add_all([un, sn, ep1, ep2])
        sess.flush()

        existing = ChatMemoryEdge(
            user_id=uid,
            source_node_id=un.node_id,
            target_node_id=sn.node_id,
            rel_type="HOLDS",
            valid_from=datetime(2024, 8, 1, tzinfo=UTC),
            source_episode_id=ep1.episode_id,
            importance=0.9,
            reasoning="买入",
        )
        sess.add(existing)
        sess.commit()
        ep2_id = ep2.episode_id
        existing_id = existing.edge_id
    finally:
        sess.close()

    memory = _build_memory(pg_memory_session_factory, judge_action="update_validity")

    # 新 edge: HOLDS 同 (User, 600519, HOLDS) 但 valid_from 不同 → judge update_validity
    await memory.archival_memory_insert(
        user_id=uid,
        content={
            "rel_type": "HOLDS",
            "source_entity_type": "User",
            "source_label": "User",
            "target_entity_type": "Stock",
            "target_label": "600519.SH",
            "valid_from": datetime(2026, 3, 31, tzinfo=UTC),
            "valid_to": None,
            "properties": {},
        },
        reasoning="演化",
        importance=0.9,
        evidence_quote="x",
        episode_id=ep2_id,
    )

    sess = pg_memory_session_factory()
    try:
        old = sess.execute(
            select(ChatMemoryEdge).where(ChatMemoryEdge.edge_id == existing_id)
        ).scalar_one()
        assert old.valid_to == datetime(2026, 3, 31, tzinfo=UTC)
        assert old.invalidated_at is None  # KEY: invalidated_at 不动
    finally:
        sess.close()


@pytest.mark.integration
async def test_e2e_contradict_existing_correction(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """场景: 同 (User, target, HOLDS) 重复但被 judge 标 contradict → invalidated_at 设."""
    _patch_age_noop(monkeypatch)
    uid, sid = _seed_user_session(pg_memory_fixture)

    sess = pg_memory_session_factory()
    try:
        un = ChatMemoryNode(user_id=uid, entity_type="User", entity_label="User")
        wrong = ChatMemoryNode(user_id=uid, entity_type="Stock", entity_label="600519.SH")
        ep1 = ChatMemoryEpisode(
            user_id=uid,
            session_id=sid,
            episode_index=0,
            user_message_text="x",
            source_kind="chat_turn",
        )
        ep2 = ChatMemoryEpisode(
            user_id=uid,
            session_id=sid,
            episode_index=1,
            user_message_text="纠正",
            source_kind="chat_turn",
        )
        sess.add_all([un, wrong, ep1, ep2])
        sess.flush()

        wrong_edge = ChatMemoryEdge(
            user_id=uid,
            source_node_id=un.node_id,
            target_node_id=wrong.node_id,
            rel_type="HOLDS",
            valid_from=datetime(2024, 8, 1, tzinfo=UTC),
            source_episode_id=ep1.episode_id,
            importance=0.9,
            reasoning="错记",
        )
        sess.add(wrong_edge)
        sess.commit()
        ep2_id = ep2.episode_id
        wrong_id = wrong_edge.edge_id
    finally:
        sess.close()

    memory = _build_memory(pg_memory_session_factory, judge_action="contradict_existing")

    # 新 edge 同 (User, 600519, HOLDS) 但 valid_from 不同 → judge contradict
    await memory.archival_memory_insert(
        user_id=uid,
        content={
            "rel_type": "HOLDS",
            "source_entity_type": "User",
            "source_label": "User",
            "target_entity_type": "Stock",
            "target_label": "600519.SH",
            "valid_from": datetime(2024, 9, 1, tzinfo=UTC),
            "valid_to": None,
            "properties": {},
        },
        reasoning="纠正记录时间",
        importance=0.9,
        evidence_quote="x",
        episode_id=ep2_id,
    )

    sess = pg_memory_session_factory()
    try:
        old = sess.execute(
            select(ChatMemoryEdge).where(ChatMemoryEdge.edge_id == wrong_id)
        ).scalar_one()
        # 关键: invalidated_at 设, valid_to 不动 (区别于 update_validity)
        assert old.invalidated_at is not None
        assert old.valid_to is None
    finally:
        sess.close()


@pytest.mark.integration
async def test_e2e_no_op_does_not_insert(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """场景: judge no_op → 不写入新 edge, 但 episode 仍标 extracted_at."""
    _patch_age_noop(monkeypatch)
    uid, sid = _seed_user_session(pg_memory_fixture)

    sess = pg_memory_session_factory()
    try:
        un = ChatMemoryNode(user_id=uid, entity_type="User", entity_label="User")
        sn = ChatMemoryNode(user_id=uid, entity_type="Stock", entity_label="600519.SH")
        ep = ChatMemoryEpisode(
            user_id=uid,
            session_id=sid,
            episode_index=0,
            user_message_text="x",
            source_kind="chat_turn",
        )
        sess.add_all([un, sn, ep])
        sess.flush()
        existing = ChatMemoryEdge(
            user_id=uid,
            source_node_id=un.node_id,
            target_node_id=sn.node_id,
            rel_type="HOLDS",
            valid_from=datetime(2026, 5, 1, tzinfo=UTC),
            source_episode_id=ep.episode_id,
            importance=0.9,
            reasoning="持有",
        )
        sess.add(existing)
        sess.commit()
        ep_id = ep.episode_id
    finally:
        sess.close()

    memory = _build_memory(pg_memory_session_factory, judge_action="no_op")

    result = await memory.archival_memory_insert(
        user_id=uid,
        content={
            "rel_type": "HOLDS",
            "source_entity_type": "User",
            "source_label": "User",
            "target_entity_type": "Stock",
            "target_label": "600519.SH",
            "valid_from": datetime(2026, 5, 1, tzinfo=UTC),
            "valid_to": None,
            "properties": {},
        },
        reasoning="重复",
        importance=0.9,
        evidence_quote="x",
        episode_id=ep_id,
    )
    assert result is None

    sess = pg_memory_session_factory()
    try:
        rows = (
            sess.execute(select(ChatMemoryEdge).where(ChatMemoryEdge.user_id == uid))
            .scalars()
            .all()
        )
        assert len(rows) == 1  # only existing, no new edge

        # episode marked extracted with edge_count=0
        ep_row = sess.execute(
            select(ChatMemoryEpisode).where(ChatMemoryEpisode.episode_id == ep_id)
        ).scalar_one()
        assert ep_row.extracted_at is not None
        assert ep_row.extraction_metadata["edge_count"] == 0
    finally:
        sess.close()

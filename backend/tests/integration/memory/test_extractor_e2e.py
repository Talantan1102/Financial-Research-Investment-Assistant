"""L1 integration: HierarchicalMemory.archival_memory_insert end-to-end Path A.

real PG + mock_qwen_embed + mock_llm_judge + mock Milvus.
Verify: edge in PG / Milvus called or outbox written / episode marked extracted.

AGE 在 macOS dev / postgres:15 不可用; archival_memory_insert pipeline 内
age_create_edge 失败时整事务 rollback (spec § 4 失败矩阵). 因此 Path A 在
没 AGE 的环境下会 PG rollback. 本 test 通过 monkeypatch age_create_edge 为 no-op
让 PG 主事务可以 commit, 验证 PG/Milvus 路径 (AGE 同事务行为单独 hardening test 验).
"""

from __future__ import annotations

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
    """让 age_create_edge / age_merge_node 在没 AGE 的环境变 no-op.

    archival_memory_insert 通过 import 内部使用, 所以 patch 模块的 attribute.
    """
    from app.memory import age_sync, hierarchical

    def _noop_edge(*_args: Any, **_kwargs: Any) -> None:
        return None

    def _noop_node(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(age_sync, "age_create_edge", _noop_edge)
    monkeypatch.setattr(age_sync, "age_merge_node", _noop_node)
    # hierarchical.py imports lazily inside method body, so module-level patch is enough
    if hasattr(hierarchical, "age_create_edge"):
        monkeypatch.setattr(hierarchical, "age_create_edge", _noop_edge, raising=False)
    if hasattr(hierarchical, "age_merge_node"):
        monkeypatch.setattr(hierarchical, "age_merge_node", _noop_node, raising=False)


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
                "u": f"e2e_{user_uuid.hex[:8]}",
                "e": f"{user_uuid.hex[:8]}@test.local",
                "p": "x",
            },
        )
        conn.execute(
            text("INSERT INTO chat_sessions (id, user_id, title) VALUES (:id, :uid, :title)"),
            {
                "id": str(session_uuid),
                "uid": str(user_uuid),
                "title": "e2e",
            },
        )
    return user_uuid, session_uuid


def _seed_episode(
    pg_memory_session_factory: Callable[[], Any], uid: UUID, sid: UUID, idx: int = 0
) -> UUID:
    sess = pg_memory_session_factory()
    try:
        ep = ChatMemoryEpisode(
            user_id=uid,
            session_id=sid,
            episode_index=idx,
            user_message_text="seed",
            source_kind="chat_turn",
        )
        sess.add(ep)
        sess.commit()
        sess.refresh(ep)
        return ep.episode_id
    finally:
        sess.close()


def _build_memory(
    pg_memory_session_factory: Callable[[], Any],
    *,
    milvus_client: Any,
    judge_action: str = "append_new",
) -> HierarchicalMemory:
    """Build HierarchicalMemory with mock Milvus + mock embed + mock judge."""
    import json

    judge_llm = AsyncMock()
    judge_llm.chat.return_value = json.dumps(
        {"action": judge_action, "reasoning": f"e2e {judge_action}"}
    )
    embed = AsyncMock()
    embed.embed.return_value = [0.1] * 1024

    return HierarchicalMemory(
        pg_session_factory=pg_memory_session_factory,
        age_executor=None,
        milvus_client=milvus_client,
        embed_service=embed,
        llm_extractor=LLMExtractor(llm_client=AsyncMock()),
        llm_judge=ConflictResolver(llm_client=judge_llm),
    )


@pytest.mark.integration
async def test_archival_memory_insert_path_a_no_existing_edges(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """场景: 首次 insert, 无 existing edges → APPEND_NEW (跳过 conflict judge)."""
    _patch_age_noop(monkeypatch)
    uid, sid = _seed_user_session(pg_memory_fixture)
    ep_id = _seed_episode(pg_memory_session_factory, uid, sid)

    mock_milvus = MagicMock()
    mock_milvus.insert = MagicMock()  # success path

    memory = _build_memory(pg_memory_session_factory, milvus_client=mock_milvus)
    new_edge = await memory.archival_memory_insert(
        user_id=uid,
        content={
            "rel_type": "HOLDS",
            "source_entity_type": "User",
            "source_label": "User",
            "target_entity_type": "Stock",
            "target_label": "600519.SH",
            "valid_from": datetime(2026, 5, 10, tzinfo=UTC),
            "valid_to": None,
            "properties": {"qty": 500},
        },
        reasoning="用户明确持有",
        importance=0.9,
        evidence_quote="我持有 500 股茅台",
        episode_id=ep_id,
    )
    assert new_edge is not None
    assert new_edge.rel_type == "HOLDS"
    assert new_edge.importance == 0.9

    # Verify PG
    sess = pg_memory_session_factory()
    try:
        rows = (
            sess.execute(select(ChatMemoryEdge).where(ChatMemoryEdge.user_id == uid))
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].edge_id == new_edge.edge_id

        # Stock node auto-created
        stock = sess.execute(
            select(ChatMemoryNode).where(
                ChatMemoryNode.user_id == uid,
                ChatMemoryNode.entity_label == "600519.SH",
            )
        ).scalar_one()
        assert stock.entity_type == "Stock"

        # Verify Milvus called
        mock_milvus.insert.assert_called_once()

        # Outbox empty (success path)
        outbox_count = sess.execute(
            text("SELECT COUNT(*) FROM pending_milvus_inserts WHERE user_id = :uid"),
            {"uid": str(uid)},
        ).scalar()
        assert outbox_count == 0
    finally:
        sess.close()


@pytest.mark.integration
async def test_archival_memory_insert_path_a_milvus_failure_outbox(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """场景: Milvus 异常 → PG 不 rollback, outbox 写入."""
    _patch_age_noop(monkeypatch)
    uid, sid = _seed_user_session(pg_memory_fixture)
    ep_id = _seed_episode(pg_memory_session_factory, uid, sid)

    failing_milvus = MagicMock()
    failing_milvus.insert.side_effect = RuntimeError("milvus offline")

    memory = _build_memory(pg_memory_session_factory, milvus_client=failing_milvus)
    new_edge = await memory.archival_memory_insert(
        user_id=uid,
        content={
            "rel_type": "WATCHES",
            "source_entity_type": "User",
            "source_label": "User",
            "target_entity_type": "Stock",
            "target_label": "000001.SZ",
            "valid_from": datetime(2026, 5, 10, tzinfo=UTC),
            "valid_to": None,
            "properties": {},
        },
        reasoning="关注",
        importance=0.5,
        evidence_quote="x",
        episode_id=ep_id,
    )
    # PG commit succeeded
    assert new_edge is not None

    sess = pg_memory_session_factory()
    try:
        outbox = sess.execute(
            text("SELECT edge_id, last_error FROM pending_milvus_inserts WHERE user_id = :uid"),
            {"uid": str(uid)},
        ).fetchone()
        assert outbox is not None
        assert "milvus offline" in outbox.last_error
    finally:
        sess.close()


@pytest.mark.integration
async def test_archival_memory_insert_marks_episode_extracted(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Step 8: episode.extracted_at / extracted_by='agent' / metadata 设置."""
    _patch_age_noop(monkeypatch)
    uid, sid = _seed_user_session(pg_memory_fixture)
    ep_id = _seed_episode(pg_memory_session_factory, uid, sid)

    mock_milvus = MagicMock()
    memory = _build_memory(pg_memory_session_factory, milvus_client=mock_milvus)
    await memory.archival_memory_insert(
        user_id=uid,
        content={
            "rel_type": "PREFERS",
            "source_entity_type": "User",
            "source_label": "User",
            "target_entity_type": "Strategy",
            "target_label": "DCF",
            "valid_from": datetime(2026, 5, 10, tzinfo=UTC),
            "valid_to": None,
            "properties": {},
        },
        reasoning="偏好 DCF",
        importance=0.5,
        evidence_quote="x",
        episode_id=ep_id,
    )

    sess = pg_memory_session_factory()
    try:
        ep = sess.execute(
            select(ChatMemoryEpisode).where(ChatMemoryEpisode.episode_id == ep_id)
        ).scalar_one()
        assert ep.extracted_at is not None
        assert ep.extracted_by == "agent"
        assert ep.extraction_metadata is not None
        assert "edge_count" in ep.extraction_metadata
        assert ep.extraction_metadata["edge_count"] == 1
        assert ep.extraction_metadata["rel_type"] == "PREFERS"
    finally:
        sess.close()


@pytest.mark.integration
async def test_archival_memory_insert_normalize_audit_flag_persists(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Step 3: normalize_entity 失败 → properties._normalize_audit 写入."""
    _patch_age_noop(monkeypatch)
    uid, sid = _seed_user_session(pg_memory_fixture)
    ep_id = _seed_episode(pg_memory_session_factory, uid, sid)

    mock_milvus = MagicMock()
    memory = _build_memory(pg_memory_session_factory, milvus_client=mock_milvus)
    new_edge = await memory.archival_memory_insert(
        user_id=uid,
        content={
            "rel_type": "HOLDS",
            "source_entity_type": "User",
            "source_label": "User",
            "target_entity_type": "Stock",
            "target_label": "茅台",  # 非 ts_code → audit_flag=True
            "valid_from": datetime(2026, 5, 10, tzinfo=UTC),
            "valid_to": None,
            "properties": {},
        },
        reasoning="x",
        importance=0.9,
        evidence_quote="x",
        episode_id=ep_id,
    )
    assert new_edge is not None
    assert "_normalize_audit" in new_edge.properties
    audit = new_edge.properties["_normalize_audit"]
    assert audit["target"] is True
    assert audit["raw_target"] == "茅台"

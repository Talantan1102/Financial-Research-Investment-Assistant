"""L1 hardening: idempotency UNIQUE + AGE failure PG rollback.

幂等键 uq_edges_idempotency_key: (source_episode_id, source_node_id, target_node_id, rel_type, valid_from)
- 同 episode 同 keys 第二次 → IntegrityError(底层 PG UNIQUE 兜底)
- AGE Cypher 失败 → 整 PG 事务 rollback (spec § 4 失败处理矩阵)
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
from app.memory.models import ChatMemoryEdge, ChatMemoryEpisode
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

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
                "u": f"hd_{user_uuid.hex[:8]}",
                "e": f"{user_uuid.hex[:8]}@test.local",
                "p": "x",
            },
        )
        conn.execute(
            text("INSERT INTO chat_sessions (id, user_id, title) VALUES (:id, :uid, :title)"),
            {"id": str(session_uuid), "uid": str(user_uuid), "title": "hd"},
        )
    return user_uuid, session_uuid


def _judge_appendnew() -> AsyncMock:
    fake = AsyncMock()
    fake.chat.return_value = json.dumps({"action": "append_new", "reasoning": "x"})
    return fake


def _build_memory(
    pg_memory_session_factory: Callable[[], Any],
    *,
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
        llm_judge=ConflictResolver(llm_client=_judge_appendnew()),
    )


@pytest.mark.integration
async def test_idempotent_double_insert_same_episode_raises_integrity(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同 episode + 同 (src, tgt, rel, valid_from) 第二次 insert → UNIQUE violation.

    幂等键 uq_edges_idempotency_key: (source_episode_id, source_node_id, target_node_id, rel_type, valid_from)
    Plan 2A 不主动检测幂等 (Plan 4 MCP wrapper 可加上层 dedup), 但底层 UNIQUE 兜底.

    第二次 judge 会看到 existing edge — 让 judge 强制返回 append_new (mock) 触发 UNIQUE.
    """
    _patch_age_noop(monkeypatch)
    uid, sid = _seed_user_session(pg_memory_fixture)

    sess = pg_memory_session_factory()
    try:
        ep = ChatMemoryEpisode(
            user_id=uid,
            session_id=sid,
            episode_index=0,
            user_message_text="x",
            source_kind="chat_turn",
        )
        sess.add(ep)
        sess.commit()
        ep_id = ep.episode_id
    finally:
        sess.close()

    memory = _build_memory(pg_memory_session_factory)

    common_args: dict[str, Any] = {
        "user_id": uid,
        "content": {
            "rel_type": "HOLDS",
            "source_entity_type": "User",
            "source_label": "User",
            "target_entity_type": "Stock",
            "target_label": "600519.SH",
            "valid_from": datetime(2026, 5, 1, tzinfo=UTC),
            "valid_to": None,
            "properties": {},
        },
        "reasoning": "持有",
        "importance": 0.9,
        "evidence_quote": "x",
        "episode_id": ep_id,
    }

    edge1 = await memory.archival_memory_insert(**common_args)
    assert edge1 is not None

    # 第二次同 episode 同 keys → IntegrityError (judge mock 强 append_new, 触发 UNIQUE 违反)
    with pytest.raises(IntegrityError):
        await memory.archival_memory_insert(**common_args)


@pytest.mark.integration
async def test_age_failure_degrades_pg_still_writes(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AGE Cypher 失败 → 边镜像降级,PG 照常写入(政策变更,2026-06-05 冒烟发现 #5)。

    原契约"AGE 失败 → PG rollback"(spec § 4 失败矩阵)在无 AGE 扩展的环境
    (生产 industry_assistant 库连可装的 age 都没有)下等于所有写入永远失败。
    新契约:PG 是 SSOT,AGE 镜像 best-effort——与节点镜像、Milvus outbox 同哲学。
    """
    uid, sid = _seed_user_session(pg_memory_fixture)

    sess = pg_memory_session_factory()
    try:
        ep = ChatMemoryEpisode(
            user_id=uid,
            session_id=sid,
            episode_index=0,
            user_message_text="x",
            source_kind="chat_turn",
        )
        sess.add(ep)
        sess.commit()
        ep_id = ep.episode_id
    finally:
        sess.close()

    # Patch age_create_edge to raise — age_merge_node 留 best-effort no-op
    from app.memory import age_sync, hierarchical

    def _failing_edge(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("AGE Cypher syntax error simulated")

    def _noop_node(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(age_sync, "age_create_edge", _failing_edge)
    monkeypatch.setattr(age_sync, "age_merge_node", _noop_node)
    if hasattr(hierarchical, "age_create_edge"):
        monkeypatch.setattr(hierarchical, "age_create_edge", _failing_edge, raising=False)
    if hasattr(hierarchical, "age_merge_node"):
        monkeypatch.setattr(hierarchical, "age_merge_node", _noop_node, raising=False)

    mock_milvus = MagicMock()
    memory = _build_memory(pg_memory_session_factory, milvus=mock_milvus)

    edge = await memory.archival_memory_insert(
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
        reasoning="x",
        importance=0.9,
        evidence_quote="x",
        episode_id=ep_id,
    )
    assert edge is not None, "AGE 镜像失败不得阻断 PG 写入(降级语义)"

    # Verify PG wrote the edge despite AGE mirror failure
    sess = pg_memory_session_factory()
    try:
        rows = (
            sess.execute(select(ChatMemoryEdge).where(ChatMemoryEdge.user_id == uid))
            .scalars()
            .all()
        )
        assert len(rows) == 1
    finally:
        sess.close()

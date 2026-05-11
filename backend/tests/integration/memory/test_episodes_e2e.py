"""L1: HierarchicalMemory episode 持久化 — write / get_unextracted / mark_extracted."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.memory.hierarchical import HierarchicalMemory
from app.memory.models import ChatMemoryEpisode
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_PG_TESTS") == "1",
    reason="PG container required",
)


def _make_user(pg_memory_fixture: dict[str, Any]) -> UUID:
    engine = pg_memory_fixture["engine"]
    user_uuid = uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, username, email, hashed_password, is_active) "
                "VALUES (:id, :u, :e, :p, true)"
            ),
            {
                "id": str(user_uuid),
                "u": f"ep_{user_uuid.hex[:8]}",
                "e": f"{user_uuid.hex[:8]}@test.local",
                "p": "x",
            },
        )
    return user_uuid


def _make_session(pg_memory_fixture: dict[str, Any], user_uuid: UUID) -> UUID:
    engine = pg_memory_fixture["engine"]
    session_uuid = uuid4()
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO chat_sessions (id, user_id, title) VALUES (:id, :uid, :title)"),
            {
                "id": str(session_uuid),
                "uid": str(user_uuid),
                "title": "test session",
            },
        )
    return session_uuid


@pytest.fixture
def hier_memory(
    pg_memory_session_factory: Callable[[], Any],
) -> HierarchicalMemory:
    return HierarchicalMemory(
        pg_session_factory=pg_memory_session_factory,
        age_executor=None,
        milvus_client=None,
        embed_service=None,
        llm_extractor=None,
        llm_judge=None,
    )


@pytest.mark.integration
async def test_write_episode_creates_row(
    hier_memory: HierarchicalMemory, pg_memory_fixture: dict[str, Any]
) -> None:
    uid = _make_user(pg_memory_fixture)
    sid = _make_session(pg_memory_fixture, uid)
    ep = await hier_memory.write_episode(
        user_id=uid,
        session_id=sid,
        episode_index=0,
        user_message="我看好茅台",
        agent_response="茅台 PE 32",
    )
    assert ep.episode_id is not None
    assert ep.user_message_text == "我看好茅台"
    assert ep.extracted_at is None
    assert ep.source_kind == "chat_turn"


@pytest.mark.integration
async def test_write_episode_unique_session_index(
    hier_memory: HierarchicalMemory, pg_memory_fixture: dict[str, Any]
) -> None:
    uid = _make_user(pg_memory_fixture)
    sid = _make_session(pg_memory_fixture, uid)
    from sqlalchemy.exc import IntegrityError

    await hier_memory.write_episode(uid, sid, 0, "u", "a")
    # 同 session 同 index 第二次 → IntegrityError(UNIQUE constraint Plan 1A 已建)
    with pytest.raises(IntegrityError):
        await hier_memory.write_episode(uid, sid, 0, "u2", "a2")


@pytest.mark.integration
async def test_get_unextracted_episodes_filters(
    hier_memory: HierarchicalMemory, pg_memory_fixture: dict[str, Any]
) -> None:
    uid = _make_user(pg_memory_fixture)
    sid = _make_session(pg_memory_fixture, uid)
    ep1 = await hier_memory.write_episode(uid, sid, 0, "u1", "a1")
    ep2 = await hier_memory.write_episode(uid, sid, 1, "u2", "a2")

    pending = await hier_memory.get_unextracted_episodes(uid, limit=10)
    pending_ids = {e.episode_id for e in pending}
    assert ep1.episode_id in pending_ids
    assert ep2.episode_id in pending_ids

    # mark ep1 extracted
    await hier_memory.mark_episode_extracted(
        ep1.episode_id, extracted_by="agent", extraction_metadata={"edges": 2}
    )
    pending2 = await hier_memory.get_unextracted_episodes(uid, limit=10)
    pending2_ids = {e.episode_id for e in pending2}
    assert ep1.episode_id not in pending2_ids
    assert ep2.episode_id in pending2_ids


@pytest.mark.integration
async def test_mark_episode_extracted_sets_metadata(
    hier_memory: HierarchicalMemory,
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
) -> None:
    uid = _make_user(pg_memory_fixture)
    sid = _make_session(pg_memory_fixture, uid)
    ep = await hier_memory.write_episode(uid, sid, 0, "u", "a")
    await hier_memory.mark_episode_extracted(
        ep.episode_id,
        extracted_by="eos_batch",
        extraction_metadata={"model": "haiku", "edges": 3, "latency_ms": 120},
    )

    sess = pg_memory_session_factory()
    try:
        ep_reread = sess.query(ChatMemoryEpisode).filter_by(episode_id=ep.episode_id).first()
        assert ep_reread is not None
        assert ep_reread.extracted_at is not None
        assert ep_reread.extracted_by == "eos_batch"
        assert ep_reread.extraction_metadata["model"] == "haiku"
    finally:
        sess.close()


@pytest.mark.integration
async def test_get_unextracted_user_isolation(
    hier_memory: HierarchicalMemory, pg_memory_fixture: dict[str, Any]
) -> None:
    """多租户隔离: user A 的 unextracted 不能漏给 user B."""
    uA = _make_user(pg_memory_fixture)
    uB = _make_user(pg_memory_fixture)
    sA = _make_session(pg_memory_fixture, uA)
    sB = _make_session(pg_memory_fixture, uB)
    epA = await hier_memory.write_episode(uA, sA, 0, "uA", "a")
    epB = await hier_memory.write_episode(uB, sB, 0, "uB", "a")

    pendingA = await hier_memory.get_unextracted_episodes(uA, limit=10)
    pA_ids = {e.episode_id for e in pendingA}
    assert epA.episode_id in pA_ids
    assert epB.episode_id not in pA_ids

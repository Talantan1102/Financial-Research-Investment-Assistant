"""L1: reconciliation 骨架 — scan inconsistent state.

Plan 1B 范围:
- scan_inconsistent_state(user_id) returns list of ReconciliationCase
- 简单 case: edge 存在但 source_episode 的 extracted_at 仍 NULL → 标
- 复杂 case (Milvus pending) → Plan 5 收束, 这里仅 placeholder

Plan 5 收束: weekly Celery job 调本入口 + 实际 retry / fix.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.memory.hierarchical import HierarchicalMemory
from app.memory.models import ChatMemoryEdge, ChatMemoryNode
from app.memory.reconciliation import scan_inconsistent_state
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
                "u": f"rc_{user_uuid.hex[:8]}",
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
async def test_scan_inconsistent_empty_user_zero_cases(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
) -> None:
    uid = _make_user(pg_memory_fixture)
    cases = await scan_inconsistent_state(uid, pg_session_factory=pg_memory_session_factory)
    assert cases == []


@pytest.mark.integration
async def test_scan_detects_edge_with_unextracted_episode(
    hier_memory: HierarchicalMemory,
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
) -> None:
    """造一个不一致 state: episode extracted_at IS NULL 但已有 edge ref 它.

    这表示进程崩溃在 Step 8(mark_extracted)之前 — 反向失败的典型 case.
    """
    uid = _make_user(pg_memory_fixture)
    sid = _make_session(pg_memory_fixture, uid)
    ep = await hier_memory.write_episode(uid, sid, 0, "u", "a")
    # 模拟 Plan 2 ship 的 archival_memory_insert 走完 Step 7 但 Step 8 崩
    sess = pg_memory_session_factory()
    try:
        u_node = ChatMemoryNode(user_id=uid, entity_type="User", entity_label="User")
        s_node = ChatMemoryNode(user_id=uid, entity_type="Stock", entity_label="600519.SH")
        sess.add_all([u_node, s_node])
        sess.flush()

        edge = ChatMemoryEdge(
            user_id=uid,
            source_node_id=u_node.node_id,
            target_node_id=s_node.node_id,
            rel_type="HOLDS",
            valid_from=datetime.now(UTC),
            source_episode_id=ep.episode_id,
            importance=0.9,
            reasoning="test",
        )
        sess.add(edge)
        sess.commit()
    finally:
        sess.close()

    cases = await scan_inconsistent_state(uid, pg_session_factory=pg_memory_session_factory)
    # 检测到 1 个 case: edge 存在但 episode extracted_at IS NULL
    assert len(cases) == 1
    assert cases[0].kind == "edge_exists_episode_unextracted"
    assert cases[0].episode_id == ep.episode_id

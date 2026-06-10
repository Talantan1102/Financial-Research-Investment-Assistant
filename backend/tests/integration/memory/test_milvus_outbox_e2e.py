"""L1 integration tests for Milvus outbox — inline try + enqueue fallthrough.

Tests against real PG fixture; mock Milvus + embed services.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from app.memory.milvus_outbox import (
    build_edge_embed_text,
    enqueue_milvus_insert,
    try_milvus_insert,
)
from app.memory.models import ChatMemoryEdge, ChatMemoryEpisode, ChatMemoryNode
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_PG_TESTS") == "1",
    reason="PG container required",
)


def test_build_edge_embed_text_format() -> None:
    """spec § 2 embed text 模板: rel_type src_type src_label → tgt_type tgt_label reasoning props."""
    text_out = build_edge_embed_text(
        rel_type="HOLDS",
        source_entity_type="User",
        source_label="User",
        target_entity_type="Stock",
        target_label="600519.SH",
        reasoning="用户说持有",
        properties={"qty": 500},
    )
    assert "HOLDS" in text_out
    assert "User" in text_out
    assert "600519.SH" in text_out
    assert "→" in text_out
    assert "用户说持有" in text_out
    assert "qty" in text_out


def _make_user_session_episode_edge(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
) -> tuple[UUID, ChatMemoryEdge, Any]:
    """Helper: 建一个 (user, session, episode, edge) 链, 返回 sess 让调用方继续用."""
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
                "u": f"out_{user_uuid.hex[:8]}",
                "e": f"{user_uuid.hex[:8]}@test.local",
                "p": "x",
            },
        )
        conn.execute(
            text("INSERT INTO chat_sessions (id, user_id, title) VALUES (:id, :uid, :title)"),
            {
                "id": str(session_uuid),
                "uid": str(user_uuid),
                "title": "outbox test",
            },
        )

    sess = pg_memory_session_factory()
    ep = ChatMemoryEpisode(
        user_id=user_uuid,
        session_id=session_uuid,
        episode_index=0,
        user_message_text="x",
        source_kind="chat_turn",
    )
    sess.add(ep)
    un = ChatMemoryNode(user_id=user_uuid, entity_type="User", entity_label="User")
    sn = ChatMemoryNode(user_id=user_uuid, entity_type="Stock", entity_label="600519.SH")
    sess.add_all([un, sn])
    sess.flush()
    edge = ChatMemoryEdge(
        user_id=user_uuid,
        source_node_id=un.node_id,
        target_node_id=sn.node_id,
        rel_type="HOLDS",
        valid_from=datetime(2026, 5, 1, tzinfo=UTC),
        source_episode_id=ep.episode_id,
        importance=0.9,
        reasoning="x",
    )
    sess.add(edge)
    sess.flush()
    return user_uuid, edge, sess


@pytest.mark.integration
async def test_try_milvus_insert_success_no_outbox(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
) -> None:
    """成功 path: insert 不走 outbox, return True."""
    user_uuid, edge, sess = _make_user_session_episode_edge(
        pg_memory_fixture, pg_memory_session_factory
    )
    try:
        mock_milvus = MagicMock()
        mock_milvus.insert = MagicMock()
        mock_embed = AsyncMock()
        mock_embed.embed.return_value = [0.1] * 1024

        ok = await try_milvus_insert(
            session=sess,
            milvus_client=mock_milvus,
            embed_service=mock_embed,
            edge=edge,
            edge_text="HOLDS User → Stock 600519.SH",
        )
        sess.commit()
        assert ok is True
        mock_milvus.insert.assert_called_once()

        # outbox 表应无该 edge_id
        result = sess.execute(
            text("SELECT COUNT(*) FROM pending_milvus_inserts WHERE edge_id = :eid"),
            {"eid": str(edge.edge_id)},
        )
        assert result.scalar() == 0
    finally:
        sess.close()


@pytest.mark.integration
async def test_try_milvus_insert_embeds_with_list_and_inserts_flat_vector(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
) -> None:
    """embed 真契约 embed(list[str]) -> list[list[float]]。outbox 过去传 bare string,
    长 edge_text 按字符切片返回多个子串向量,插入的 embedding 形态错 → struct/维度错,
    毒化向量写入。必须 embed([edge_text]) 收 list,并取 [0] 插入单条 flat 向量。"""
    user_uuid, edge, sess = _make_user_session_episode_edge(
        pg_memory_fixture, pg_memory_session_factory
    )
    try:
        mock_milvus = MagicMock()
        mock_milvus.insert = MagicMock()
        mock_embed = AsyncMock()
        mock_embed.embed.return_value = [[0.1] * 1024]  # 真契约形态

        ok = await try_milvus_insert(
            session=sess,
            milvus_client=mock_milvus,
            embed_service=mock_embed,
            edge=edge,
            edge_text="HOLDS User → Stock 600519.SH 用户长期持有贵州茅台逻辑是消费升级",
        )
        assert ok is True
        mock_embed.embed.assert_awaited_once_with(
            ["HOLDS User → Stock 600519.SH 用户长期持有贵州茅台逻辑是消费升级"]
        )
        inserted = mock_milvus.insert.call_args.kwargs["data"][0]["embedding"]
        assert len(inserted) == 1024, "插入的应是单条 flat 1024 维向量,不是嵌套"
        assert all(isinstance(x, float) for x in inserted)
    finally:
        sess.close()


@pytest.mark.integration
async def test_try_milvus_insert_failure_falls_through_to_outbox(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
) -> None:
    """异常 path: milvus.insert 抛 → 写 outbox, return False, 不抛."""
    user_uuid, edge, sess = _make_user_session_episode_edge(
        pg_memory_fixture, pg_memory_session_factory
    )
    try:
        mock_milvus = MagicMock()
        mock_milvus.insert.side_effect = RuntimeError("milvus connection refused")
        mock_embed = AsyncMock()
        mock_embed.embed.return_value = [0.1] * 1024

        ok = await try_milvus_insert(
            session=sess,
            milvus_client=mock_milvus,
            embed_service=mock_embed,
            edge=edge,
            edge_text="HOLDS User → Stock 600519.SH",
        )
        sess.commit()
        assert ok is False

        # outbox 表 inserted
        result = sess.execute(
            text(
                "SELECT edge_id, last_error, retry_count FROM pending_milvus_inserts "
                "WHERE edge_id = :eid"
            ),
            {"eid": str(edge.edge_id)},
        )
        row = result.fetchone()
        assert row is not None
        assert "milvus connection refused" in row.last_error
        assert row.retry_count == 0
    finally:
        sess.close()


@pytest.mark.integration
async def test_try_milvus_insert_embed_failure_also_outbox(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
) -> None:
    """embed 失败也走 outbox (跟 milvus 失败一样, 都不 rollback PG)."""
    user_uuid, edge, sess = _make_user_session_episode_edge(
        pg_memory_fixture, pg_memory_session_factory
    )
    try:
        mock_milvus = MagicMock()
        mock_embed = AsyncMock()
        mock_embed.embed.side_effect = RuntimeError("qwen api 503")

        ok = await try_milvus_insert(
            session=sess,
            milvus_client=mock_milvus,
            embed_service=mock_embed,
            edge=edge,
            edge_text="HOLDS User → Stock 600519.SH",
        )
        sess.commit()
        assert ok is False
        mock_milvus.insert.assert_not_called()  # 没到 milvus call

        result = sess.execute(
            text("SELECT last_error FROM pending_milvus_inserts WHERE edge_id = :eid"),
            {"eid": str(edge.edge_id)},
        )
        row = result.fetchone()
        assert row is not None
        assert "qwen" in row.last_error.lower()
    finally:
        sess.close()


@pytest.mark.integration
async def test_enqueue_idempotent_via_on_conflict(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
) -> None:
    """同 edge_id 重复 enqueue → ON CONFLICT 更新 last_error, 不抛."""
    user_uuid, edge, sess = _make_user_session_episode_edge(
        pg_memory_fixture, pg_memory_session_factory
    )
    try:
        enqueue_milvus_insert(
            session=sess,
            edge_id=edge.edge_id,
            edge_text="x",
            user_id=edge.user_id,
            rel_type=edge.rel_type,
            last_error="first error",
        )
        enqueue_milvus_insert(
            session=sess,
            edge_id=edge.edge_id,
            edge_text="x",
            user_id=edge.user_id,
            rel_type=edge.rel_type,
            last_error="second error",
        )
        sess.commit()
        result = sess.execute(
            text("SELECT last_error, retry_count FROM pending_milvus_inserts WHERE edge_id = :eid"),
            {"eid": str(edge.edge_id)},
        )
        row = result.fetchone()
        assert row is not None
        assert row.last_error == "second error"
    finally:
        sess.close()

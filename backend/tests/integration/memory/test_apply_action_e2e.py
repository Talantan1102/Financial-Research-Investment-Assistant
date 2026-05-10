"""L1 integration tests for Step 6 apply_action — bi-temporal correctness.

Per shared-contracts § 3, HierarchicalMemory uses **sync** SQLAlchemy session
(callable factory). apply_action is a sync helper that takes Session.

bi-temporal 4 字段:
- valid_from / valid_to: 事实生效区间 (现实演化用)
- recorded_at / invalidated_at: 系统记录区间 (记错纠正用)

测试覆盖 4 action × bi-temporal correctness:
- update_validity: valid_to set, invalidated_at unchanged
- contradict_existing: invalidated_at set, valid_to unchanged
- append_new: existing untouched
- no_op: no insert, no mutate
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.memory.conflict_resolver import ConflictAction, ConflictVerdict, apply_action
from app.memory.models import ChatMemoryEdge, ChatMemoryEpisode, ChatMemoryNode
from sqlalchemy import select, text

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
                "u": f"app_{user_uuid.hex[:8]}",
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


@pytest.mark.integration
def test_apply_action_update_validity_sets_valid_to_only(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
) -> None:
    """场景: 用户先持有, 后说卖了 → existing.valid_to = new.valid_from, invalidated_at 不变."""
    uid = _make_user(pg_memory_fixture)
    sid = _make_session(pg_memory_fixture, uid)
    sess = pg_memory_session_factory()
    try:
        ep1 = ChatMemoryEpisode(
            user_id=uid,
            session_id=sid,
            episode_index=0,
            user_message_text="我 2024-08 买了茅台",
            agent_response_text="ok",
            source_kind="chat_turn",
        )
        ep2 = ChatMemoryEpisode(
            user_id=uid,
            session_id=sid,
            episode_index=1,
            user_message_text="3 月清了茅台",
            agent_response_text="ok",
            source_kind="chat_turn",
        )
        sess.add_all([ep1, ep2])
        sess.flush()

        user_node = ChatMemoryNode(user_id=uid, entity_type="User", entity_label="User")
        stock_node = ChatMemoryNode(user_id=uid, entity_type="Stock", entity_label="600519.SH")
        sess.add_all([user_node, stock_node])
        sess.flush()

        existing_edge = ChatMemoryEdge(
            user_id=uid,
            source_node_id=user_node.node_id,
            target_node_id=stock_node.node_id,
            rel_type="HOLDS",
            valid_from=datetime(2024, 8, 1, tzinfo=UTC),
            valid_to=None,
            invalidated_at=None,
            source_episode_id=ep1.episode_id,
            importance=0.9,
            reasoning="持有",
        )
        sess.add(existing_edge)
        sess.flush()
        existing_edge_id = existing_edge.edge_id

        verdict = ConflictVerdict(action=ConflictAction.UPDATE_VALIDITY, reasoning="卖了")
        new_valid_from = datetime(2026, 3, 31, tzinfo=UTC)

        new_edge = apply_action(
            session=sess,
            verdict=verdict,
            existing_edge_ids=[existing_edge_id],
            user_id=uid,
            source_node_id=user_node.node_id,
            target_node_id=stock_node.node_id,
            rel_type="SOLD",
            valid_from=new_valid_from,
            valid_to=None,
            source_episode_id=ep2.episode_id,
            importance=0.9,
            reasoning="清仓",
            properties={},
        )
        sess.commit()

        # Verify existing edge: valid_to 设置为 new.valid_from, invalidated_at 仍 NULL
        sess.refresh(existing_edge)
        assert existing_edge.valid_to == new_valid_from
        assert existing_edge.invalidated_at is None

        # Verify new edge inserted
        assert new_edge is not None
        assert new_edge.rel_type == "SOLD"
        assert new_edge.valid_from == new_valid_from
        assert new_edge.invalidated_at is None
    finally:
        sess.close()


@pytest.mark.integration
def test_apply_action_contradict_sets_invalidated_at_only(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
) -> None:
    """场景: 用户澄清记录错 → existing.invalidated_at = now(), valid_to 不变."""
    uid = _make_user(pg_memory_fixture)
    sid = _make_session(pg_memory_fixture, uid)
    sess = pg_memory_session_factory()
    try:
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
            user_message_text="记错了, 是五粮液",
            source_kind="chat_turn",
        )
        sess.add_all([ep1, ep2])
        sess.flush()

        user_node = ChatMemoryNode(user_id=uid, entity_type="User", entity_label="User")
        wrong_stock = ChatMemoryNode(user_id=uid, entity_type="Stock", entity_label="600519.SH")
        right_stock = ChatMemoryNode(user_id=uid, entity_type="Stock", entity_label="000858.SZ")
        sess.add_all([user_node, wrong_stock, right_stock])
        sess.flush()

        wrong_edge = ChatMemoryEdge(
            user_id=uid,
            source_node_id=user_node.node_id,
            target_node_id=wrong_stock.node_id,
            rel_type="HOLDS",
            valid_from=datetime(2024, 8, 1, tzinfo=UTC),
            valid_to=None,
            invalidated_at=None,
            source_episode_id=ep1.episode_id,
            importance=0.9,
            reasoning="错",
        )
        sess.add(wrong_edge)
        sess.flush()
        wrong_edge_id = wrong_edge.edge_id

        verdict = ConflictVerdict(action=ConflictAction.CONTRADICT_EXISTING, reasoning="纠正")
        new_edge = apply_action(
            session=sess,
            verdict=verdict,
            existing_edge_ids=[wrong_edge_id],
            user_id=uid,
            source_node_id=user_node.node_id,
            target_node_id=right_stock.node_id,
            rel_type="HOLDS",
            valid_from=datetime(2024, 8, 1, tzinfo=UTC),
            valid_to=None,
            source_episode_id=ep2.episode_id,
            importance=0.9,
            reasoning="纠正",
            properties={},
        )
        sess.commit()

        sess.refresh(wrong_edge)
        # 关键: invalidated_at 设, valid_to 不动 (区别于 update_validity)
        assert wrong_edge.invalidated_at is not None
        assert wrong_edge.valid_to is None
        assert new_edge is not None
        assert new_edge.target_node_id == right_stock.node_id
        assert new_edge.invalidated_at is None
    finally:
        sess.close()


@pytest.mark.integration
def test_apply_action_append_new_inserts_only_new_edge(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
) -> None:
    """场景: 不矛盾 → 仅 INSERT, 不动 existing."""
    uid = _make_user(pg_memory_fixture)
    sid = _make_session(pg_memory_fixture, uid)
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
        sess.flush()

        user_node = ChatMemoryNode(user_id=uid, entity_type="User", entity_label="User")
        sec1 = ChatMemoryNode(user_id=uid, entity_type="Sector", entity_label="食品饮料")
        sec2 = ChatMemoryNode(user_id=uid, entity_type="Sector", entity_label="金融")
        sess.add_all([user_node, sec1, sec2])
        sess.flush()

        existing = ChatMemoryEdge(
            user_id=uid,
            source_node_id=user_node.node_id,
            target_node_id=sec1.node_id,
            rel_type="PREFERS",
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            valid_to=None,
            invalidated_at=None,
            source_episode_id=ep.episode_id,
            importance=0.5,
            reasoning="偏好",
        )
        sess.add(existing)
        sess.flush()
        existing_id = existing.edge_id

        verdict = ConflictVerdict(action=ConflictAction.APPEND_NEW, reasoning="独立")
        new_edge = apply_action(
            session=sess,
            verdict=verdict,
            existing_edge_ids=[existing_id],
            user_id=uid,
            source_node_id=user_node.node_id,
            target_node_id=sec2.node_id,  # 不同 target, 独立共存
            rel_type="PREFERS",
            valid_from=datetime(2026, 5, 1, tzinfo=UTC),
            valid_to=None,
            source_episode_id=ep.episode_id,
            importance=0.5,
            reasoning="新偏好",
            properties={},
        )
        sess.commit()

        sess.refresh(existing)
        assert existing.valid_to is None
        assert existing.invalidated_at is None  # 不动
        assert new_edge is not None
        assert new_edge.target_node_id == sec2.node_id
    finally:
        sess.close()


@pytest.mark.integration
def test_apply_action_no_op_returns_none(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
) -> None:
    """场景: no_op → 不写入, 返回 None."""
    uid = _make_user(pg_memory_fixture)
    sid = _make_session(pg_memory_fixture, uid)
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
        sess.flush()

        user_node = ChatMemoryNode(user_id=uid, entity_type="User", entity_label="User")
        stock = ChatMemoryNode(user_id=uid, entity_type="Stock", entity_label="600519.SH")
        sess.add_all([user_node, stock])
        sess.flush()

        verdict = ConflictVerdict(action=ConflictAction.NO_OP, reasoning="重复")
        result = apply_action(
            session=sess,
            verdict=verdict,
            existing_edge_ids=[],
            user_id=uid,
            source_node_id=user_node.node_id,
            target_node_id=stock.node_id,
            rel_type="HOLDS",
            valid_from=datetime(2026, 5, 1, tzinfo=UTC),
            valid_to=None,
            source_episode_id=ep.episode_id,
            importance=0.9,
            reasoning="持有",
            properties={},
        )
        sess.commit()
        assert result is None

        # Verify no edge written
        rows = (
            sess.execute(select(ChatMemoryEdge).where(ChatMemoryEdge.user_id == uid))
            .scalars()
            .all()
        )
        assert len(rows) == 0
    finally:
        sess.close()

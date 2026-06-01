"""L1: instrumentation 表 schema + 落库 helper.

契约 § 17 A4: 表名严守 chat_memory_retrieval_logs / chat_memory_retrieval_feedback.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.memory.instrumentation import log_retrieval_hit, log_user_reject
from app.memory.models import ChatMemoryEdge, ChatMemoryEpisode, ChatMemoryNode
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_PG_TESTS") == "1",
    reason="PG container required",
)


def test_retrieval_logs_table_exists(pg_memory_fixture: dict[str, Any]) -> None:
    engine = pg_memory_fixture["engine"]
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_name = 'chat_memory_retrieval_logs'
                ORDER BY ordinal_position
                """
            )
        ).fetchall()
    cols = {row[0]: row[1] for row in rows}
    assert "log_id" in cols
    assert "user_id" in cols
    assert "query_text" in cols
    assert "retrieved_edge_ids" in cols
    assert "rrf_scores" in cols
    assert "top_k_valid_from_p90_days" in cols
    assert "retriever_breakdown" in cols
    assert "latency_ms" in cols
    assert "created_at" in cols


def test_retrieval_feedback_table_exists(pg_memory_fixture: dict[str, Any]) -> None:
    engine = pg_memory_fixture["engine"]
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'chat_memory_retrieval_feedback'
                """
            )
        ).fetchall()
    cols = {row[0] for row in rows}
    assert "feedback_id" in cols
    assert "edge_id" in cols
    assert "user_id" in cols
    assert "feedback_kind" in cols
    assert "reason" in cols
    assert "created_at" in cols


def test_log_retrieval_hit_inserts_row(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
) -> None:
    """log_retrieval_hit 落库 1 行, p90 字段计算正确."""
    user_id = uuid4()
    edges_meta: dict[str, dict[str, Any]] = {
        "e1": {
            "rel_type": "HOLDS",
            "importance": 0.9,
            "valid_from": datetime.now(UTC) - timedelta(days=10),
            "valid_to": None,
        },
        "e2": {
            "rel_type": "PREFERS",
            "importance": 0.5,
            "valid_from": datetime.now(UTC) - timedelta(days=20),
            "valid_to": None,
        },
    }
    sess = pg_memory_session_factory()
    try:
        log_id = log_retrieval_hit(
            sess,
            user_id=user_id,
            query_text="我对茅台的看法",
            retrieved_edge_ids=["e1", "e2"],
            rrf_scores={"e1": 0.05, "e2": 0.03},
            edges_meta=edges_meta,
            retriever_breakdown={"bm25": 2, "vector": 1, "graph": 0},
            latency_ms=120,
        )
        sess.commit()
    finally:
        sess.close()

    # verify row landed
    engine = pg_memory_fixture["engine"]
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT log_id, user_id, query_text, top_k_valid_from_p90_days, latency_ms
                FROM chat_memory_retrieval_logs WHERE log_id = :lid
                """
            ),
            {"lid": str(log_id)},
        ).fetchone()
    assert row is not None
    assert str(row[0]) == str(log_id)
    assert str(row[1]) == str(user_id)
    assert row[2] == "我对茅台的看法"
    # p90 计算 (C49 fix): 2 个 sample (10, 20), idx = int((2-1) * 0.9) = 0 → ages[0] = 10.0
    assert row[3] is not None and 9.0 < row[3] < 11.0
    assert row[4] == 120


def test_log_user_reject_inserts_row(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
) -> None:
    """log_user_reject feedback_kind 各值落库 + check constraint 起作用."""
    engine = pg_memory_fixture["engine"]
    user_uuid = uuid4()
    session_uuid = uuid4()
    # seed user / chat_session / episode / edge
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, username, email, hashed_password, is_active) "
                "VALUES (:id, :u, :e, :p, true)"
            ),
            {
                "id": str(user_uuid),
                "u": f"instr_{user_uuid.hex[:8]}",
                "e": f"{user_uuid.hex[:8]}@test.local",
                "p": "x",
            },
        )
        conn.execute(
            text("INSERT INTO chat_sessions (id, user_id, title) VALUES (:id, :uid, :title)"),
            {"id": str(session_uuid), "uid": str(user_uuid), "title": "instr"},
        )

    sess = pg_memory_session_factory()
    try:
        ep = ChatMemoryEpisode(
            user_id=user_uuid,
            session_id=session_uuid,
            episode_index=0,
            user_message_text="seed",
            source_kind="test_seed",
        )
        sess.add(ep)
        sess.flush()

        n1 = ChatMemoryNode(user_id=user_uuid, entity_type="User", entity_label="User")
        n2 = ChatMemoryNode(user_id=user_uuid, entity_type="Stock", entity_label="600519.SH")
        sess.add(n1)
        sess.add(n2)
        sess.flush()

        edge = ChatMemoryEdge(
            user_id=user_uuid,
            source_node_id=n1.node_id,
            target_node_id=n2.node_id,
            rel_type="HOLDS",
            valid_from=datetime.now(UTC),
            source_episode_id=ep.episode_id,
            importance=0.9,
        )
        sess.add(edge)
        sess.flush()
        edge_id = edge.edge_id
        sess.commit()
    finally:
        sess.close()

    sess2 = pg_memory_session_factory()
    try:
        log_user_reject(
            sess2,
            user_id=user_uuid,
            edge_id=edge_id,
            feedback_kind="reject",
            reason="not relevant",
        )
        sess2.commit()
    finally:
        sess2.close()

    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT feedback_kind, reason FROM chat_memory_retrieval_feedback
                WHERE edge_id = :eid AND user_id = :uid
                """
            ),
            {"eid": str(edge_id), "uid": str(user_uuid)},
        ).fetchone()
    assert row is not None
    assert row[0] == "reject"
    assert row[1] == "not relevant"


def test_log_user_reject_invalid_kind_raises() -> None:
    """invalid feedback_kind 应 raise ValueError 而非 DB CHECK constraint."""
    fake_session = type("FakeSession", (), {"execute": lambda *a, **k: None})()
    with pytest.raises(ValueError, match="reject"):
        log_user_reject(
            fake_session,
            user_id=uuid4(),
            edge_id=uuid4(),
            feedback_kind="bogus",
        )


def _make_user(_session: Any, _user_id: UUID) -> None:
    pass  # unused stub kept for future expansion

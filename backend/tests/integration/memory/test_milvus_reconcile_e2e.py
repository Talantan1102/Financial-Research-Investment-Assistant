"""L1 — Milvus pending reconciliation 端到端 (real PG + mock Milvus + mock embed).

Spec § 4 末尾失败矩阵 行 5 (Milvus 失败 → 写 pending → 5min retry).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from app.memory.reconciliation import (
    MAX_RECONCILE_RETRIES,
    reconcile_pending_milvus_inserts,
)
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("SKIP_PG_TESTS") == "1",
        reason="PG container required",
    ),
]


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
                "u": f"mr_{user_uuid.hex[:8]}",
                "e": f"{user_uuid.hex[:8]}@test.local",
                "p": "x",
            },
        )
        conn.execute(
            text("INSERT INTO chat_sessions (id, user_id, title) VALUES (:id, :uid, :t)"),
            {"id": str(session_uuid), "uid": str(user_uuid), "t": "mr"},
        )
    return user_uuid, session_uuid


def _seed_real_edge(pg_memory_fixture: dict[str, Any], user_id: UUID, session_id: UUID) -> UUID:
    """Seed real chat_memory_edges row (FK target for pending_milvus_inserts)."""
    from app.memory.models import (
        ChatMemoryEdge,
        ChatMemoryEpisode,
        ChatMemoryNode,
    )

    engine = pg_memory_fixture["engine"]
    SessionLocal = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    sess = SessionLocal()
    try:
        ep = ChatMemoryEpisode(
            episode_id=uuid4(),
            user_id=user_id,
            session_id=session_id,
            episode_index=0,
            user_message_text="seed",
            source_kind="chat_turn",
            created_at=datetime.now(tz=UTC),
        )
        sess.add(ep)
        src = ChatMemoryNode(
            node_id=uuid4(),
            user_id=user_id,
            entity_type="User",
            entity_label="User",
            properties={},
        )
        tgt = ChatMemoryNode(
            node_id=uuid4(),
            user_id=user_id,
            entity_type="Stock",
            entity_label="600519.SH",
            properties={},
        )
        sess.add(src)
        sess.add(tgt)
        sess.flush()
        edge = ChatMemoryEdge(
            edge_id=uuid4(),
            user_id=user_id,
            source_node_id=src.node_id,
            target_node_id=tgt.node_id,
            rel_type="HOLDS",
            valid_from=datetime.now(tz=UTC),
            source_episode_id=ep.episode_id,
            importance=0.9,
            reasoning="test edge for reconcile",
            properties={},
        )
        sess.add(edge)
        sess.commit()
        eid: UUID = edge.edge_id  # type: ignore[assignment]
        return eid
    finally:
        sess.close()


def _seed_pending(
    pg_memory_fixture: dict[str, Any],
    user_id: UUID,
    session_id: UUID,
    *,
    last_error: str = "milvus down",
    retry_count: int = 0,
) -> tuple[UUID, int]:
    """Insert pending_milvus_inserts row (table created by Plan 2A migration).

    Returns (edge_id, pending_id).
    """
    edge_id = _seed_real_edge(pg_memory_fixture, user_id, session_id)
    engine = pg_memory_fixture["engine"]
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """INSERT INTO pending_milvus_inserts
                (edge_id, edge_text, user_id, rel_type, retry_count, last_error)
                VALUES(:eid, :etext, :uid, :rt, :rc, :err)
                RETURNING id"""
            ),
            {
                "eid": str(edge_id),
                "etext": "test edge for reconcile",
                "uid": str(user_id),
                "rt": "HOLDS",
                "rc": retry_count,
                "err": last_error,
            },
        ).fetchone()
    pid: int = int(row[0]) if row else 0
    return edge_id, pid


def _count_pending(pg_memory_fixture: dict[str, Any]) -> int:
    engine = pg_memory_fixture["engine"]
    with engine.connect() as conn:
        return int(conn.execute(text("SELECT COUNT(*) FROM pending_milvus_inserts")).scalar() or 0)


def _clear_pending(pg_memory_fixture: dict[str, Any]) -> None:
    """每个测试前清空 pending — 避免 session-scoped fixture 累积污染."""
    engine = pg_memory_fixture["engine"]
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM pending_milvus_inserts"))


@pytest.fixture(autouse=True)
def _clean_pending(pg_memory_fixture: dict[str, Any]) -> None:
    _clear_pending(pg_memory_fixture)


def test_reconcile_clears_pending_on_success(pg_memory_fixture: dict[str, Any]) -> None:
    """Mock embed + insert 都成功 → pending 行被删."""
    engine = pg_memory_fixture["engine"]
    SessionLocal = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    user_id, session_id = _seed_user_session(pg_memory_fixture)
    _edge_id, _pid = _seed_pending(pg_memory_fixture, user_id, session_id)

    fake_embed = AsyncMock(return_value=[0.01] * 1024)
    fake_milvus = MagicMock()
    fake_milvus.insert = MagicMock(return_value=None)

    initial = _count_pending(pg_memory_fixture)
    result = reconcile_pending_milvus_inserts(
        session_factory=SessionLocal,
        embed_fn=fake_embed,
        milvus_client=fake_milvus,
    )
    assert result.processed >= 1
    assert result.succeeded >= 1
    assert result.failed == 0
    assert _count_pending(pg_memory_fixture) == initial - 1


def test_reconcile_insert_payload_includes_user_id_and_rel_type(
    pg_memory_fixture: dict[str, Any],
) -> None:
    """C57: the Milvus insert payload must carry user_id + rel_type (the collection
    schema requires both). The old impl sent only {edge_id, embedding}, so every
    real retry failed schema validation and silently exhausted MAX_RECONCILE_RETRIES.
    The prior success test masked this because MagicMock.insert accepts any payload.
    """
    engine = pg_memory_fixture["engine"]
    SessionLocal = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    user_id, session_id = _seed_user_session(pg_memory_fixture)
    _edge_id, _pid = _seed_pending(pg_memory_fixture, user_id, session_id)

    fake_embed = AsyncMock(return_value=[0.01] * 1024)
    fake_milvus = MagicMock()
    fake_milvus.insert = MagicMock(return_value=None)

    reconcile_pending_milvus_inserts(
        session_factory=SessionLocal,
        embed_fn=fake_embed,
        milvus_client=fake_milvus,
    )
    fake_milvus.insert.assert_called_once()
    data = fake_milvus.insert.call_args.kwargs["data"][0]
    assert data["user_id"] == str(user_id)
    assert data["rel_type"] == "HOLDS"
    assert "embedding" in data
    assert data["edge_id"] == str(_edge_id)


def test_reconcile_increments_retry_count_on_failure(
    pg_memory_fixture: dict[str, Any],
) -> None:
    """embed 抛异常 → pending.retry_count + 1, last_error 更新."""
    engine = pg_memory_fixture["engine"]
    SessionLocal = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    user_id, session_id = _seed_user_session(pg_memory_fixture)
    edge_id, _pid = _seed_pending(pg_memory_fixture, user_id, session_id, retry_count=0)

    fake_embed = AsyncMock(side_effect=RuntimeError("dashscope 503"))
    fake_milvus = MagicMock()

    result = reconcile_pending_milvus_inserts(
        session_factory=SessionLocal,
        embed_fn=fake_embed,
        milvus_client=fake_milvus,
    )
    assert result.processed >= 1
    assert result.failed >= 1
    # Row still exists with bumped retry_count
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT retry_count, last_error FROM pending_milvus_inserts WHERE edge_id=:eid"),
            {"eid": str(edge_id)},
        ).fetchone()
    assert row is not None
    assert int(row[0]) == 1
    assert "dashscope" in (row[1] or "")


def test_reconcile_alerts_after_max_retries(
    pg_memory_fixture: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    """retry_count 已达 MAX_RECONCILE_RETRIES → log error 标 alert, 不再 retry."""
    engine = pg_memory_fixture["engine"]
    SessionLocal = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    user_id, session_id = _seed_user_session(pg_memory_fixture)
    _edge_id, _pid = _seed_pending(
        pg_memory_fixture, user_id, session_id, retry_count=MAX_RECONCILE_RETRIES
    )

    # Embed should NOT be called (already over the threshold)
    fake_embed = AsyncMock(return_value=[0.01] * 1024)
    fake_milvus = MagicMock()
    fake_milvus.insert = MagicMock(return_value=None)

    with caplog.at_level("ERROR"):
        result = reconcile_pending_milvus_inserts(
            session_factory=SessionLocal,
            embed_fn=fake_embed,
            milvus_client=fake_milvus,
        )
    assert result.alerted >= 1
    assert any("max_reconcile_retries_exceeded" in rec.getMessage() for rec in caplog.records)
    # Row preserved (not deleted, not re-attempted)
    fake_embed.assert_not_called()


def test_reconcile_celery_task_wires_to_reconciliation(
    pg_memory_fixture: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Celery task body invokes reconcile_pending_milvus_inserts and surfaces stats."""
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "1")
    monkeypatch.setenv("CELERY_TASK_EAGER_PROPAGATES", "1")

    from app.memory.reconciliation import ReconcileResult
    from app.tasks import memory as memory_tasks

    fake_result = ReconcileResult(processed=3, succeeded=2, failed=1, alerted=0)
    monkeypatch.setattr(memory_tasks, "_run_milvus_reconciliation", lambda: fake_result)

    out = memory_tasks.reconcile_pending_milvus.apply().get()
    assert out["processed"] == 3
    assert out["succeeded"] == 2
    assert out["failed"] == 1
    assert out["alerted"] == 0

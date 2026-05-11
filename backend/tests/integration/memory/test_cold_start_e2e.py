"""L1: cold start 3 路 seed + 幂等."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.memory.cold_start import seed_user_graph
from app.memory.models import ChatMemoryEdge, ChatMemoryEpisode, ChatMemoryNode
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_PG_TESTS") == "1",
    reason="PG container required",
)


def _make_user_with_positions(pg_memory_fixture: dict[str, Any]) -> UUID:
    """创建一个测试 user + 2 持仓."""
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
                "u": f"cs_{user_uuid.hex[:8]}",
                "e": f"{user_uuid.hex[:8]}@test.local",
                "p": "x",
            },
        )
        conn.execute(
            text(
                "INSERT INTO positions "
                "(id, user_id, ts_code, name, quantity, avg_cost, total_cost, "
                "realized_pnl, is_silenced, updated_at) VALUES "
                "(:id, :uid, :code, :name, :qty, :ac, :tc, :rp, false, :ts)"
            ),
            [
                {
                    "id": str(uuid4()),
                    "uid": str(user_uuid),
                    "code": "600519.SH",
                    "name": "贵州茅台",
                    "qty": 500,
                    "ac": Decimal("1500.0"),
                    "tc": Decimal("750000.0"),
                    "rp": Decimal("0"),
                    "ts": datetime(2025, 1, 1),
                },
                {
                    "id": str(uuid4()),
                    "uid": str(user_uuid),
                    "code": "600036.SH",
                    "name": "招商银行",
                    "qty": 200,
                    "ac": Decimal("35.0"),
                    "tc": Decimal("7000.0"),
                    "rp": Decimal("0"),
                    "ts": datetime(2025, 1, 1),
                },
            ],
        )
    return user_uuid


@pytest.mark.integration
async def test_seed_user_graph_creates_holds_edges(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
) -> None:
    user_id = _make_user_with_positions(pg_memory_fixture)
    await seed_user_graph(user_id, pg_session_factory=pg_memory_session_factory)

    sess = pg_memory_session_factory()
    try:
        edges = (
            sess.query(ChatMemoryEdge)
            .filter(
                ChatMemoryEdge.user_id == user_id,
                ChatMemoryEdge.rel_type == "HOLDS",
            )
            .all()
        )
        # 2 持仓 → 2 HOLDS edges
        assert len(edges) == 2
        for e in edges:
            assert e.importance == 0.9  # cold start 高 importance
            assert e.invalidated_at is None
            assert e.source_episode_id is not None
    finally:
        sess.close()


@pytest.mark.integration
async def test_seed_creates_cold_start_seed_episode(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
) -> None:
    user_id = _make_user_with_positions(pg_memory_fixture)
    await seed_user_graph(user_id, pg_session_factory=pg_memory_session_factory)
    sess = pg_memory_session_factory()
    try:
        seed_eps = (
            sess.query(ChatMemoryEpisode)
            .filter(
                ChatMemoryEpisode.user_id == user_id,
                ChatMemoryEpisode.source_kind == "cold_start_seed",
            )
            .all()
        )
        assert len(seed_eps) == 1
    finally:
        sess.close()


@pytest.mark.integration
async def test_seed_idempotent_rerun_no_dup(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
) -> None:
    """重跑 cold start: 已 seeded 短路 + 即便不短路也走 UNIQUE constraint 不重复."""
    user_id = _make_user_with_positions(pg_memory_fixture)
    await seed_user_graph(user_id, pg_session_factory=pg_memory_session_factory)
    await seed_user_graph(user_id, pg_session_factory=pg_memory_session_factory)

    sess = pg_memory_session_factory()
    try:
        holds = (
            sess.query(ChatMemoryEdge)
            .filter(
                ChatMemoryEdge.user_id == user_id,
                ChatMemoryEdge.rel_type == "HOLDS",
            )
            .all()
        )
        assert len(holds) == 2  # 仍 2 条, 不是 4 条
    finally:
        sess.close()


@pytest.mark.integration
async def test_seed_creates_user_node_and_stock_nodes(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
) -> None:
    user_id = _make_user_with_positions(pg_memory_fixture)
    await seed_user_graph(user_id, pg_session_factory=pg_memory_session_factory)
    sess = pg_memory_session_factory()
    try:
        nodes = sess.query(ChatMemoryNode).filter(ChatMemoryNode.user_id == user_id).all()
        labels = {n.entity_label for n in nodes}
        types = {n.entity_type for n in nodes}
        assert "User" in labels
        assert "600519.SH" in labels
        assert "600036.SH" in labels
        assert "Stock" in types
        assert "User" in types
    finally:
        sess.close()

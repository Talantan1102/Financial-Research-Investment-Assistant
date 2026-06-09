"""L1: 3-way hybrid retrieval e2e — 真 PG (BM25), mock Milvus + embed.

设计取舍:
- 跑真 PG seed + 真 BM25 (PG GIN tsvector + jieba), 这是 Plan 3 主要新逻辑.
- Vector / Graph 路径用 mock — Plan 1A milvus collection 真存在但 Plan 3 还没 wire
  embed→insert flow(Plan 2A 已 wire write); search 端的 e2e 留 L2 cassette.
- 多租户隔离测试用真 PG WHERE user_id 过滤.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from app.memory.hierarchical import HierarchicalMemory
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_PG_TESTS") == "1",
    reason="PG container required",
)


def _seed_user_session(engine: Any, user_id: UUID, session_id: UUID) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, username, email, hashed_password, is_active) "
                "VALUES (:id, :u, :e, :p, true)"
            ),
            {
                "id": str(user_id),
                "u": f"r3_{user_id.hex[:8]}",
                "e": f"{user_id.hex[:8]}@test.local",
                "p": "x",
            },
        )
        conn.execute(
            text("INSERT INTO chat_sessions (id, user_id, title) VALUES (:id, :uid, :title)"),
            {"id": str(session_id), "uid": str(user_id), "title": "retriever e2e"},
        )


def _seed_test_edges(
    factory: Callable[[], Any],
    user_id: UUID,
    session_id: UUID,
    specs: list[dict[str, Any]],
) -> None:
    """Direct ORM seed — bypass extractor."""
    from app.memory.models import ChatMemoryEdge, ChatMemoryEpisode, ChatMemoryNode

    sess = factory()
    try:
        ep = ChatMemoryEpisode(
            user_id=user_id,
            session_id=session_id,
            episode_index=0,
            user_message_text="seed",
            source_kind="test_seed",
        )
        sess.add(ep)
        sess.flush()

        # User node — get_or_create
        user_node = ChatMemoryNode(
            user_id=user_id, entity_type="User", entity_label="User", search_tokens="User"
        )
        sess.add(user_node)
        sess.flush()

        for spec in specs:
            target_node = ChatMemoryNode(
                user_id=user_id,
                entity_type=spec.get("entity_type", "Stock"),
                entity_label=spec["label"],
                search_tokens=spec["label"],
            )
            sess.add(target_node)
            sess.flush()

            now = datetime.now(UTC)
            edge = ChatMemoryEdge(
                user_id=user_id,
                source_node_id=user_node.node_id,
                target_node_id=target_node.node_id,
                rel_type=spec["rel_type"],
                valid_from=now - timedelta(days=spec["days_old"]),
                source_episode_id=ep.episode_id,
                importance=spec["imp"],
                search_tokens=spec["label"],
            )
            sess.add(edge)
        sess.commit()
    finally:
        sess.close()


def _make_memory(
    factory: Callable[[], Any],
    *,
    milvus: Any | None = None,
    embed: Any | None = None,
) -> HierarchicalMemory:
    return HierarchicalMemory(
        pg_session_factory=factory,
        age_executor=None,
        milvus_client=milvus,
        embed_service=embed,
        llm_extractor=None,
        llm_judge=None,
    )


@pytest.mark.asyncio
async def test_archival_search_high_importance_recent_first(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
) -> None:
    """高 importance + 近期 HOLDS 排第一.

    BM25 only (Milvus None) — 测试 RRF v2 importance + time decay 在 BM25 单路上的效果.
    """
    user_id = uuid4()
    session_id = uuid4()
    _seed_user_session(pg_memory_fixture["engine"], user_id, session_id)
    _seed_test_edges(
        pg_memory_session_factory,
        user_id,
        session_id,
        [
            # 高 importance + 近期 + 含 "茅台"
            {"label": "茅台", "rel_type": "HOLDS", "imp": 0.9, "days_old": 10},
            # low importance + 近期 + 含 "茅台"
            {"label": "茅台 ETF", "rel_type": "STUDIED", "imp": 0.2, "days_old": 10},
        ],
    )

    memory = _make_memory(pg_memory_session_factory)
    results = await memory.archival_memory_search(user_id, query="茅台", k=3)
    assert len(results) >= 1
    # 第一个应是高 importance HOLDS
    assert results[0].rel_type == "HOLDS"
    assert results[0].importance == 0.9


@pytest.mark.asyncio
async def test_archival_search_old_low_importance_still_retrieved(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
) -> None:
    """衰减底 0.5 验证: 1 年前 importance=0.2 fact 仍可召回 (score > 0)."""
    user_id = uuid4()
    session_id = uuid4()
    _seed_user_session(pg_memory_fixture["engine"], user_id, session_id)
    _seed_test_edges(
        pg_memory_session_factory,
        user_id,
        session_id,
        [
            {
                "label": "TestStockOld",
                "rel_type": "EXPRESSED_VIEW",
                "imp": 0.2,
                "days_old": 365,
            },
        ],
    )

    memory = _make_memory(pg_memory_session_factory)
    results = await memory.archival_memory_search(user_id, query="TestStockOld", k=5)
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_archival_search_user_isolation(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
) -> None:
    """多租户隔离 — userA 检索不应看到 userB 数据."""
    user_a = uuid4()
    user_b = uuid4()
    sess_a = uuid4()
    sess_b = uuid4()
    _seed_user_session(pg_memory_fixture["engine"], user_a, sess_a)
    _seed_user_session(pg_memory_fixture["engine"], user_b, sess_b)
    _seed_test_edges(
        pg_memory_session_factory,
        user_a,
        sess_a,
        [{"label": "UserA_Stock", "rel_type": "HOLDS", "imp": 0.9, "days_old": 10}],
    )
    _seed_test_edges(
        pg_memory_session_factory,
        user_b,
        sess_b,
        [{"label": "UserB_Stock", "rel_type": "HOLDS", "imp": 0.9, "days_old": 10}],
    )

    memory = _make_memory(pg_memory_session_factory)
    results_a = await memory.archival_memory_search(user_a, query="Stock", k=10)
    # Edge labels we got — none of UserB
    for edge in results_a:
        # edge.search_tokens 含 label
        assert "UserB" not in (edge.search_tokens or "")


@pytest.mark.asyncio
async def test_archival_search_edges_readable_after_session_close(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
) -> None:
    """生产 SessionLocal 默认 expire_on_commit=True:archival_memory_search 内
    session.commit() 会 expire 所有属性,随后 expunge 把已失效对象 detach,
    调用方再访问 edge.target_node_id 触发 lazy refresh → DetachedInstanceError
    (对话流评估读侧拿到边却渲染崩溃的根因)。search 必须保证返回的边脱离
    session 后列属性仍可读 —— 用 expire_on_commit=True 工厂复现生产口径。"""
    from sqlalchemy.orm import sessionmaker

    user_id = uuid4()
    session_id = uuid4()
    _seed_user_session(pg_memory_fixture["engine"], user_id, session_id)
    _seed_test_edges(
        pg_memory_session_factory,
        user_id,
        session_id,
        [{"label": "茅台", "rel_type": "HOLDS", "imp": 0.9, "days_old": 10}],
    )

    # 模拟生产:expire_on_commit=True
    engine = pg_memory_fixture["engine"]
    prod_like = sessionmaker(bind=engine, future=True, expire_on_commit=True)
    memory = _make_memory(lambda: prod_like())

    results = await memory.archival_memory_search(user_id, query="茅台", k=3)
    assert len(results) >= 1
    edge = results[0]
    # 以下访问在 search 的 session 关闭之后发生 —— 不得抛 DetachedInstanceError
    _ = str(edge.target_node_id)
    _ = edge.rel_type
    _ = edge.valid_from
    _ = edge.valid_to
    _ = edge.invalidated_at
    _ = edge.properties


@pytest.mark.asyncio
async def test_archival_search_with_mock_vector(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
) -> None:
    """Vector 路径 mocked — 验证 BM25 + Vector 都贡献 RRF 输入."""
    user_id = uuid4()
    session_id = uuid4()
    _seed_user_session(pg_memory_fixture["engine"], user_id, session_id)
    _seed_test_edges(
        pg_memory_session_factory,
        user_id,
        session_id,
        [
            {"label": "茅台", "rel_type": "HOLDS", "imp": 0.9, "days_old": 10},
            {"label": "五粮液", "rel_type": "PREFERS", "imp": 0.5, "days_old": 30},
        ],
    )

    # Find an edge_id to mock vector hit
    sess = pg_memory_session_factory()
    try:
        rows = sess.execute(
            text("SELECT edge_id FROM chat_memory_edges WHERE user_id = :uid LIMIT 1"),
            {"uid": str(user_id)},
        ).fetchall()
        edge_id = str(rows[0][0])
    finally:
        sess.close()

    embed_service = MagicMock()
    embed_service.embed = AsyncMock(return_value=[0.0] * 1024)

    milvus = MagicMock()
    milvus.search = MagicMock(
        return_value=[[{"id": edge_id, "distance": 0.3, "entity": {"edge_id": edge_id}}]]
    )

    memory = _make_memory(pg_memory_session_factory, milvus=milvus, embed=embed_service)
    results = await memory.archival_memory_search(user_id, query="茅台", k=5)
    assert len(results) >= 1
    embed_service.embed.assert_awaited()
    milvus.search.assert_called()


@pytest.mark.asyncio
async def test_archival_search_logs_to_retrieval_logs_table(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
) -> None:
    """instrumentation: archival_memory_search 落 chat_memory_retrieval_logs 一行."""
    user_id = uuid4()
    session_id = uuid4()
    _seed_user_session(pg_memory_fixture["engine"], user_id, session_id)
    _seed_test_edges(
        pg_memory_session_factory,
        user_id,
        session_id,
        [{"label": "茅台", "rel_type": "HOLDS", "imp": 0.9, "days_old": 10}],
    )

    memory = _make_memory(pg_memory_session_factory)
    await memory.archival_memory_search(user_id, query="茅台", k=3)

    engine = pg_memory_fixture["engine"]
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT query_text, latency_ms, retriever_breakdown
                FROM chat_memory_retrieval_logs
                WHERE user_id = :uid
                ORDER BY created_at DESC LIMIT 1
                """
            ),
            {"uid": str(user_id)},
        ).fetchone()
    assert row is not None
    assert row[0] == "茅台"
    assert row[1] is not None  # latency_ms recorded
    # retriever_breakdown 含 bm25 / vector / graph keys
    rb = row[2] or {}
    assert "bm25" in rb
    assert "vector" in rb
    assert "graph" in rb


# ---------------------------------------------------------------------------
# C9: graph_traverse PG node_id lookup — regression tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graph_traverse_pg_resolves_node_id_before_age(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
) -> None:
    """C9 regression: graph_traverse must look up node_id from PG and pass it to
    AGE Cypher — not filter on entity_label/user_id which don't exist on AGE nodes.

    With a real PG node seeded, graph_traverse should call age_executor.cypher
    with a Cypher string that contains node_id from PG, not entity_label.
    """
    from app.memory.models import ChatMemoryNode
    from app.memory.retriever import graph_traverse

    user_id = uuid4()
    session_id = uuid4()
    _seed_user_session(pg_memory_fixture["engine"], user_id, session_id)

    # Seed a ChatMemoryNode directly in PG
    sess = pg_memory_session_factory()
    try:
        node = ChatMemoryNode(
            user_id=user_id,
            entity_type="Stock",
            entity_label="贵州茅台",
            search_tokens="贵州茅台",
        )
        sess.add(node)
        sess.commit()
        expected_node_id = str(node.node_id)
    finally:
        sess.close()

    # Mock AGE executor — returns empty (AGE not running in CI)
    age_executor = MagicMock()
    age_executor.cypher = AsyncMock(return_value=[])

    # Use a fresh session for the query
    sess2 = pg_memory_session_factory()
    try:
        results = await graph_traverse(
            sess2,
            age_executor=age_executor,
            user_id=user_id,
            start_label="贵州茅台",
            hops=2,
        )
    finally:
        sess2.close()

    # AGE was called with node_id (not entity_label), and params contain no uid
    age_executor.cypher.assert_awaited_once()
    cypher_str = age_executor.cypher.call_args.args[1]
    cypher_params = age_executor.cypher.call_args.args[2]

    assert f"node_id: '{expected_node_id}'" in cypher_str, (
        f"Cypher should contain node_id='{expected_node_id}', got: {cypher_str!r}"
    )
    assert "entity_label" not in cypher_str, "Cypher must not filter on entity_label (not in AGE)"
    assert "user_id" not in cypher_params, "AGE params must not include user_id (PG-layer scoping)"
    assert results == []  # AGE mock returned empty


@pytest.mark.asyncio
async def test_graph_traverse_unknown_label_returns_empty_no_age_call(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
) -> None:
    """C9 regression: unknown entity_label → [] without calling AGE."""
    from app.memory.retriever import graph_traverse

    user_id = uuid4()
    session_id = uuid4()
    _seed_user_session(pg_memory_fixture["engine"], user_id, session_id)

    age_executor = MagicMock()
    age_executor.cypher = AsyncMock(return_value=[{"some": "data"}])

    sess = pg_memory_session_factory()
    try:
        results = await graph_traverse(
            sess,
            age_executor=age_executor,
            user_id=user_id,
            start_label="DoesNotExistLabel_xyz",
            hops=1,
        )
    finally:
        sess.close()

    assert results == []
    age_executor.cypher.assert_not_awaited()

"""L0: 3 路 retriever — bm25_search / vector_search / graph_traverse.

设计取舍 (Plan 3 实施期):
- 沿用 HierarchicalMemory 的 sync Session pattern, 不引 AsyncEngine.
- bm25_search / vector_search / graph_traverse 接收 sync Session, 调用方负责 commit/rollback.
- async 仅在 vector_search (embed_service.embed 可能 awaitable) 与 graph_traverse 内部出现.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from app.memory.retriever import (
    bm25_search,
    format_edges_meta_for_rrf,
    graph_traverse,
    vector_search,
)


class TestBm25Search:
    def test_jieba_tokenize_query_then_call_pg(self) -> None:
        """query 走 jieba.cut_for_search 切词, 再 plainto_tsquery."""
        sess = MagicMock()
        eid = uuid4()
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(
            return_value=[
                {
                    "edge_id": str(eid),
                    "bm25_score": 0.8,
                    "rel_type": "HOLDS",
                    "importance": 0.9,
                    "valid_from": datetime.now(UTC),
                    "valid_to": None,
                }
            ]
        )
        sess.execute = MagicMock(return_value=mock_result)

        user_id = uuid4()
        results = bm25_search(sess, user_id=user_id, query="茅台", k=10)
        assert len(results) == 1
        assert "edge_id" in results[0]
        # 校验 SQL 包含 plainto_tsquery + invalidated_at IS NULL filter
        call_args = sess.execute.call_args
        sql_str = str(call_args[0][0])
        assert "plainto_tsquery" in sql_str
        assert "invalidated_at IS NULL" in sql_str

    def test_empty_query_returns_empty_list(self) -> None:
        sess = MagicMock()
        results = bm25_search(sess, user_id=uuid4(), query="", k=10)
        assert results == []
        sess.execute.assert_not_called()

    def test_whitespace_only_query_returns_empty(self) -> None:
        sess = MagicMock()
        results = bm25_search(sess, user_id=uuid4(), query="   \t\n  ", k=10)
        assert results == []


class TestVectorSearch:
    @pytest.mark.asyncio
    async def test_calls_embed_then_milvus_search(self) -> None:
        """vector_search: 1) embed query 2) Milvus search 3) join PG meta."""
        embed_service = MagicMock()
        embed_service.embed = AsyncMock(return_value=[0.0] * 1024)

        milvus_client = MagicMock()
        eid = str(uuid4())
        milvus_client.search = MagicMock(
            return_value=[[{"id": eid, "distance": 0.3, "entity": {"edge_id": eid}}]]
        )

        sess = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(
            return_value=[
                {
                    "edge_id": eid,
                    "rel_type": "HOLDS",
                    "importance": 0.9,
                    "valid_from": datetime.now(UTC),
                    "valid_to": None,
                }
            ]
        )
        sess.execute = MagicMock(return_value=mock_result)

        results = await vector_search(
            sess,
            milvus_client=milvus_client,
            embed_service=embed_service,
            user_id=uuid4(),
            query="茅台白酒",
            k=10,
        )
        assert len(results) == 1
        assert results[0]["edge_id"] == eid
        embed_service.embed.assert_awaited_once()
        milvus_client.search.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self) -> None:
        results = await vector_search(
            MagicMock(),
            milvus_client=MagicMock(),
            embed_service=MagicMock(),
            user_id=uuid4(),
            query="",
            k=10,
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_user_id_filter_in_milvus_expr(self) -> None:
        """spec § 5 + 多租户隔离: Milvus search 必须带 user_id filter."""
        embed_service = MagicMock()
        embed_service.embed = AsyncMock(return_value=[0.0] * 1024)
        milvus_client = MagicMock()
        milvus_client.search = MagicMock(return_value=[[]])
        sess = MagicMock()

        await vector_search(
            sess,
            milvus_client=milvus_client,
            embed_service=embed_service,
            user_id=uuid4(),
            query="x",
            k=5,
        )
        call_kwargs = milvus_client.search.call_args.kwargs
        # filter expression 必须含 user_id
        assert "user_id" in (call_kwargs.get("filter") or "")

    @pytest.mark.asyncio
    async def test_sync_embed_service_supported(self) -> None:
        """embed_service.embed 同步返回 list[float] 也能跑(legacy fallback)."""
        embed_service = MagicMock()
        embed_service.embed = MagicMock(return_value=[0.0] * 1024)  # sync, not awaitable
        milvus_client = MagicMock()
        milvus_client.search = MagicMock(return_value=[[]])
        sess = MagicMock()

        results = await vector_search(
            sess,
            milvus_client=milvus_client,
            embed_service=embed_service,
            user_id=uuid4(),
            query="x",
            k=5,
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_milvus_returns_no_hits_returns_empty(self) -> None:
        embed_service = MagicMock()
        embed_service.embed = AsyncMock(return_value=[0.0] * 1024)
        milvus_client = MagicMock()
        milvus_client.search = MagicMock(return_value=[[]])  # empty inner list
        sess = MagicMock()
        results = await vector_search(
            sess,
            milvus_client=milvus_client,
            embed_service=embed_service,
            user_id=uuid4(),
            query="x",
            k=5,
        )
        assert results == []


class TestGraphTraverse:
    @pytest.mark.asyncio
    async def test_2_hop_traversal(self) -> None:
        sess = MagicMock()
        age_executor = MagicMock()
        # AGE returns empty list - no row data parsing needed for this test
        age_executor.cypher = AsyncMock(return_value=[])

        results = await graph_traverse(
            sess,
            age_executor=age_executor,
            user_id=uuid4(),
            start_label="User",
            hops=2,
            rel_types=["HOLDS", "BELONGS_TO"],
        )
        # 调用了 AGE Cypher
        age_executor.cypher.assert_awaited_once()
        cypher_str = age_executor.cypher.call_args.args[1]
        assert "MATCH" in cypher_str
        assert "*1..2" in cypher_str
        assert results == []

    @pytest.mark.asyncio
    async def test_invalid_hops_raises(self) -> None:
        sess = MagicMock()
        with pytest.raises(ValueError, match="hops"):
            await graph_traverse(
                sess,
                age_executor=MagicMock(),
                user_id=uuid4(),
                start_label="User",
                hops=10,
            )

    @pytest.mark.asyncio
    async def test_default_rel_types_uses_all(self) -> None:
        """rel_types=None → 全部 11 类传到 AGE 参数."""
        sess = MagicMock()
        age_executor = MagicMock()
        age_executor.cypher = AsyncMock(return_value=[])
        await graph_traverse(
            sess,
            age_executor=age_executor,
            user_id=uuid4(),
            start_label="User",
            hops=1,
            rel_types=None,
        )
        params = age_executor.cypher.call_args.args[2]
        assert "rel_types" in params
        assert len(params["rel_types"]) == 11

    @pytest.mark.asyncio
    async def test_age_executor_none_returns_empty(self) -> None:
        """AGE 不可用时(executor=None) → 空 list, 不报错."""
        sess = MagicMock()
        results = await graph_traverse(
            sess,
            age_executor=None,
            user_id=uuid4(),
            start_label="User",
            hops=1,
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_age_executor_raises_returns_empty(self) -> None:
        """AGE 调用 raise (e.g., extension not installed) → fallback 空 list."""
        sess = MagicMock()
        age_executor = MagicMock()
        age_executor.cypher = AsyncMock(side_effect=Exception("AGE not loaded"))
        results = await graph_traverse(
            sess,
            age_executor=age_executor,
            user_id=uuid4(),
            start_label="User",
            hops=2,
        )
        assert results == []


class TestFormatEdgesMetaForRrf:
    def test_aggregates_3_retriever_results_by_edge_id(self) -> None:
        bm25 = [
            {
                "edge_id": "e1",
                "rel_type": "HOLDS",
                "importance": 0.9,
                "valid_from": datetime(2024, 1, 1, tzinfo=UTC),
                "valid_to": None,
            }
        ]
        vec = [
            {
                "edge_id": "e2",
                "rel_type": "PREFERS",
                "importance": 0.5,
                "valid_from": datetime(2024, 6, 1, tzinfo=UTC),
                "valid_to": None,
            }
        ]
        graph: list[dict[str, Any]] = []
        meta = format_edges_meta_for_rrf([bm25, vec, graph])
        assert "e1" in meta and "e2" in meta
        assert meta["e1"]["rel_type"] == "HOLDS"
        assert meta["e2"]["rel_type"] == "PREFERS"

    def test_dedupes_when_edge_in_multiple_retrievers(self) -> None:
        bm25 = [
            {
                "edge_id": "e1",
                "rel_type": "HOLDS",
                "importance": 0.9,
                "valid_from": datetime(2024, 1, 1, tzinfo=UTC),
                "valid_to": None,
            }
        ]
        vec = [
            {
                "edge_id": "e1",
                "rel_type": "HOLDS",
                "importance": 0.9,
                "valid_from": datetime(2024, 1, 1, tzinfo=UTC),
                "valid_to": None,
            }
        ]
        meta = format_edges_meta_for_rrf([bm25, vec])
        assert len(meta) == 1

    def test_uuid_edge_id_normalized_to_str(self) -> None:
        eid = uuid4()
        item = [
            {
                "edge_id": eid,  # UUID object
                "rel_type": "HOLDS",
                "importance": 0.9,
                "valid_from": datetime(2024, 1, 1, tzinfo=UTC),
                "valid_to": None,
            }
        ]
        meta = format_edges_meta_for_rrf([item])
        assert str(eid) in meta

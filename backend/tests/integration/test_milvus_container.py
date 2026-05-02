"""L1 integration — 真 Milvus 容器 + mock embedding/parser:
collection schema / search expr / multi-collection 路由 / filter 字段."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest
from app.services.kb_search_service import MilvusKbSearchService
from app.services.milvus_client import (
    COLLECTION_FINANCIAL,
    COLLECTION_POLICY,
    COLLECTION_RESEARCH,
    EMBEDDING_DIM,
    MilvusKbClient,
)


@pytest.fixture
async def real_milvus_client(milvus_test_container: dict[str, Any]):
    """Per-test fresh client with cleared collections."""
    client = MilvusKbClient(
        host=milvus_test_container["host"],
        port=milvus_test_container["port"],
    )
    await client.drop_all()  # clean slate
    await client.ensure_collections()
    yield client
    await client.drop_all()


@pytest.fixture
def mock_embedding() -> Any:
    svc = AsyncMock()
    svc.embed = AsyncMock(side_effect=lambda texts: [[0.1] * EMBEDDING_DIM for _ in texts])
    svc.dimension = EMBEDDING_DIM
    svc.model_name = "fake"
    return svc


async def test_ensure_collections_creates_three(real_milvus_client: MilvusKbClient) -> None:
    """Verify 3 collection 都被创建,schema 字段对."""
    for name in (COLLECTION_RESEARCH, COLLECTION_FINANCIAL, COLLECTION_POLICY):
        # 通过 pymilvus 直接 verify 存在 + 字段
        coll = real_milvus_client._client.describe_collection(name)
        field_names = [f["name"] for f in coll["fields"]]
        assert "doc_id" in field_names
        assert "vector" in field_names

    # 类型特定字段
    research_coll = real_milvus_client._client.describe_collection(COLLECTION_RESEARCH)
    assert "broker" in [f["name"] for f in research_coll["fields"]]


async def test_insert_and_search_round_trip(
    real_milvus_client: MilvusKbClient, mock_embedding: Any
) -> None:
    """插入 1 条 → search 应能查到."""
    row: dict[str, Any] = {
        "doc_id": "test_d1",
        "chunk_id": "test_d1::0",
        "chunk_index": 0,
        "chunk_text": "测试搜索用文本",
        "vector": [0.5] * EMBEDDING_DIM,
        "pub_date": "2024-01-01",
        "source_url": "http://example.com",
        "source_type": "research",
        "broker": "招商证券",
        "industry": "新能源",
        "rating": "买入",
        "target_price": 250.0,
        "analyst": "张三",
    }
    await real_milvus_client.insert(COLLECTION_RESEARCH, [row])
    # Milvus 默认 flush 后才能 search;pymilvus 2.4+ 自动 flush 但需要时间
    await asyncio.sleep(2)

    svc = MilvusKbSearchService(milvus=real_milvus_client, embedding_service=mock_embedding)
    hits = await svc.search(
        query="测试",
        collections=[COLLECTION_RESEARCH],
        top_k=5,
    )
    assert len(hits) >= 1
    assert hits[0].chunk_text == "测试搜索用文本"


async def test_multi_collection_route(
    real_milvus_client: MilvusKbClient, mock_embedding: Any
) -> None:
    """3 collection 各插 1 条,collections=None 时跨查应返回 3 条."""
    rows = {
        COLLECTION_RESEARCH: {
            "doc_id": "r1",
            "chunk_id": "r1::0",
            "chunk_index": 0,
            "chunk_text": "研报内容",
            "vector": [0.1] * EMBEDDING_DIM,
            "pub_date": "2024-01-01",
            "source_url": "",
            "source_type": "research",
            "broker": "招商",
            "industry": "新能源",
            "rating": "买入",
            "target_price": 0.0,
            "analyst": "",
        },
        COLLECTION_FINANCIAL: {
            "doc_id": "f1",
            "chunk_id": "f1::0",
            "chunk_index": 0,
            "chunk_text": "财报内容",
            "vector": [0.1] * EMBEDDING_DIM,
            "pub_date": "2024-01-01",
            "source_url": "",
            "source_type": "financial",
            "company_code": "600519",
            "company_name": "茅台",
            "fiscal_year": 2024,
            "fiscal_quarter": "Q3",
            "section": "管理层",
        },
        COLLECTION_POLICY: {
            "doc_id": "p1",
            "chunk_id": "p1::0",
            "chunk_index": 0,
            "chunk_text": "政策内容",
            "vector": [0.1] * EMBEDDING_DIM,
            "pub_date": "2024-01-01",
            "source_url": "",
            "source_type": "policy",
            "issuer": "证监会",
            "doc_number": "[2024]1号",
            "scope": "新能源",
        },
    }
    for coll, row in rows.items():
        await real_milvus_client.insert(coll, [row])
    await asyncio.sleep(2)

    svc = MilvusKbSearchService(milvus=real_milvus_client, embedding_service=mock_embedding)
    hits = await svc.search(query="x", collections=None, top_k=10)
    types = {h.metadata.get("source_type") for h in hits}
    assert {"research", "financial", "policy"} <= types


async def test_filter_expr_works(real_milvus_client: MilvusKbClient, mock_embedding: Any) -> None:
    """Insert 2 条 broker 不同的 research,filters={broker} 只返回匹配."""
    rows = [
        {
            "doc_id": "r1",
            "chunk_id": "r1::0",
            "chunk_index": 0,
            "chunk_text": "招商研报",
            "vector": [0.1] * EMBEDDING_DIM,
            "pub_date": "2024-06-01",
            "source_url": "",
            "source_type": "research",
            "broker": "招商证券",
            "industry": "新能源",
            "rating": "买入",
            "target_price": 0.0,
            "analyst": "",
        },
        {
            "doc_id": "r2",
            "chunk_id": "r2::0",
            "chunk_index": 0,
            "chunk_text": "中信研报",
            "vector": [0.1] * EMBEDDING_DIM,
            "pub_date": "2024-06-01",
            "source_url": "",
            "source_type": "research",
            "broker": "中信证券",
            "industry": "新能源",
            "rating": "买入",
            "target_price": 0.0,
            "analyst": "",
        },
    ]
    await real_milvus_client.insert(COLLECTION_RESEARCH, rows)
    await asyncio.sleep(2)

    svc = MilvusKbSearchService(milvus=real_milvus_client, embedding_service=mock_embedding)
    hits = await svc.search(
        query="x",
        collections=[COLLECTION_RESEARCH],
        top_k=10,
        filters={"broker": "招商证券"},
    )
    assert len(hits) >= 1
    assert all(h.metadata.get("broker") == "招商证券" for h in hits)

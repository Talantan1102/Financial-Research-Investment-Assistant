"""L0 — KbSearchService Protocol + MilvusKbSearchService(mock MilvusKbClient)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from app.services.kb_search_service import (
    KbHit,
    KbSearchService,
    MilvusKbSearchService,
)
from app.services.milvus_client import (
    COLLECTION_FINANCIAL,
    COLLECTION_POLICY,
    COLLECTION_RESEARCH,
)


def test_milvus_service_implements_protocol() -> None:
    fake_client = AsyncMock()
    fake_embedding = AsyncMock()
    svc = MilvusKbSearchService(milvus=fake_client, embedding_service=fake_embedding)
    assert isinstance(svc, KbSearchService)


@pytest.mark.asyncio
async def test_search_calls_embed_then_milvus() -> None:
    fake_client = AsyncMock()
    fake_client.search = AsyncMock(
        return_value=[
            {
                "chunk_id": "d1::0",
                "chunk_text": "找到",
                "doc_id": "d1",
                "distance": 0.05,
                "pub_date": "2024-01-01",
                "source_url": "u",
                "source_type": "research",
                "broker": "招商",
                "industry": "新能源",
                "rating": "买入",
                "target_price": 0.0,
                "analyst": "",
            }
        ]
    )

    fake_embedding = AsyncMock()
    fake_embedding.embed = AsyncMock(return_value=[[0.1] * 1024])

    svc = MilvusKbSearchService(milvus=fake_client, embedding_service=fake_embedding)
    hits = await svc.search(query="测试", collections=["kb_research"], top_k=5)

    fake_embedding.embed.assert_called_once_with(["测试"])
    fake_client.search.assert_called_once()
    assert len(hits) == 1
    assert isinstance(hits[0], KbHit)
    assert hits[0].chunk_text == "找到"
    assert hits[0].similarity == pytest.approx(0.95)  # 1 - 0.05 cosine distance


@pytest.mark.asyncio
async def test_search_default_collections_means_all_three() -> None:
    """collections=None 应跨 3 个 collection 并查并合并."""
    fake_client = AsyncMock()
    call_args_record = []

    async def fake_search(collection_name, **kw):
        call_args_record.append(collection_name)
        return [
            {
                "chunk_id": f"{collection_name}::0",
                "chunk_text": "x",
                "doc_id": "d",
                "distance": 0.1,
                "pub_date": "",
                "source_url": "",
                "source_type": collection_name.replace("kb_", ""),
            }
        ]

    fake_client.search = fake_search
    fake_embedding = AsyncMock()
    fake_embedding.embed = AsyncMock(return_value=[[0.1] * 1024])

    svc = MilvusKbSearchService(milvus=fake_client, embedding_service=fake_embedding)
    hits = await svc.search(query="x", collections=None, top_k=5)

    assert sorted(call_args_record) == sorted(
        [
            COLLECTION_RESEARCH,
            COLLECTION_FINANCIAL,
            COLLECTION_POLICY,
        ]
    )
    assert len(hits) == 3


@pytest.mark.asyncio
async def test_search_filters_translated_to_expr() -> None:
    """filters 字段转成 milvus expr."""
    fake_client = AsyncMock()
    captured_expr: dict = {}

    async def fake_search(collection_name, *, query_vector, top_k, expr, output_fields=None):
        captured_expr["expr"] = expr
        return []

    fake_client.search = fake_search
    fake_embedding = AsyncMock()
    fake_embedding.embed = AsyncMock(return_value=[[0.1] * 1024])

    svc = MilvusKbSearchService(milvus=fake_client, embedding_service=fake_embedding)
    await svc.search(
        query="x",
        collections=[COLLECTION_RESEARCH],
        top_k=5,
        filters={"broker": "招商证券", "pub_date_after": "2024-01-01"},
    )

    expr = captured_expr["expr"]
    assert 'broker == "招商证券"' in expr
    assert 'pub_date >= "2024-01-01"' in expr


@pytest.mark.asyncio
async def test_search_threshold_filters_low_similarity_hits() -> None:
    fake_client = AsyncMock()
    fake_client.search = AsyncMock(
        return_value=[
            {
                "chunk_id": "good",
                "chunk_text": "x",
                "doc_id": "d",
                "distance": 0.1,
                "pub_date": "",
                "source_url": "",
                "source_type": "research",
            },  # similarity = 0.9
            {
                "chunk_id": "bad",
                "chunk_text": "y",
                "doc_id": "d",
                "distance": 0.6,
                "pub_date": "",
                "source_url": "",
                "source_type": "research",
            },  # similarity = 0.4
        ]
    )

    fake_embedding = AsyncMock()
    fake_embedding.embed = AsyncMock(return_value=[[0.1] * 1024])

    svc = MilvusKbSearchService(milvus=fake_client, embedding_service=fake_embedding)
    hits = await svc.search(
        query="x",
        collections=[COLLECTION_RESEARCH],
        top_k=10,
        threshold=0.5,
    )

    assert len(hits) == 1
    assert hits[0].chunk_id == "good"


@pytest.mark.asyncio
async def test_search_unknown_filter_field_raises() -> None:
    """filters 字段必须在白名单(spec 节 5)."""
    fake_client = AsyncMock()
    fake_embedding = AsyncMock()
    fake_embedding.embed = AsyncMock(return_value=[[0.1] * 1024])
    svc = MilvusKbSearchService(milvus=fake_client, embedding_service=fake_embedding)

    with pytest.raises(ValueError, match="not in filter whitelist"):
        await svc.search(
            query="x",
            collections=[COLLECTION_RESEARCH],
            top_k=5,
            filters={"random_attr": "foo"},
        )

"""L0 — MilvusClient wrapper(mock pymilvus.MilvusClient)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from app.services.milvus_client import (
    COLLECTION_FINANCIAL,
    COLLECTION_POLICY,
    COLLECTION_RESEARCH,
    EMBEDDING_DIM,
    MilvusKbClient,
    schema_for,
)


def test_collection_names_are_constants() -> None:
    assert COLLECTION_RESEARCH == "kb_research"
    assert COLLECTION_FINANCIAL == "kb_financial"
    assert COLLECTION_POLICY == "kb_policy"
    assert EMBEDDING_DIM == 1024


def test_schema_for_research_includes_broker() -> None:
    schema = schema_for(COLLECTION_RESEARCH)
    field_names = [f.name for f in schema.fields]
    # 公共字段
    assert "doc_id" in field_names
    assert "chunk_id" in field_names
    assert "chunk_text" in field_names
    assert "vector" in field_names
    assert "pub_date" in field_names
    # 类型特定
    assert "broker" in field_names
    assert "industry" in field_names
    assert "rating" in field_names
    assert "target_price" in field_names
    assert "analyst" in field_names


def test_schema_for_financial_includes_company_code() -> None:
    schema = schema_for(COLLECTION_FINANCIAL)
    field_names = [f.name for f in schema.fields]
    assert "company_code" in field_names
    assert "fiscal_year" in field_names
    assert "fiscal_quarter" in field_names
    assert "section" in field_names


def test_schema_for_policy_includes_issuer() -> None:
    schema = schema_for(COLLECTION_POLICY)
    field_names = [f.name for f in schema.fields]
    assert "issuer" in field_names
    assert "doc_number" in field_names
    assert "scope" in field_names


def test_schema_for_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unknown collection"):
        schema_for("kb_bogus")


@pytest.mark.asyncio
async def test_client_ensures_collections_only_creates_missing() -> None:
    """ensure_collections 调用 has_collection / create_collection / create_index."""
    fake_pymilvus = MagicMock()
    # 一开始全部不存在
    fake_pymilvus.has_collection.side_effect = [False, False, False]

    with patch("app.services.milvus_client.MilvusClient", return_value=fake_pymilvus):
        client = MilvusKbClient(host="127.0.0.1", port=19530)
        await client.ensure_collections()

    assert fake_pymilvus.has_collection.call_count == 3
    assert fake_pymilvus.create_collection.call_count == 3
    assert fake_pymilvus.create_index.call_count == 3


@pytest.mark.asyncio
async def test_client_insert_calls_pymilvus() -> None:
    fake = MagicMock()
    with patch("app.services.milvus_client.MilvusClient", return_value=fake):
        client = MilvusKbClient(host="127.0.0.1", port=19530)
        await client.insert(
            COLLECTION_RESEARCH,
            [
                {
                    "doc_id": "d1",
                    "chunk_id": "d1::0",
                    "chunk_index": 0,
                    "chunk_text": "test",
                    "vector": [0.1] * EMBEDDING_DIM,
                    "pub_date": "2024-01-01",
                    "source_url": "http://example.com",
                    "source_type": "research",
                    "broker": "招商证券",
                    "industry": "新能源",
                    "rating": "买入",
                    "target_price": 250.0,
                    "analyst": "张三",
                }
            ],
        )

    fake.insert.assert_called_once()
    args, kwargs = fake.insert.call_args
    assert kwargs.get("collection_name") == COLLECTION_RESEARCH or args[0] == COLLECTION_RESEARCH


@pytest.mark.asyncio
async def test_client_search_returns_hits() -> None:
    fake = MagicMock()
    fake.search.return_value = [
        [
            {
                "id": "d1::0",
                "distance": 0.123,
                "entity": {
                    "doc_id": "d1",
                    "chunk_id": "d1::0",
                    "chunk_text": "找到的文本",
                    "pub_date": "2024-01-01",
                    "source_url": "http://e.com",
                    "source_type": "research",
                    "broker": "招商证券",
                    "industry": "新能源",
                    "rating": "买入",
                    "target_price": 250.0,
                    "analyst": "张三",
                },
            }
        ]
    ]
    with patch("app.services.milvus_client.MilvusClient", return_value=fake):
        client = MilvusKbClient(host="127.0.0.1", port=19530)
        results = await client.search(
            COLLECTION_RESEARCH,
            query_vector=[0.1] * EMBEDDING_DIM,
            top_k=5,
            expr=None,
        )

    assert len(results) == 1
    assert results[0]["chunk_text"] == "找到的文本"
    assert results[0]["distance"] == pytest.approx(0.123)

"""L2 e2e — 真 Milvus 容器 + 真 qwen embedding API(cassette)."""

from __future__ import annotations

from typing import Any

import pytest
from app.services.kb_factory import build_kb_search_service_from_env

pytestmark = pytest.mark.vcr


@pytest.fixture
async def real_kb_service(
    milvus_test_container: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("KB_MODE", "real")
    monkeypatch.setenv("EMBEDDING_MODE", "qwen")
    monkeypatch.setenv("MILVUS_HOST", str(milvus_test_container["host"]))
    monkeypatch.setenv("MILVUS_PORT", str(milvus_test_container["port"]))
    return build_kb_search_service_from_env()


@pytest.fixture(autouse=True)
async def seed_milvus(milvus_test_container: dict[str, Any]) -> None:
    import asyncio

    from app.services.milvus_client import COLLECTION_RESEARCH, EMBEDDING_DIM, MilvusKbClient

    client = MilvusKbClient(
        host=str(milvus_test_container["host"]),
        port=int(milvus_test_container["port"]),
    )
    await client.drop_all()
    await client.ensure_collections()
    row = {
        "doc_id": "seed_d1",
        "chunk_id": "seed_d1::0",
        "chunk_index": 0,
        "chunk_text": "招商证券对宁德时代未来 5 年新能源车业务展望乐观,给予买入评级",
        "vector": [0.1] * EMBEDDING_DIM,
        "pub_date": "2024-06-15",
        "source_url": "http://e.com",
        "source_type": "research",
        "broker": "招商证券",
        "industry": "新能源",
        "rating": "买入",
        "target_price": 250.0,
        "analyst": "张三",
    }
    await client.insert(COLLECTION_RESEARCH, [row])
    await asyncio.sleep(2)


@pytest.mark.asyncio
async def test_kb_search_e2e_cassette(real_kb_service: Any) -> None:
    """全链路:真 Milvus + 真 qwen embedding(cassette replay)."""
    hits = await real_kb_service.search(
        query="新能源车展望",
        collections=["kb_research"],
        top_k=5,
    )
    assert len(hits) >= 1
    assert "宁德" in hits[0].chunk_text or "新能源" in hits[0].chunk_text


@pytest.mark.asyncio
async def test_kb_search_filter_e2e_cassette(real_kb_service: Any) -> None:
    """带 broker filter 的全链路."""
    hits = await real_kb_service.search(
        query="新能源",
        collections=["kb_research"],
        top_k=5,
        filters={"broker": "招商证券"},
    )
    assert all(h.metadata.get("broker") == "招商证券" for h in hits)

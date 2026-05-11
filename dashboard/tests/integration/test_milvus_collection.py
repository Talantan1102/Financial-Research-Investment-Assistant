"""Milvus collection — 真 Milvus fixture(若起 docker compose milvus)。Plan 1 Task 8。"""

from __future__ import annotations

import os

import pytest

from dashboard.derive.deep_card_types import DeepCard
from dashboard.state.milvus_collection import embedding_text

milvus_skip = pytest.mark.skipif(
    os.getenv("MILVUS_HOST") is None,
    reason="real Milvus integration; set MILVUS_HOST=localhost MILVUS_PORT=19530",
)


def test_embedding_text_combines_fields() -> None:
    c = DeepCard(
        cap_id="x",
        what="LLM 输出 schema",
        why="避免下游解析失败",
        tradeoff="选 schema 因为兼容协议支持",
    )
    text = embedding_text(c, name_cn="输出 Schema 约束")
    assert "输出 Schema 约束" in text
    assert "LLM 输出 schema" in text
    assert "避免下游解析失败" in text
    assert "选 schema" in text


def test_embedding_text_skips_empty_fields() -> None:
    c = DeepCard(cap_id="x", what="only what")
    text = embedding_text(c, name_cn="N")
    assert "only what" in text
    assert "\n\n\n" not in text


@milvus_skip
@pytest.mark.asyncio
async def test_milvus_upsert_and_search() -> None:
    """需启动真 Milvus + EMBEDDING_MODE=real qwen API key。"""
    from app.services.embedding_factory import build_embedding_service_from_env

    from dashboard.state.milvus_collection import DeepCardMilvusClient

    client = DeepCardMilvusClient(
        host=os.environ["MILVUS_HOST"],
        port=int(os.getenv("MILVUS_PORT", "19530")),
    )
    embedder = build_embedding_service_from_env()
    await client.ensure_collection()
    c = DeepCard(cap_id="test.1", what="LangGraph supervisor")
    vec = (await embedder.embed([embedding_text(c, name_cn="T")]))[0]
    await client.upsert(
        [
            {
                "cap_id": c.cap_id,
                "embedding": vec,
                "dimension": "03",
                "name_cn": "T",
                "status": "lit",
                "confidence": 0,
            }
        ]
    )
    results = await client.search(vec, top_k=1)
    assert len(results) >= 1
    assert results[0]["cap_id"] == "test.1"
    await client.delete("test.1")

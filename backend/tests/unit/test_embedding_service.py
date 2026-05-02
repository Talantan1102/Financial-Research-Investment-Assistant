"""L0 — EmbeddingService Protocol + QwenEmbeddingService + BGE stub."""

from __future__ import annotations

from typing import Any

import pytest
from app.services.embedding_service import (
    BGEEmbeddingService,
    EmbeddingService,
    QwenEmbeddingService,
)


def test_qwen_implements_protocol() -> None:
    svc = QwenEmbeddingService(api_key="sk-test")
    # Protocol 检查:有 embed / dimension / model_name
    assert isinstance(svc, EmbeddingService)
    assert svc.dimension == 1024
    assert svc.model_name == "text-embedding-v3"


def test_bge_stub_raises_not_implemented() -> None:
    """BGE local backend is v0.9+; v0.7 只占位,call embed 必须 raise."""
    svc = BGEEmbeddingService()
    assert svc.dimension == 1024
    assert svc.model_name == "BAAI/bge-m3"
    with pytest.raises(NotImplementedError, match="v0.9"):
        import asyncio

        asyncio.run(svc.embed(["test"]))


@pytest.mark.asyncio
async def test_qwen_embed_calls_dashscope_and_returns_vectors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mock dashscope.TextEmbedding.call;verify batching + vector return."""
    fake_response = type(
        "Resp",
        (),
        {
            "status_code": 200,
            "output": {
                "embeddings": [
                    {"embedding": [0.1] * 1024, "text_index": 0},
                    {"embedding": [0.2] * 1024, "text_index": 1},
                ]
            },
            "usage": {"total_tokens": 10},
        },
    )()

    monkeypatch.setattr("dashscope.TextEmbedding.call", lambda **kw: fake_response)

    svc = QwenEmbeddingService(api_key="sk-test")
    vectors = await svc.embed(["text 1", "text 2"])

    assert len(vectors) == 2
    assert all(len(v) == 1024 for v in vectors)
    assert vectors[0][0] == pytest.approx(0.1)
    assert vectors[1][0] == pytest.approx(0.2)


@pytest.mark.asyncio
async def test_qwen_embed_batches_at_10(monkeypatch: pytest.MonkeyPatch) -> None:
    """qwen API max batch = 10(Spike 5 实测,文档说 25 但 11+ 被拒);> 10 inputs 应自动切批."""
    call_count = 0

    def fake_call(*, model: str, input: list[str], dimension: int, **kw: Any) -> Any:
        nonlocal call_count
        call_count += 1
        # 验证每次 batch ≤ 10
        assert len(input) <= 10
        return type(
            "Resp",
            (),
            {
                "status_code": 200,
                "output": {
                    "embeddings": [
                        {"embedding": [float(i) / 100] * dimension, "text_index": i}
                        for i in range(len(input))
                    ]
                },
                "usage": {"total_tokens": 5 * len(input)},
            },
        )()

    monkeypatch.setattr("dashscope.TextEmbedding.call", fake_call)

    svc = QwenEmbeddingService(api_key="sk-test")
    texts = [f"text {i}" for i in range(25)]  # 25 inputs → 3 batches(10 + 10 + 5)
    vectors = await svc.embed(texts)

    assert len(vectors) == 25
    assert call_count == 3


@pytest.mark.asyncio
async def test_qwen_embed_raises_on_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """status_code != 200 raise."""
    bad_resp = type(
        "Resp",
        (),
        {"status_code": 401, "output": None, "message": "invalid key", "usage": {}},
    )()
    monkeypatch.setattr("dashscope.TextEmbedding.call", lambda **kw: bad_resp)

    svc = QwenEmbeddingService(api_key="sk-bad")
    with pytest.raises(RuntimeError, match="dashscope.*401"):
        await svc.embed(["text"])

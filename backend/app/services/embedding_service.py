"""EmbeddingService Protocol + Qwen API impl + BGE-M3 local stub.

设计动机参照 spec docs/superpowers/specs/2026-05-02-v0.7-kb-search-milvus-design.md 节 6:
  - Protocol-based dispatch,build via factory(EMBEDDING_MODE switch)
  - v0.7 default = qwen(text-embedding-v3, 1024 dim)
  - v0.9+ 切 BGE-M3(1024 dim)— 同维,无需改 Milvus collection schema
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Protocol, runtime_checkable

import dashscope

_QWEN_MAX_BATCH = 10  # Spike 5 实测限制(API 文档说 25 但 11+ 被拒)


@runtime_checkable
class EmbeddingService(Protocol):
    """Embedding backend Protocol;通过 EMBEDDING_MODE 切换."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed batch of texts to vectors. caller 应保证 texts 非空."""
        ...

    @property
    def dimension(self) -> int:
        """Vector dimension(qwen 1024, BGE-M3 1024)."""
        ...

    @property
    def model_name(self) -> str:
        """Backend model identifier."""
        ...


class QwenEmbeddingService:
    """Dashscope text-embedding-v3 backend(v0.7 default).

    复用 LLMService 的 dashscope 凭证 / RateLimiter / CostBudget(call 走 dashscope SDK,
    reliability 通过 LLMService 内部 wrap;若直接调 SDK 这里复用就缺失 — 让
    `embedding_factory.build_embedding_service_from_env` 走 LLMService injection 路径).
    """

    dimension = 1024
    model_name = "text-embedding-v3"

    def __init__(self, api_key: str, *, base_url: str | None = None) -> None:
        self._api_key = api_key
        self._base_url = base_url
        dashscope.api_key = api_key
        if base_url:
            dashscope.base_http_api_url = base_url

    async def _call_api(self, batch: list[str]) -> Any:
        """Call dashscope.TextEmbedding.call, supporting both sync SDK and AsyncMock in tests."""
        result = await asyncio.to_thread(
            dashscope.TextEmbedding.call,
            model=self.model_name,
            input=batch,
            dimension=self.dimension,
        )
        # AsyncMock (used in tests) returns a coroutine when called in to_thread;
        # real dashscope SDK returns a plain response object.
        if inspect.iscoroutine(result):
            result = await result
        return result

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        out: list[list[float]] = []
        for i in range(0, len(texts), _QWEN_MAX_BATCH):
            batch = texts[i : i + _QWEN_MAX_BATCH]
            resp = await self._call_api(batch)
            if resp.status_code != 200:
                raise RuntimeError(
                    f"dashscope embed failed: {resp.status_code} {getattr(resp, 'message', '')}"
                )
            embeddings = resp.output["embeddings"]
            embeddings.sort(key=lambda x: x.get("text_index", 0))
            out.extend(e["embedding"] for e in embeddings)
        return out


class BGEEmbeddingService:
    """BGE-M3 本地部署 stub — v0.9+ 真实现.

    保留这个 class 是为了让 `EMBEDDING_MODE=bge_local` 在 factory 里能 import 到一个类型,
    实际调用 raise NotImplementedError 提示走 v0.9+ spec。
    """

    dimension = 1024
    model_name = "BAAI/bge-m3"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError(
            "BGE-M3 local backend is v0.9+ feature; "
            "see docs/superpowers/specs/2026-05-02-v0.7-kb-search-milvus-design.md 节 6"
        )

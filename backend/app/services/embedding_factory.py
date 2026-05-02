"""build_embedding_service_from_env — EMBEDDING_MODE switch."""

from __future__ import annotations

import os

from app.services.embedding_service import (
    BGEEmbeddingService,
    EmbeddingService,
    QwenEmbeddingService,
)


def build_embedding_service_from_env() -> EmbeddingService:
    """Build EmbeddingService based on EMBEDDING_MODE env var.

    EMBEDDING_MODE values:
      - "qwen"(default): dashscope text-embedding-v3
      - "bge_local": BGE-M3 本地(v0.9+ feature, raise on use)

    需要 DASHSCOPE_API_KEY env var(qwen mode)。
    """
    mode = os.getenv("EMBEDDING_MODE", "qwen")
    if mode == "qwen":
        api_key = os.environ.get("DASHSCOPE_API_KEY")
        if not api_key:
            raise RuntimeError("EMBEDDING_MODE=qwen requires DASHSCOPE_API_KEY env var")
        base_url = os.environ.get("DASHSCOPE_BASE_URL")
        return QwenEmbeddingService(api_key=api_key, base_url=base_url)
    if mode == "bge_local":
        return BGEEmbeddingService()
    raise ValueError(f"Unknown EMBEDDING_MODE: {mode!r}; expected 'qwen' or 'bge_local'")

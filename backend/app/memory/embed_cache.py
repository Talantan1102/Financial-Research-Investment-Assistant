"""Embedding cache(spec § 4 优化 #5)— per-user keyed Redis hash.

契约 § 9 / § 17 A2-3 强制 per-user:防止"用户 A 跟用户 B 共享 embed"导致语义污染.
qwen text-embedding-v3 输出 1024d float vector,JSON 序列化压缩存 Redis.

Key 格式: memory:embed:{user_id}:{sha1(text)[:16]}
TTL: 默认 24h(86_400 s).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID


class EmbedCache:
    """Per-user keyed embedding cache(契约 § 9 / § 17 A2-3 final 3 参数版本).

    Key 格式: ``memory:embed:{user_id}:{sha1(text)[:16]}``
    TTL: 默认 24h(spec § 4 优化 #5).
    """

    def __init__(self, redis_client: Any, ttl_seconds: int = 86_400) -> None:
        self._redis = redis_client
        self._ttl = ttl_seconds

    def _cache_key(self, text: str, user_id: UUID) -> str:
        h = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
        return f"memory:embed:{user_id}:{h}"

    async def get_or_compute(
        self,
        text: str,
        user_id: UUID,
        compute_fn: Callable[[], Awaitable[list[float]]],
    ) -> list[float]:
        """Hit → return cached vector;miss → compute_fn() → setex → return.

        per-user keyed (防 cross-user embed 污染).
        contract § 17 A2 (3) final 3 参数版本.
        """
        key = self._cache_key(text, user_id)
        raw = self._redis.get(key)
        if raw is not None:
            return list(json.loads(raw))

        vec = await compute_fn()
        self._redis.setex(key, self._ttl, json.dumps(vec))
        return list(vec)

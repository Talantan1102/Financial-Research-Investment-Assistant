"""ReliableKbSearchService — retry + TTLCache + cache_hit metric.

Wraps any KbSearchService;preserves Protocol。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Any

from cachetools import TTLCache

from app.services.kb_search_service import KbHit, KbSearchService

logger = logging.getLogger(__name__)


class ReliableKbSearchService:
    """Retry + LRU(TTLCache)wrapper around an inner KbSearchService."""

    def __init__(
        self,
        *,
        inner: KbSearchService,
        cache_size: int = 1000,
        cache_ttl: int = 3600,
        max_retries: int = 3,
        backoff_base: float = 0.5,
    ) -> None:
        self._inner = inner
        self._cache: TTLCache = TTLCache(maxsize=cache_size, ttl=cache_ttl)
        self._max_retries = max_retries
        self._backoff_base = backoff_base

    async def search(
        self,
        query: str,
        collections: list[str] | None = None,
        top_k: int = 5,
        threshold: float | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[KbHit]:
        cache_key = self._make_cache_key(query, collections, top_k, threshold, filters)
        if cache_key in self._cache:
            logger.info(
                "kb_cache_hit query_hash=%s collections=%s",
                cache_key[:8],
                collections,
            )
            return self._cache[cache_key]

        logger.info(
            "kb_cache_miss query_hash=%s collections=%s",
            cache_key[:8],
            collections,
        )

        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                result = await self._inner.search(
                    query=query,
                    collections=collections,
                    top_k=top_k,
                    threshold=threshold,
                    filters=filters,
                )
                self._cache[cache_key] = result
                return result
            except Exception as e:  # noqa: BLE001
                last_exc = e
                if attempt < self._max_retries - 1:
                    backoff = self._backoff_base * (2**attempt)
                    logger.warning(
                        "kb_search_retry attempt=%d backoff=%.2fs error=%s",
                        attempt + 1,
                        backoff,
                        e,
                    )
                    await asyncio.sleep(backoff)
        assert last_exc is not None
        raise last_exc

    @staticmethod
    def _make_cache_key(
        query: str,
        collections: list[str] | None,
        top_k: int,
        threshold: float | None,
        filters: dict[str, Any] | None,
    ) -> str:
        payload = json.dumps(
            {
                "q": query,
                "c": sorted(collections) if collections else None,
                "k": top_k,
                "t": threshold,
                "f": dict(sorted(filters.items())) if filters else None,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

"""L0 — ReliableKbSearchService:retry + TTLCache + metric."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from app.services.kb_search_service import KbHit
from app.services.reliable_kb_service import ReliableKbSearchService


@pytest.mark.asyncio
async def test_cache_hit_skips_inner() -> None:
    inner = AsyncMock()
    hit = KbHit(
        chunk_id="d1::0",
        chunk_text="x",
        similarity=0.9,
        metadata={"doc_id": "d1", "source_type": "research"},
    )
    inner.search = AsyncMock(return_value=[hit])

    rel = ReliableKbSearchService(inner=inner, cache_size=10, cache_ttl=60)

    h1 = await rel.search(query="同样问题", collections=["kb_research"], top_k=5)
    h2 = await rel.search(query="同样问题", collections=["kb_research"], top_k=5)

    assert h1 == h2
    assert inner.search.call_count == 1  # 第二次命中 cache,inner 没再调


@pytest.mark.asyncio
async def test_retry_on_transient_error() -> None:
    inner = AsyncMock()
    call_count = {"n": 0}

    async def flaky_search(**kw):
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise ConnectionError("transient milvus down")
        return [KbHit(chunk_id="x", chunk_text="ok", similarity=1.0, metadata={"source_type": "x"})]

    inner.search = flaky_search

    rel = ReliableKbSearchService(inner=inner, max_retries=3, backoff_base=0.01)
    hits = await rel.search(query="x", collections=None, top_k=5)

    assert call_count["n"] == 3  # 2 fails + 1 success
    assert len(hits) == 1


@pytest.mark.asyncio
async def test_retry_exhausted_raises() -> None:
    inner = AsyncMock()
    inner.search = AsyncMock(side_effect=ConnectionError("milvus down"))

    rel = ReliableKbSearchService(inner=inner, max_retries=3, backoff_base=0.01)
    with pytest.raises(ConnectionError):
        await rel.search(query="x", collections=None, top_k=5)
    assert inner.search.call_count == 3


@pytest.mark.asyncio
async def test_metric_emit_on_hit_and_miss(caplog: pytest.LogCaptureFixture) -> None:
    """cache hit / miss 各自 log 一条 metric line(简单 stdout / log,无外部 metric backend)."""
    import logging

    inner = AsyncMock()
    inner.search = AsyncMock(
        return_value=[
            KbHit(chunk_id="x", chunk_text="ok", similarity=1.0, metadata={"source_type": "x"})
        ]
    )

    rel = ReliableKbSearchService(inner=inner, cache_size=10, cache_ttl=60)

    with caplog.at_level(logging.INFO, logger="app.services.reliable_kb_service"):
        await rel.search(query="q", collections=None, top_k=5)
        await rel.search(query="q", collections=None, top_k=5)

    miss_logs = [r for r in caplog.records if "kb_cache_miss" in r.getMessage()]
    hit_logs = [r for r in caplog.records if "kb_cache_hit" in r.getMessage()]
    assert len(miss_logs) == 1
    assert len(hit_logs) == 1

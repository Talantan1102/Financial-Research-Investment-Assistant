"""L0 — ChunkEmbedCache sqlite vector cache."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.kb.ingest.cache import ChunkEmbedCache


@pytest.mark.asyncio
async def test_cache_miss_returns_none(tmp_path: Path) -> None:
    cache = ChunkEmbedCache(db_path=tmp_path / ".embed_cache.sqlite")
    await cache.init()
    assert await cache.get("text", "model_x", 1024) is None


@pytest.mark.asyncio
async def test_cache_set_and_get(tmp_path: Path) -> None:
    cache = ChunkEmbedCache(db_path=tmp_path / ".embed_cache.sqlite")
    await cache.init()

    vector = [0.1, 0.2, 0.3, 0.4]
    await cache.set("某段文本", "qwen-v3", 4, vector)

    got = await cache.get("某段文本", "qwen-v3", 4)
    assert got is not None
    assert got == pytest.approx(vector)


@pytest.mark.asyncio
async def test_cache_key_includes_model_and_dimension(tmp_path: Path) -> None:
    """同 text 不同 model / dim → 不同 cache 项."""
    cache = ChunkEmbedCache(db_path=tmp_path / ".embed_cache.sqlite")
    await cache.init()
    await cache.set("text", "qwen-v3", 1024, [0.1] * 1024)

    # 不同 model — miss
    assert await cache.get("text", "bge-m3", 1024) is None
    # 不同 dim — miss(plan bug fix:原写 1024,改 512 真测试不同 dim)
    assert await cache.get("text", "qwen-v3", 512) is None
    # 完全匹配 — hit
    got = await cache.get("text", "qwen-v3", 1024)
    assert got is not None


@pytest.mark.asyncio
async def test_cache_hit_rate(tmp_path: Path) -> None:
    cache = ChunkEmbedCache(db_path=tmp_path / ".embed_cache.sqlite")
    await cache.init()
    await cache.set("a", "m", 4, [0.1] * 4)

    await cache.get("a", "m", 4)  # hit
    await cache.get("b", "m", 4)  # miss
    await cache.get("a", "m", 4)  # hit

    stats = cache.stats
    assert stats["hits"] == 2
    assert stats["misses"] == 1

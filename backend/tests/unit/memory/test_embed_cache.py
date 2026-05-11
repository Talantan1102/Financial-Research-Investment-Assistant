"""L0 — EmbedCache per-user keyed(spec § 4 优化 #5,契约 § 9 / § 17 A2-3).

3 参数版本: get_or_compute(text, user_id, compute_fn).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.memory.embed_cache import EmbedCache


class FakeRedis:
    """In-memory Redis stub. setex 模拟 TTL(测试不真等)."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.calls: list[str] = []

    def get(self, key: str) -> str | None:
        self.calls.append(f"GET {key}")
        return self.store.get(key)

    def setex(self, key: str, ttl: int, value: str) -> bool:
        self.calls.append(f"SETEX {key} {ttl}")
        self.store[key] = value
        return True


@pytest.fixture
def redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def cache(redis: FakeRedis) -> EmbedCache:
    return EmbedCache(redis_client=redis, ttl_seconds=86_400)


@pytest.mark.asyncio
async def test_miss_then_compute_then_hit(cache: EmbedCache) -> None:
    user_id = uuid4()
    counter = {"calls": 0}

    async def compute() -> list[float]:
        counter["calls"] += 1
        return [0.1] * 1024

    v1 = await cache.get_or_compute("茅台估值", user_id, compute)
    v2 = await cache.get_or_compute("茅台估值", user_id, compute)

    assert v1 == [0.1] * 1024
    assert v2 == [0.1] * 1024
    assert counter["calls"] == 1, "second call must hit cache"


@pytest.mark.asyncio
async def test_per_user_isolation(cache: EmbedCache) -> None:
    """契约 § 9: 同 text 不同 user → 不同 cache key, 防 cross-user 污染."""
    u1 = uuid4()
    u2 = uuid4()
    counter = {"calls": 0}

    async def compute() -> list[float]:
        counter["calls"] += 1
        return [float(counter["calls"])] * 4

    v_u1 = await cache.get_or_compute("茅台", u1, compute)
    v_u2 = await cache.get_or_compute("茅台", u2, compute)

    assert v_u1 != v_u2, "different users must NOT share embed cache"
    assert counter["calls"] == 2


def test_cache_key_format(cache: EmbedCache) -> None:
    """key=memory:embed:{user_id}:{sha1(text)[:16]}(契约 § 9 强制格式)."""
    user_id = uuid4()
    key = cache._cache_key("茅台估值", user_id)
    assert key.startswith(f"memory:embed:{user_id}:")
    suffix = key.split(":")[-1]
    assert len(suffix) == 16


@pytest.mark.asyncio
async def test_setex_called_with_ttl(redis: FakeRedis) -> None:
    """miss 路径必须 setex 写库 + 带 TTL."""
    cache = EmbedCache(redis_client=redis, ttl_seconds=42)
    user_id = uuid4()

    async def compute() -> list[float]:
        return [0.5] * 8

    await cache.get_or_compute("a", user_id, compute)
    assert any("SETEX" in c and " 42" in c for c in redis.calls)


@pytest.mark.asyncio
async def test_same_text_same_user_returns_cached_vector_value(redis: FakeRedis) -> None:
    """第二次 hit 时 vec 来自 cache, 跟 compute_fn 第一次返回值一致."""
    cache = EmbedCache(redis_client=redis)
    user_id = uuid4()
    sequence = iter([[1.0, 2.0, 3.0], [9.9, 9.9, 9.9]])  # 第二次 compute 不应被调

    async def compute() -> list[float]:
        return next(sequence)

    v1 = await cache.get_or_compute("t", user_id, compute)
    v2 = await cache.get_or_compute("t", user_id, compute)
    assert v1 == [1.0, 2.0, 3.0]
    assert v2 == [1.0, 2.0, 3.0], "hit cache 必须返回第一次 compute 值, 不调 compute_fn"

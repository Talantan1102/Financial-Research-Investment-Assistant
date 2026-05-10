"""L0 — @with_prompt_cache decorator(spec § 4 优化 #1, 契约 § 9 key 命名)."""

from __future__ import annotations

import pytest
from app.memory.prompt_cache import PromptCacheStore, with_prompt_cache


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def setex(self, key: str, ttl: int, value: str) -> bool:
        self.store[key] = value
        return True


@pytest.fixture
def store() -> PromptCacheStore:
    return PromptCacheStore(redis_client=FakeRedis(), default_ttl=300)


def test_key_format(store: PromptCacheStore) -> None:
    """契约 § 9: key=memory:prompt_cache:{name}:v1:..."""
    key = store._key(name="extraction", system_prompt="abc", model="qwen-plus")
    assert key.startswith("memory:prompt_cache:extraction:v1:")


def test_key_includes_sha_suffix(store: PromptCacheStore) -> None:
    """key 末段 sha1[:16] 16 char."""
    key = store._key(name="judge", system_prompt="abc", model="qwen-plus")
    suffix = key.split(":")[-1]
    assert len(suffix) == 16


@pytest.mark.asyncio
async def test_decorator_caches_system_prompt(store: PromptCacheStore) -> None:
    """同一 system_prompt + model 第二次调用走 cache(LLM 不再调)."""
    counter = {"calls": 0}

    @with_prompt_cache(store=store, name="extraction")
    async def call_llm(*, system_prompt: str, user_prompt: str, model: str) -> str:
        counter["calls"] += 1
        return f"reply:{user_prompt}"

    r1 = await call_llm(system_prompt="SYS", user_prompt="U1", model="qwen-plus")
    r2 = await call_llm(system_prompt="SYS", user_prompt="U2", model="qwen-plus")

    # user prompt 不同必须真调 LLM, 但 system 部分 mark cached
    assert counter["calls"] == 2
    assert r1.startswith("reply:")
    assert r2.startswith("reply:")
    # 第二次调用必须命中 system cache mark
    assert store.is_cached(name="extraction", system_prompt="SYS", model="qwen-plus")


@pytest.mark.asyncio
async def test_different_system_prompt_separate_cache(store: PromptCacheStore) -> None:
    @with_prompt_cache(store=store, name="extraction")
    async def call_llm(*, system_prompt: str, user_prompt: str, model: str) -> str:
        return "ok"

    await call_llm(system_prompt="SYS_A", user_prompt="x", model="qwen-plus")
    await call_llm(system_prompt="SYS_B", user_prompt="x", model="qwen-plus")
    assert store.is_cached(name="extraction", system_prompt="SYS_A", model="qwen-plus")
    assert store.is_cached(name="extraction", system_prompt="SYS_B", model="qwen-plus")
    k_a = store._key(name="extraction", system_prompt="SYS_A", model="qwen-plus")
    k_b = store._key(name="extraction", system_prompt="SYS_B", model="qwen-plus")
    assert k_a != k_b


def test_is_cached_default_false(store: PromptCacheStore) -> None:
    """未 mark 过的 prompt is_cached() 必须 False."""
    assert not store.is_cached(name="extraction", system_prompt="UNKNOWN", model="qwen-plus")


def test_mark_used_persists(store: PromptCacheStore) -> None:
    store.mark_used(name="judge", system_prompt="X", model="qwen-plus")
    assert store.is_cached(name="judge", system_prompt="X", model="qwen-plus")

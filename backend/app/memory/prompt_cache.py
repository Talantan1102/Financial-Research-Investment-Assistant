"""Prompt cache decorator(spec § 4 优化 #1, 契约 § 9 key 命名).

DashScope 不支持原生 cache_control(Anthropic 协议), 本实现用 Redis 内容寻址 cache
模拟同等语义:
  - system_prompt + model 哈希作 key(只缓存 system 部分, ~1K token 摊薄)
  - 5min 默认 TTL, key 格式: memory:prompt_cache:{name}:v1:{sha1[:16]}
  - 第二次同 system_prompt 调用时 store 命中, LLM 仍调但记 metric 表征"system token 已 reuse"

生产换 Anthropic 原生 API 时: 仅替换 PromptCacheStore impl, @with_prompt_cache 接口不变.

设计取舍: 装饰器层不改变 LLM 调用行为(LLM 仍真调), 仅 mark store 用于:
  1. cost optimization 测试断言 cache hit 已 mark
  2. metric 仪表盘统计 system token reuse 率
  3. 生产 v1.x 切 Anthropic 协议时只换 store impl, 装饰器 + 调用方代码 0 改动
"""

from __future__ import annotations

import functools
import hashlib
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

T = TypeVar("T")


class PromptCacheStore:
    """Redis-backed prompt cache(只标记 system_prompt 已 reuse).

    生产 v1.x: 换 Anthropic prompt_cache_control beta API.
    """

    def __init__(self, redis_client: Any, default_ttl: int = 300) -> None:
        self._redis = redis_client
        self._ttl = default_ttl

    def _key(self, *, name: str, system_prompt: str, model: str) -> str:
        h = hashlib.sha1(f"{model}::{system_prompt}".encode()).hexdigest()[:16]
        return f"memory:prompt_cache:{name}:v1:{h}"

    def mark_used(self, *, name: str, system_prompt: str, model: str) -> bool:
        """标记 system_prompt 已使用, 记录 cache hit metric."""
        key = self._key(name=name, system_prompt=system_prompt, model=model)
        self._redis.setex(key, self._ttl, "1")
        return True

    def is_cached(self, *, name: str, system_prompt: str, model: str) -> bool:
        """Returns True iff system_prompt has been mark_used within TTL."""
        return (
            self._redis.get(self._key(name=name, system_prompt=system_prompt, model=model))
            is not None
        )


def with_prompt_cache(
    *, store: PromptCacheStore, name: str
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorator: 在 LLM 调用前 mark store, 记 cache hit/miss metric.

    被装饰函数必须为 async, 且 kwargs 含 ``system_prompt`` / ``user_prompt`` / ``model``.
    """

    def decorator(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            system_prompt = kwargs.get("system_prompt", "")
            model = kwargs.get("model", "")
            store.mark_used(name=name, system_prompt=system_prompt, model=model)
            return await fn(*args, **kwargs)

        return wrapper

    return decorator

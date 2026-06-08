"""L0/L1 — ToolResultCache."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio  # noqa: F401 — registers asyncio mode
from app.services.tool_result_cache import (
    DEFAULT_TTL_BY_TOOL,
    CacheHit,
    ToolResultCache,
)


def test_default_ttl_per_tool():
    assert DEFAULT_TTL_BY_TOOL["get_stock_quote"] == 300
    assert DEFAULT_TTL_BY_TOOL["get_financials"] == 86400
    assert DEFAULT_TTL_BY_TOOL["get_news"] == 3600
    assert DEFAULT_TTL_BY_TOOL["web_search"] == 1800
    assert DEFAULT_TTL_BY_TOOL["kb_search"] == 86400
    assert DEFAULT_TTL_BY_TOOL["compare_stocks"] == 300


def test_cache_key_namespaces_user(monkeypatch):
    cache = ToolResultCache(session_factory=lambda: None)
    k1 = cache.cache_key(user_id="u1", tool_name="get_quote", args={"a": 1})
    k2 = cache.cache_key(user_id="u2", tool_name="get_quote", args={"a": 1})
    assert k1 != k2  # G2: user namespace prevents leak across users


def test_cache_key_args_normalized():
    cache = ToolResultCache(session_factory=lambda: None)
    k1 = cache.cache_key(user_id="u1", tool_name="t", args={"a": 1, "b": 2})
    k2 = cache.cache_key(user_id="u1", tool_name="t", args={"b": 2, "a": 1})
    assert k1 == k2  # arg ordering doesn't matter


# ---------------------------------------------------------------------------
# L1 — PG 集成测试:TTL tz-aware 比较守护
#
# 回归测试: get_or_compute 第二次调用必须从 PG 读回 tz-aware 的 expires_at
# 并与 datetime.now(UTC) 比较——旧实现用 datetime.utcnow()(naive)触发
# "can't compare offset-naive and offset-aware datetimes" TypeError。
#
# 验证路径:
#   1. 第一次调用 → MISS → compute_fn 执行 → 结果写入 PG
#   2. 第二次调用 → 新建 session → SELECT 读回 tz-aware expires_at → HIT
#      (第二次读回时正是会触发 tz 比较的路径)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_second_call_hits_cache_no_tz_error(pg_async_session_factory):
    """L1: 两次 get_or_compute 调用中第二次从 PG 读回 tz-aware expires_at 不抛 TypeError。

    守护 bug: datetime.utcnow()(naive) vs PG DateTime(timezone=True) 读回的
    tz-aware datetime → TypeError: can't compare offset-naive and offset-aware
    datetimes。修复后 datetime.now(UTC) 与 PG 读回值均为 tz-aware,比较正常。

    Regression test: 若回滚到 datetime.utcnow() 此测试必须 FAIL。
    """
    call_count = 0

    async def compute_fn() -> dict:
        nonlocal call_count
        call_count += 1
        return {"price": 42.0, "currency": "CNY"}

    # 每次测试用唯一 user_id,避免 pg_async_session_factory 不做 TRUNCATE
    # 导致上次运行残留缓存命中,掩盖 MISS 断言。
    unique_user = f"test_tz_{uuid.uuid4().hex[:12]}"
    cache = ToolResultCache(session_factory=pg_async_session_factory)

    # --- 第一次调用: MISS, compute_fn 被执行 ---
    result1, status1 = await cache.get_or_compute(
        user_id=unique_user,
        tool_name="get_stock_quote",
        args={"ticker": "600519.SH"},
        compute_fn=compute_fn,
        ttl_seconds=300,
    )
    assert status1 == CacheHit.MISS, f"第一次调用应为 MISS, 实际: {status1}"
    assert result1 == {"price": 42.0, "currency": "CNY"}
    assert call_count == 1, "第一次调用后 compute_fn 应恰好执行 1 次"

    # --- 第二次调用: HIT, 从 PG 重新 SELECT, 触发 tz-aware 比较 ---
    # get_or_compute 每次 async with session_factory() as sess 新开 session,
    # 保证第二次是真正重新从 PG 读取 row(含 tz-aware expires_at),而非 session 缓存。
    result2, status2 = await cache.get_or_compute(
        user_id=unique_user,
        tool_name="get_stock_quote",
        args={"ticker": "600519.SH"},
        compute_fn=compute_fn,
        ttl_seconds=300,
    )
    # 若 tz 比较抛 TypeError,pytest 会在这里捕获为测试失败,而非断言失败
    assert status2 == CacheHit.HIT, f"第二次调用应为 HIT(缓存命中), 实际: {status2}"
    assert result2 == {"price": 42.0, "currency": "CNY"}
    assert call_count == 1, "第二次调用不应再执行 compute_fn(应命中缓存)"

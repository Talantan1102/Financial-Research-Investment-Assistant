"""L0 — ToolResultCache."""

from __future__ import annotations

from app.services.tool_result_cache import (
    DEFAULT_TTL_BY_TOOL,
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

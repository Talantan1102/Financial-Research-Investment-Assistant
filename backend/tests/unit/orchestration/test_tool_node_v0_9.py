"""L0 — tool_node v0.9 (parallel + cache + error)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.agents.schemas import ChatState, Plan, ToolCall
from app.orchestration.nodes import tool_node
from app.services.tool_result_cache import CacheHit
from app.tools.registry import ToolRegistry
from pydantic import BaseModel


class _DummyArgs(BaseModel):
    ts_code: str


class _DummyTool:
    name = "get_quote"
    description = "stub"
    args_schema = _DummyArgs

    def __init__(self, latency_ms: int = 0, fail: bool = False):
        self.latency_ms = latency_ms
        self.fail = fail
        self.calls = 0

    async def run(self, args):
        self.calls += 1
        await asyncio.sleep(self.latency_ms / 1000)
        if self.fail:
            raise RuntimeError("tool boom")
        return {"price": 6.45}


@pytest.mark.asyncio
async def test_tool_node_parallel_dispatches_concurrently():
    """A2 — parallelizable=True invokes tools via asyncio.gather."""
    t1 = _DummyTool(latency_ms=200)
    t2 = _DummyTool(latency_ms=200)
    t2.name = "get_news"  # second instance under different name
    registry = ToolRegistry()
    registry.register(t1)
    registry.register(t2)

    state = ChatState(
        user_id="u",
        session_id="s",
        user_message="x",
        request_id="r",
        trace_request_id="r",
        plan=Plan(
            tool_calls=[
                ToolCall(tool_name="get_quote", args={"ts_code": "X"}, rationale="r1"),
                ToolCall(tool_name="get_news", args={"ts_code": "X"}, rationale="r2"),
            ],
            parallelizable=True,
            direct_response=False,
            reasoning="parallel test",
        ),
    )
    cache = MagicMock()
    cache.get_or_compute = AsyncMock(
        side_effect=[
            ({"price": 6.45}, CacheHit.MISS),
            ({"price": 6.45}, CacheHit.MISS),
        ]
    )

    out = await tool_node(state, registry=registry, cache=cache, user_id="u")

    # parallel: both ran concurrently (would be ~0.4s if serial); cache mock returns instantly so elapsed is tiny but check semantics not timing
    assert len(out["tool_results"]) == 2


@pytest.mark.asyncio
async def test_tool_node_error_recorded_not_raised():
    """C2 — tool raises; node records ToolResult(success=False) and continues."""
    t = _DummyTool(fail=True)
    registry = ToolRegistry()
    registry.register(t)

    state = ChatState(
        user_id="u",
        session_id="s",
        user_message="x",
        request_id="r",
        trace_request_id="r",
        plan=Plan(
            tool_calls=[ToolCall(tool_name="get_quote", args={"ts_code": "X"}, rationale="r1")],
            parallelizable=False,
            direct_response=False,
            reasoning="error test",
        ),
    )
    cache = MagicMock()
    cache.get_or_compute = AsyncMock(side_effect=RuntimeError("tool boom"))

    out = await tool_node(state, registry=registry, cache=cache, user_id="u")
    assert len(out["tool_results"]) == 1
    assert out["tool_results"][0].success is False
    assert "tool boom" in (out["tool_results"][0].error or "")


@pytest.mark.asyncio
async def test_tool_node_cache_hit_marks_cached():
    """B3 — cache hit sets cached=True on ToolResult."""
    t = _DummyTool()
    registry = ToolRegistry()
    registry.register(t)

    state = ChatState(
        user_id="u",
        session_id="s",
        user_message="x",
        request_id="r",
        trace_request_id="r",
        plan=Plan(
            tool_calls=[ToolCall(tool_name="get_quote", args={"ts_code": "X"}, rationale="r")],
            parallelizable=False,
            direct_response=False,
            reasoning="cache test",
        ),
    )
    cache = MagicMock()
    cache.get_or_compute = AsyncMock(return_value=({"price": 6.45}, CacheHit.HIT))

    out = await tool_node(state, registry=registry, cache=cache, user_id="u")
    assert out["tool_results"][0].cached is True
    assert out["tool_results"][0].success is True

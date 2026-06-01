"""Regression tests for C17, C52, C56 fixes in app/orchestration/nodes.py.

C17 — asyncio.CancelledError in parallel tool dispatch must NOT propagate; it
      must become a ToolResult(success=False) with siblings still recorded.

C52 — _dispatch_one must use the public ToolNotFoundError contract instead of
      peeking at the private registry._tools dict.

C56 — tool_node writes one tool.* span per dispatch when trace_service is
      provided; also covers failing tools (error span) and the no-trace-service
      path (no-op).
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.agents.schemas import ChatState, Plan, ToolCall
from app.orchestration.nodes import _dispatch_one, tool_node
from app.services.tool_result_cache import CacheHit
from app.tools.base import ToolError, ToolNotFoundError
from app.tools.registry import ToolRegistry
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------


class _ArgModel(BaseModel):
    ts_code: str


class _OkTool:
    """Always-succeeds stub tool."""

    name = "ok_tool"
    description = "always ok"
    args_schema = _ArgModel

    async def run(self, args: _ArgModel) -> dict[str, Any]:
        return {"price": 42.0}


class _SlowOkTool:
    """Succeeds after a short sleep — used to prove siblings still run."""

    name = "slow_tool"
    description = "slow but ok"
    args_schema = _ArgModel

    async def run(self, args: _ArgModel) -> dict[str, Any]:
        await asyncio.sleep(0.05)
        return {"price": 9.9}


def _make_state(tool_calls: list[ToolCall], parallelizable: bool = False) -> ChatState:
    """Build a minimal ChatState for tool_node tests."""
    return ChatState(
        user_id="u1",
        session_id="s1",
        user_message="test",
        request_id="req-test",
        trace_request_id="req-test",
        plan=Plan(
            tool_calls=tool_calls,
            parallelizable=parallelizable,
            direct_response=False,
            reasoning="test",
        ),
    )


def _make_cache(return_value: tuple[dict, CacheHit] | None = None) -> MagicMock:
    """Build a minimal ToolResultCache mock."""
    cache = MagicMock()
    if return_value is None:
        cache.get_or_compute = AsyncMock(return_value=({"price": 42.0}, CacheHit.MISS))
    else:
        cache.get_or_compute = AsyncMock(return_value=return_value)
    return cache


# ---------------------------------------------------------------------------
# C17 — CancelledError must not escape parallel gather
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_c17_cancelled_error_becomes_tool_result_failure():
    """C17: asyncio.CancelledError in one parallel coroutine → ToolResult(success=False),
    sibling tool still recorded.
    """
    ok_tool = _OkTool()
    registry = ToolRegistry()
    registry.register(ok_tool)

    # First call cancels immediately; second call succeeds
    cache = MagicMock()
    cache.get_or_compute = AsyncMock(
        side_effect=[
            asyncio.CancelledError("worker cancelled"),
            ({"price": 42.0}, CacheHit.MISS),
        ]
    )

    # Register a second tool under a different name for the second call
    ok_tool2 = _OkTool()
    ok_tool2.name = "ok_tool2"
    registry.register(ok_tool2)

    # Build state with two different tool names so gather coroutines run in order
    state2 = _make_state(
        tool_calls=[
            ToolCall(tool_name="ok_tool", args={"ts_code": "A"}, rationale="r1"),
            ToolCall(tool_name="ok_tool2", args={"ts_code": "B"}, rationale="r2"),
        ],
        parallelizable=True,
    )

    out = await tool_node(state2, registry=registry, cache=cache, user_id="u1")
    results = out["tool_results"]

    assert len(results) == 2, "both calls should produce a ToolResult"
    # First coroutine raised CancelledError → success=False
    assert results[0].success is False
    assert "CancelledError" in (results[0].error or "")
    # Second coroutine succeeded
    assert results[1].success is True


@pytest.mark.asyncio
async def test_c17_cancelled_error_does_not_propagate():
    """C17: CancelledError must NOT escape tool_node as an unhandled exception."""
    ok_tool = _OkTool()
    registry = ToolRegistry()
    registry.register(ok_tool)

    cache = MagicMock()
    cache.get_or_compute = AsyncMock(side_effect=asyncio.CancelledError("revoked"))

    state = _make_state(
        tool_calls=[ToolCall(tool_name="ok_tool", args={"ts_code": "X"}, rationale="r")],
        parallelizable=True,
    )

    # Must not raise
    out = await tool_node(state, registry=registry, cache=cache, user_id="u1")
    assert out["tool_results"][0].success is False


# ---------------------------------------------------------------------------
# C52 — public ToolNotFoundError contract, no private _tools peek
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_c52_unregistered_tool_returns_failure():
    """C52: calling _dispatch_one with an unregistered tool name returns
    ToolResult(success=False, error='not registered') using the public
    ToolNotFoundError rather than peeking at registry._tools.
    """
    registry = ToolRegistry()  # empty — nothing registered
    cache = _make_cache()

    tc = ToolCall(tool_name="nonexistent_tool", args={"ts_code": "X"}, rationale="r")
    result = await _dispatch_one(tc, registry, cache, user_id="u1")

    assert result.success is False
    assert "not registered" in (result.error or "")
    assert result.tool_name == "nonexistent_tool"


@pytest.mark.asyncio
async def test_c52_get_called_not_private_attr(monkeypatch):
    """C52: _dispatch_one must route through registry.get(), not registry._tools.

    Patch registry.get() to raise ToolNotFoundError directly. If _dispatch_one
    still peeks at registry._tools first (old code), the patched get() would never
    be called and the test would fail because no ToolResult(success=False) is
    returned via the correct path. After the fix, get() is called, raises, and
    _dispatch_one catches ToolNotFoundError cleanly.
    """

    registry = ToolRegistry()
    get_calls: list[str] = []

    def _fake_get(name: str):
        get_calls.append(name)
        raise ToolNotFoundError(f"no tool registered with name={name!r}")

    monkeypatch.setattr(registry, "get", _fake_get)

    cache = _make_cache()
    tc = ToolCall(tool_name="missing", args={}, rationale="r")

    result = await _dispatch_one(tc, registry, cache, user_id="u1")

    assert result.success is False
    assert "not registered" in (result.error or "")
    # C52 fix: registry.get() must have been invoked
    assert "missing" in get_calls, "registry.get() was never called — old _tools peek still active"


@pytest.mark.asyncio
async def test_c52_tool_node_with_unregistered_name_via_tool_node():
    """C52: tool_node with an unregistered name produces ToolResult(success=False)."""
    registry = ToolRegistry()
    cache = _make_cache()

    state = _make_state(
        tool_calls=[ToolCall(tool_name="ghost", args={"ts_code": "Y"}, rationale="r")]
    )

    out = await tool_node(state, registry=registry, cache=cache, user_id="u1")
    assert out["tool_results"][0].success is False
    assert "not registered" in (out["tool_results"][0].error or "")


# ---------------------------------------------------------------------------
# C56 — TraceService span writing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_c56_span_written_for_successful_tool():
    """C56: tool_node writes one span for a successful tool call."""
    ok_tool = _OkTool()
    registry = ToolRegistry()
    registry.register(ok_tool)
    cache = _make_cache()

    # Fake synchronous TraceService with write_span tracking
    written_spans: list[Any] = []

    class _FakeTraceService:
        def write_span(self, span: Any) -> None:
            written_spans.append(span)

    state = _make_state(
        tool_calls=[ToolCall(tool_name="ok_tool", args={"ts_code": "Z"}, rationale="r")]
    )

    out = await tool_node(
        state,
        registry=registry,
        cache=cache,
        user_id="u1",
        trace_service=_FakeTraceService(),
    )

    assert out["tool_results"][0].success is True
    assert len(written_spans) == 1
    span = written_spans[0]
    assert span.name == "tool.ok_tool"
    assert span.request_id == "req-test"
    assert span.error is None


@pytest.mark.asyncio
async def test_c56_span_written_for_failing_tool():
    """C56: tool_node writes a span with error set when the tool fails."""
    ok_tool = _OkTool()
    registry = ToolRegistry()
    registry.register(ok_tool)

    cache = MagicMock()
    cache.get_or_compute = AsyncMock(side_effect=ToolError("service unavailable"))

    written_spans: list[Any] = []

    class _FakeTraceService:
        def write_span(self, span: Any) -> None:
            written_spans.append(span)

    state = _make_state(
        tool_calls=[ToolCall(tool_name="ok_tool", args={"ts_code": "Z"}, rationale="r")]
    )

    out = await tool_node(
        state,
        registry=registry,
        cache=cache,
        user_id="u1",
        trace_service=_FakeTraceService(),
    )

    assert out["tool_results"][0].success is False
    assert len(written_spans) == 1
    span = written_spans[0]
    assert span.error is not None
    assert "service unavailable" in span.error


@pytest.mark.asyncio
async def test_c56_span_written_for_unregistered_tool():
    """C56: span is also written when a tool is not registered (error path)."""
    registry = ToolRegistry()
    cache = _make_cache()

    written_spans: list[Any] = []

    class _FakeTraceService:
        def write_span(self, span: Any) -> None:
            written_spans.append(span)

    state = _make_state(tool_calls=[ToolCall(tool_name="unknown", args={}, rationale="r")])

    out = await tool_node(
        state,
        registry=registry,
        cache=cache,
        user_id="u1",
        trace_service=_FakeTraceService(),
    )

    assert out["tool_results"][0].success is False
    assert len(written_spans) == 1
    span = written_spans[0]
    assert span.name == "tool.unknown"
    assert "not registered" in (span.error or "")


@pytest.mark.asyncio
async def test_c56_no_span_when_trace_service_is_none():
    """C56: when trace_service=None (default), no spans are attempted."""
    ok_tool = _OkTool()
    registry = ToolRegistry()
    registry.register(ok_tool)
    cache = _make_cache()

    state = _make_state(
        tool_calls=[ToolCall(tool_name="ok_tool", args={"ts_code": "Z"}, rationale="r")]
    )

    # Must not raise; no spans written
    with patch("app.orchestration.nodes.asyncio.to_thread") as mock_to_thread:
        out = await tool_node(state, registry=registry, cache=cache, user_id="u1")
        mock_to_thread.assert_not_called()

    assert out["tool_results"][0].success is True


@pytest.mark.asyncio
async def test_c56_two_tools_produce_two_spans():
    """C56: parallel dispatch of two tools → two spans."""
    ok_tool = _OkTool()
    ok_tool2 = _OkTool()
    ok_tool2.name = "ok_tool2"
    registry = ToolRegistry()
    registry.register(ok_tool)
    registry.register(ok_tool2)

    cache = MagicMock()
    cache.get_or_compute = AsyncMock(
        side_effect=[
            ({"price": 1.0}, CacheHit.MISS),
            ({"price": 2.0}, CacheHit.MISS),
        ]
    )

    written_spans: list[Any] = []

    class _FakeTraceService:
        def write_span(self, span: Any) -> None:
            written_spans.append(span)

    state = _make_state(
        tool_calls=[
            ToolCall(tool_name="ok_tool", args={"ts_code": "A"}, rationale="r1"),
            ToolCall(tool_name="ok_tool2", args={"ts_code": "B"}, rationale="r2"),
        ],
        parallelizable=True,
    )

    out = await tool_node(
        state,
        registry=registry,
        cache=cache,
        user_id="u1",
        trace_service=_FakeTraceService(),
    )

    assert len(out["tool_results"]) == 2
    assert len(written_spans) == 2
    span_names = {s.name for s in written_spans}
    assert span_names == {"tool.ok_tool", "tool.ok_tool2"}


@pytest.mark.asyncio
async def test_c56_trace_write_failure_does_not_propagate():
    """C56: if write_span raises, tool_node must not propagate the error."""
    ok_tool = _OkTool()
    registry = ToolRegistry()
    registry.register(ok_tool)
    cache = _make_cache()

    class _BrokenTraceService:
        def write_span(self, span: Any) -> None:
            raise RuntimeError("DB down")

    state = _make_state(
        tool_calls=[ToolCall(tool_name="ok_tool", args={"ts_code": "Z"}, rationale="r")]
    )

    # Must not raise even though write_span fails
    out = await tool_node(
        state,
        registry=registry,
        cache=cache,
        user_id="u1",
        trace_service=_BrokenTraceService(),
    )

    assert out["tool_results"][0].success is True

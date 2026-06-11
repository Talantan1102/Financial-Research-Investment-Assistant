"""ToolHub 工具 span 写入 — 成功/失败/缓存命中三态 + 非致命。"""

from __future__ import annotations

import pytest
from app.chatloop.state import ChatLoopState
from app.chatloop.tool_hub import ToolHub
from app.services.llm_step import StepToolCall
from pydantic import BaseModel


class _CapturingTrace:
    def __init__(self) -> None:
        self.spans: list = []

    def write_span(self, span) -> None:
        self.spans.append(span)


class _Args(BaseModel):
    pass


class _FakeQuoteTool:
    """非 InProcessTool → 走数据工具路径(无 cache 直跑)。"""

    name = "get_quote"
    args_schema = _Args

    async def run(self, validated) -> dict:
        return {"price": 42}


def _state() -> ChatLoopState:
    return ChatLoopState(
        user_id="u1",
        session_id="s1",
        request_id="req-1",
        messages=[],
        step=3,
    )


def _call() -> StepToolCall:
    return StepToolCall(id="c1", name="get_quote", arguments="{}")


@pytest.mark.asyncio
async def test_success_writes_one_tool_span() -> None:
    trace = _CapturingTrace()
    hub = ToolHub(trace=trace)
    hub.register_inprocess([_FakeQuoteTool()])  # type: ignore[list-item]
    await hub.dispatch([_call()], _state())

    assert len(trace.spans) == 1
    span = trace.spans[0]
    assert span.name == "tool:get_quote"
    assert span.request_id == "req-1"
    assert span.parent_id is None
    assert span.metadata["kind"] == "tool"
    assert span.metadata["success"] is True
    assert span.metadata["cached"] is False
    assert span.metadata["step"] == 3
    assert span.metadata["latency_ms"] >= 0
    assert span.error is None
    # 隐私:inputs/outputs 不带工具结果原文
    assert "price" not in str(span.outputs)


@pytest.mark.asyncio
async def test_unknown_tool_writes_failed_span() -> None:
    trace = _CapturingTrace()
    hub = ToolHub(trace=trace)  # 不注册任何工具
    await hub.dispatch([_call()], _state())

    assert len(trace.spans) == 1
    span = trace.spans[0]
    assert span.name == "tool:get_quote"
    assert span.metadata["success"] is False
    assert span.error is not None


@pytest.mark.asyncio
async def test_trace_write_failure_is_nonfatal() -> None:
    class _BoomTrace:
        def write_span(self, span) -> None:
            raise RuntimeError("db down")

    hub = ToolHub(trace=_BoomTrace())
    hub.register_inprocess([_FakeQuoteTool()])  # type: ignore[list-item]
    results = await hub.dispatch([_call()], _state())  # 不得抛
    assert results[0].success is True


@pytest.mark.asyncio
async def test_no_trace_writes_nothing() -> None:
    hub = ToolHub()  # trace=None
    hub.register_inprocess([_FakeQuoteTool()])  # type: ignore[list-item]
    results = await hub.dispatch([_call()], _state())
    assert results[0].success is True  # 行为不变

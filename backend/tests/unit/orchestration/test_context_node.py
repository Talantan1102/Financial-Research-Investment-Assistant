"""L0 — context_node behavior."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from app.agents.in_session_memory import InSessionMemory
from app.agents.schemas import ChatState, HistoryMessage, ToolResult
from app.orchestration.context_node import context_node


@pytest.fixture
def mem_no_summarize():
    """Mem stub that never triggers summarize."""
    m = InSessionMemory()
    m.summarize = AsyncMock(return_value="")  # never called
    return m


@pytest.mark.asyncio
async def test_context_node_loads_history_dedupes_tools(mem_no_summarize):
    state = ChatState(
        user_id="u1",
        session_id="s1",
        user_message="next q",
        request_id="r1",
        trace_request_id="r1",
        tool_results=[
            ToolResult(
                tool_name="t", args={"a": 1}, output={"v": "r1"}, success=True, latency_ms=0
            ),
            ToolResult(
                tool_name="t", args={"a": 1}, output={"v": "r2"}, success=True, latency_ms=0
            ),
        ],
    )
    out = await context_node(state, memory=mem_no_summarize)
    assert len(out["tool_results"]) == 1
    # last one wins per dedup logic
    assert out["tool_results"][0].output == {"v": "r2"}


@pytest.mark.asyncio
async def test_context_node_triggers_summarize_when_needed():
    mem = InSessionMemory()
    mem.summarize = AsyncMock(return_value="(摘要 mock)")
    mem.needs_summarize = lambda state, max_tokens=0: True

    state = ChatState(
        user_id="u1",
        session_id="s1",
        user_message="q",
        request_id="r1",
        trace_request_id="r1",
        history=[
            HistoryMessage(role="user", content="x" * 100, turn_index=i, timestamp=datetime.now())
            for i in range(10)
        ],
    )
    out = await context_node(state, memory=mem)
    assert out["history_summary"] == "(摘要 mock)"
    assert len(out["history"]) == 4  # only recent K kept

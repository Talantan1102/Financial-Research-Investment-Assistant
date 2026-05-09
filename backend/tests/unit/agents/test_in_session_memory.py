"""L0 — Memory Protocol + InSessionMemory (Q4 E).

Adapted to existing ToolResult schema:
  - args: dict[str, Any]  (not args_json: str)
  - success: bool         (not ok: bool)
  - output: dict | None   (not result_json: str)
  - latency_ms: int
"""

from __future__ import annotations

from datetime import datetime

import pytest
from app.agents.in_session_memory import InSessionMemory
from app.agents.memory_protocol import Memory
from app.agents.schemas import ChatState, HistoryMessage, ToolResult


@pytest.fixture
def empty_state():
    return ChatState(
        user_id="u1",
        session_id="s1",
        user_message="hi",
        request_id="r1",
        trace_request_id="r1",
    )


def test_in_session_memory_implements_protocol():
    mem = InSessionMemory()
    assert isinstance(mem, Memory)


def test_needs_summarize_below_threshold(empty_state):
    mem = InSessionMemory()
    for i in range(5):
        empty_state.history.append(
            HistoryMessage(
                role="user",
                content="short msg",
                turn_index=i,
                timestamp=datetime.now(),
            )
        )
    assert mem.needs_summarize(empty_state, max_tokens=24_000) is False


def test_needs_summarize_above_threshold(empty_state):
    mem = InSessionMemory()
    long_text = "x " * 600
    for i in range(50):
        empty_state.history.append(
            HistoryMessage(
                role="user",
                content=long_text,
                turn_index=i,
                timestamp=datetime.now(),
            )
        )
    assert mem.needs_summarize(empty_state, max_tokens=24_000) is True


def test_dedup_tool_results_keeps_only_latest_per_signature(empty_state):
    mem = InSessionMemory()
    common_args = {"ts_code": "601398.SH"}
    empty_state.tool_results = [
        ToolResult(
            tool_name="get_quote",
            args=common_args,
            success=True,
            output={"price": 1.0},
            latency_ms=10,
        ),
        ToolResult(
            tool_name="get_quote",
            args=common_args,
            success=True,
            output={"price": 2.0},
            latency_ms=10,
        ),
        ToolResult(
            tool_name="get_quote",
            args=common_args,
            success=True,
            output={"price": 3.0},
            latency_ms=10,
        ),
    ]
    deduped = mem.dedup_tool_results(empty_state.tool_results)
    assert len(deduped) == 1
    assert deduped[0].output == {"price": 3.0}


def test_dedup_keeps_different_signatures(empty_state):
    mem = InSessionMemory()
    empty_state.tool_results = [
        ToolResult(
            tool_name="get_quote", args={"x": 1}, success=True, output={"r": "r1"}, latency_ms=10
        ),
        ToolResult(
            tool_name="get_quote", args={"x": 2}, success=True, output={"r": "r2"}, latency_ms=10
        ),
        ToolResult(
            tool_name="get_news", args={"x": 1}, success=True, output={"r": "r3"}, latency_ms=10
        ),
    ]
    deduped = mem.dedup_tool_results(empty_state.tool_results)
    assert len(deduped) == 3

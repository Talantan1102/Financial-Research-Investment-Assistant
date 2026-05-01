"""L0 — agent I/O schemas: Plan / ToolCall / ToolResult / GraphState / StepResult."""

import pytest
from app.agents.schemas import (
    GraphState,
    Plan,
    StepResult,
    ToolCall,
    ToolResult,
)
from pydantic import ValidationError


def test_plan_with_tools() -> None:
    p = Plan(
        tool_calls=[
            ToolCall(
                tool_name="get_stock_quote", args={"ts_code": "600519.SH"}, rationale="user asked"
            )
        ],
        direct_response=False,
        reasoning="single tool call for price query",
    )
    assert len(p.tool_calls) == 1


def test_plan_direct_response_no_tools() -> None:
    p = Plan(tool_calls=[], direct_response=True, reasoning="greeting")
    assert p.direct_response is True


def test_plan_direct_response_with_tools_rejected() -> None:
    with pytest.raises(ValidationError, match="direct_response=True"):
        Plan(
            tool_calls=[ToolCall(tool_name="x", args={}, rationale="r")],
            direct_response=True,
            reasoning="conflict",
        )


def test_plan_no_tools_no_direct_rejected() -> None:
    with pytest.raises(ValidationError, match="direct_response=False"):
        Plan(tool_calls=[], direct_response=False, reasoning="empty")


def test_tool_result_success() -> None:
    r = ToolResult(
        tool_name="get_stock_quote",
        args={"ts_code": "600519.SH"},
        success=True,
        output={"price": 1820.5},
        error=None,
        latency_ms=320,
    )
    assert r.output == {"price": 1820.5}
    assert r.error is None


def test_tool_result_failure() -> None:
    r = ToolResult(
        tool_name="x",
        args={},
        success=False,
        output=None,
        error="connection refused",
        latency_ms=5,
    )
    assert r.error == "connection refused"


def test_graph_state_minimal() -> None:
    s = GraphState(
        user_id="u1",
        session_id="s1",
        user_message="茅台股价?",
        request_id="req-abc12345",
    )
    assert s.plan is None
    assert s.tool_results == []
    assert s.final_response is None


def test_step_result_state_update() -> None:
    sr = StepResult(
        state_update={"plan": {"tool_calls": [], "direct_response": True, "reasoning": "x"}},
        span_metadata={"k": "v"},
    )
    assert "plan" in sr.state_update

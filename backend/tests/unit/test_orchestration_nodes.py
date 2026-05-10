"""L0 — orchestration nodes: planner_node / tool_node / responder_node."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from app.agents.schemas import GraphState, Plan, ToolCall, ToolResult
from app.tools.base import Tool
from app.tools.registry import ToolRegistry
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _state(**overrides: Any) -> GraphState:
    defaults: dict[str, Any] = {
        "user_id": "u",
        "session_id": "s",
        "user_message": "茅台股价?",
        "request_id": "req-node-test",
        "trace_request_id": "req-node-test",
    }
    defaults.update(overrides)
    return GraphState(**defaults)


# ---------------------------------------------------------------------------
# Stub tool for tool_node tests
# ---------------------------------------------------------------------------


class _OkArgs(BaseModel):
    query: str


class _OkTool(Tool):
    name = "stub_ok"
    description = "Returns {'ok': 1}."
    args_schema = _OkArgs

    async def run(self, args: BaseModel) -> dict[str, Any]:
        return {"ok": 1}


# ---------------------------------------------------------------------------
# planner_node tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_planner_node_returns_state_update(
    monkeypatch: pytest.MonkeyPatch,
    mock_llm_client: Any,
) -> None:
    """planner_node returns a dict containing 'plan' key."""
    monkeypatch.setenv("LLM_MODE", "mock")

    from app.agents.chat_planner import ChatPlanner
    from app.orchestration.nodes import planner_node
    from app.services.llm_service import LLMService
    from app.tools.get_stock_quote import StockQuoteTool

    svc = LLMService(client=mock_llm_client)
    reg = ToolRegistry()
    reg.register(StockQuoteTool(tushare=None))
    planner = ChatPlanner(llm=svc, registry=reg)

    state = _state()
    result = await planner_node(state, planner=planner)

    assert "plan" in result
    assert isinstance(result["plan"], Plan)


# ---------------------------------------------------------------------------
# tool_node tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_node_no_plan_returns_empty() -> None:
    """tool_node returns {} when state.plan is None."""
    from app.orchestration.nodes import tool_node
    from app.services.tool_result_cache import ToolResultCache

    state = _state(plan=None)
    result = await tool_node(state, registry=ToolRegistry(), cache=ToolResultCache(session_factory=MagicMock()))
    assert result == {}


@pytest.mark.asyncio
async def test_tool_node_executes_calls() -> None:
    """tool_node fans out plan.tool_calls through registry, returns tool_results."""
    from app.orchestration.nodes import tool_node
    from app.services.tool_result_cache import ToolResultCache

    reg = ToolRegistry()
    reg.register(_OkTool())

    plan = Plan(
        tool_calls=[ToolCall(tool_name="stub_ok", args={"query": "hi"}, rationale="test")],
        direct_response=False,
        reasoning="unit test",
    )
    state = _state(plan=plan)
    result = await tool_node(state, registry=reg, cache=ToolResultCache(session_factory=MagicMock()))

    assert "tool_results" in result
    results: list[ToolResult] = result["tool_results"]
    assert len(results) == 1
    tr = results[0]
    assert tr.success is True
    assert tr.output == {"ok": 1}
    assert tr.tool_name == "stub_ok"


# ---------------------------------------------------------------------------
# responder_node tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_responder_node_returns_state_update(
    monkeypatch: pytest.MonkeyPatch,
    mock_llm_client: Any,
) -> None:
    """responder_node returns a dict containing 'final_response' key."""
    monkeypatch.setenv("LLM_MODE", "mock")

    from app.agents.responder import Responder
    from app.orchestration.nodes import responder_node
    from app.services.llm_service import LLMService

    svc = LLMService(client=mock_llm_client)
    responder = Responder(llm=svc)

    state = _state(
        tool_results=[
            ToolResult(
                tool_name="stub_ok",
                args={"query": "hi"},
                success=True,
                output={"ok": 1},
                latency_ms=1,
            )
        ]
    )
    result = await responder_node(state, responder=responder)

    assert "final_response" in result
    assert isinstance(result["final_response"], str)
    assert len(result["final_response"]) > 0

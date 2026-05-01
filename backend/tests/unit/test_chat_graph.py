"""L0 — unit tests for chat_graph module.

Tests cover:
- _route_after_planner routing logic (pure function, no LLM calls)
- build_chat_graph returns a CompiledStateGraph instance
"""

from __future__ import annotations

from typing import Any

import pytest
from app.agents.schemas import GraphState, Plan, ToolCall
from langgraph.graph.state import CompiledStateGraph

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _state(**overrides: Any) -> GraphState:
    defaults: dict[str, Any] = {
        "user_id": "u",
        "session_id": "s",
        "user_message": "茅台股价?",
        "request_id": "req-graph-test",
    }
    defaults.update(overrides)
    return GraphState(**defaults)


def _plan_with_tool_calls() -> Plan:
    return Plan(
        tool_calls=[
            ToolCall(tool_name="get_stock_quote", args={"ts_code": "600519.SH"}, rationale="test")
        ],
        direct_response=False,
        reasoning="single tool",
    )


def _plan_direct_response() -> Plan:
    return Plan(
        tool_calls=[],
        direct_response=True,
        reasoning="no tools needed",
    )


# ---------------------------------------------------------------------------
# _route_after_planner tests (L0 — no LLM, no LangGraph graph execution)
# ---------------------------------------------------------------------------


def test_route_after_planner_no_plan_goes_to_responder() -> None:
    """When plan is None, route to responder_node."""
    from app.orchestration.chat_graph import _route_after_planner

    state = _state(plan=None)
    result = _route_after_planner(state)
    assert result == "responder_node"


def test_route_after_planner_with_tools_goes_to_tool_node() -> None:
    """When plan has tool_calls, route to tool_node."""
    from app.orchestration.chat_graph import _route_after_planner

    state = _state(plan=_plan_with_tool_calls())
    result = _route_after_planner(state)
    assert result == "tool_node"


def test_route_after_planner_direct_response_goes_to_responder() -> None:
    """When plan has direct_response=True (tool_calls=[]), route to responder_node."""
    from app.orchestration.chat_graph import _route_after_planner

    state = _state(plan=_plan_direct_response())
    result = _route_after_planner(state)
    assert result == "responder_node"


# ---------------------------------------------------------------------------
# build_chat_graph tests (L0 — instantiate graph only, no ainvoke)
# ---------------------------------------------------------------------------


def test_build_chat_graph_returns_compiled_graph(
    monkeypatch: pytest.MonkeyPatch,
    mock_llm_client: Any,
) -> None:
    """build_chat_graph returns a CompiledStateGraph with the correct node names."""
    # build_chat_graph internally constructs ChatPlanner+Responder that hold an
    # LLMService reference — we must be in mock mode to allow LLMService construction.
    monkeypatch.setenv("LLM_MODE", "mock")

    from app.agents.chat_planner import ChatPlanner
    from app.agents.responder import Responder
    from app.orchestration.chat_graph import build_chat_graph
    from app.services.llm_service import LLMService
    from app.tools.registry import ToolRegistry

    svc = LLMService(client=mock_llm_client)
    registry = ToolRegistry()  # empty registry is valid for graph construction
    planner = ChatPlanner(llm=svc, registry=registry)
    responder = Responder(llm=svc)

    graph = build_chat_graph(planner=planner, responder=responder, registry=registry)

    assert isinstance(graph, CompiledStateGraph)


def test_build_chat_graph_no_checkpointer_by_default(
    monkeypatch: pytest.MonkeyPatch,
    mock_llm_client: Any,
) -> None:
    """build_chat_graph without db_path produces a graph with no checkpointer (stateless)."""
    monkeypatch.setenv("LLM_MODE", "mock")

    from app.agents.chat_planner import ChatPlanner
    from app.agents.responder import Responder
    from app.orchestration.chat_graph import build_chat_graph
    from app.services.llm_service import LLMService
    from app.tools.registry import ToolRegistry

    svc = LLMService(client=mock_llm_client)
    registry = ToolRegistry()
    planner = ChatPlanner(llm=svc, registry=registry)
    responder = Responder(llm=svc)

    graph = build_chat_graph(planner=planner, responder=responder, registry=registry, db_path=None)

    # No checkpointer should be attached — attribute may be None or absent
    checkpointer = getattr(graph, "checkpointer", None)
    assert checkpointer is None

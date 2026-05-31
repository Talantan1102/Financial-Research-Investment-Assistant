"""C6 regression tests — _route_after_planner must not return skill/resource node
names when skill_loader is None (nodes not registered → KeyError in LangGraph).

Two families:
  1. Pure function tests for _route_after_planner with skill_loader_available flag.
  2. build_chat_graph structural test confirming edge_map is consistent with nodes.
"""

from __future__ import annotations

from functools import partial
from typing import Any
from unittest.mock import MagicMock

from app.agents.schemas import ChatState, Plan, ToolCall
from app.orchestration.chat_graph import _route_after_planner

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(**plan_kwargs: Any) -> ChatState:
    defaults: dict[str, Any] = {
        "direct_response": True,
        "tool_calls": [],
        "reasoning": "r",
    }
    defaults.update(plan_kwargs)
    plan = Plan(**defaults)
    return ChatState(
        user_id="u",
        session_id="s",
        user_message="x",
        request_id="r",
        trace_request_id="r",
        plan=plan,
    )


# ---------------------------------------------------------------------------
# C6: skill_loader=None path — must NOT route to skill_load_node / resource_load_node
# ---------------------------------------------------------------------------


def test_route_load_skill_without_loader_falls_to_responder() -> None:
    """C6: plan.load_skill set but skill_loader_available=False → responder_node (not KeyError)."""
    state = _make_state(load_skill="risk_assessment")
    # skill_loader_available defaults to False
    result = _route_after_planner(state, skill_loader_available=False)
    assert result == "responder_node"


def test_route_load_resource_without_loader_falls_to_responder() -> None:
    """C6: plan.load_resource set but skill_loader_available=False → responder_node (not KeyError)."""
    state = _make_state(load_resource={"skill": "x", "ref": "resources/x.yaml"})
    result = _route_after_planner(state, skill_loader_available=False)
    assert result == "responder_node"


def test_route_default_skill_loader_available_false() -> None:
    """C6: default kwarg value is False — old call site without kwarg is safe."""
    state = _make_state(load_skill="risk_assessment")
    # calling without skill_loader_available must not raise and must NOT return skill_load_node
    result = _route_after_planner(state)
    assert result == "responder_node"


# ---------------------------------------------------------------------------
# C6: skill_loader present — still routes to skill/resource nodes
# ---------------------------------------------------------------------------


def test_route_load_skill_with_loader_routes_correctly() -> None:
    """C6: skill_loader_available=True preserves routing to skill_load_node."""
    state = _make_state(load_skill="risk_assessment")
    result = _route_after_planner(state, skill_loader_available=True)
    assert result == "skill_load_node"


def test_route_load_resource_with_loader_routes_correctly() -> None:
    """C6: skill_loader_available=True preserves routing to resource_load_node."""
    state = _make_state(load_resource={"skill": "x", "ref": "resources/x.yaml"})
    result = _route_after_planner(state, skill_loader_available=True)
    assert result == "resource_load_node"


# ---------------------------------------------------------------------------
# C6: build_chat_graph structural guard — edge_map is consistent with registered nodes
# ---------------------------------------------------------------------------


def test_build_chat_graph_no_loader_edge_map_excludes_skill_nodes() -> None:
    """C6: build_chat_graph(skill_loader=None) must not include skill/resource in edge_map.

    We verify via the compiled graph's node registry — if skill/resource nodes were in
    edge_map but not registered this would already fail at .compile().  Conversely if they
    are absent from node registry they cannot be targets.
    """
    from app.agents.in_session_memory import InSessionMemory
    from app.orchestration.chat_graph import build_chat_graph
    from app.services.tool_result_cache import ToolResultCache

    class _NopPlanner:
        async def run(self, state: Any) -> dict[str, Any]:
            return {"plan": None}

    class _NopResponder:
        async def run(self, state: Any) -> dict[str, Any]:
            return {"final_response": ""}

    class _NopRegistry:
        def get(self, name: str) -> None:
            return None

        def list_tools(self) -> list[Any]:
            return []

    g = build_chat_graph(
        planner=_NopPlanner(),  # type: ignore[arg-type]
        responder=_NopResponder(),  # type: ignore[arg-type]
        registry=_NopRegistry(),  # type: ignore[arg-type]
        memory=InSessionMemory(),
        cache=ToolResultCache(session_factory=MagicMock()),
        skill_loader=None,
    )

    node_names = set(g.get_graph().nodes.keys())
    # Skill/resource nodes must NOT be registered when loader is None
    assert "skill_load_node" not in node_names
    assert "resource_load_node" not in node_names
    # Core nodes must still be present
    assert "planner_node" in node_names
    assert "responder_node" in node_names
    assert "tool_node" in node_names


# ---------------------------------------------------------------------------
# C6: partial binding test — the bound router never targets an absent node
# ---------------------------------------------------------------------------


def test_partial_bound_router_consistent_with_edge_map_no_loader() -> None:
    """C6: partial(_route_after_planner, skill_loader_available=False) only returns
    keys present in the edge_map when skill_loader is None."""
    edge_map = {"tool_node": "tool_node", "responder_node": "responder_node"}
    router_fn = partial(_route_after_planner, skill_loader_available=False)

    state_skill = _make_state(load_skill="some_skill")
    state_resource = _make_state(load_resource={"skill": "x", "ref": "r.yaml"})
    state_tool = _make_state(
        direct_response=False,
        tool_calls=[ToolCall(tool_name="t", args={}, rationale="r")],
    )
    state_direct = _make_state()

    for state in (state_skill, state_resource, state_tool, state_direct):
        result = router_fn(state)
        assert result in edge_map, (
            f"router returned {result!r} which is not in edge_map keys {set(edge_map)}"
        )

"""L0 — chat_graph v0.9 wiring."""

from __future__ import annotations

from app.agents.in_session_memory import InSessionMemory
from app.orchestration.chat_graph import build_chat_graph


class _NoOpPlanner:
    async def run(self, state):
        return {"plan": None}


class _NoOpResponder:
    async def run(self, state):
        return {"final_response": ""}


class _NoOpRegistry:
    def get(self, name):
        return None

    def list_tools(self):
        return []


class _NoOpCache:
    async def get_or_compute(self, **kw):
        return ({}, None)


def test_build_chat_graph_with_required_nodes():
    """All v0.9 nodes are registered and edges connect."""
    g = build_chat_graph(
        planner=_NoOpPlanner(),
        responder=_NoOpResponder(),
        registry=_NoOpRegistry(),
        memory=InSessionMemory(),
        cache=_NoOpCache(),
        checkpointer=None,  # stateless for unit test
    )
    nodes = list(g.get_graph().nodes)
    assert "context_node" in nodes
    assert "planner_node" in nodes
    assert "tool_node" in nodes
    assert "responder_node" in nodes

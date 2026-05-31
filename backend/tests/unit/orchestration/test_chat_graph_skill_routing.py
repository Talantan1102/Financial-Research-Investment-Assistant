"""Smoke test: planner emits load_skill → graph routes to skill_load_node."""

from __future__ import annotations

from app.agents.schemas import ChatState, Plan
from app.orchestration.chat_graph import _route_after_planner


def _make_state(**plan_kwargs) -> ChatState:
    defaults: dict = {"direct_response": True, "tool_calls": [], "reasoning": "r"}
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


def test_route_load_skill():
    # C6: must pass skill_loader_available=True to get skill routing
    s = _make_state(load_skill="risk_assessment")
    assert _route_after_planner(s, skill_loader_available=True) == "skill_load_node"


def test_route_load_resource():
    # C6: must pass skill_loader_available=True to get resource routing
    s = _make_state(load_resource={"skill": "x", "ref": "resources/x.yaml"})
    assert _route_after_planner(s, skill_loader_available=True) == "resource_load_node"


def test_route_tool_call():
    from app.agents.schemas import ToolCall

    s = _make_state(
        tool_calls=[ToolCall(tool_name="t", args={}, rationale="r")],
        direct_response=False,
    )
    assert _route_after_planner(s) == "tool_node"


def test_route_respond_direct():
    s = _make_state()
    assert _route_after_planner(s) == "responder_node"


def test_route_no_plan_falls_to_responder():
    s = ChatState(
        user_id="u",
        session_id="s",
        user_message="x",
        request_id="r",
        trace_request_id="r",
        plan=None,
    )
    assert _route_after_planner(s) == "responder_node"

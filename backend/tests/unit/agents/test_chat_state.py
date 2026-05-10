"""L0 — ChatState v0.9 schema."""

from __future__ import annotations

from app.agents.schemas import ChatState


def test_chat_state_has_v0_9_fields():
    s = ChatState(
        user_id="u1",
        session_id="s1",
        user_message="hi",
        request_id="r1",
        trace_request_id="r1",
    )
    # legacy
    assert s.user_id == "u1"
    assert s.session_id == "s1"
    # v0.9 history
    assert s.history == []
    assert s.history_summary is None
    # tool result mgmt
    assert s.tool_results == []
    assert s.tool_result_cache == {}
    # plan / final (legacy)
    assert s.plan is None
    assert s.final_response is None
    # escalation (Plan 3 will use; Plan 1 just reserves)
    assert s.escalate_offered is False
    assert s.escalate_confirmed is False
    # observability
    assert s.cost_so_far == 0.0
    assert s.span_stack == []


def test_chat_state_is_aliased_for_legacy_callers():
    """Legacy code may import GraphState; alias must work."""
    from app.agents.schemas import GraphState

    assert GraphState is ChatState

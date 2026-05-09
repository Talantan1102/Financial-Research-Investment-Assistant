"""L0 — ResearchState chat-derived fields (Plan 3 hook)."""

from __future__ import annotations

from app.agents.escalation_protocol import Entity, Preference
from app.agents.schemas import ResearchState


def test_research_state_default_chat_fields_empty():
    s = ResearchState(
        user_id="u",
        session_id="s",
        user_message="x",
        request_id="r",
    )
    assert s.chat_extracted_entities == []
    assert s.chat_extracted_preferences == []
    assert s.chat_known_tool_results == []
    assert s.chat_session_id is None


def test_research_state_accepts_chat_signals():
    s = ResearchState(
        user_id="u",
        session_id="s",
        user_message="x",
        request_id="r",
        chat_extracted_entities=[
            Entity(
                name="工商银行",
                ts_code="601398.SH",
                role="primary_target",
                mention_turn_indices=[0],
            ),
        ],
        chat_extracted_preferences=[
            Preference(text="风控优先", category="risk_tolerance", confidence=0.8),
        ],
        chat_session_id="chat-abc",
    )
    assert s.chat_extracted_entities[0].name == "工商银行"
    assert s.chat_extracted_preferences[0].category == "risk_tolerance"
    assert s.chat_session_id == "chat-abc"

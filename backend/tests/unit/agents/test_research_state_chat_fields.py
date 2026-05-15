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


def test_research_state_has_writer_retry_fields() -> None:
    """v1.x: writer_retry_count + writer_critic_feedback added."""
    from app.agents.schemas import ResearchState

    s = ResearchState(user_id="u", session_id="s", user_message="m", request_id="r")
    assert s.writer_retry_count == 0
    assert s.writer_critic_feedback is None


def test_research_state_writer_retry_count_max_1() -> None:
    """writer_retry_count is bounded ge=0 le=1 (MAX_WRITER_RETRY)."""
    import pytest
    from app.agents.schemas import ResearchState
    from pydantic import ValidationError

    # 0 and 1 OK
    s0 = ResearchState(
        user_id="u", session_id="s", user_message="m", request_id="r", writer_retry_count=0
    )
    s1 = ResearchState(
        user_id="u", session_id="s", user_message="m", request_id="r", writer_retry_count=1
    )
    assert s0.writer_retry_count == 0
    assert s1.writer_retry_count == 1

    # 2 should fail
    with pytest.raises(ValidationError):
        ResearchState(
            user_id="u", session_id="s", user_message="m", request_id="r", writer_retry_count=2
        )

    # -1 should fail
    with pytest.raises(ValidationError):
        ResearchState(
            user_id="u", session_id="s", user_message="m", request_id="r", writer_retry_count=-1
        )


def test_research_state_writer_critic_feedback_max_length_300() -> None:
    import pytest
    from app.agents.schemas import ResearchState
    from pydantic import ValidationError

    # 300 chars OK
    ResearchState(
        user_id="u",
        session_id="s",
        user_message="m",
        request_id="r",
        writer_critic_feedback="x" * 300,
    )
    # 301 fails
    with pytest.raises(ValidationError):
        ResearchState(
            user_id="u",
            session_id="s",
            user_message="m",
            request_id="r",
            writer_critic_feedback="x" * 301,
        )


def test_research_state_has_distilled_chat_fields() -> None:
    """v1.x: escalation_intent / discussion_focus / explicit_exclusions."""
    from app.agents.schemas import ResearchState

    s = ResearchState(user_id="u", session_id="s", user_message="m", request_id="r")
    assert s.escalation_intent == ""
    assert s.discussion_focus == []
    assert s.explicit_exclusions == []


def test_research_state_distilled_field_constraints() -> None:
    import pytest
    from app.agents.schemas import ResearchState
    from pydantic import ValidationError

    # escalation_intent max 200
    with pytest.raises(ValidationError):
        ResearchState(
            user_id="u",
            session_id="s",
            user_message="m",
            request_id="r",
            escalation_intent="x" * 201,
        )
    # discussion_focus max 5 items
    with pytest.raises(ValidationError):
        ResearchState(
            user_id="u",
            session_id="s",
            user_message="m",
            request_id="r",
            discussion_focus=["f"] * 6,
        )
    # explicit_exclusions max 3 items
    with pytest.raises(ValidationError):
        ResearchState(
            user_id="u",
            session_id="s",
            user_message="m",
            request_id="r",
            explicit_exclusions=["e"] * 4,
        )


def test_research_state_accepts_filled_distilled_fields() -> None:
    from app.agents.schemas import ResearchState

    s = ResearchState(
        user_id="u",
        session_id="s",
        user_message="m",
        request_id="r",
        escalation_intent="客户希望对茅台做全面尽调",
        discussion_focus=["担心负债率", "对比五粮液"],
        explicit_exclusions=["不关心 ESG"],
    )
    assert s.escalation_intent.startswith("客户")
    assert len(s.discussion_focus) == 2
    assert len(s.explicit_exclusions) == 1

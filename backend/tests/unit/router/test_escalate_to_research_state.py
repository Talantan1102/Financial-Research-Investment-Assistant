"""L0 — packet_to_research_state adapter."""

from __future__ import annotations

from datetime import UTC, datetime

from app.agents.escalation_protocol import (
    ChatDerivedSignals,
    Entity,
    EscalationPacket,
    ExplicitTask,
    KnownFacts,
    Preference,
    SessionMetadata,
    ToolResultRef,
)
from app.router.escalate import packet_to_research_state


def test_adapter_copies_chat_signals():
    pkt = EscalationPacket(
        explicit_task=ExplicitTask(
            raw_last_user_turn="深度尽调 ICBC",
            extracted_intent="full_due_diligence",
            target_ts_code="601398.SH",
            target_entity_name="工商银行",
        ),
        chat_derived_signals=ChatDerivedSignals(
            entities=[
                Entity(
                    name="工商银行",
                    ts_code="601398.SH",
                    role="primary_target",
                    mention_turn_indices=[0],
                ),
                Entity(
                    name="招商银行",
                    ts_code="600036.SH",
                    role="comparative_target",
                    mention_turn_indices=[2],
                ),
            ],
            preferences=[
                Preference(text="风控优先", category="risk_tolerance", confidence=0.8),
            ],
            extraction_confidence=0.8,
        ),
        known_facts=KnownFacts(
            tool_results=[
                ToolResultRef(
                    tool_name="get_stock_quote",
                    tool_args={"ts_code": "601398.SH"},
                    result_summary="6.45 元",
                    cached_at=datetime.now(UTC),
                    cache_id="anon::get_stock_quote::abc",
                ),
            ],
        ),
        session_metadata=SessionMetadata(
            chat_session_id="chat-abc",
            chat_turn_count=3,
            user_confirmed_at=datetime.now(UTC),
        ),
    )
    state = packet_to_research_state(pkt, request_id="r1")
    assert state.user_message == "深度尽调 ICBC"
    assert state.target_ts_code == "601398.SH"
    assert state.target_entity == "工商银行"
    assert state.chat_session_id == "chat-abc"
    assert len(state.chat_extracted_entities) == 2
    assert len(state.chat_extracted_preferences) == 1
    assert len(state.chat_known_tool_results) == 1
    assert state.session_id == "r1"

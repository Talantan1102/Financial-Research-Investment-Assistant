"""Confidence-gated distilled fields injection in packet_to_research_state."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import patch

from app.agents.escalation_protocol import (
    ChatDerivedSignals,
    Entity,
    EscalationPacket,
    ExplicitTask,
    KnownFacts,
    SessionMetadata,
)
from app.router.escalate import (
    ESCALATION_CONFIDENCE_THRESHOLD_DEFAULT,
    get_confidence_threshold,
    packet_to_research_state,
)


def _now():
    return datetime.now(UTC)


def _mk_packet(
    *,
    intent: str = "客户希望对茅台做全面尽调",
    focus: list[str] | None = None,
    exclusions: list[str] | None = None,
    llm_self: str = "high",
    target_ts: str = "600519.SH",
    target_name: str = "贵州茅台",
    turn_count: int = 5,
) -> EscalationPacket:
    return EscalationPacket(
        explicit_task=ExplicitTask(
            raw_last_user_turn="帮我做个茅台尽调",
            extracted_intent=intent,
            target_ts_code=target_ts,
            target_entity_name=target_name,
        ),
        chat_derived_signals=ChatDerivedSignals(
            entities=[Entity(name=target_name, ts_code=target_ts, role="primary_target")],
            extraction_confidence=0.85,
        ),
        known_facts=KnownFacts(),
        session_metadata=SessionMetadata(
            chat_session_id="sess1",
            chat_turn_count=turn_count,
            user_confirmed_at=_now(),
        ),
        escalation_intent=intent,
        discussion_focus=focus or ["担心负债率"],
        explicit_exclusions=exclusions or ["不关心 ESG"],
        llm_self_confidence=llm_self,
        confidence_rationale="ok",
    )


# ── env var ─────────────────────────────────────────────────────────────


def test_default_threshold_value() -> None:
    assert ESCALATION_CONFIDENCE_THRESHOLD_DEFAULT == 0.7


def test_get_confidence_threshold_uses_env_var() -> None:
    with patch.dict(os.environ, {"ESCALATION_CONFIDENCE_THRESHOLD": "0.85"}):
        assert get_confidence_threshold() == 0.85


def test_get_confidence_threshold_defaults_when_env_missing() -> None:
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("ESCALATION_CONFIDENCE_THRESHOLD", None)
        assert get_confidence_threshold() == ESCALATION_CONFIDENCE_THRESHOLD_DEFAULT


def test_get_confidence_threshold_invalid_env_falls_back_to_default() -> None:
    with patch.dict(os.environ, {"ESCALATION_CONFIDENCE_THRESHOLD": "not_a_number"}):
        assert get_confidence_threshold() == ESCALATION_CONFIDENCE_THRESHOLD_DEFAULT


# ── packet_to_research_state confidence gating ──────────────────────────


def test_high_conf_packet_populates_distilled_fields() -> None:
    """LLM=high + 5 turns + entities → conf 1.0 ≥ 0.7 → distilled fields set."""
    pkt = _mk_packet()
    state = packet_to_research_state(
        pkt,
        request_id="r1",
        chat_history=[type("M", (), {"content": "贵州茅台 600519.SH"})() for _ in range(5)],
    )
    assert state.escalation_intent == "客户希望对茅台做全面尽调"
    assert state.discussion_focus == ["担心负债率"]
    assert state.explicit_exclusions == ["不关心 ESG"]


def test_low_conf_packet_falls_back_form_style() -> None:
    """LLM=low → conf ≤ 0.3 < 0.7 → distilled fields cleared, user_message = raw_last_turn."""
    pkt = _mk_packet(llm_self="low")
    state = packet_to_research_state(
        pkt,
        request_id="r1",
        chat_history=[type("M", (), {"content": "贵州茅台"})() for _ in range(5)],
    )
    assert state.escalation_intent == ""
    assert state.discussion_focus == []
    assert state.explicit_exclusions == []
    assert state.user_message == "帮我做个茅台尽调"  # raw_last_user_turn fallback


def test_below_threshold_env_override() -> None:
    """env-set threshold can be lowered to let medium-conf through."""
    pkt = _mk_packet(llm_self="medium")  # conf=0.6
    with patch.dict(os.environ, {"ESCALATION_CONFIDENCE_THRESHOLD": "0.5"}):
        state = packet_to_research_state(
            pkt,
            request_id="r1",
            chat_history=[type("M", (), {"content": "贵州茅台"})() for _ in range(5)],
        )
        assert state.escalation_intent == "客户希望对茅台做全面尽调"


def test_packet_to_state_backwards_compat_no_history() -> None:
    """If caller doesn't pass chat_history, behaviour falls back (treat as low-conf)
    or compatibility path — old call sites still work.

    Choose behavior: when chat_history is None, treat conf as low → no
    distilled fields (safe default; tests can opt-in by passing history).
    """
    pkt = _mk_packet()
    state = packet_to_research_state(pkt, request_id="r1")
    # No history → cannot compute deterministic confidence → distilled empty
    assert state.escalation_intent == ""
    assert state.discussion_focus == []


def test_state_preserves_other_packet_fields() -> None:
    """Confidence gating must NOT affect other ResearchState fields."""
    pkt = _mk_packet()
    state = packet_to_research_state(pkt, request_id="r1")
    assert state.target_ts_code == "600519.SH"
    assert state.target_entity == "贵州茅台"
    assert state.chat_session_id == "sess1"
    assert state.user_id == "anonymous"
    assert len(state.chat_extracted_entities) == 1

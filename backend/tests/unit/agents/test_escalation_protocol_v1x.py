"""v1.x EscalationPacket — 3 distillation fields + llm_self_confidence."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.agents.escalation_protocol import (
    ChatDerivedSignals,
    EscalationPacket,
    ExplicitTask,
    KnownFacts,
    SessionMetadata,
)
from pydantic import ValidationError


def _now():
    return datetime.now(UTC)


def _base_kwargs(**overrides):
    base = {
        "explicit_task": ExplicitTask(raw_last_user_turn="x", extracted_intent="做尽调"),
        "chat_derived_signals": ChatDerivedSignals(extraction_confidence=0.8),
        "known_facts": KnownFacts(),
        "session_metadata": SessionMetadata(
            chat_session_id="s1",
            chat_turn_count=5,
            user_confirmed_at=_now(),
        ),
        "escalation_intent": "客户希望对贵州茅台做全面尽调",
        "discussion_focus": ["客户担心负债率", "对比五粮液"],
        "explicit_exclusions": ["不关心 ESG"],
        "llm_self_confidence": "high",
        "confidence_rationale": "对话明确,有 5 轮上下文",
    }
    base.update(overrides)
    return base


def test_packet_accepts_new_fields() -> None:
    p = EscalationPacket(**_base_kwargs())
    assert p.escalation_intent.startswith("客户希望")
    assert len(p.discussion_focus) == 2
    assert p.llm_self_confidence == "high"
    assert p.confidence_rationale.startswith("对话明确")


def test_packet_default_field_values() -> None:
    """Missing new fields → safe defaults."""
    p = EscalationPacket(
        explicit_task=ExplicitTask(raw_last_user_turn="x", extracted_intent="y"),
        chat_derived_signals=ChatDerivedSignals(extraction_confidence=0.5),
        known_facts=KnownFacts(),
        session_metadata=SessionMetadata(
            chat_session_id="s", chat_turn_count=1, user_confirmed_at=_now(),
        ),
    )
    assert p.escalation_intent == ""
    assert p.discussion_focus == []
    assert p.explicit_exclusions == []
    assert p.llm_self_confidence == "medium"
    assert p.confidence_rationale == ""


def test_packet_intent_max_length_200() -> None:
    with pytest.raises(ValidationError):
        EscalationPacket(**_base_kwargs(escalation_intent="x" * 201))


def test_packet_discussion_focus_max_items_5() -> None:
    with pytest.raises(ValidationError):
        EscalationPacket(**_base_kwargs(discussion_focus=["f1", "f2", "f3", "f4", "f5", "f6"]))


def test_packet_explicit_exclusions_max_items_3() -> None:
    with pytest.raises(ValidationError):
        EscalationPacket(**_base_kwargs(explicit_exclusions=["e1", "e2", "e3", "e4"]))


def test_packet_discussion_focus_item_length_30() -> None:
    """Each item ≤ 30 chars."""
    long_item = "x" * 31
    with pytest.raises(ValidationError) as exc:
        EscalationPacket(**_base_kwargs(discussion_focus=[long_item]))
    # Error message should help diagnose
    assert "discussion_focus" in str(exc.value) or "30" in str(exc.value)


def test_packet_explicit_exclusions_item_length_30() -> None:
    long_item = "y" * 31
    with pytest.raises(ValidationError):
        EscalationPacket(**_base_kwargs(explicit_exclusions=[long_item]))


def test_packet_llm_self_confidence_literal() -> None:
    """Only high/medium/low accepted."""
    with pytest.raises(ValidationError):
        EscalationPacket(**_base_kwargs(llm_self_confidence="super_high"))


def test_packet_confidence_rationale_max_length_100() -> None:
    with pytest.raises(ValidationError):
        EscalationPacket(**_base_kwargs(confidence_rationale="z" * 101))


def test_packet_serializes_with_new_fields() -> None:
    p = EscalationPacket(**_base_kwargs())
    d = p.model_dump()
    for k in ("escalation_intent", "discussion_focus", "explicit_exclusions",
              "llm_self_confidence", "confidence_rationale"):
        assert k in d


def test_packet_backwards_compatible_construction() -> None:
    """Old-shape construction (no v1.x fields) still works — only adds defaults."""
    p = EscalationPacket(
        explicit_task=ExplicitTask(raw_last_user_turn="x", extracted_intent="y"),
        chat_derived_signals=ChatDerivedSignals(extraction_confidence=0.5),
        known_facts=KnownFacts(),
        session_metadata=SessionMetadata(
            chat_session_id="s", chat_turn_count=1, user_confirmed_at=_now(),
        ),
        missing_field_hints=[],
    )
    assert p.llm_self_confidence == "medium"

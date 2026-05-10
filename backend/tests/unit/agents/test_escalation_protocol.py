"""L0 — EscalationPacket schema (E1)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.agents.escalation_protocol import (
    ChatDerivedSignals,
    Entity,
    EscalationPacket,
    ExplicitTask,
    FieldEdit,
    KnownFacts,
    MissingFieldHint,
    Preference,
    SessionMetadata,
    ToolResultRef,
)


def _now() -> datetime:
    return datetime.now(UTC)


def test_explicit_task_minimal():
    t = ExplicitTask(
        raw_last_user_turn="给我做一份 ICBC 完整尽调",
        extracted_intent="full_due_diligence",
    )
    assert t.target_ts_code is None
    assert t.target_entity_name is None
    assert t.user_extra_message is None


def test_entity_role_enum():
    e = Entity(
        name="工商银行",
        ts_code="601398.SH",
        role="primary_target",
        mention_turn_indices=[0, 2],
    )
    assert e.role == "primary_target"
    with pytest.raises(ValueError):
        Entity(name="X", ts_code=None, role="bogus_role", mention_turn_indices=[])


def test_preference_confidence_range():
    p = Preference(text="保守", category="risk_tolerance", confidence=0.85)
    assert 0 <= p.confidence <= 1
    with pytest.raises(ValueError):
        Preference(text="x", category="risk_tolerance", confidence=1.5)


def test_full_escalation_packet_roundtrip():
    pkt = EscalationPacket(
        explicit_task=ExplicitTask(
            raw_last_user_turn="深度尽调一下 ICBC",
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
                    mention_turn_indices=[0, 2, 4],
                ),
                Entity(
                    name="招商银行",
                    ts_code="600036.SH",
                    role="comparative_target",
                    mention_turn_indices=[3],
                ),
            ],
            preferences=[
                Preference(text="风控优先", category="risk_tolerance", confidence=0.9),
            ],
            open_questions=["招行的不良率怎么样"],
            inferred_persona="保守型零售投资者",
            extraction_confidence=0.78,
        ),
        known_facts=KnownFacts(
            tool_results=[
                ToolResultRef(
                    tool_name="get_stock_quote",
                    tool_args={"ts_code": "601398.SH"},
                    result_summary="现价 6.45 元",
                    cached_at=_now(),
                    cache_id="anon::get_stock_quote::abc123",
                ),
            ],
        ),
        session_metadata=SessionMetadata(
            chat_session_id="chat-abc123",
            chat_turn_count=5,
            chat_history_summary="用户问 ICBC 现价 + 不良率, 又对比招行",
            user_confirmed_at=_now(),
            user_edits=[
                FieldEdit(
                    field_path="chat_derived_signals.preferences[0].text",
                    llm_value="风控优先",
                    user_value="风控优先 + 长线持有",
                    edit_type="modify",
                ),
            ],
        ),
        missing_field_hints=[
            MissingFieldHint(
                field_path="explicit_task.target_ts_code",
                reason="llm_uncertain",
                llm_question_for_user="您说的 ICBC 是工商银行 (601398.SH) 吗?",
            ),
        ],
    )
    j = pkt.model_dump_json()
    restored = EscalationPacket.model_validate_json(j)
    assert restored.explicit_task.target_ts_code == "601398.SH"
    assert len(restored.chat_derived_signals.entities) == 2
    assert restored.session_metadata.user_edits[0].edit_type == "modify"
    assert restored.missing_field_hints[0].reason == "llm_uncertain"


def test_field_edit_types():
    for etype in ("modify", "delete", "add"):
        e = FieldEdit(field_path="x.y", llm_value="a", user_value="b", edit_type=etype)
        assert e.edit_type == etype
    with pytest.raises(ValueError):
        FieldEdit(field_path="x", llm_value=None, user_value=None, edit_type="bogus")


def test_missing_field_hint_reason_enum():
    for reason in ("llm_uncertain", "schema_required_but_empty", "user_skipped"):
        h = MissingFieldHint(field_path="x", reason=reason, llm_question_for_user="?")
        assert h.reason == reason


def test_packet_with_minimal_fields():
    pkt = EscalationPacket(
        explicit_task=ExplicitTask(
            raw_last_user_turn="x",
            extracted_intent="unknown",
        ),
        chat_derived_signals=ChatDerivedSignals(),
        known_facts=KnownFacts(),
        session_metadata=SessionMetadata(
            chat_session_id="s1",
            chat_turn_count=1,
            chat_history_summary=None,
            user_confirmed_at=_now(),
        ),
    )
    assert pkt.missing_field_hints == []

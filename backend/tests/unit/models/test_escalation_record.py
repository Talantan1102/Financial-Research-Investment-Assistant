"""L0 — EscalationRecord ORM."""

from __future__ import annotations

from app.models.escalation_record import EscalationRecord


def test_escalation_record_mapper_has_required_fields():
    """Mapper-level field presence (avoids needing a real session)."""
    cols = {c.name for c in EscalationRecord.__table__.columns}
    expected = {
        "id",
        "session_id",
        "packet_draft",
        "packet_confirmed",
        "user_edits",
        "research_report_id",
        "status",
        "created_at",
        "confirmed_at",
        "completed_at",
        "error_msg",
    }
    assert expected.issubset(cols), f"missing: {expected - cols}"


def test_escalation_record_status_default_is_draft():
    """Default status column value is 'draft' at mapper level."""
    status_col = EscalationRecord.__table__.columns["status"]
    assert status_col.default is not None
    assert status_col.default.arg == "draft"


def test_escalation_record_session_id_cascades_on_delete():
    """FK to chat_sessions has ON DELETE CASCADE."""
    fks = list(EscalationRecord.__table__.columns["session_id"].foreign_keys)
    assert len(fks) == 1
    assert fks[0].ondelete == "CASCADE"


def test_escalation_record_research_report_id_set_null_on_delete():
    fks = list(EscalationRecord.__table__.columns["research_report_id"].foreign_keys)
    assert len(fks) == 1
    assert fks[0].ondelete == "SET NULL"

"""EscalationRecord ORM — chat→research escalation persistence (E12 trace)."""

from __future__ import annotations

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


class EscalationRecord(Base):
    __tablename__ = "escalation_records"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    packet_draft = Column(JSONB(), nullable=False)
    packet_confirmed = Column(JSONB(), nullable=True)
    user_edits = Column(JSONB(), nullable=True)

    # research_reports.id is VARCHAR(64), not UUID
    research_report_id = Column(
        String(64),
        ForeignKey("research_reports.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    status = Column(String(16), nullable=False, default="draft", server_default="draft", index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_msg = Column(String(2048), nullable=True)

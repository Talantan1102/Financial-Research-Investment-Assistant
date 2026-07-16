"""Persistent run-control domain models."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base
from app.run_control.types import ACTIVE_RUN_STATUSES, AttemptStatus, PauseType, RunStatus


def _quoted_values(values: list[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


_RUN_STATUS_VALUES = [status.value for status in RunStatus]
_ATTEMPT_STATUS_VALUES = [status.value for status in AttemptStatus]
_ACTIVE_RUN_STATUS_VALUES = sorted(status.value for status in ACTIVE_RUN_STATUSES)
_PAUSE_TYPE_VALUES = [pause_type.value for pause_type in PauseType]


class RunSession(Base):
    __tablename__ = "run_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    title = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_run_sessions_tenant_id"),
    )


class RunMessage(Base):
    __tablename__ = "run_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    session_id = Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    role = Column(String(32), nullable=False)
    content = Column(Text, nullable=False)
    status = Column(String(32), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "session_id"],
            ["run_sessions.tenant_id", "run_sessions.id"],
            name="fk_run_messages_tenant_session",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id",
            "session_id",
            "id",
            name="uq_run_messages_tenant_session_id",
        ),
    )


class Run(Base):
    __tablename__ = "runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True),
        nullable=False,
    )
    session_id = Column(
        UUID(as_uuid=True),
        nullable=False,
    )
    created_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    run_type = Column(String(32), nullable=False, default="chat")
    status = Column(String(32), nullable=False)
    idempotency_key = Column(String(255), nullable=False)
    request_hash = Column(String(64), nullable=False)
    input_message_id = Column(
        UUID(as_uuid=True),
        nullable=False,
    )
    final_message_id = Column(
        UUID(as_uuid=True),
        nullable=True,
    )
    replaces_run_id = Column(
        UUID(as_uuid=True),
        nullable=True,
    )
    retry_count = Column(Integer, nullable=False, default=0)
    queue_reason = Column(String(64), nullable=True)
    error_code = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    queued_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    assigned_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    cancel_requested_at = Column(DateTime, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "session_id"],
            ["run_sessions.tenant_id", "run_sessions.id"],
            name="fk_runs_tenant_session",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "session_id", "input_message_id"],
            ["run_messages.tenant_id", "run_messages.session_id", "run_messages.id"],
            name="fk_runs_input_message_provenance",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "session_id", "final_message_id"],
            ["run_messages.tenant_id", "run_messages.session_id", "run_messages.id"],
            name="fk_runs_final_message_provenance",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "session_id", "created_by_user_id", "replaces_run_id"],
            ["runs.tenant_id", "runs.session_id", "runs.created_by_user_id", "runs.id"],
            name="fk_runs_replacement_provenance",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "tenant_id",
            "created_by_user_id",
            "idempotency_key",
            name="uq_run_idempotency",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_runs_tenant_id"),
        UniqueConstraint(
            "tenant_id",
            "session_id",
            "created_by_user_id",
            "id",
            name="uq_runs_replacement_identity",
        ),
        CheckConstraint("run_type = 'chat'", name="ck_runs_chat_type"),
        CheckConstraint(
            f"status IN ({_quoted_values(_RUN_STATUS_VALUES)})",
            name="ck_runs_fixed_status",
        ),
        CheckConstraint("retry_count BETWEEN 0 AND 1", name="ck_runs_retry_count"),
        Index(
            "uq_run_one_nonterminal_per_session",
            "session_id",
            unique=True,
            postgresql_where=text(
                f"status IN ({_quoted_values(_ACTIVE_RUN_STATUS_VALUES)})"
            ),
        ),
        Index("ix_runs_tenant_status_queued_at", "tenant_id", "status", "queued_at"),
    )


class RunAttempt(Base):
    __tablename__ = "run_attempts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attempt_no = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False)
    worker_id = Column(String(255), nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    error_code = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("run_id", "attempt_no", name="uq_run_attempt_no"),
        UniqueConstraint("run_id", "id", name="uq_run_attempt_identity"),
        CheckConstraint(
            f"status IN ({_quoted_values(_ATTEMPT_STATUS_VALUES)})",
            name="ck_run_attempts_fixed_status",
        ),
    )


class RunPause(Base):
    __tablename__ = "run_pauses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pause_no = Column(Integer, nullable=False)
    pause_type = Column(String(32), nullable=False)
    request_payload = Column(JSONB, nullable=False)
    continuation_payload = Column(JSONB, nullable=False)
    response_payload = Column(JSONB, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("run_id", "pause_no", name="uq_run_pause_no"),
        CheckConstraint(
            f"pause_type IN ({_quoted_values(_PAUSE_TYPE_VALUES)})",
            name="ck_run_pauses_fixed_type",
        ),
    )


class RunEvent(Base):
    __tablename__ = "run_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    run_id = Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    attempt_id = Column(
        UUID(as_uuid=True),
        nullable=True,
    )
    seq = Column(Integer, nullable=False)
    event_type = Column(String(128), nullable=False)
    payload = Column(JSONB, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["runs.tenant_id", "runs.id"],
            name="fk_run_events_tenant_run",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["run_id", "attempt_id"],
            ["run_attempts.run_id", "run_attempts.id"],
            name="fk_run_events_attempt_provenance",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("run_id", "seq", name="uq_run_event_seq"),
    )

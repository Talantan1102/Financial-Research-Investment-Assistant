"""PostgreSQL scheduling and transactional-outbox models for run control."""

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
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base
from app.run_control.types import OutboxType, WorkerStatus


def _quoted_values(values: list[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


_WORKER_STATUS_VALUES = [status.value for status in WorkerStatus]
_OUTBOX_TYPE_VALUES = [event_type.value for event_type in OutboxType]


class RunWorker(Base):
    __tablename__ = "run_workers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    worker_type = Column(String(32), nullable=False, default="chat")
    capacity = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False)
    heartbeat_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_assigned_at = Column(DateTime, nullable=True)
    metadata_payload = Column("metadata", JSONB, nullable=False, default=dict)

    __table_args__ = (
        CheckConstraint("worker_type = 'chat'", name="ck_run_workers_chat_type"),
        CheckConstraint("capacity > 0", name="ck_run_workers_positive_capacity"),
        CheckConstraint(
            f"status IN ({_quoted_values(_WORKER_STATUS_VALUES)})",
            name="ck_run_workers_fixed_status",
        ),
    )


class RunTenantScheduling(Base):
    __tablename__ = "run_tenant_scheduling"

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    last_dispatched_at = Column(DateTime, nullable=True)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class RunOutbox(Base):
    __tablename__ = "run_outbox"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type = Column(String(64), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    run_id = Column(UUID(as_uuid=True), nullable=False)
    attempt_id = Column(UUID(as_uuid=True), nullable=True)
    worker_id = Column(UUID(as_uuid=True), nullable=True)
    payload = Column(JSONB, nullable=False, default=dict)
    dedupe_key = Column(String(255), nullable=False)
    available_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    claimed_at = Column(DateTime, nullable=True)
    claimed_by = Column(String(255), nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    next_attempt_at = Column(DateTime, nullable=True)
    delivery_attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["runs.tenant_id", "runs.id"],
            name="fk_run_outbox_tenant_run",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["run_id", "attempt_id"],
            ["run_attempts.run_id", "run_attempts.id"],
            name="fk_run_outbox_attempt_provenance",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["run_id", "attempt_id", "worker_id"],
            ["run_attempts.run_id", "run_attempts.id", "run_attempts.worker_id"],
            name="fk_run_outbox_attempt_worker_provenance",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("dedupe_key", name="uq_run_outbox_dedupe_key"),
        CheckConstraint(
            f"event_type IN ({_quoted_values(_OUTBOX_TYPE_VALUES)})",
            name="ck_run_outbox_fixed_type",
        ),
        CheckConstraint(
            "delivery_attempts >= 0",
            name="ck_run_outbox_nonnegative_delivery_attempts",
        ),
        CheckConstraint(
            "worker_id IS NULL OR attempt_id IS NOT NULL",
            name="ck_run_outbox_worker_requires_attempt",
        ),
        Index("ix_run_outbox_next_attempt_at", "next_attempt_at"),
    )

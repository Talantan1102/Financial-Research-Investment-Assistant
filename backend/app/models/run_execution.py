"""Persistent tool-ledger and model-usage facts for Run execution."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base

_TOOL_EXECUTION_STATUSES = ("started", "completed", "failed", "approval_required")


def _quoted_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class RunToolExecution(Base):
    __tablename__ = "run_tool_executions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attempt_id = Column(UUID(as_uuid=True), nullable=False)
    tool_call_id = Column(String(255), nullable=False)
    idempotency_key = Column(String(255), nullable=False)
    semantic_key = Column(String(64), nullable=False)
    tool_name = Column(String(255), nullable=False)
    request_summary = Column(JSONB, nullable=False)
    safe_to_retry = Column(Boolean, nullable=False, default=False)
    status = Column(String(32), nullable=False)
    reservation_token = Column(UUID(as_uuid=True), nullable=True)
    reservation_expires_at = Column(DateTime, nullable=True)
    execution_epoch = Column(Integer, nullable=False, default=0)
    result_summary = Column(JSONB(none_as_null=True), nullable=True)
    error_code = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "attempt_id"],
            ["run_attempts.run_id", "run_attempts.id"],
            name="fk_run_tool_executions_attempt_provenance",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("run_id", "idempotency_key", name="uq_run_tool_idempotency"),
        CheckConstraint(
            f"status IN ({_quoted_values(_TOOL_EXECUTION_STATUSES)})",
            name="ck_run_tool_executions_fixed_status",
        ),
        CheckConstraint(
            "octet_length(request_summary::text) <= 16384",
            name="ck_run_tool_request_summary_size",
        ),
        CheckConstraint(
            "result_summary IS NULL OR octet_length(result_summary::text) <= 65536",
            name="ck_run_tool_result_summary_size",
        ),
        CheckConstraint(
            "execution_epoch >= 0",
            name="ck_run_tool_execution_epoch_nonnegative",
        ),
        CheckConstraint(
            "(status = 'started' AND finished_at IS NULL "
            "AND result_summary IS NULL AND error_code IS NULL AND error_message IS NULL "
            "AND reservation_token IS NOT NULL AND reservation_expires_at IS NOT NULL "
            "AND execution_epoch > 0) "
            "OR (status = 'completed' AND finished_at IS NOT NULL "
            "AND result_summary IS NOT NULL AND error_code IS NULL AND error_message IS NULL) "
            "OR (status = 'failed' AND finished_at IS NOT NULL "
            "AND result_summary IS NULL AND (error_code IS NOT NULL OR error_message IS NOT NULL)) "
            "OR (status = 'approval_required' AND finished_at IS NULL "
            "AND result_summary IS NULL AND error_code IS NULL AND error_message IS NULL "
            "AND reservation_token IS NULL AND reservation_expires_at IS NULL)",
            name="ck_run_tool_execution_row_shape",
        ),
        Index("ix_run_tool_semantic_recovery", "run_id", "semantic_key", "status"),
    )


class RunUsageRecord(Base):
    __tablename__ = "run_usage_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attempt_id = Column(UUID(as_uuid=True), nullable=False)
    provider = Column(String(64), nullable=False)
    model = Column(String(255), nullable=False)
    input_tokens = Column(Integer, nullable=False)
    output_tokens = Column(Integer, nullable=False)
    cached_tokens = Column(Integer, nullable=False)
    total_tokens = Column(Integer, nullable=False)
    cost_cny = Column(Numeric(18, 8), nullable=False, default=Decimal("0"))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "attempt_id"],
            ["run_attempts.run_id", "run_attempts.id"],
            name="fk_run_usage_records_attempt_provenance",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "input_tokens >= 0",
            name="ck_run_usage_input_tokens_nonnegative",
        ),
        CheckConstraint(
            "output_tokens >= 0",
            name="ck_run_usage_output_tokens_nonnegative",
        ),
        CheckConstraint(
            "cached_tokens >= 0",
            name="ck_run_usage_cached_tokens_nonnegative",
        ),
        CheckConstraint(
            "total_tokens >= 0",
            name="ck_run_usage_total_tokens_nonnegative",
        ),
        CheckConstraint(
            "total_tokens = input_tokens + output_tokens",
            name="ck_run_usage_total_consistent",
        ),
        CheckConstraint(
            "cached_tokens <= input_tokens",
            name="ck_run_usage_cached_within_input",
        ),
        CheckConstraint("cost_cny >= 0", name="ck_run_usage_cost_cny_nonnegative"),
        Index("ix_run_usage_model_total_tokens", "model", "total_tokens"),
    )

"""Posterior calibration weekly job audit model(spec § 11 末尾 #3).

每次 weekly calibration 一行, 审计 importance 三档调整.
SQL DDL: backend/scripts/migrations/2026-05-11-c5-plan5-calibration-table.sql
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import (
    UUID as PgUUID,  # noqa: N811  (PG-specific UUID type alias to avoid clash with stdlib uuid.UUID)
)
from sqlalchemy.sql import func

from app.core.database import Base


class ChatMemoryCalibrationRun(Base):
    """每次 weekly calibration 一行, 审计 importance 三档调整."""

    __tablename__ = "chat_memory_calibration_runs"

    run_id = Column(PgUUID(as_uuid=True), primary_key=True)
    started_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    finished_at = Column(DateTime(timezone=True))
    scanned_edges = Column(Integer, nullable=False, default=0)
    promoted_to_high = Column(Integer, nullable=False, default=0)
    demoted_to_medium = Column(Integer, nullable=False, default=0)
    overridden_to_low = Column(Integer, nullable=False, default=0)
    status = Column(String(32), nullable=False, default="running")
    error_message = Column(Text)

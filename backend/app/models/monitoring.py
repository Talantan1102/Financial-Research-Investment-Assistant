"""Monitoring SQLAlchemy models — v1.0 持仓监控 主 PG 落地(决策 5).

设计 ref: docs/superpowers/specs/2026-05-08-v1.0-portfolio-monitoring-engine-design.md § 3.1
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class DetailStatus(StrEnum):
    """spec § 3.2 详情卡状态机。"""

    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class MonitoringRun(Base):
    """一次 detection cycle 的 metadata."""

    __tablename__ = "monitoring_runs"

    id = Column(String(36), primary_key=True)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,  # NULL when triggered for full scan (no per-user filter)
        index=True,
    )
    cycle_id = Column(String(36), nullable=False, index=True)  # 一个 cycle 内多 user run 共享
    trigger_type = Column(String(32), nullable=False)  # cron / disclosure / manual
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String(16), nullable=False, default="running")  # running / success / failed
    error_message = Column(String(2048), nullable=True)
    cost_cny = Column(Float, nullable=False, default=0.0)

    __table_args__ = (UniqueConstraint("cycle_id", "user_id", name="uq_runs_cycle_user"),)


class MonitoringSignal(Base):
    """单条 SignalRule 判定结果。"""

    __tablename__ = "monitoring_signals"

    id = Column(String(36), primary_key=True)
    run_id = Column(
        String(36), ForeignKey("monitoring_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ts_code = Column(String(10), nullable=False, index=True)
    rule_name = Column(String(64), nullable=False)
    level = Column(String(16), nullable=False)  # green / yellow / red
    detected_value = Column(String(64), nullable=True)
    threshold = Column(String(64), nullable=True)
    explanation = Column(String(1024), nullable=True)
    raw_data_ref = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class MonitoringAlert(Base):
    """异动详情卡(标红 alert)。spec § 3.2 detail_status 状态机."""

    __tablename__ = "monitoring_alerts"

    id = Column(String(36), primary_key=True)
    run_id = Column(
        String(36), ForeignKey("monitoring_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ts_code = Column(String(10), nullable=False, index=True)
    alert_level = Column(String(16), nullable=False)  # yellow / red
    report_json = Column(JSON, nullable=False, default=dict)
    report_markdown = Column(String, nullable=True)  # TEXT in PG
    detail_status = Column(String(16), nullable=False, default=DetailStatus.PENDING)
    error_message = Column(String(2048), nullable=True)
    escalated = Column(Boolean, nullable=False, default=False)
    escalation_status = Column(String(32), nullable=True)
    deep_dive_text = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    notifications = relationship(
        "Notification", back_populates="alert", cascade="all, delete-orphan"
    )


class Notification(Base):
    """邮件 / in-app 通知发送记录。"""

    __tablename__ = "notifications"

    id = Column(String(36), primary_key=True)
    alert_id = Column(
        String(36),
        ForeignKey("monitoring_alerts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    channel = Column(String(16), nullable=False)  # in_app / email
    recipient = Column(String(256), nullable=True)
    sent_at = Column(DateTime, nullable=True)
    send_status = Column(String(16), nullable=False)  # sent / failed
    error_message = Column(String(2048), nullable=True)
    read_at = Column(DateTime, nullable=True)

    alert = relationship("MonitoringAlert", back_populates="notifications")

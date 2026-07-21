"""ResearchReport SQLAlchemy model — v0.9.x 研报持久化层.

设计 ref: docs/superpowers/specs/2026-05-06-v0.9.x-frontend-rebuild-design.md § 7.2

不与 ResearchCheckpoint(LangGraph state)冲突,共存,用途不同:
- ResearchCheckpoint:LangGraph 状态保存,中断后恢复(running/paused state)
- ResearchReport:最终研报 JSON 持久化,前端历史列表 + 详情展示用(InvestmentDueDiligenceReport)

类型选型:
- 生产 = PostgreSQL,使用 JSONB / UUID native 类型
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Column, DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class ResearchReport(Base):
    """投资尽调研报最终持久化记录."""

    __tablename__ = "research_reports"

    # 主键:研报 ID — 通常等于 LangGraph thread_id 或单独 uuid
    id = Column(String(64), primary_key=True)

    # FK → users.id (UUID(as_uuid=True) in production)
    # nullable=True 允许 anon / pre-auth 流程
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # 业务字段
    target_name = Column(String(128), nullable=False, index=True)
    target_ts_code = Column(String(16), nullable=True, index=True)
    status = Column(String(16), nullable=False)  # streaming|completed|failed

    # InvestmentDueDiligenceReport 完整 JSON
    report_json = Column(JSONB(), nullable=False)

    # 成本(LLM 调用累计 ¥)
    cost = Column(Numeric(10, 2), nullable=False, default=Decimal("0"))

    # 时间戳
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # JOIN trace 用 (TraceService request_id)
    request_id = Column(String(64), nullable=True, index=True)

    # chat→research 升级链路溯源 (E13/E14)
    # ON DELETE SET NULL: 删 chat session 时保留研报记录
    source_chat_session_id = Column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    source_session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("run_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_run_id = Column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # 关系
    user = relationship("User", backref="research_reports")

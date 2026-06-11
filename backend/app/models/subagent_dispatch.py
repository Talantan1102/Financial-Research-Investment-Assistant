"""subagent_dispatch_runs — chat 内子 agent 派发审计表(spec 2026-06-11 §8.2)。

一行 = 一个子循环。批次字段(batch_id/scenario_type)去规范化到每行,聚合用。
create_all 幂等建表(项目不引 alembic)。
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.core.database import Base


class SubagentDispatchRun(Base):
    __tablename__ = "subagent_dispatch_runs"

    id = Column(String(64), primary_key=True)
    batch_id = Column(String(64), nullable=False)
    parent_request_id = Column(String(64), nullable=False)
    turn_id = Column(String(64), nullable=True)
    scenario_type = Column(String(32), nullable=True)
    subtask_id = Column(String(64), nullable=False)
    goal_packet = Column(JSONB(), nullable=False, default=dict)
    tool_scope = Column(JSONB(), nullable=False, default=list)
    result_summary = Column(Text, nullable=True)
    result_refs = Column(JSONB(), nullable=False, default=list)
    status = Column(String(16), nullable=False)
    gap_note = Column(Text, nullable=True)
    tokens = Column(Integer, nullable=False, default=0)
    cost_cny = Column(Float, nullable=False, default=0.0)
    steps_used = Column(Integer, nullable=False, default=0)
    duration_ms = Column(Integer, nullable=False, default=0)
    tier = Column(String(16), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_subagent_batch", "batch_id"),
        Index("idx_subagent_parent_req", "parent_request_id"),
        Index("idx_subagent_scenario", "scenario_type"),
        Index("idx_subagent_status", "status"),
        Index("idx_subagent_created", "created_at"),
    )

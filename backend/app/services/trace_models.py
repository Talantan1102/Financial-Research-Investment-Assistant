"""Span + TraceTree — the in-memory shape of one trace.

`Span` is the wire format and the SQLite row format (1:1). `TraceTree` is a
view-model built from a set of spans sharing a request_id. Both are stable
across v0~v3 per spec § 9 — adding fields is fine, renaming/removing breaks
all downstream consumers (eval reader, future trace exporter).

Plan 4 ship (C.5): MCPToolCallLog SQLAlchemy table — spec § 6 周报 SQL data
source. Each row = one MCP tool invocation with latency / result count / error.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import (
    UUID as PgUUID,  # noqa: N811  (re-alias to disambiguate from stdlib uuid.UUID)
)
from sqlalchemy.sql import func

from app.core.database import Base


class Span(BaseModel):
    model_config = ConfigDict(frozen=True)

    span_id: str
    request_id: str
    parent_id: str | None
    name: str
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    metadata: dict[str, Any]
    started_at: datetime
    ended_at: datetime
    error: str | None

    @model_validator(mode="after")
    def _check_times(self) -> Span:
        if self.ended_at < self.started_at:
            raise ValueError("ended_at must be >= started_at")
        return self

    @property
    def latency_ms(self) -> int:
        return int((self.ended_at - self.started_at).total_seconds() * 1000)


class TraceTree(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    request_id: str
    root_span: Span
    root_span_children: list[Span]
    total_latency_ms: int
    total_cost_cny: float
    cache_hit_rate: float

    @classmethod
    def from_spans(cls, spans: list[Span]) -> TraceTree:
        if not spans:
            raise ValueError("from_spans called with empty list")
        request_ids = {s.request_id for s in spans}
        if len(request_ids) != 1:
            raise ValueError(f"spans must share one request_id, got {request_ids}")
        request_id = next(iter(request_ids))
        roots = [s for s in spans if s.parent_id is None]
        if not roots:
            raise ValueError("no root span (all spans have a parent_id)")
        if len(roots) > 1:
            raise ValueError(f"multiple root spans: {[s.span_id for s in roots]}")
        root = roots[0]
        children = [s for s in spans if s.parent_id == root.span_id]
        cache_hits = [bool(s.metadata.get("cache_hit", False)) for s in spans]
        return cls(
            request_id=request_id,
            root_span=root,
            root_span_children=children,
            total_latency_ms=root.latency_ms,
            total_cost_cny=sum(float(s.metadata.get("cost_cny", 0.0)) for s in spans),
            cache_hit_rate=(sum(cache_hits) / len(cache_hits)) if cache_hits else 0.0,
        )


# ---------------------------------------------------------------------------
# C.5 Plan 4: MCPToolCallLog — tool routing 监控 SQL data source.
# Each MCP tool invocation appends one row (Plan 4 _common.write_tool_call_log).
# Queried by backend/scripts/memory/weekly_tool_routing_report.sql.
# ---------------------------------------------------------------------------

# L0 sqlite override-friendly variants
_UUID_COL = PgUUID(as_uuid=True).with_variant(String(36), "sqlite")
_JSONB_COL = JSONB().with_variant(JSON, "sqlite")


class MCPToolCallLog(Base):
    """One row per MCP tool invocation — drives spec § 6 weekly routing report.

    user_id stored as String to match PR #39 trace's legacy str habit (not
    PgUUID) — keeps 周报 SQL filter expressions simple and avoids casting.
    """

    __tablename__ = "mcp_tool_call_log"

    id = Column(_UUID_COL, primary_key=True, default=uuid4)
    user_id = Column(String(64), nullable=False)
    tool_name = Column(String(64), nullable=False)
    args_json = Column(_JSONB_COL, nullable=False, default=dict)
    result_count = Column(Integer, nullable=False, default=0)
    latency_ms = Column(Float, nullable=False, default=0.0)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        # 周报 SQL 按 tool_name + created_at 过滤
        Index("idx_mcp_tool_call_log_tool_created", "tool_name", "created_at"),
        # per-user routing 报表
        Index("idx_mcp_tool_call_log_user", "user_id"),
    )

"""ToolResultCache ORM — per-tool TTL cache, user_id namespaced (G2)."""

from __future__ import annotations

from sqlalchemy import JSON, Column, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base


class ToolResultCacheRow(Base):
    __tablename__ = "tool_result_cache"

    cache_key = Column(String(128), primary_key=True)  # u_id||tool||hash
    user_id = Column(String(64), nullable=False, index=True)
    tool_name = Column(String(64), nullable=False, index=True)
    args = Column(JSONB().with_variant(JSON, "sqlite"), nullable=False)
    result = Column(JSONB().with_variant(JSON, "sqlite"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)

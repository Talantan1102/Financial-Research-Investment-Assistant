"""User-owned watchlist state and append-only mutation audits."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ts_code = Column(String(10), nullable=False)
    name = Column(String(50), nullable=False)
    note = Column(Text, nullable=True)
    monitoring_enabled = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "ts_code",
            name="uq_watchlist_items_user_ts_code",
        ),
    )


class WatchlistAudit(Base):
    """Immutable history: the application only inserts audit rows."""

    __tablename__ = "watchlist_audits"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_id = Column(
        UUID(as_uuid=True),
        ForeignKey("watchlist_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action = Column(String(16), nullable=False)
    before_json = Column(JSONB(none_as_null=True), nullable=True)
    after_json = Column(JSONB(none_as_null=True), nullable=True)
    source_session_id = Column(String(128), nullable=True)
    source_tool_call_id = Column(String(128), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    @property
    def session_id(self) -> str | None:
        return self.source_session_id

    @property
    def tool_call_id(self) -> str | None:
        return self.source_tool_call_id

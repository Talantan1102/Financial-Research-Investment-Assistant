"""User-owned watchlist state and append-only mutation audits."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    DDL,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    event,
    false,
    func,
    text,
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
        Index(
            "ix_watchlist_items_monitoring_enabled_true",
            "user_id",
            "ts_code",
            postgresql_where=text("monitoring_enabled IS TRUE"),
        ),
    )


class WatchlistAudit(Base):
    """Immutable history: the application only inserts audit rows."""

    __tablename__ = "watchlist_audits"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_id = Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
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


event.listen(
    WatchlistAudit.__table__,
    "after_create",
    DDL(
        """
        CREATE OR REPLACE FUNCTION reject_watchlist_audit_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'watchlist_audits are append-only'
                USING ERRCODE = '55000';
        END;
        $$ LANGUAGE plpgsql
        """
    ).execute_if(dialect="postgresql"),
)
event.listen(
    WatchlistAudit.__table__,
    "after_create",
    DDL(
        """
        CREATE TRIGGER watchlist_audits_append_only
        BEFORE UPDATE OR DELETE ON watchlist_audits
        FOR EACH ROW EXECUTE FUNCTION reject_watchlist_audit_mutation()
        """
    ).execute_if(dialect="postgresql"),
)

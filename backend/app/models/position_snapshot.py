import datetime

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class PositionSnapshot(Base):
    __tablename__ = "position_snapshots"

    id = Column(String(36), primary_key=True)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    ts_code = Column(String(10), nullable=False, index=True)
    asset_class = Column(String(32), nullable=False, default="stock")
    snapshot_date = Column(Date, nullable=False, index=True)
    quantity = Column(Integer, nullable=False)
    market_price = Column(Numeric(12, 4), nullable=False)
    market_value = Column(Numeric(14, 2), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "ts_code", "snapshot_date", name="uq_snapshot_user_code_date"),
        Index("idx_snapshot_user_date", "user_id", "snapshot_date"),
    )

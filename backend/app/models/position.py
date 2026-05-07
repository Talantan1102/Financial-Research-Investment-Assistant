"""Position SQLAlchemy model — v1.0 持仓监控 materialized 状态(决策 1).

设计 ref: docs/superpowers/specs/2026-05-07-v1.0-portfolio-data-model-engineering-design.md § 2.2

不变量:Trade 写完后 Position 跟 Trade 严格一致(单事务保证)。
清仓再回来:quantity 重算到 0 时保留行(realized_pnl 累计有价值),
用户再买入是同一行 UPDATE 而不是新建。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class Position(Base):
    """用户在某只股上的当前状态快照(quantity / avg_cost / realized_pnl / 现价 cache)。"""

    __tablename__ = "positions"

    id = Column(String(36), primary_key=True)

    user_id = Column(
        UUID(as_uuid=True).with_variant(String(36), "sqlite"),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    ts_code = Column(String(10), nullable=False, index=True)
    name = Column(String(50), nullable=False)
    quantity = Column(Integer, nullable=False, default=0)
    avg_cost = Column(Numeric(12, 4), nullable=False, default=Decimal("0"))
    total_cost = Column(Numeric(14, 2), nullable=False, default=Decimal("0"))
    realized_pnl = Column(Numeric(14, 2), nullable=False, default=Decimal("0"))

    # 决策 3:监控引擎 30min 周期写入,dashboard 读取算浮盈
    last_quote_price = Column(Numeric(12, 4), nullable=True)
    last_quote_at = Column(DateTime, nullable=True)

    # v1.x 静默仓位口子(spec § 7)
    is_silenced = Column(Boolean, nullable=False, default=False)

    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", backref="positions")

    __table_args__ = (UniqueConstraint("user_id", "ts_code", name="uq_positions_user_tscode"),)

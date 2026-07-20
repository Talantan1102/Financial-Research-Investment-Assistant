"""Trade SQLAlchemy model — v1.0 持仓监控 SoT(交易记录,immutable except type=initial).

设计 ref: docs/superpowers/specs/2026-05-07-v1.0-portfolio-data-model-engineering-design.md § 2.1

类型选型:
- 生产 = PostgreSQL,使用 UUID native + Numeric
"""

from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class TradeType(enum.Enum):
    """三态:initial(虚拟初始仓位,始终可改)/ buy / sell。"""

    INITIAL = "initial"
    BUY = "buy"
    SELL = "sell"


class Trade(Base):
    """用户录入的单笔交易记录(SoT)。Position 表从 Trade 全集 fold 出。"""

    __tablename__ = "trades"

    id = Column(String(36), primary_key=True)

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    ts_code = Column(String(10), nullable=False, index=True)
    name = Column(String(50), nullable=False)
    type = Column(Enum(TradeType), nullable=False)
    quantity = Column(Integer, nullable=False)
    price = Column(Numeric(18, 4), nullable=False)
    trade_date = Column(Date, nullable=False, default=date.today)
    note = Column(Text, nullable=True)
    paper_account_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    paper_account_generation = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    user = relationship("User", backref="trades")

    __table_args__ = (
        ForeignKeyConstraint(
            ["paper_account_id", "user_id", "paper_account_generation"],
            ["paper_accounts.id", "paper_accounts.user_id", "paper_accounts.generation"],
            name="fk_trades_paper_account_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(paper_account_id IS NULL) = (paper_account_generation IS NULL)",
            name="ck_trades_paper_scope_all_or_none",
        ),
        Index("ix_trades_user_tscode_date", "user_id", "ts_code", "trade_date"),
    )

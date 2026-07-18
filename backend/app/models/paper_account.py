"""PostgreSQL models for versioned simulated trading accounts."""

from __future__ import annotations

import enum
import uuid
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


class PaperAccountStatus(enum.StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"


_ACCOUNT_STATUS = Enum(
    PaperAccountStatus,
    name="paper_account_status",
    values_callable=lambda members: [member.value for member in members],
    validate_strings=True,
)


class PaperAccount(Base):
    __tablename__ = "paper_accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    generation = Column(Integer, nullable=False)
    initial_cash = Column(Numeric(18, 2), nullable=False)
    available_cash = Column(Numeric(18, 2), nullable=False)
    frozen_cash = Column(Numeric(18, 2), nullable=False)
    commission_rate = Column(Numeric(10, 8), nullable=False)
    minimum_commission = Column(Numeric(10, 2), nullable=False)
    status = Column(_ACCOUNT_STATUS, nullable=False)
    version = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("user_id", "generation", name="uq_paper_accounts_user_generation"),
        Index(
            "uq_paper_accounts_active_user",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        CheckConstraint("generation > 0", name="ck_paper_accounts_generation_positive"),
        CheckConstraint("initial_cash >= 0", name="ck_paper_accounts_initial_cash_nonnegative"),
        CheckConstraint("available_cash >= 0", name="ck_paper_accounts_available_cash_nonnegative"),
        CheckConstraint("frozen_cash >= 0", name="ck_paper_accounts_frozen_cash_nonnegative"),
        CheckConstraint(
            "commission_rate >= 0", name="ck_paper_accounts_commission_rate_nonnegative"
        ),
        CheckConstraint(
            "minimum_commission >= 0",
            name="ck_paper_accounts_minimum_commission_nonnegative",
        ),
        CheckConstraint("version > 0", name="ck_paper_accounts_version_positive"),
    )

    @classmethod
    def new(
        cls,
        *,
        user_id: uuid.UUID,
        generation: int,
        initial_cash: Decimal,
        commission_rate: Decimal = Decimal("0.00030000"),
        minimum_commission: Decimal = Decimal("5.00"),
    ) -> PaperAccount:
        """Build an active account without relying on flush-time defaults."""
        return cls(
            user_id=user_id,
            generation=generation,
            initial_cash=initial_cash,
            available_cash=initial_cash,
            frozen_cash=Decimal("0.00"),
            commission_rate=commission_rate,
            minimum_commission=minimum_commission,
            status=PaperAccountStatus.ACTIVE,
            version=1,
        )


class PaperCashLedger(Base):
    __tablename__ = "paper_cash_ledger"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("paper_accounts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    generation = Column(Integer, nullable=False)
    kind = Column(String(32), nullable=False, index=True)
    amount = Column(Numeric(18, 2), nullable=False)
    available_before = Column(Numeric(18, 2), nullable=False)
    available_after = Column(Numeric(18, 2), nullable=False)
    frozen_before = Column(Numeric(18, 2), nullable=False)
    frozen_after = Column(Numeric(18, 2), nullable=False)
    business_key = Column(String(128), nullable=False, unique=True)
    order_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    fill_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("generation > 0", name="ck_paper_cash_ledger_generation_positive"),
        CheckConstraint(
            "available_before >= 0 AND available_after >= 0",
            name="ck_paper_cash_ledger_available_nonnegative",
        ),
        CheckConstraint(
            "frozen_before >= 0 AND frozen_after >= 0",
            name="ck_paper_cash_ledger_frozen_nonnegative",
        ),
    )


class PaperHoldingLot(Base):
    __tablename__ = "paper_holding_lots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("paper_accounts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    generation = Column(Integer, nullable=False)
    ts_code = Column(String(16), nullable=False, index=True)
    name = Column(String(64), nullable=False)
    source_fill_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    original_quantity = Column(Integer, nullable=False)
    remaining_quantity = Column(Integer, nullable=False)
    frozen_quantity = Column(Integer, nullable=False)
    unit_cost = Column(Numeric(18, 4), nullable=False)
    available_on = Column(Date, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("generation > 0", name="ck_paper_holding_lots_generation_positive"),
        CheckConstraint(
            "original_quantity >= 0", name="ck_paper_holding_lots_original_nonnegative"
        ),
        CheckConstraint(
            "remaining_quantity >= 0", name="ck_paper_holding_lots_remaining_nonnegative"
        ),
        CheckConstraint("frozen_quantity >= 0", name="ck_paper_holding_lots_frozen_nonnegative"),
        CheckConstraint(
            "remaining_quantity <= original_quantity",
            name="ck_paper_holding_lots_remaining_within_original",
        ),
        CheckConstraint(
            "frozen_quantity <= remaining_quantity",
            name="ck_paper_holding_lots_frozen_within_remaining",
        ),
        CheckConstraint("unit_cost >= 0", name="ck_paper_holding_lots_unit_cost_nonnegative"),
        Index("ix_paper_holding_lots_account_symbol", "account_id", "ts_code"),
    )


class PaperAccountResetAudit(Base):
    __tablename__ = "paper_account_reset_audits"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    old_account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("paper_accounts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    new_account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("paper_accounts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    old_generation = Column(Integer, nullable=False)
    new_generation = Column(Integer, nullable=False)
    source_session_id = Column(String(64), nullable=False)
    confirmation_id = Column(String(64), nullable=False)
    pre_reset_summary = Column(JSONB(), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "old_generation > 0", name="ck_paper_account_reset_old_generation_positive"
        ),
        CheckConstraint(
            "new_generation > old_generation",
            name="ck_paper_account_reset_generation_increases",
        ),
    )

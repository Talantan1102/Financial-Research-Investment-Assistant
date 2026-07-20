"""PostgreSQL models for simulated orders, fills, and match-pass audits."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

from app.core.database import Base


class AwareDateTime(TypeDecorator[datetime]):
    """Reject timestamps whose UTC offset cannot be determined before binding."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        del dialect
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("timestamp must be timezone-aware")
        return value


class OrderSide(enum.StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(enum.StrEnum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(enum.StrEnum):
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    QUEUED = "queued"
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    REJECTED = "rejected"


_ORDER_SIDE = Enum(
    OrderSide,
    name="paper_order_side",
    values_callable=lambda members: [member.value for member in members],
    validate_strings=True,
)
_ORDER_TYPE = Enum(
    OrderType,
    name="paper_order_type",
    values_callable=lambda members: [member.value for member in members],
    validate_strings=True,
)
_ORDER_STATUS = Enum(
    OrderStatus,
    name="paper_order_status",
    values_callable=lambda members: [member.value for member in members],
    validate_strings=True,
)


class PaperOrder(Base):
    __tablename__ = "paper_orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    account_generation = Column(Integer, nullable=False)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    client_request_id = Column(String(128), nullable=True)
    source_session_id = Column(String(64), nullable=False)
    source_message_id = Column(String(64), nullable=False)
    proposal_fingerprint = Column(String(64), nullable=False)
    ts_code = Column(String(16), nullable=False, index=True)
    name = Column(String(64), nullable=False)
    side = Column(_ORDER_SIDE, nullable=False)
    order_type = Column(_ORDER_TYPE, nullable=False)
    quantity = Column(Integer, nullable=False)
    limit_price = Column(Numeric(18, 4), nullable=True)
    filled_quantity = Column(Integer, nullable=False, default=0)
    avg_fill_price = Column(Numeric(18, 4), nullable=True)
    reserved_cash = Column(Numeric(18, 2), nullable=False, default=Decimal("0.00"))
    reserved_quantity = Column(Integer, nullable=False, default=0)
    status = Column(_ORDER_STATUS, nullable=False)
    original_proposal = Column(JSONB(none_as_null=True), nullable=False)
    confirmed_payload = Column(JSONB(none_as_null=True), nullable=True)
    user_edits = Column(JSONB(none_as_null=True), nullable=True)
    quote_snapshot = Column(JSONB(none_as_null=True), nullable=False)
    rules_version = Column(String(64), nullable=False)
    reject_code = Column(String(64), nullable=True)
    reject_message = Column(Text, nullable=True)
    expires_at = Column(AwareDateTime(), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    confirmed_at = Column(AwareDateTime(), nullable=True)
    completed_at = Column(AwareDateTime(), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["account_id", "user_id", "account_generation"],
            ["paper_accounts.id", "paper_accounts.user_id", "paper_accounts.generation"],
            name="fk_paper_orders_account_user_generation",
            ondelete="RESTRICT",
        ),
        Index(
            "uq_paper_orders_user_client_request",
            "user_id",
            "client_request_id",
            unique=True,
            postgresql_where=text("client_request_id IS NOT NULL"),
        ),
        UniqueConstraint(
            "account_id",
            "account_generation",
            "proposal_fingerprint",
            name="uq_paper_orders_account_generation_proposal",
        ),
        UniqueConstraint(
            "id",
            "account_id",
            "account_generation",
            name="uq_paper_orders_id_account_generation",
        ),
        CheckConstraint(
            "account_generation > 0",
            name="ck_paper_orders_account_generation_positive",
        ),
        CheckConstraint(
            "client_request_id IS NULL OR btrim(client_request_id) <> ''",
            name="ck_paper_orders_client_request_nonblank",
        ),
        CheckConstraint(
            "btrim(source_session_id) <> '' AND btrim(source_message_id) <> ''",
            name="ck_paper_orders_source_ids_nonblank",
        ),
        CheckConstraint(
            "proposal_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_paper_orders_proposal_fingerprint_sha256",
        ),
        CheckConstraint("quantity > 0", name="ck_paper_orders_quantity_positive"),
        CheckConstraint(
            "filled_quantity >= 0 AND filled_quantity <= quantity",
            name="ck_paper_orders_filled_quantity_range",
        ),
        CheckConstraint(
            "(order_type = 'market' AND limit_price IS NULL) OR "
            "(order_type = 'limit' AND limit_price IS NOT NULL AND limit_price > 0)",
            name="ck_paper_orders_type_limit_price",
        ),
        CheckConstraint(
            "(filled_quantity = 0 AND avg_fill_price IS NULL) OR "
            "(filled_quantity > 0 AND avg_fill_price IS NOT NULL AND avg_fill_price > 0)",
            name="ck_paper_orders_fill_average",
        ),
        CheckConstraint(
            "(status IN ('awaiting_confirmation', 'queued', 'open', 'rejected') "
            "AND filled_quantity = 0) OR "
            "(status = 'partially_filled' AND filled_quantity > 0 "
            "AND filled_quantity < quantity) OR "
            "(status = 'filled' AND filled_quantity = quantity) OR "
            "(status IN ('cancelled', 'expired') AND filled_quantity < quantity)",
            name="ck_paper_orders_status_filled_quantity",
        ),
        CheckConstraint(
            "(client_request_id IS NULL AND confirmed_payload IS NULL "
            "AND confirmed_at IS NULL) OR "
            "(client_request_id IS NOT NULL AND confirmed_payload IS NOT NULL "
            "AND confirmed_at IS NOT NULL)",
            name="ck_paper_orders_confirmation_bundle",
        ),
        CheckConstraint(
            "(status = 'awaiting_confirmation' AND client_request_id IS NULL) OR "
            "(status IN ('queued', 'open', 'partially_filled', 'filled', "
            "'expired', 'rejected') AND client_request_id IS NOT NULL) OR "
            "(status = 'cancelled' AND "
            "(filled_quantity = 0 OR client_request_id IS NOT NULL))",
            name="ck_paper_orders_status_confirmation",
        ),
        CheckConstraint(
            "(limit_price IS NULL OR limit_price::text NOT IN "
            "('NaN', 'Infinity', '-Infinity')) AND "
            "(avg_fill_price IS NULL OR avg_fill_price::text NOT IN "
            "('NaN', 'Infinity', '-Infinity'))",
            name="ck_paper_orders_financial_values_finite",
        ),
        CheckConstraint(
            "reserved_cash >= 0 AND reserved_cash::text NOT IN ('NaN', 'Infinity', '-Infinity')",
            name="ck_paper_orders_reserved_cash_valid",
        ),
        CheckConstraint(
            "reserved_quantity >= 0",
            name="ck_paper_orders_reserved_quantity_nonnegative",
        ),
        CheckConstraint(
            "(status IN ('awaiting_confirmation', 'rejected', 'filled', "
            "'cancelled', 'expired') AND reserved_cash = 0 AND reserved_quantity = 0) OR "
            "(status IN ('queued', 'open', 'partially_filled') AND "
            "((side = 'buy' AND reserved_cash > 0 AND reserved_quantity = 0) OR "
            "(side = 'sell' AND reserved_cash = 0 AND reserved_quantity > 0)))",
            name="ck_paper_orders_reservation_lifecycle",
        ),
        CheckConstraint(
            "(status = 'rejected' AND reject_code IS NOT NULL AND reject_message IS NOT NULL) "
            "OR (status <> 'rejected' AND reject_code IS NULL AND reject_message IS NULL)",
            name="ck_paper_orders_reject_details",
        ),
        CheckConstraint(
            "(status IN ('filled', 'cancelled', 'expired', 'rejected') "
            "AND completed_at IS NOT NULL) OR "
            "(status NOT IN ('filled', 'cancelled', 'expired', 'rejected') "
            "AND completed_at IS NULL)",
            name="ck_paper_orders_terminal_completion",
        ),
        Index("ix_paper_orders_account_status", "account_id", "status"),
        Index("ix_paper_orders_status_expires", "status", "expires_at"),
    )


class PaperFill(Base):
    __tablename__ = "paper_fills"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(
        UUID(as_uuid=True),
        ForeignKey("paper_orders.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    fill_seq = Column(Integer, nullable=False)
    quantity = Column(Integer, nullable=False)
    price = Column(Numeric(18, 4), nullable=False)
    gross_amount = Column(Numeric(18, 4), nullable=False)
    commission = Column(Numeric(18, 4), nullable=False)
    stamp_duty = Column(Numeric(18, 4), nullable=False)
    transfer_fee = Column(Numeric(18, 4), nullable=False)
    quote_timestamp = Column(AwareDateTime(), nullable=False)
    quote_source = Column(String(64), nullable=False)
    executed_at = Column(AwareDateTime(), nullable=False)
    trade_id = Column(UUID(as_uuid=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("order_id", "fill_seq", name="uq_paper_fills_order_sequence"),
        UniqueConstraint("trade_id", name="uq_paper_fills_trade"),
        CheckConstraint("fill_seq > 0", name="ck_paper_fills_sequence_positive"),
        CheckConstraint("quantity > 0", name="ck_paper_fills_quantity_positive"),
        CheckConstraint("price > 0", name="ck_paper_fills_price_positive"),
        CheckConstraint("gross_amount > 0", name="ck_paper_fills_gross_positive"),
        CheckConstraint(
            "gross_amount = quantity * price",
            name="ck_paper_fills_gross_matches_quantity_price",
        ),
        CheckConstraint("commission >= 0", name="ck_paper_fills_commission_nonnegative"),
        CheckConstraint("stamp_duty >= 0", name="ck_paper_fills_stamp_duty_nonnegative"),
        CheckConstraint("transfer_fee >= 0", name="ck_paper_fills_transfer_fee_nonnegative"),
        CheckConstraint(
            "price::text NOT IN ('NaN', 'Infinity', '-Infinity') AND "
            "gross_amount::text NOT IN ('NaN', 'Infinity', '-Infinity') AND "
            "commission::text NOT IN ('NaN', 'Infinity', '-Infinity') AND "
            "stamp_duty::text NOT IN ('NaN', 'Infinity', '-Infinity') AND "
            "transfer_fee::text NOT IN ('NaN', 'Infinity', '-Infinity')",
            name="ck_paper_fills_financial_values_finite",
        ),
        CheckConstraint("btrim(quote_source) <> ''", name="ck_paper_fills_quote_source_nonblank"),
    )


class PaperLotReservation(Base):
    __tablename__ = "paper_lot_reservations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    lot_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    account_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    account_generation = Column(Integer, nullable=False)
    reserved_quantity = Column(Integer, nullable=False)
    remaining_quantity = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["order_id", "account_id", "account_generation"],
            ["paper_orders.id", "paper_orders.account_id", "paper_orders.account_generation"],
            name="fk_paper_lot_reservations_order_account_generation",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["lot_id", "account_id", "account_generation"],
            [
                "paper_holding_lots.id",
                "paper_holding_lots.account_id",
                "paper_holding_lots.generation",
            ],
            name="fk_paper_lot_reservations_lot_account_generation",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("order_id", "lot_id", name="uq_paper_lot_reservations_order_lot"),
        CheckConstraint(
            "account_generation > 0",
            name="ck_paper_lot_reservations_generation_positive",
        ),
        CheckConstraint(
            "reserved_quantity > 0 AND remaining_quantity >= 0 "
            "AND remaining_quantity <= reserved_quantity",
            name="ck_paper_lot_reservations_quantity_range",
        ),
    )


class PaperMatchPass(Base):
    __tablename__ = "paper_match_passes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(
        UUID(as_uuid=True),
        ForeignKey("paper_orders.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    quote_timestamp = Column(AwareDateTime(), nullable=False)
    match_pass = Column(Integer, nullable=False)
    quote_source = Column(String(64), nullable=False)
    snapshot_summary = Column(JSONB(none_as_null=True), nullable=False)
    consumed_levels = Column(JSONB(none_as_null=True), nullable=False)
    matched_quantity = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "order_id",
            "quote_timestamp",
            "match_pass",
            name="uq_paper_match_passes_watermark",
        ),
        CheckConstraint("match_pass > 0", name="ck_paper_match_passes_pass_positive"),
        CheckConstraint(
            "matched_quantity >= 0",
            name="ck_paper_match_passes_matched_quantity_nonnegative",
        ),
        CheckConstraint(
            "btrim(quote_source) <> ''",
            name="ck_paper_match_passes_quote_source_nonblank",
        ),
    )

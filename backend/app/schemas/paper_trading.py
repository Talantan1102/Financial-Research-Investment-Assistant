from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from app.models.paper_account import PaperAccountStatus
from app.models.paper_order import OrderSide, OrderStatus, OrderType
from app.services.paper_trading.types import FeeBreakdown, MarketPhase, RealtimeQuote

Money = Annotated[
    Decimal,
    Field(gt=0, max_digits=18, decimal_places=2, allow_inf_nan=False),
]


class InitialCashUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    initial_cash: Money


class PaperAccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    generation: int
    initial_cash: Decimal
    available_cash: Decimal
    frozen_cash: Decimal
    status: PaperAccountStatus

    @field_serializer("initial_cash", "available_cash", "frozen_cash")
    def serialize_money(self, value: Decimal) -> str:
        return f"{value:.2f}"


class OrderDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    side: OrderSide
    ts_code: str
    name: str
    quantity: int = Field(strict=True, gt=0)
    order_type: OrderType
    limit_price: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=18,
        decimal_places=4,
        allow_inf_nan=False,
    )

    @field_validator("ts_code", "name")
    @classmethod
    def nonblank_identity(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("security identity must not be blank")
        return normalized

    @model_validator(mode="after")
    def order_type_matches_limit_price(self) -> OrderDraft:
        if self.order_type is OrderType.MARKET and self.limit_price is not None:
            raise ValueError("market orders must not include limit_price")
        if self.order_type is OrderType.LIMIT and self.limit_price is None:
            raise ValueError("limit orders require limit_price")
        return self


class OrderPreview(BaseModel):
    model_config = ConfigDict(frozen=True)

    order_id: UUID
    draft: OrderDraft
    quote: RealtimeQuote
    estimated_gross: Decimal
    estimated_fees: FeeBreakdown
    estimated_cash_required: Decimal
    available_cash: Decimal
    sellable_quantity: int
    market_phase: MarketPhase
    rules_version: str


class OrderPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft: OrderDraft


class OrderDraftPreview(BaseModel):
    """Side-effect-free page preview, intentionally without a persisted order id."""

    model_config = ConfigDict(frozen=True)

    draft: OrderDraft
    quote: RealtimeQuote
    estimated_gross: Decimal
    estimated_fees: FeeBreakdown
    estimated_cash_required: Decimal
    available_cash: Decimal
    sellable_quantity: int
    market_phase: MarketPhase
    rules_version: str


class OrderConfirmRequest(OrderPreviewRequest):
    client_request_id: str = Field(min_length=1, max_length=128)

    @field_validator("client_request_id")
    @classmethod
    def nonblank_client_request_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("client_request_id must not be blank")
        return normalized


class ConfirmationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation_id: str = Field(min_length=1, max_length=128)

    @field_validator("confirmation_id")
    @classmethod
    def nonblank_confirmation_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("confirmation_id must not be blank")
        return normalized


class ResetPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    initial_cash: Money


class ResetConfirmRequest(ResetPreviewRequest):
    session_id: str = Field(min_length=1, max_length=64)
    confirmation_id: str = Field(min_length=1, max_length=64)

    @field_validator("session_id", "confirmation_id")
    @classmethod
    def nonblank_reset_identity(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("confirmation identity must not be blank")
        return normalized


class PaperOrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    account_generation: int
    ts_code: str
    name: str
    side: OrderSide
    order_type: OrderType
    quantity: int
    limit_price: Decimal | None
    filled_quantity: int
    avg_fill_price: Decimal | None
    reserved_cash: Decimal
    reserved_quantity: int
    status: OrderStatus
    original_proposal: dict[str, Any]
    confirmed_payload: dict[str, Any] | None
    user_edits: dict[str, Any] | None
    quote_snapshot: dict[str, Any]
    rules_version: str
    reject_code: str | None
    reject_message: str | None
    expires_at: datetime
    created_at: datetime
    confirmed_at: datetime | None
    completed_at: datetime | None

    @field_serializer("limit_price", "avg_fill_price")
    def serialize_optional_price(self, value: Decimal | None) -> str | None:
        return None if value is None else f"{value:.4f}"

    @field_serializer("reserved_cash")
    def serialize_reserved_cash(self, value: Decimal) -> str:
        return f"{value:.2f}"


class PaperFillRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_id: UUID
    fill_seq: int
    quantity: int
    price: Decimal
    gross_amount: Decimal
    commission: Decimal
    stamp_duty: Decimal
    transfer_fee: Decimal
    quote_timestamp: datetime
    quote_source: str
    executed_at: datetime
    trade_id: UUID

    @field_serializer("price", "gross_amount", "commission", "stamp_duty", "transfer_fee")
    def serialize_fill_money(self, value: Decimal) -> str:
        return f"{value:.4f}"


class PaperHoldingRead(BaseModel):
    generation: int
    ts_code: str
    name: str
    quantity: int
    frozen_quantity: int
    sellable_quantity: int
    average_cost: Decimal

    @field_serializer("average_cost")
    def serialize_unit_cost(self, value: Decimal) -> str:
        return f"{value:.4f}"


class PaperCashLedgerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    generation: int
    kind: str
    amount: Decimal
    available_before: Decimal
    available_after: Decimal
    frozen_before: Decimal
    frozen_after: Decimal
    business_key: str
    order_id: UUID | None
    fill_id: UUID | None
    created_at: datetime

    @field_serializer(
        "amount", "available_before", "available_after", "frozen_before", "frozen_after"
    )
    def serialize_ledger_money(self, value: Decimal) -> str:
        return f"{value:.2f}"


class CancelPreviewRead(BaseModel):
    order_id: UUID
    status: OrderStatus
    filled_quantity: int
    remaining_quantity: int
    reserved_cash: Decimal
    reserved_quantity: int

    @field_serializer("reserved_cash")
    def serialize_cancel_cash(self, value: Decimal) -> str:
        return f"{value:.2f}"


class ResetPreviewRead(BaseModel):
    account_id: UUID
    generation: int
    current_initial_cash: Decimal
    replacement_initial_cash: Decimal

    @field_serializer("current_initial_cash", "replacement_initial_cash")
    def serialize_reset_cash(self, value: Decimal) -> str:
        return f"{value:.2f}"

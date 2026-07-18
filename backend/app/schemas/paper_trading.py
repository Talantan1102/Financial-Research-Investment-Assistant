from __future__ import annotations

from decimal import Decimal
from typing import Annotated
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
from app.models.paper_order import OrderSide, OrderType
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
    quantity: int = Field(gt=0)
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

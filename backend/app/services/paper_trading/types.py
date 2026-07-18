from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MarketPhase(StrEnum):
    CLOSED = "closed"
    OPENING_AUCTION = "opening_auction"
    MORNING = "morning"
    LUNCH = "lunch"
    AFTERNOON = "afternoon"
    CLOSING_AUCTION = "closing_auction"


class QuoteLevel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)

    price: Decimal = Field(gt=0)
    quantity: int = Field(ge=0)


class RealtimeQuote(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)

    ts_code: str
    name: str
    quoted_at: datetime
    previous_close: Decimal = Field(gt=0)
    last_price: Decimal = Field(gt=0)
    bids: tuple[QuoteLevel, ...]
    asks: tuple[QuoteLevel, ...]
    source: str
    suspended: bool

    @field_validator("bids", "asks")
    @classmethod
    def five_levels(cls, value: tuple[QuoteLevel, ...]) -> tuple[QuoteLevel, ...]:
        if len(value) != 5:
            raise ValueError("exactly five quote levels required")
        return value


class RuleSet(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)

    version: str
    effective_from: date
    board: str
    risk_warning: bool
    side: str
    buy_lot_size: int
    price_tick: Decimal
    price_limit_ratio: Decimal
    quote_freshness_seconds: int


class FeeBreakdown(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)

    commission: Decimal
    stamp_duty: Decimal
    transfer_fee: Decimal

    @property
    def total(self) -> Decimal:
        return self.commission + self.stamp_duty + self.transfer_fee

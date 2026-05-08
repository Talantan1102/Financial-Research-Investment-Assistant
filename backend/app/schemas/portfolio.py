"""Pydantic schemas for portfolio endpoints — v1.0 持仓监控。

Spec ref: docs/superpowers/specs/2026-05-07-v1.0-portfolio-data-model-engineering-design.md § 2。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

TradeTypeStr = Literal["initial", "buy", "sell"]


class TradeCreate(BaseModel):
    """POST /portfolio/trades 入参。"""

    model_config = ConfigDict(extra="forbid")

    ts_code: str = Field(min_length=1, max_length=10)
    name: str = Field(min_length=1, max_length=50)
    type: TradeTypeStr
    quantity: int = Field(gt=0)
    price: Decimal = Field(gt=Decimal("0"))
    trade_date: date
    note: str | None = None


class TradeUpdate(BaseModel):
    """PATCH /portfolio/trades/{id} 入参 — 仅 INITIAL trade 可调用,且 type 不可改。"""

    model_config = ConfigDict(extra="forbid")

    ts_code: str | None = Field(default=None, min_length=1, max_length=10)
    name: str | None = Field(default=None, min_length=1, max_length=50)
    quantity: int | None = Field(default=None, gt=0)
    price: Decimal | None = Field(default=None, gt=Decimal("0"))
    trade_date: date | None = None
    note: str | None = None


class TradeRead(BaseModel):
    """Trade 出参(POST 创建后 / GET 列表)。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    ts_code: str
    name: str
    type: TradeTypeStr
    quantity: int
    price: Decimal
    trade_date: date
    note: str | None
    created_at: datetime

    @field_validator("type", mode="before")
    @classmethod
    def coerce_trade_type(cls, v: object) -> str:
        """ORM 返回 TradeType 枚举实例,序列化前取 .value。"""
        if hasattr(v, "value"):
            return str(v.value)
        return str(v)


class PositionRead(BaseModel):
    """GET /portfolio/positions 单条出参。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    ts_code: str
    name: str
    quantity: int
    avg_cost: Decimal
    total_cost: Decimal
    realized_pnl: Decimal
    last_quote_price: Decimal | None
    last_quote_at: datetime | None
    is_silenced: bool


class OnboardingRequest(BaseModel):
    """POST /portfolio/onboarding 入参 — 一次性录入多笔 INITIAL trade(雪球做法)。"""

    model_config = ConfigDict(extra="forbid")

    trades: list[TradeCreate] = Field(min_length=1)


class OnboardingResponse(BaseModel):
    """onboarding 完成后回传插入的 trades + 生成的 positions。"""

    trades: list[TradeRead]
    positions: list[PositionRead]

"""Closed model-facing schemas for paper-trading chat tools."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PlacePaperOrderArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    side: Literal["buy", "sell"]
    ts_code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    quantity: int = Field(strict=True, gt=0)
    order_type: Literal["market", "limit"]
    limit_price: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)

    @field_validator("ts_code", "name")
    @classmethod
    def strip_nonblank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value

    @model_validator(mode="after")
    def validate_limit_shape(self) -> PlacePaperOrderArgs:
        if self.order_type == "market" and self.limit_price is not None:
            raise ValueError("market orders must not include limit_price")
        if self.order_type == "limit" and self.limit_price is None:
            raise ValueError("limit orders require limit_price")
        return self


class CancelPaperOrderArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_id: UUID


class ResetPaperAccountArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    initial_cash: Decimal = Field(gt=0, max_digits=18, decimal_places=2, allow_inf_nan=False)


class GetPaperAccountArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListPaperOrdersArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str | None = None
    ts_code: str | None = None
    limit: int = Field(default=50, ge=1, le=100)


class GetPaperOrderArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_id: UUID


__all__ = [
    "CancelPaperOrderArgs",
    "GetPaperAccountArgs",
    "GetPaperOrderArgs",
    "ListPaperOrdersArgs",
    "PlacePaperOrderArgs",
    "ResetPaperAccountArgs",
]

from __future__ import annotations

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer

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
    status: str

    @field_serializer("initial_cash", "available_cash", "frozen_cash")
    def serialize_money(self, value: Decimal) -> str:
        return f"{value:.2f}"

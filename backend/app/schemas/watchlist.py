from __future__ import annotations

import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

TsCode = Annotated[str, Field(pattern=r"^\d{6}\.(?:SH|SZ)$")]
StockName = Annotated[str, Field(min_length=1, max_length=50)]
WatchlistNote = Annotated[str, Field(max_length=2000)]


class WatchlistCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ts_code: TsCode
    name: StockName
    note: WatchlistNote | None = None
    monitoring_enabled: bool = False


class WatchlistUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: StockName | None = None
    note: WatchlistNote | None = None
    monitoring_enabled: bool | None = None

    @model_validator(mode="after")
    def reject_explicit_null_for_required_storage_fields(self) -> WatchlistUpdate:
        for field_name in ("name", "monitoring_enabled"):
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class WatchlistRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ts_code: str
    name: str
    note: str | None
    monitoring_enabled: bool


class WatchlistRemoveResponse(BaseModel):
    removed: bool

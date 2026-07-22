from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class WatchlistCreate(BaseModel):
    ts_code: str
    name: str
    note: str | None = None
    monitoring_enabled: bool = False


class WatchlistUpdate(BaseModel):
    name: str | None = None
    note: str | None = None
    monitoring_enabled: bool | None = None


class WatchlistRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    ts_code: str
    name: str
    note: str | None
    monitoring_enabled: bool

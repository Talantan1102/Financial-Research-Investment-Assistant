"""Stable HTTP schemas for the v1 Session read-model API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RunSessionUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255, strict=True)

    model_config = ConfigDict(extra="forbid")

    @field_validator("title", mode="before")
    @classmethod
    def strip_title(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class RunSessionResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    created_by_user_id: UUID
    title: str | None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None

    model_config = ConfigDict(from_attributes=True)

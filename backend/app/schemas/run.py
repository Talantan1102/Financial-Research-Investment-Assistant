"""Stable HTTP schemas for the v1 Run control-plane API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.run_control.types import RunStatus


class RunCreateRequest(BaseModel):
    session_id: UUID | None = None
    prompt: str = Field(min_length=1, max_length=100_000)
    replaces_run_id: UUID | None = None

    @field_validator("prompt")
    @classmethod
    def reject_blank_prompt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("prompt must not be blank")
        return value


class RunResumeRequest(BaseModel):
    response: dict[str, object]


class RunResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    session_id: UUID
    created_by_user_id: UUID
    run_type: Literal["chat"]
    status: RunStatus
    replaces_run_id: UUID | None
    retry_count: int
    created_at: datetime
    queued_at: datetime
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None

    model_config = ConfigDict(from_attributes=True)


class TraceItem(BaseModel):
    span_id: str
    request_id: str
    parent_id: str | None
    name: str
    inputs: dict[str, object]
    outputs: dict[str, object]
    metadata: dict[str, object]
    started_at: datetime
    ended_at: datetime
    error: str | None


class RunTraceResponse(BaseModel):
    items: list[TraceItem]

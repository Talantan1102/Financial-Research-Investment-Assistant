"""Stable HTTP schemas for the v1 Session read-model API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.chatloop.outcomes import ActionRequiredOutcome


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


class RunMessageResponse(BaseModel):
    id: UUID
    role: str
    content: str
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RunRevisionResponse(BaseModel):
    id: UUID
    replaces_run_id: UUID | None
    status: str
    prompt: str
    prompt_is_full: bool
    final_message_summary: str | None
    created_at: datetime
    finished_at: datetime | None


class RunSessionDetailResponse(RunSessionResponse):
    messages: list[RunMessageResponse]
    has_more: bool
    active_run_id: UUID | None
    active_run_status: str | None
    active_pause_id: UUID | None
    active_pause_type: str | None
    active_pause_request: dict[str, object] | None
    revisions: list[RunRevisionResponse]
    revisions_has_more: bool
    revisions_next_cursor: str | None
    latest_run_id: UUID | None
    latest_run_status: str | None
    latest_run_outcome: ActionRequiredOutcome | None = None

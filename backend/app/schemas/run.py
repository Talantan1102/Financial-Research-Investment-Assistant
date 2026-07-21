"""Stable HTTP schemas for the v1 Run control-plane API."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.run_control.types import RunStatus

_REDIS_STREAM_ID = re.compile(r"^(?:0|[1-9][0-9]*)-(?:0|[1-9][0-9]*)$")


@dataclass(frozen=True)
class RunEventCursor:
    durable_seq: int = 0
    redis_id: str = "0-0"

    @classmethod
    def parse(cls, raw: str | None) -> RunEventCursor:
        if raw is None:
            return cls()
        if raw.isascii() and raw.isdecimal():
            return cls(durable_seq=int(raw))
        parts = raw.split(":")
        if (
            len(parts) != 3
            or parts[0] != "v1"
            or not parts[1].isascii()
            or not parts[1].isdecimal()
            or _REDIS_STREAM_ID.fullmatch(parts[2]) is None
        ):
            raise ValueError("invalid Run event cursor")
        return cls(durable_seq=int(parts[1]), redis_id=parts[2])

    def encode(self) -> str:
        return f"v1:{self.durable_seq}:{self.redis_id}"


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

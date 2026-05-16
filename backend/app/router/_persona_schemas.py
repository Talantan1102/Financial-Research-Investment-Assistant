"""persona_router Pydantic schemas (Plan Task 7)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

TargetSection = Literal["user", "agent"]


class PersonaItemOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    text: str
    source: TargetSection
    position: int
    created_at: datetime
    updated_at: datetime


class PersonaListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_declared: list[PersonaItemOut] = Field(default_factory=list)
    agent_inferred: list[PersonaItemOut] = Field(default_factory=list)


class PersonaPostRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=500)
    target_section: TargetSection

    @field_validator("text")
    @classmethod
    def _strip_and_check(cls, v: str) -> str:
        # Field(max_length=500) 已先验长度; 此处只补 strip 后非空检查
        # (Field min_length=1 拦 "" 不拦 "   ")
        stripped = v.strip()
        if not stripped:
            raise ValueError("text must not be empty after strip")
        return stripped


class PersonaPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=500)

    @field_validator("text")
    @classmethod
    def _strip_and_check(cls, v: str) -> str:
        # Field(max_length=500) 已先验长度; 此处只补 strip 后非空检查
        # (Field min_length=1 拦 "" 不拦 "   ")
        stripped = v.strip()
        if not stripped:
            raise ValueError("text must not be empty after strip")
        return stripped

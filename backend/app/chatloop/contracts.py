"""Pure chat-loop runtime contracts with no agent/service/ORM import graph."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ToolResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool_name: str
    args: dict[str, Any]
    success: bool
    output: dict[str, Any] | None = None
    error: str | None = None
    latency_ms: int = Field(ge=0)
    cached: bool = False
    tool_call_data: dict[str, Any] | None = None


__all__ = ["ToolResult"]

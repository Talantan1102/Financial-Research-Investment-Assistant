"""Closed event vocabulary for request-local task graphs."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RuntimeEventType(StrEnum):
    TASK_STARTED = "task.started"
    TASK_OUTPUT_DELTA = "task.output_delta"
    TASK_PERMISSION_REQUIRED = "task.permission_required"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_CANCELLED = "task.cancelled"
    GRAPH_COMPLETED = "graph.completed"


class RuntimeEvent(BaseModel):
    """One scheduler notification; task results remain authoritative."""

    model_config = ConfigDict(frozen=True)

    type: RuntimeEventType
    task_id: str | None = None
    attempt: int = 0
    data: dict[str, Any] = Field(default_factory=dict)

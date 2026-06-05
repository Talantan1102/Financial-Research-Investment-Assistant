"""LoopEvent — SSE 与 trace 的统一信封(spec § 5.1)。

ToolLoop 主动发射这些事件;chat_runner 直接 XADD 进 Redis Streams,
不再有 LangGraph astream_events 的节点名匹配适配层。
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

EventType = Literal[
    "step_start",
    "token",
    "reasoning",
    "tool_call",
    "tool_start",
    "tool_end",
    "tool_error",
    "skill_load",
    "steer_merged",
    "loop_halt",
    "approval_request",
    "escalate_request",
    "cost_update",
    "done",
    "error",
]


class LoopEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: EventType
    seq: int
    step: int
    data: dict[str, Any] = Field(default_factory=dict)

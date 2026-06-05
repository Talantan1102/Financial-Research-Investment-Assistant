"""LLM 单圈调用的结果/增量类型 — chatloop 与 LLM 协议的解耦边界(spec § 2.1)。

降级路径(qwen 无原生 tool_calls 时)只换 stream_step 内部实现,
本模块类型不变,循环及以上零改。
"""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel


class StepToolCall(BaseModel):
    id: str
    name: str
    arguments: str  # 原始 JSON 串(流式分片拼接产物)

    @property
    def parsed_args(self) -> dict:
        try:
            parsed = json.loads(self.arguments or "{}")
        except json.JSONDecodeError as e:
            raise ValueError(f"tool_call arguments 不是合法 JSON: {self.arguments!r}") from e
        if not isinstance(parsed, dict):
            raise ValueError(f"tool_call arguments 须为 object: {self.arguments!r}")
        return parsed


class StepDelta(BaseModel):
    """流式增量 — emit 给 SSE 的最小单元。"""
    kind: Literal["content", "reasoning", "tool_call"]
    text: str = ""
    tool_name: str | None = None  # kind=tool_call 且 name 首次到达时携带


class StepResult(BaseModel):
    content: str
    tool_calls: list[StepToolCall]
    finish_reason: str  # stop | tool_calls | length | ...
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int  # KV-cache 命中(一等观测指标,spec § 2.4)
    cost_cny: float

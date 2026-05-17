"""v1.x A5b: Bull/Bear debate schemas.

AdvocateOutput: 单 advocate 单轮输出(arguments + strongest + rebut_targets + confidence)
DebateTrace: 2 轮完整 trace,Analyst 节点写入 state.debate_trace,dashboard 可观测

Design 原则(spec § 9):
- AdvocateOutput frozen=True (产出后不变)
- arguments min_length=3, max_length=5 强制 advocate 给 3-5 条
- strongest_argument max_length=300 防 LLM 自评滥用
- rebut_targets 默认空 list (round 1 不填,round 2 才填)
- confidence Literal high/medium/low (LLM 元认知信号)

spec ref: 2026-05-16-v1.x-bull-bear-debate-design.md § 9
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["AdvocateOutput", "DebateTrace"]


class AdvocateOutput(BaseModel):
    """Bull/Bear advocate 单轮输出。"""

    model_config = ConfigDict(frozen=True)

    arguments: list[str] = Field(min_length=3, max_length=5)
    strongest_argument: str = Field(max_length=300, description="advocate 自评最强一条")
    rebut_targets: list[str] = Field(
        default_factory=list,
        max_length=5,
        description="v2 才填 — 引用对方 v1 哪些论据被反驳(原文片段)",
    )
    confidence: Literal["high", "medium", "low"]


class DebateTrace(BaseModel):
    """v1.x A5b: 完整 debate 历史,dashboard 可观测。"""

    model_config = ConfigDict(frozen=True)

    bull_v1: AdvocateOutput | None = None
    bear_v1: AdvocateOutput | None = None
    bull_v2: AdvocateOutput | None = None
    bear_v2: AdvocateOutput | None = None
    total_cost_cny: float = Field(ge=0.0)
    total_latency_ms: int = Field(ge=0)
    rounds_completed: int = Field(ge=0, le=2)

"""dispatch_subagents — chat 内只读扇出子 agent 派发原语(spec 2026-06-11)。

子循环 = 同一个 ToolLoop 类换受限依赖(只读子 hub / max_steps=4 / tier=fast /
白纸 context)。与深度研报彻底隔离:子循环只读白名单不含 offer_deep_research /
dispatch_subagents(禁串门 + 禁递归)。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ── 护栏常量 ──────────────────────────────────────────────────────────────
MAX_SUBAGENTS = 8  # 个数上限(spec §4.2);超出让模型分批派
CHILD_MAX_STEPS = 4  # 子循环硬步数上限(spec §4.2)
CHILD_BUDGET_FRACTION = 0.6  # 给整批的预算占当轮剩余预算比例
CHILD_MIN_CNY = 0.005  # 单子循环预算下限(低于则拒派)
CHILD_TIER = "fast"

# 子循环只读白名单(MCP 数据工具) — 不含 memory_* / skill / control / dispatch
READONLY_SUBAGENT_TOOLS: list[str] = [
    "get_stock_quote",
    "get_financial_statements",
    "kb_search",
    "get_news",
    "web_search",
    "get_market_indicators",
    "get_corporate_actions",
]


class SubtaskRequest(BaseModel):
    """一个子任务的 LLM-facing 表(主 AI 填)。harness 补 subtask_id/tool_scope/tier/caps。"""

    goal: str
    target: str | None = None  # ts_code / 信息源标识
    output_hint: str = ""  # 想要的产出形状
    boundary: str | None = None  # 边界(如"只看近一年")


class SubagentResult(BaseModel):
    """一个子循环的回收结果(原文摘要直传,进程内对象)。"""

    model_config = ConfigDict(frozen=True)

    subtask_id: str
    target: str | None
    summary: str  # 子循环自己的终答原文(verbatim,不复述)
    evidence_refs: list[str] = Field(default_factory=list)
    status: Literal["ok", "partial", "failed"]
    gap_note: str | None = None
    tokens_spent: int = 0
    cost_cny: float = 0.0
    steps_used: int = 0
    tier: str = CHILD_TIER


__all__ = [
    "CHILD_BUDGET_FRACTION",
    "CHILD_MAX_STEPS",
    "CHILD_MIN_CNY",
    "CHILD_TIER",
    "MAX_SUBAGENTS",
    "READONLY_SUBAGENT_TOOLS",
    "SubagentResult",
    "SubtaskRequest",
]

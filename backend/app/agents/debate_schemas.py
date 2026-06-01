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

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from app.agents.schemas import ResearchState

__all__ = ["AdvocateOutput", "DebateTrace", "format_valuation_block"]


def format_valuation_block(state: ResearchState, side: Literal["bull", "bear"]) -> str:
    """C62: 单一 SSOT — bull/bear 共享估值 block 注入函数，通过 side 控制差异。

    bull 侧: pe_value / dcf_base / dcf_bull / outlier_diagnosis
    bear 侧: pe_value / dcf_base / dcf_bear / outlier_diagnosis / severity warning
    """
    va = state.valuation_analysis
    if va is None:
        return ""
    lines: list[str] = []
    if va.pe_value is not None:
        lines.append(f"  - PE 理论价: {va.pe_value:,.2f}")
    if va.dcf_base is not None:
        lines.append(f"  - DCF base: {va.dcf_base:,.2f}")
    if side == "bull":
        if va.dcf_bull is not None:
            lines.append(f"  - DCF bull: {va.dcf_bull:,.2f}")
        if va.dcf_bear is not None:
            lines.append(f"  - DCF bear: {va.dcf_bear:,.2f}")
    else:  # bear
        if va.dcf_bear is not None:
            lines.append(f"  - DCF bear: {va.dcf_bear:,.2f}")
        if va.valuation_consistency == "severe":
            lines.append("  - cross-check severity: SEVERE (打架信号, bear 应利用)")
    if va.outlier_diagnosis is not None:
        lines.append(f"  - outlier diagnosis: {va.outlier_diagnosis.narrative}")
    if not lines:
        return ""
    return "\n估值数据(A5a cross-check):\n" + "\n".join(lines) + "\n"


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
    """v1.x A5b: 完整 debate 历史 (0-2 轮),dashboard 可观测。"""

    model_config = ConfigDict(frozen=True)

    bull_v1: AdvocateOutput | None = None
    bear_v1: AdvocateOutput | None = None
    bull_v2: AdvocateOutput | None = None
    bear_v2: AdvocateOutput | None = None
    total_cost_cny: float = Field(ge=0.0)
    total_latency_ms: int = Field(ge=0)
    rounds_completed: int = Field(ge=0, le=2)

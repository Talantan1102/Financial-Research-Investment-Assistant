"""dispatch_subagents — chat 内只读扇出子 agent 派发原语(spec 2026-06-11)。

子循环 = 同一个 ToolLoop 类换受限依赖(只读子 hub / max_steps=4 / tier=fast /
白纸 context)。与深度研报彻底隔离:子循环只读白名单不含 offer_deep_research /
dispatch_subagents(禁串门 + 禁递归)。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.chatloop.context import ContextDeps
from app.chatloop.events import LoopEvent, SeqCounter
from app.chatloop.gates import GateConfig
from app.chatloop.loop import ToolLoop
from app.chatloop.state import ChatLoopState
from app.chatloop.tool_hub import ToolHub

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


# ── 子循环系统提示 + 子任务渲染 + 只读 hub builder ─────────────────────────

CHILD_SYSTEM_PROMPT = (
    "你是一个只读检索子助手。只做被指派的这一件查取任务,用给到的只读工具查清后,"
    "用最多 3 句话给出结论性摘要(含关键数字)。不要寒暄、不要展开分析、不要追问。"
    "查不到就直说缺什么。你看不到主对话历史,也不知道别的子任务在做什么。"
)


def _render_subtask(req: SubtaskRequest) -> str:
    lines = [f"任务目标:{req.goal}"]
    if req.target:
        lines.append(f"对象:{req.target}")
    if req.output_hint:
        lines.append(f"产出格式:{req.output_hint}")
    if req.boundary:
        lines.append(f"边界:{req.boundary}")
    return "\n".join(lines)


def build_child_tool_hub(
    registry: Any, *, emit: Any, seq_counter: SeqCounter, cache: Any
) -> ToolHub:
    """构造子循环的只读 hub(flat schema,只挂只读白名单工具)。"""
    hub = ToolHub(emit=emit, cache=cache, seq_counter=seq_counter, progressive=False)
    hub.register_subset(registry, READONLY_SUBAGENT_TOOLS)
    return hub


class SubagentFactory:
    """起子循环 + 收回 SubagentResult。per-turn 在 build_turn_components 构造。"""

    def __init__(
        self,
        *,
        llm: Any,
        registry: Any,
        cache: Any,
        emit: Callable[[LoopEvent], Awaitable[None]],
        seq_counter: SeqCounter,
        gate_cfg: GateConfig,
        audit_repo: Any | None,
    ) -> None:
        self._llm = llm
        self._registry = registry
        self._cache = cache
        self._emit = emit
        self._seq = seq_counter
        self._gate_cfg = gate_cfg
        self._audit = audit_repo

    def _lane_emit(self, subtask_id: str) -> Callable[[LoopEvent], Awaitable[None]]:
        async def _wrapped(ev: LoopEvent) -> None:
            tagged = ev.model_copy(update={"data": {**ev.data, "lane": subtask_id}})
            await self._emit(tagged)

        return _wrapped

    async def spawn_one(
        self, req: SubtaskRequest, parent: ChatLoopState, *, subtask_id: str,
        child_cny: float = CHILD_MIN_CNY, child_tokens: int = 20_000,
    ) -> SubagentResult:
        child_state = ChatLoopState(
            user_id=parent.user_id,
            session_id=parent.session_id,
            request_id=f"{parent.request_id}::sub::{subtask_id}",
            messages=[{"role": "user", "content": _render_subtask(req)}],
        )
        child_hub = build_child_tool_hub(
            self._registry, emit=self._lane_emit(subtask_id),
            seq_counter=self._seq, cache=self._cache,
        )
        deps = ContextDeps(
            system_prompt=CHILD_SYSTEM_PROMPT, persona_block="", skill_listing="",
            history_block=(), max_steps=CHILD_MAX_STEPS, max_cny=child_cny,
        )
        loop = ToolLoop(
            llm=self._llm, tool_hub=child_hub, context_deps=deps,
            gate_cfg=GateConfig(
                max_steps=CHILD_MAX_STEPS, max_cny=child_cny, max_tokens=child_tokens
            ),
            emit=self._lane_emit(subtask_id), seq_counter=self._seq, tier=CHILD_TIER,
        )
        try:
            final = await loop.run(child_state)
        except Exception as exc:  # noqa: BLE001 — fail loud,包成 failed 结果不抛
            return SubagentResult(
                subtask_id=subtask_id, target=req.target, summary="",
                evidence_refs=[], status="failed", gap_note=f"子循环异常:{exc}",
                tokens_spent=0, cost_cny=0.0, steps_used=0, tier=CHILD_TIER,
            )
        status: str = "ok" if final.halt_reason in (None, "natural") else "partial"
        refs = [e.cache_key for e in final.ledger.entries if e.cache_key]
        gap = None if status == "ok" else f"子循环未自然收尾({final.halt_reason})"
        return SubagentResult(
            subtask_id=subtask_id, target=req.target,
            summary=final.final_response or "", evidence_refs=refs,
            status=status, gap_note=gap, tokens_spent=final.budget_spent_tokens,
            cost_cny=final.budget_spent_cny, steps_used=final.step, tier=CHILD_TIER,
        )

    async def dispatch(
        self, subtasks: list[SubtaskRequest], parent: ChatLoopState
    ) -> list[SubagentResult]:
        n = len(subtasks)
        # 预算切片:给整批 = 当轮剩余 × FRACTION,均分到每个子循环
        remaining_cny = max(0.0, self._gate_cfg.max_cny - parent.budget_spent_cny)
        remaining_tokens = max(0, self._gate_cfg.max_tokens - parent.budget_spent_tokens)
        child_cny = max(CHILD_MIN_CNY, (remaining_cny * CHILD_BUDGET_FRACTION) / n)
        child_tokens = max(5_000, int((remaining_tokens * CHILD_BUDGET_FRACTION) / n))

        await self._emit_plain(
            "dispatch_start", parent.step,
            n=n, subtasks=[{"subtask_id": f"sub-{i}", "goal": s.goal[:60]}
                           for i, s in enumerate(subtasks)],
        )
        results: list[SubagentResult] = await asyncio.gather(
            *(self.spawn_one(req, parent, subtask_id=f"sub-{i}",
                             child_cny=child_cny, child_tokens=child_tokens)
              for i, req in enumerate(subtasks))
        )
        # 预算回滚进父 state(ChatLoopState 字段可变)
        for r in results:
            parent.budget_spent_cny += r.cost_cny
            parent.budget_spent_tokens += r.tokens_spent
        # 审计落库(best-effort)
        if self._audit is not None:
            try:
                self._audit.record_batch(parent=parent, subtasks=subtasks, results=results)
            except Exception:  # noqa: BLE001 — 留痕非致命
                pass
        await self._emit_plain(
            "dispatch_end", parent.step,
            n=n, results=[{"subtask_id": r.subtask_id, "status": r.status} for r in results],
        )
        return results

    async def _emit_plain(self, type_: str, step: int, /, **data: Any) -> None:
        seq = self._seq.next()
        await self._emit(LoopEvent(type=type_, seq=seq, step=step, data=data))  # type: ignore[arg-type]


__all__ = [
    "CHILD_BUDGET_FRACTION",
    "CHILD_MAX_STEPS",
    "CHILD_MIN_CNY",
    "CHILD_SYSTEM_PROMPT",
    "CHILD_TIER",
    "MAX_SUBAGENTS",
    "READONLY_SUBAGENT_TOOLS",
    "SubagentFactory",
    "SubagentResult",
    "SubtaskRequest",
    "build_child_tool_hub",
]

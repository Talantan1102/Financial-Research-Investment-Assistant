"""ChatLoopState + ToolLedger — 一个 turn 的全部纯数据层(spec § 2.4 / § 4.1)。

设计红线:
- messages 是 OpenAI 格式 list[dict],single source of truth;
- assistant 消息携带 role/content/tool_calls;
  思考模型回传 reasoning_content 时额外写入轨迹(SFT 监督目标),
  但 context.py 在投影到 LLM 窗口时会剥离该字段,确保不回送 LLM;
- assistant(tool_calls) 后必须跟全部对应 tool 消息(apply_results 保证);
- ToolLedger 不进 LLM 窗口,只进 state。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.chatloop.approval_edits import ApprovedInput
from app.chatloop.contracts import ToolResult
from app.services.llm_step import StepResult, StepToolCall

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def args_hash_of(args: dict[str, Any]) -> str:
    """canonical JSON(sort_keys, ensure_ascii=False)→ sha256 前 16 位。"""
    serialized = json.dumps(args, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# ToolLedger
# ---------------------------------------------------------------------------


class LedgerEntry(BaseModel):
    """一次工具调用的台账行 — 不进 LLM 窗口(spec § 2.4)。"""

    model_config = ConfigDict(frozen=True)

    step: int
    tool_call_id: str | None = None
    tool_name: str
    args_hash: str  # sha256(canonical json)[:16]
    digest: str  # ≤200 字摘要
    success: bool
    cache_key: str | None = None

    @property
    def signature(self) -> str:
        return f"{self.tool_name}:{self.args_hash}"


class ToolLedger(BaseModel):
    entries: list[LedgerEntry] = Field(default_factory=list)
    # 渐进披露:本 turn 已检索文档的工具名
    searched_docs: set[str] = Field(default_factory=set)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def record(
        self,
        *,
        step: int,
        tool_call_id: str | None = None,
        tool_name: str,
        args: dict[str, Any],
        digest: str,
        success: bool,
        cache_key: str | None = None,
    ) -> LedgerEntry:
        """记录一次工具调用,返回新建的台账行。"""
        entry = LedgerEntry(
            step=step,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            args_hash=args_hash_of(args),
            digest=digest[:200],
            success=success,
            cache_key=cache_key,
        )
        self.entries.append(entry)
        return entry

    def find_success(self, *, tool_name: str, args: dict[str, Any]) -> LedgerEntry | None:
        """同签名且 success 的最新条目(turn 内去重)。"""
        target_hash = args_hash_of(args)
        target_sig = f"{tool_name}:{target_hash}"
        # 从后往前找,返回最新的 success 条目
        for entry in reversed(self.entries):
            if entry.signature == target_sig and entry.success:
                return entry
        return None

    def signature_set(self, step: int) -> set[str]:
        """某一圈发起的全部调用签名(打转指纹)。"""
        return {e.signature for e in self.entries if e.step == step}

    def fail_count(self, signature: str) -> int:
        """同签名累计失败次数(烧签名判据)。"""
        return sum(1 for e in self.entries if e.signature == signature and not e.success)

    def trailing_failure_count(self) -> int:
        """从台账末尾往回数连续 success=False 的条数(跨签名乱试判据)。

        任意一次成功即截断计数。被烧签名拒绝的调用不进台账,故不污染此计数;
        只有真分发并失败的调用计入——抓的是"一直在失败",不是"调用频率"。
        """
        count = 0
        for entry in reversed(self.entries):
            if entry.success:
                break
            count += 1
        return count

    def to_extractor_view(self) -> list[dict[str, Any]]:
        """升级物料:仅 success 条目 → [{"tool_name", "summary", "cache_id"}]。

        cache_key 为 None 时 cache_id 字段仍带 None——summary 有价值,不滤掉。
        """
        return [
            {
                "tool_name": e.tool_name,
                "summary": e.digest,
                "cache_id": e.cache_key,
            }
            for e in self.entries
            if e.success
        ]


# ---------------------------------------------------------------------------
# ChatLoopState
# ---------------------------------------------------------------------------


class ChatLoopState(BaseModel):
    """一个 turn 的全部状态。

    turn 原子语义:不持久化,崩溃即弃(spec § 4.1)。
    """

    user_id: str
    session_id: str
    request_id: str
    messages: list[dict[str, Any]]  # OpenAI 格式,single source of truth
    ledger: ToolLedger = Field(default_factory=ToolLedger)
    step: int = 0
    budget_spent_cny: float = 0.0
    budget_spent_tokens: int = 0
    prompt_tokens_total: int = 0
    completion_tokens_total: int = 0
    cached_tokens_total: int = 0
    burned_signatures: set[str] = Field(default_factory=set)
    halt_reason: str | None = None  # natural|max_steps|budget|spinning|repeated_failures|escalate
    escalate_offered: bool = False
    escalate_reason: str | None = None
    tool_choice: str = "auto"  # 升级熔断时被置 "none"(spec § 3.5)
    active_skill: str | None = None  # 活跃技能方法论不降级(spec § 3.4)
    downgraded_msg_indices: set[int] = Field(default_factory=set)  # turn 内降级幂等标记
    # ① 上下文压力安全阀:本圈按总量收紧降级跑了几轮(0=未触发);榨到下限仍超目标(best-effort)
    context_pressure_passes: int = 0
    context_pressure_floor_hit: bool = False
    final_response: str | None = None  # = 最后一条 assistant content
    approved_inputs: dict[str, ApprovedInput] = Field(default_factory=dict, exclude=True)

    model_config = ConfigDict(arbitrary_types_allowed=True)


# ---------------------------------------------------------------------------
# 状态折叠纯函数
# ---------------------------------------------------------------------------


def apply_step(state: ChatLoopState, step_result: StepResult) -> ChatLoopState:
    """LLM 一圈输出折叠进 state。

    - append assistant 消息(content + tool_calls,OpenAI 回传格式;
      无 tool_calls 时不带该键);
    - 若 step_result.reasoning 非空,写入 assistant_msg["reasoning_content"]
      供 SFT 轨迹收集;context.py 的 assemble_context 在投影到 LLM 窗口时会剥离该字段,
      确保 reasoning_content 进轨迹但不回送 LLM;
    - step+1;
    - 预算累计(completion+prompt tokens, cost);
    - finish_reason=="stop" 且无 tool_calls → final_response=content。

    返回 state(原地更新后返回同对象,调用方只用返回值)。
    """
    # 构建 assistant 消息
    assistant_msg: dict[str, Any] = {
        "role": "assistant",
        "content": step_result.content,
    }

    # 思考模型的推理过程:写入轨迹(SFT 监督目标),投影时由 assemble_context 剥离
    if step_result.reasoning:
        assistant_msg["reasoning_content"] = step_result.reasoning

    if step_result.tool_calls:
        # 转成 OpenAI tool_calls 格式
        assistant_msg["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": tc.arguments,
                },
            }
            for tc in step_result.tool_calls
        ]

    state.messages.append(assistant_msg)
    state.step += 1
    state.budget_spent_tokens += step_result.prompt_tokens + step_result.completion_tokens
    state.budget_spent_cny += step_result.cost_cny
    # ⑦ token 拆分累计(解锁 KV-cache 命中率 = cached/prompt;budget_spent_tokens 语义不动)
    state.prompt_tokens_total += step_result.prompt_tokens
    state.completion_tokens_total += step_result.completion_tokens
    state.cached_tokens_total += step_result.cached_tokens

    if step_result.finish_reason == "stop" and not step_result.tool_calls:
        state.final_response = step_result.content

    return state


def apply_results(
    state: ChatLoopState,
    results: list[ToolResult],
    calls: list[StepToolCall],
) -> ChatLoopState:
    """工具结果折叠:按 calls 顺序逐个 append tool 消息。

    协议红线:assistant(tool_calls) 后必须跟全部对应 tool 消息(每个 tool_call_id 一条)。
    长度断言 fail loud,保证 calls 与 results 一一对应。

    注:ledger 记账由 ToolHub 负责,本函数只管 messages 协议红线。
    """
    assert len(calls) == len(results), (
        f"apply_results: calls({len(calls)}) 与 results({len(results)}) 长度不匹配"
    )

    for call, result in zip(calls, results):
        if result.success and result.output is not None:
            content = json.dumps(result.output, ensure_ascii=False)
        elif not result.success:
            error_msg = result.error or "unknown error"
            content = f"[ERROR] {error_msg}"
        else:
            # success=True but output is None
            content = json.dumps(None, ensure_ascii=False)

        state.messages.append(
            {
                "role": "tool",
                "tool_call_id": call.id,
                "content": content,
            }
        )

    return state


def turn_summary(state: ChatLoopState) -> dict[str, Any]:
    """turn 级账单:成本/调用数/token 拆分/KV-cache 命中率(done 事件 data 用,⑦)。

    cache_hit_rate = cached_tokens / prompt_tokens(prompt=0 时取 0,不除零)。
    llm_calls = state.step(每圈一次 LLM);tool_calls = 台账条数。
    """
    p = state.prompt_tokens_total
    return {
        "cost_cny": round(state.budget_spent_cny, 4),
        "llm_calls": state.step,
        "tool_calls": len(state.ledger.entries),
        "prompt_tokens": p,
        "completion_tokens": state.completion_tokens_total,
        "cached_tokens": state.cached_tokens_total,
        "cache_hit_rate": round(state.cached_tokens_total / p, 3) if p else 0.0,
    }

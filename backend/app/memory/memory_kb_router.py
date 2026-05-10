"""Memory vs KB Search 检索路由 — supervisor router 决策模块。

spec ref:
  - docs/superpowers/specs/2026-05-10-c5-cross-session-memory-design.md § 11 末尾 #7
  - docs/superpowers/plans/2026-05-11-c5-plan-shared-contracts.md § 8

设计:
  - rule_match: 优先规则匹配(precision 高,延迟低,无 LLM cost)
  - LLM fallback(constrained, balanced tier, JSON output): 处理边界 case(规则未命中)
  - 默认 fallback: ["memory"](个人化场景多 — spec § 11 末尾 #7 (d))

输出 retrieval_targets ∈ {["memory"], ["kb"], ["both"]}.

§ 17 audit: 触发词清单 一字不漂移(契约 § 8 锁死)。
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

if TYPE_CHECKING:
    from app.services.llm_service import LLMService

logger = logging.getLogger(__name__)

# === § 8 契约触发词清单(不可漂移) ===

MEMORY_TRIGGER_WORDS: list[str] = [
    "我",
    "我的",
    "上次",
    "之前",
    "持仓",
    "偏好",
    "策略",
    "看好",
    "看空",
    "想法",
    "态度",
    "我说",
    "我提",
]

KB_TRIGGER_WORDS: list[str] = [
    "研报",
    "财报",
    "公告",
    "政策",
    "行业分析",
    "新闻",
    "市场",
    "宏观",
    "板块",
    "事件",
    "数据",
]

BOTH_TRIGGER_PATTERNS: list[str] = [
    r"基于我.*推荐",
    r"结合我.*",
    r"根据我.*分析",
    r"我.*的.*行业",
    r"我.*的.*相关",
    r"我.*跟.*对比",
]

RetrievalTarget = Literal["memory", "kb", "both"]


class RouterDecision(BaseModel):
    """One retrieval routing decision emitted by rule_match or LLM fallback."""

    model_config = ConfigDict(frozen=True)

    retrieval_targets: list[RetrievalTarget] = Field(
        ...,
        min_length=1,
        max_length=1,
        description=(
            "Single-element list per spec § 11 #7 — one of 'memory'/'kb'/'both'. "
            "List form preserved for forward-compat (e.g. multi-route fan-out)."
        ),
    )
    reasoning: str = Field(..., min_length=1, max_length=500)

    @field_validator("retrieval_targets")
    @classmethod
    def _check_target(cls, v: list[str]) -> list[str]:
        for t in v:
            if t not in ("memory", "kb", "both"):
                raise ValueError(f"Invalid target: {t!r}")
        return v


# === 规则层(precision-first) ===


def _hit_both_pattern(query: str) -> str | None:
    for pat in BOTH_TRIGGER_PATTERNS:
        m = re.search(pat, query)
        if m:
            return pat
    return None


def _hit_memory_word(query: str) -> str | None:
    for w in MEMORY_TRIGGER_WORDS:
        if w in query:
            return w
    return None


def _hit_kb_word(query: str) -> str | None:
    for w in KB_TRIGGER_WORDS:
        if w in query:
            return w
    return None


def rule_match(query: str) -> RouterDecision | None:
    """Pure-function rule-based routing.

    Returns None when no rule fires(让 LLM fallback 接);否则给 confidence-high decision。

    优先级:
      1. BOTH_TRIGGER_PATTERNS 命中 → both(最高优先级,防 memory 关键词遮蔽)
      2. memory + kb 都命中 → both(双触发)
      3. 单一类命中 → 对应 target
      4. 都不命中 → None
    """
    both_pat = _hit_both_pattern(query)
    if both_pat is not None:
        return RouterDecision(
            retrieval_targets=["both"],
            reasoning=f"both-pattern hit: {both_pat!r}",
        )

    mem_w = _hit_memory_word(query)
    kb_w = _hit_kb_word(query)

    if mem_w and kb_w:
        return RouterDecision(
            retrieval_targets=["both"],
            reasoning=f"both memory({mem_w!r}) and kb({kb_w!r}) words hit",
        )
    if mem_w:
        return RouterDecision(
            retrieval_targets=["memory"],
            reasoning=f"memory word hit: {mem_w!r}",
        )
    if kb_w:
        return RouterDecision(
            retrieval_targets=["kb"],
            reasoning=f"kb word hit: {kb_w!r}",
        )

    return None


# === LLM fallback layer(constrained-router pattern) ===

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL)

_LLM_ROUTER_PROMPT_TEMPLATE = """\
你是金融研究助手 chat 的检索路由 LLM。判断用户问题应该走哪条检索:

- "memory": 用户私人记忆(持仓 / 偏好 / 历史想法 / "我"/"我的"/"上次")
- "kb": 公开市场知识库(研报 / 财报 / 公告 / 政策 / 新闻 / 市场动态)
- "both": 个人化结合公开知识(基于我的持仓推荐 / 结合我的偏好分析 etc.)

用户问题:
{query}

严格按下列 JSON 输出, 不要带任何额外文字:
{{
  "retrieval_targets": ["<memory|kb|both>"],
  "reasoning": "<一句话解释为什么>"
}}

注意: retrieval_targets 是单元素 list, 必须是 "memory"/"kb"/"both" 三选一。
"""


class LLMRouterFallback:
    """Constrained-LLM fallback for router decisions when rules miss.

    Calls LLMService.chat(tier='balanced') + JSON output (constrained-router pattern,
    aligned with PR #39 ResearchPlanner). LLMService.chat is sync, so .decide() is
    sync too; the ``async def`` form is preserved for forward-compat with potential
    LLMService async transition.

    Invalid output(JSON parse fail / schema invalid / chat exception)falls back to
    ["memory"] per spec § 11 末尾 #7 (d).
    """

    def __init__(self, llm: LLMService) -> None:
        self._llm = llm

    async def decide(self, query: str) -> RouterDecision:
        prompt = _LLM_ROUTER_PROMPT_TEMPLATE.format(query=query)
        try:
            resp = self._llm.chat(prompt=prompt, tier="balanced")
        except Exception as e:  # noqa: BLE001 — LLM transient failure 全部 fallback
            logger.warning("LLMRouterFallback chat failed: %s — fallback to memory", e)
            return RouterDecision(
                retrieval_targets=["memory"],
                reasoning=f"llm fallback to memory due to chat error: {e!r}",
            )

        content = resp.content.strip()
        m = _CODE_FENCE_RE.match(content)
        if m:
            content = m.group(1).strip()

        try:
            parsed = json.loads(content)
            decision = RouterDecision.model_validate(parsed)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(
                "LLMRouterFallback parse failed: %s — content=%r — fallback to memory",
                e,
                content[:200],
            )
            return RouterDecision(
                retrieval_targets=["memory"],
                reasoning=f"llm fallback to memory due to parse/validate: {e!r}",
            )

        return decision


async def decide_retrieval_targets(
    query: str,
    llm_fallback: LLMRouterFallback | None,
) -> RouterDecision:
    """Top-level routing — rule first, LLM fallback, else default to memory.

    Args:
        query: 用户原始问题文本
        llm_fallback: 可选 LLMRouterFallback 实例,None 时无 LLM 调用(纯规则路径)

    Returns:
        RouterDecision with retrieval_targets ∈ {["memory"], ["kb"], ["both"]}.

    spec § 11 末尾 #7 (d): 默认 fallback ["memory"](个人化场景多)。
    """
    decision = rule_match(query)
    if decision is not None:
        return decision

    if llm_fallback is not None:
        return await llm_fallback.decide(query)

    return RouterDecision(
        retrieval_targets=["memory"],
        reasoning="no rule match & no llm fallback configured — default fallback to memory",
    )

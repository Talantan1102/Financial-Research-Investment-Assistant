"""Metric 3: Faithful Answer.

spec § 10 Metric 3:
    claims = decompose_to_claims(answer)
    grounded = sum(1 for c in claims if is_grounded(c, retrieved_facts))
    return grounded / len(claims)

特殊扩展(本 spec 任务要求): 在 LLM grounding judge 之外, 也校验
retrieved_fact 的 source_episode_id 关联的 episode 原文是否 substring 包含
claim 的关键词(provenance 强校验).

目标 ≥ 0.85.
"""

from __future__ import annotations

from typing import Any, Protocol


class JudgeProtocol(Protocol):
    """LLM judge 抽象接口 — 两个能力: decompose answer + ground claim."""

    async def decompose_to_claims(self, answer: str) -> list[str]:
        """把 answer 拆成 atomic claim list (LLM 调用)."""
        ...

    async def is_grounded(self, claim: str, facts: list[dict[str, Any]]) -> bool:
        """判断 claim 是否被 facts 中至少一条支持 (LLM 调用)."""
        ...


async def faithful_answer(
    answer: str,
    retrieved_facts: list[dict[str, Any]],
    judge: JudgeProtocol | None,
) -> float:
    """Return [0.0, 1.0] — 被 fact 支撑的 claim 比例.

    空 answer → 1.0 (vacuously faithful — agent 没 hallucinate).
    answer 非空但 judge=None → ValueError (调用方契约错误).
    decompose 返回空 list → 1.0 (LLM 没识别出 atomic claim, 不算 hallucination).
    """
    if not answer.strip():
        return 1.0
    if judge is None:
        raise ValueError("judge required for non-empty answer")
    claims = await judge.decompose_to_claims(answer)
    if not claims:
        return 1.0
    grounded = 0
    for c in claims:
        if await judge.is_grounded(c, retrieved_facts):
            grounded += 1
    return grounded / len(claims)


def claim_in_episode_text(claim: str, facts: list[dict[str, Any]]) -> bool:
    """Provenance 强校验: claim 关键词是否在任一 retrieved fact 的 episode 原文 substring 出现.

    spec 任务要求: "检查回答内容是否在原 episode 找得到 substring"
    fact dict 需含 '_episode_text' 字段 (检索时 join 出来).

    单 fact 没有 _episode_text 跳过该 fact (不强制 fail).
    所有 fact 都没有 _episode_text → False (provenance 不可校验).

    用作 grounding judge 的辅助 / 测试 oracle, 真 LLM judge 独立调用.
    """
    if not claim or not claim.strip():
        return False
    claim_norm = "".join(claim.split())
    if not claim_norm:
        return False
    any_text_seen = False
    for f in facts:
        ep_text = f.get("_episode_text")
        if not ep_text:
            continue
        any_text_seen = True
        ep_norm = "".join(ep_text.split())
        if claim_norm in ep_norm:
            return True
    return False if any_text_seen else False

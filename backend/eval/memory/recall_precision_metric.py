"""Metric 1: Recall Precision.

spec § 10 Metric 1:
    precision = relevant_count / len(retrieved_facts)
    relevant 由 LLM-judge 输出 yes/no 决定.

目标 top-5 ≥ 0.7.

设计:
    judge 是 Protocol, 允许 mock (test) 和 real LLM (live eval) 互换.
    fact dict 通用形态: {rel_type, source_label, target_label, properties, ...}
"""

from __future__ import annotations

from typing import Any, Protocol


class JudgeProtocol(Protocol):
    """LLM judge 抽象接口.

    real impl: backend/eval/memory/_runner_deps.py _LiveJudge (haiku 调 LLM).
    mock impl: backend/tests/conftest.py mock_llm_judge (set_canned_verdicts).
    """

    async def eval(self, query: str, fact: dict[str, Any], prompt: str) -> str:
        """Return 'yes' or 'no' (case-insensitive)."""
        ...


JUDGE_PROMPT = """\
You are evaluating whether a fact is relevant to a user query in a financial assistant.

Query: {query}
Fact: {fact_repr}

Answer with exactly "yes" or "no" — is this fact relevant to the query?
"""


def _fact_repr(fact: dict[str, Any]) -> str:
    rt = fact.get("rel_type", "")
    sl = fact.get("source_label", "User")
    tl = fact.get("target_label", "")
    props = fact.get("properties", {})
    return f"{sl} -[{rt}]-> {tl} (props={props})"


async def recall_precision(
    query: str,
    retrieved_facts: list[dict[str, Any]],
    judge: JudgeProtocol | None,
) -> float:
    """Return precision ∈ [0.0, 1.0].

    空集 → 0.0 (无法判断, 视为 fail).
    非空但 judge=None → ValueError (调用方契约错误).
    """
    if not retrieved_facts:
        return 0.0
    if judge is None:
        raise ValueError("judge required when retrieved_facts non-empty")
    relevant = 0
    for fact in retrieved_facts:
        verdict = await judge.eval(
            query=query,
            fact=fact,
            prompt=JUDGE_PROMPT.format(query=query, fact_repr=_fact_repr(fact)),
        )
        if verdict.strip().lower().startswith("yes"):
            relevant += 1
    return relevant / len(retrieved_facts)

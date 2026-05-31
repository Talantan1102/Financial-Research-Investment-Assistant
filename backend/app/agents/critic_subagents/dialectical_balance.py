"""v1.x A5b: Critic 第 8 维 — dialectical_balance rule-based scorer.

评分规则(spec § 9.2):
  - debate_trace is None → 10.0 (skip, debate failed / not run)
  - bull/bear 双方都 ≥ 2 条 argument 出现在 narrative → 9.0 (真双向)
  - 只有一边 ≥ 2 条 → 3.0 (掩盖一面)
  - 双方各仅 1 条 → 6.0 (论据稀薄)
  - bull_v1/v2 + bear_v1/v2 全 None → 10.0 skip

阈值 < 7.0 触发 writer retry (Task 8 wire 进 graph)。
sync API,跟 ValuationConsistencyScorer 同 pattern。

spec ref: 2026-05-16-v1.x-bull-bear-debate-design.md § 9 / § 11
"""

from __future__ import annotations

from app.agents.base import Agent
from app.agents.debate_schemas import DebateTrace
from app.agents.schemas import CriticDimension, CriticDimensionScore, ResearchState, StepResult
from app.services.llm_response import Tier
from app.services.llm_service import LLMService

__all__ = ["DialecticalBalanceScorer"]


def _pick_final_arguments(trace: DebateTrace | None) -> tuple[list[str], list[str]] | None:
    """从 DebateTrace 选 final v2 (rounds_completed=2) 或 v1 (rounds_completed=1).

    全 None / rounds_completed=0 → return None (caller 判 skip)."""
    if trace is None:
        return None
    if trace.rounds_completed == 2:
        bull = trace.bull_v2
        bear = trace.bear_v2
    elif trace.rounds_completed == 1:
        bull = trace.bull_v1
        bear = trace.bear_v1
    else:
        return None
    if bull is None or bear is None:
        return None
    return (list(bull.arguments), list(bear.arguments))


def _count_substring_matches(text: str, candidates: list[str]) -> int:
    """统计 candidates 中有多少条作为 substring 出现在 text 中."""
    return sum(1 for c in candidates if c in text)


class DialecticalBalanceScorer(Agent):
    """Critic 第 8 维 scorer. Rule-based, sync API. 不调 LLM."""

    name = "DialecticalBalanceScorer"
    dimension: CriticDimension = "dialectical_balance"
    state_field = "dialectical_balance_score"
    model_tier: Tier = "fast"

    def __init__(self, *, llm: LLMService) -> None:
        super().__init__(llm)

    def step(self, state: ResearchState) -> StepResult:  # type: ignore[override]
        """v1.x A5b 评 narrative 是否真双向论证."""
        picked = _pick_final_arguments(state.debate_trace)
        if picked is None:
            return StepResult(
                state_update={
                    self.state_field: CriticDimensionScore(
                        dimension=self.dimension,
                        score=10.0,
                        evidence="skip (no debate trace or advocate全失败)",
                        sub_agent_request_id=state.request_id,
                        is_skip=True,  # C18: excluded from overall_score
                    )
                },
                span_metadata={"agent": self.name, "dimension": self.dimension, "skipped": True},
            )

        bull_args, bear_args = picked
        report_md = state.report_markdown or ""
        bull_count = _count_substring_matches(report_md, bull_args)
        bear_count = _count_substring_matches(report_md, bear_args)

        if bull_count >= 2 and bear_count >= 2:
            score, evidence = 9.0, f"双向论证 (bull {bull_count} / bear {bear_count})"
        elif bull_count >= 2 and bear_count < 2:
            score, evidence = 3.0, f"掩盖看空 (bull {bull_count} / bear {bear_count})"
        elif bear_count >= 2 and bull_count < 2:
            score, evidence = 3.0, f"掩盖看多 (bull {bull_count} / bear {bear_count})"
        elif bull_count == 1 and bear_count == 1:
            score, evidence = 6.0, "论据稀薄 (bull 1 / bear 1)"
        else:
            score, evidence = (
                4.0,
                f"narrative 几乎不引用 debate (bull {bull_count} / bear {bear_count})",
            )

        return StepResult(
            state_update={
                self.state_field: CriticDimensionScore(
                    dimension=self.dimension,
                    score=score,
                    evidence=evidence,
                    sub_agent_request_id=state.request_id,
                )
            },
            span_metadata={
                "agent": self.name,
                "dimension": self.dimension,
                "bull_count": bull_count,
                "bear_count": bear_count,
            },
        )

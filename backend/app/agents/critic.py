"""Critic — orchestrates 6-dim parallel scoring via LangGraph subgraph (Send API).

The actual fan-out + reduce happens at the orchestration layer
(critic_subgraph.py). Critic class itself owns the sub_agents list and
provides:
  - dispatch_subagent(name, state) → real implementation (override v0
    base.py's NotImplementedError placeholder)
  - aggregate_scores helper for the subgraph reduce phase
  - step() sync fallback for unit-test of Agent contract

6 dimensions (v0.8.4):
  factuality / coverage / insight / structure / conciseness /
  input_context_appropriateness (第 6 scorer — 报告是否真 condition on 6 input 字段)
"""

from __future__ import annotations

from app.agents.base import Agent
from app.agents.schemas import (
    CriticDimensionScore,
    CriticReport,
    ResearchState,
    StepResult,
)
from app.services.llm_response import Tier
from app.services.llm_service import LLMService


class Critic(Agent):
    name = "Critic"
    model_tier: Tier = "balanced"  # nominal; aggregate doesn't call LLM

    def __init__(self, llm: LLMService, scorers: list[Agent]) -> None:
        super().__init__(llm)
        self._scorers = scorers

    @property
    def scorers(self) -> list[Agent]:
        return list(self._scorers)

    def step(self, state: ResearchState) -> StepResult:  # type: ignore[override]
        """Sync fallback (used by unit tests, not LangGraph subgraph)."""
        scores: list[CriticDimensionScore] = []
        for scorer in self._scorers:
            sr = scorer.step(state)  # type: ignore[arg-type]
            for v in sr.state_update.values():
                if isinstance(v, CriticDimensionScore):
                    scores.append(v)
        report = aggregate_scores(scores, summary="(unit-test aggregation)")
        return StepResult(
            state_update={"critic_report": report},
            span_metadata={"agent": "Critic", "n_scorers": len(self._scorers)},
        )

    def dispatch_subagent(self, name: str, state: ResearchState) -> StepResult:  # type: ignore[override]
        """Override v0 base.py 的 NotImplementedError 占位。"""
        target = next((s for s in self._scorers if s.name == name), None)
        if target is None:
            raise KeyError(f"sub-agent {name!r} not found in Critic._scorers")
        return target.step(state)  # type: ignore[arg-type]


def aggregate_scores(dims: list[CriticDimensionScore], *, summary: str = "") -> CriticReport:
    """Compute overall_score = mean(dim scores), excluding skip-sentinel dims.

    C18: ValuationConsistencyScorer and DialecticalBalanceScorer return
    score=10.0 with is_skip=True when their optional feature (A5a/A5b) was not
    run.  Including those 10.0s would inflate the reported overall_score.
    We use getattr so this is forward-compatible even before schemas.py adds
    the is_skip field (the field defaults False once added; until then every dim
    is treated as active, which is the pre-fix behaviour).
    """
    if not dims:
        return CriticReport(dimensions=[], overall_score=0.0, summary_markdown=summary)
    # C18: filter out skip-sentinel dims; keep all dims in the report for display
    active = [d for d in dims if not getattr(d, "is_skip", False)]
    overall = 0.0 if not active else sum(d.score for d in active) / len(active)
    return CriticReport(dimensions=dims, overall_score=overall, summary_markdown=summary)

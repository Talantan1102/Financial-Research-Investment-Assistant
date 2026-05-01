"""Critic — orchestrates 5-dim parallel scoring via LangGraph subgraph (Send API).

The actual fan-out + reduce happens at the orchestration layer
(critic_subgraph.py). Critic class itself owns the sub_agents list and
provides:
  - dispatch_subagent(name, state) → real implementation (override v0
    base.py's NotImplementedError placeholder)
  - aggregate_scores helper for the subgraph reduce phase
  - step() sync fallback for unit-test of Agent contract
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
    """Compute overall_score = mean(dim scores)."""
    if not dims:
        return CriticReport(dimensions=[], overall_score=0.0, summary_markdown=summary)
    overall = sum(d.score for d in dims) / len(dims)
    return CriticReport(dimensions=dims, overall_score=overall, summary_markdown=summary)

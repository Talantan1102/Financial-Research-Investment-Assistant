"""Critic 内部 subgraph — Send API fan-out 7 sub-agents + reduce + aggregate.

v1.x A5a: 加入第 7 维 valuation_consistency (rule-based scorer, 不调 LLM)。
"""

from __future__ import annotations

import operator
from typing import Annotated, Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from pydantic import BaseModel, ConfigDict, Field

from app.agents.critic import Critic, aggregate_scores
from app.agents.investment_dd_schema import InvestmentDueDiligenceReport, ValuationAnalysis
from app.agents.schemas import (
    CriticDimensionScore,
    CriticReport,
    Insight,
    InvestmentHorizon,
    InvestmentObjective,
    ResearchPlan,
    ResearchState,
    RiskTolerance,
    ToolResult,
)


class _CriticSubState(BaseModel):
    """Subgraph state — top-level field names mirrored + collected_scores reducer."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_id: str
    session_id: str
    user_message: str
    request_id: str
    report_markdown: str | None = None
    investment_report: InvestmentDueDiligenceReport | None = None
    insights: list[Insight] = Field(default_factory=list)
    plan: ResearchPlan | None = None
    tool_results: list[ToolResult] = Field(default_factory=list)

    # v0.8.4 — 6 structured input fields (for InputContextAppropriatenessScorer)
    target_ts_code: str | None = None
    client_total_aum: float | None = None
    client_existing_position: float | None = None
    investment_objective: InvestmentObjective | None = None
    investment_horizon: InvestmentHorizon | None = None
    risk_tolerance: RiskTolerance | None = None

    # v1.x A5a — multi-model cross-check signals (for ValuationConsistencyScorer)
    valuation_analysis: ValuationAnalysis | None = None

    # reducer field — 7 scorer 各自 append 一个,框架自动 concat (operator.add 对 list 是 concat)
    collected_scores: Annotated[list[CriticDimensionScore], operator.add] = Field(
        default_factory=list
    )

    # Output field — written by aggregate node
    critic_report: CriticReport | None = None


def _scorer_node_factory(critic: Critic, scorer_name: str) -> Any:
    """Wrap scorer.step into a node function appending its score to collected_scores."""

    async def node(state: dict[str, Any]) -> dict[str, Any]:
        # LangGraph sends dicts when using Send API, so we normalise via Pydantic.
        s = _CriticSubState.model_validate(state)
        rs = ResearchState(
            user_id=s.user_id,
            session_id=s.session_id,
            user_message=s.user_message,
            request_id=s.request_id,
            report_markdown=s.report_markdown,
            investment_report=s.investment_report,
            insights=s.insights,
            plan=s.plan,
            tool_results=s.tool_results,
            # v0.8.4 — pass 6 structured input fields for InputContextAppropriatenessScorer
            target_ts_code=s.target_ts_code,
            client_total_aum=s.client_total_aum,
            client_existing_position=s.client_existing_position,
            investment_objective=s.investment_objective,
            investment_horizon=s.investment_horizon,
            risk_tolerance=s.risk_tolerance,
            # v1.x A5a — pass multi-model cross-check for ValuationConsistencyScorer
            valuation_analysis=s.valuation_analysis,
        )
        # v0.9.x note: 不 wrap asyncio.to_thread — 该 wrap 让 6 scorer 真并发,
        # VCR cassette 按调用顺序匹配 LLM responses,导致 b1_differential
        # input_context_appropriateness score 错位 (8.5+ → 6.0). critic 是
        # 短任务 (每个几百 tokens),sync 调用即使 serialize 也不会卡 event
        # loop 太久; 真正卡的是 Writer 长 LLM 调用 (8000 tokens),那边保留
        # to_thread wrap.
        sr = critic.dispatch_subagent(name=scorer_name, state=rs)
        scores = [v for v in sr.state_update.values() if isinstance(v, CriticDimensionScore)]
        return {"collected_scores": scores}

    return node


def _planner_router(state: _CriticSubState) -> list[Send]:
    """Fan-out to 7 scorer nodes via Send API (v1.x A5a)."""
    payload = state.model_dump()
    return [
        Send("scorer_factuality", payload),
        Send("scorer_coverage", payload),
        Send("scorer_insight", payload),
        Send("scorer_structure", payload),
        Send("scorer_conciseness", payload),
        Send("scorer_input_context", payload),
        Send("scorer_valuation_consistency", payload),
    ]


async def _aggregate_node(state: _CriticSubState) -> dict[str, Any]:
    n = len(state.collected_scores)
    avg = sum(d.score for d in state.collected_scores) / n if n > 0 else 0.0
    summary = f"{n}-dim parallel scoring; collected={n}; overall={avg:.2f}"
    report = aggregate_scores(state.collected_scores, summary=summary)
    return {"critic_report": report}


def build_critic_subgraph(critic: Critic) -> Any:
    """Build the Critic subgraph; compile into a node-friendly object."""
    g: StateGraph[Any, Any, Any, Any] = StateGraph(_CriticSubState)

    g.add_node("scorer_factuality", _scorer_node_factory(critic, "FactualityScorer"))
    g.add_node("scorer_coverage", _scorer_node_factory(critic, "CoverageScorer"))
    g.add_node("scorer_insight", _scorer_node_factory(critic, "InsightScorer"))
    g.add_node("scorer_structure", _scorer_node_factory(critic, "StructureScorer"))
    g.add_node("scorer_conciseness", _scorer_node_factory(critic, "ConcisenessScorer"))
    g.add_node(
        "scorer_input_context",
        _scorer_node_factory(critic, "InputContextAppropriatenessScorer"),
    )
    g.add_node(
        "scorer_valuation_consistency",
        _scorer_node_factory(critic, "ValuationConsistencyScorer"),
    )
    g.add_node("aggregate", _aggregate_node)

    g.add_conditional_edges(
        START,
        _planner_router,
        [
            "scorer_factuality",
            "scorer_coverage",
            "scorer_insight",
            "scorer_structure",
            "scorer_conciseness",
            "scorer_input_context",
            "scorer_valuation_consistency",
        ],
    )
    for n in [
        "scorer_factuality",
        "scorer_coverage",
        "scorer_insight",
        "scorer_structure",
        "scorer_conciseness",
        "scorer_input_context",
        "scorer_valuation_consistency",
    ]:
        g.add_edge(n, "aggregate")
    g.add_edge("aggregate", END)

    return g.compile()

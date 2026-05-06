"""L1 integration — v0.8.5 retry edge in research_graph.py.

Verifies the conditional edge that routes back from critic_node to
research_planner_node when PlanCorrectnessScorer scores < 8.5 AND
planner_retry_count < 2 (max 2 retries).

Graph topology under test::

    START → research_planner_node → data_collector_node → analyst_node
          → writer_node → critic_node →┐
                                       ├─(plan_correctness < 8.5
                                       │  AND retry < 2) → planner_retry_transition
                                       │                  → research_planner_node (loop)
                                       └─(else)            → END

Test strategy:
  - All 4 outer-graph agents (planner / collector / analyst / writer) and the
    Critic are wired with stubs that produce deterministic StepResults — no
    real LLM calls. The PlanCorrectnessScorer is monkeypatched so we control
    the score sequence.
  - The retry router is the real one from research_graph.py.
  - The transition node is the real one from research_graph.py.
  - We assert final state.planner_retry_count + state.plan == observed score.

spec ref: docs/superpowers/specs/2026-05-05-v0.8.5-constrained-router-design.md § 4.4
spec ref: docs/superpowers/plans/2026-05-05-v0.8.5-constrained-router-implementation.md § Task 9
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from app.agents.base import Agent
from app.agents.critic import Critic
from app.agents.critic_subagents.plan_correctness_scorer import PlanCorrectnessScorer
from app.agents.investment_dd_schema import (
    DEFAULT_DISCLAIMER,
    FinancialAnalysis,
    IndustryAnalysis,
    InvestmentDueDiligenceReport,
    InvestmentRecommendation,
    LegalQualification,
    PriceRange,
    RiskAssessment,
    TargetOverview,
    ValuationAnalysis,
)
from app.agents.research_planner import ResearchPlanner
from app.agents.schemas import (
    CriticDimensionScore,
    Insight,
    ResearchPlan,
    ResearchState,
    StepResult,
    Subtask,
    ToolResult,
)
from app.orchestration.research_graph import build_research_graph

# ---------------------------------------------------------------------------
# Stub agents — return deterministic StepResults so the graph topology can run
# without any LLM calls. Only PlanCorrectnessScorer is exercised (mocked below).
# ---------------------------------------------------------------------------


class _StubResearchPlanner(ResearchPlanner):
    """Returns a fixed plan_id=balanced + rationale, bypasses LLM call."""

    name = "ResearchPlanner"

    def step(self, state: ResearchState) -> StepResult:  # type: ignore[override]
        plan = ResearchPlan(
            plan_id="balanced",
            rationale="stub planner",
            subtasks=[
                Subtask(
                    subtask_id="overview",
                    description="stub",
                    required_tools=["get_stock_quote"],
                    rationale="stub",
                )
            ],
        )
        return StepResult(state_update={"plan": plan}, span_metadata={"agent": "ResearchPlanner"})


class _StubDataCollector(Agent):
    """Returns one canned ToolResult; never touches a real ToolRegistry."""

    name = "DataCollector"
    model_tier = "fast"

    def step(self, state: ResearchState) -> StepResult:  # type: ignore[override]
        tr = ToolResult(
            tool_name="get_stock_quote",
            args={"ts_code": "600519.SH"},
            success=True,
            output={"price": 1820.5},
            error=None,
            latency_ms=10,
        )
        return StepResult(state_update={"tool_results": [tr]}, span_metadata={})

    async def collect_async(self, state: ResearchState) -> StepResult:
        return self.step(state)


class _StubAnalyst(Agent):
    """Returns a single Insight."""

    name = "Analyst"
    model_tier = "fast"

    def step(self, state: ResearchState) -> StepResult:  # type: ignore[override]
        ins = Insight(
            subtask_id="overview",
            finding="stub finding",
            supporting_data=[{"price": 1820.5}],
            confidence="medium",
        )
        return StepResult(state_update={"insights": [ins]}, span_metadata={})


class _StubWriter(Agent):
    """Returns a minimal InvestmentDueDiligenceReport without LLM."""

    name = "Writer"
    model_tier = "balanced"

    def step(self, state: ResearchState) -> StepResult:  # type: ignore[override]
        report = _build_minimal_report(state.request_id)
        return StepResult(
            state_update={
                "investment_report": report,
                "report_markdown": "# stub report",
                "chart_specs": [],
            },
            span_metadata={},
        )

    async def run(self, state: ResearchState) -> ResearchState:
        sr = self.step(state)
        return state.model_copy(update=sr.state_update)


def _build_minimal_report(request_id: str) -> InvestmentDueDiligenceReport:
    """Construct the smallest valid InvestmentDueDiligenceReport for stub Writer."""
    return InvestmentDueDiligenceReport(
        target_name="贵州茅台",
        target_ts_code="600519.SH",
        request_id=request_id,
        generated_at=datetime(2026, 5, 5, 12, 0, 0),
        target_overview=TargetOverview(narrative="stub", main_business="stub"),
        legal_qualification=LegalQualification(
            narrative="stub",
            legal_status="stub",
            business_qualifications=[],
            adverse_records=[],
        ),
        financial_analysis=FinancialAnalysis(
            narrative="stub",
            key_metrics=[],
            profitability_analysis="stub",
            growth_analysis="stub",
            return_analysis="stub",
            cash_flow_analysis="stub",
            valuation_analysis=ValuationAnalysis(narrative="stub"),
        ),
        industry_analysis=IndustryAnalysis(
            narrative="stub",
            industry_name="stub",
            industry_outlook="stub",
            competitive_position="stub",
            key_competitors=[],
            policy_impact="stub",
        ),
        risk_assessment=RiskAssessment(
            narrative="stub",
            market_risk=[],
            growth_risk=[],
            event_risk=[],
            valuation_risk=[],
            overall_risk_level="medium",
        ),
        investment_recommendation=InvestmentRecommendation(
            narrative="stub",
            recommendation="recommend_hold",
            recommended_position_size_pct=5.0,
            recommended_holding_period="medium_term",
            recommended_entry_price_range=PriceRange(low=1700.0, high=1800.0),
            recommended_stop_loss_price=1600.0,
            estimated_target_price_range=PriceRange(low=1900.0, high=2100.0),
            position_management_conditions=[],
        ),
        disclaimer=DEFAULT_DISCLAIMER,
    )


# ---------------------------------------------------------------------------
# Stub scorers — emit fixed scores so plan_correctness is the only varying dim.
# ---------------------------------------------------------------------------


class _StubFixedScorer(Agent):
    """Reusable stub scorer: emits a CriticDimensionScore with a fixed score.

    Used for the 6 non-plan-correctness dimensions which the retry router does
    not consult. score=10.0 keeps overall_score numerically reasonable.

    NB: ``self.name`` must exactly match the class-name string the critic
    subgraph uses to dispatch (FactualityScorer / CoverageScorer / …).
    """

    model_tier = "balanced"

    def __init__(self, *, scorer_class_name: str, dim_name: str) -> None:  # noqa: D401
        # Dont call Agent.__init__ — we never use self._llm.
        self.name = scorer_class_name
        self._dim_name = dim_name

    def step(self, state: ResearchState) -> StepResult:  # type: ignore[override]
        score = CriticDimensionScore(
            dimension=self._dim_name,  # type: ignore[arg-type]
            score=10.0,
            evidence="stub",
            sub_agent_request_id=state.request_id,
        )
        return StepResult(
            state_update={f"{self._dim_name}_score": score},
            span_metadata={"agent": self.name, "dimension": self._dim_name},
        )


# ---------------------------------------------------------------------------
# PlanCorrectness mock factory — yields a sequence of scores across calls.
# ---------------------------------------------------------------------------


def _make_pc_scorer_with_score_sequence(
    score_sequence: list[float],
) -> tuple[PlanCorrectnessScorer, list[float]]:
    """Build a real PlanCorrectnessScorer subclass that yields scores per call.

    Returns (scorer, calls_list_ref). ``calls_list_ref`` is mutated to record
    each consumed score so tests can assert on call count.
    """

    class _StubPlanCorrectnessScorer(PlanCorrectnessScorer):
        name = "PlanCorrectnessScorer"

        def __init__(self) -> None:  # noqa: D401
            # Skip super().__init__ — we never use self._llm.
            self._sequence = list(score_sequence)
            self._calls: list[float] = []

        def step(self, state: ResearchState) -> StepResult:  # type: ignore[override]
            if not self._sequence:
                raise AssertionError(
                    "PlanCorrectnessScorer called more times than scripted in test"
                )
            score = self._sequence.pop(0)
            self._calls.append(score)
            dim = CriticDimensionScore(
                dimension="plan_correctness",
                score=score,
                evidence=f"mock evidence retry {len(self._calls)}",
                sub_agent_request_id=state.request_id,
            )
            return StepResult(
                state_update={"plan_correctness_score": dim},
                span_metadata={"agent": self.name, "dimension": "plan_correctness"},
            )

    inst = _StubPlanCorrectnessScorer()
    return inst, inst._calls


# ---------------------------------------------------------------------------
# Graph builder helper
# ---------------------------------------------------------------------------


def _build_graph_with_pc_score_sequence(score_sequence: list[float]) -> tuple[Any, list[float]]:
    """Build a research graph with stub agents + a scripted PlanCorrectnessScorer."""
    # _llm passed to ResearchPlanner only used by Agent.__init__; stubs override step()
    # so any sentinel works. Use a MagicMock-safe placeholder.
    sentinel_llm: Any = object()
    planner = _StubResearchPlanner.__new__(_StubResearchPlanner)
    planner._llm = sentinel_llm
    collector = _StubDataCollector.__new__(_StubDataCollector)
    collector._llm = sentinel_llm
    analyst = _StubAnalyst.__new__(_StubAnalyst)
    analyst._llm = sentinel_llm
    writer = _StubWriter.__new__(_StubWriter)
    writer._llm = sentinel_llm

    # 6 fixed scorers (10.0) + 1 scripted plan_correctness scorer.
    # scorer_class_name must match the critic_subgraph dispatch keys
    # (FactualityScorer / CoverageScorer / …).
    pc_scorer, calls = _make_pc_scorer_with_score_sequence(score_sequence)
    scorers: list[Agent] = [
        _StubFixedScorer(scorer_class_name="FactualityScorer", dim_name="factuality"),
        _StubFixedScorer(scorer_class_name="CoverageScorer", dim_name="coverage"),
        _StubFixedScorer(scorer_class_name="InsightScorer", dim_name="insight"),
        _StubFixedScorer(scorer_class_name="StructureScorer", dim_name="structure"),
        _StubFixedScorer(scorer_class_name="ConcisenessScorer", dim_name="conciseness"),
        _StubFixedScorer(
            scorer_class_name="InputContextAppropriatenessScorer",
            dim_name="input_context_appropriateness",
        ),
        pc_scorer,
    ]
    critic = Critic.__new__(Critic)
    critic._llm = sentinel_llm
    critic._scorers = scorers

    graph = build_research_graph(
        planner=planner,
        collector=collector,  # type: ignore[arg-type]
        analyst=analyst,  # type: ignore[arg-type]
        writer=writer,  # type: ignore[arg-type]
        critic=critic,
        db_path=None,
    )
    return graph, calls


def _make_initial_state() -> ResearchState:
    return ResearchState(
        user_id="test",
        session_id="sess-retry",
        user_message="测试 retry edge",
        request_id="req-retry-001",
        target_ts_code="600519.SH",
        client_total_aum=10_000_000.0,
        investment_objective="balanced",
        investment_horizon="medium_term",
        risk_tolerance="moderate",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_planner_retry_when_plan_correctness_low() -> None:
    """1 轮 retry 收敛: 第 1 次 5.0 → retry → 第 2 次 9.0 → continue.

    Expected: planner_retry_count == 1 at terminal state, both scorer calls
    consumed, final critic_report.plan_correctness == 9.0.
    """
    graph, calls = _build_graph_with_pc_score_sequence([5.0, 9.0])
    initial = _make_initial_state()

    result = await graph.ainvoke(initial.model_dump())
    final = ResearchState.model_validate(result)

    assert final.planner_retry_count == 1, (
        f"Expected retry_count=1 (1 retry to converge), got {final.planner_retry_count}"
    )
    assert calls == [5.0, 9.0], f"Expected scorer called twice with [5.0, 9.0], got {calls}"
    assert final.critic_report is not None
    assert final.critic_report.get_score("plan_correctness") == 9.0
    # Critic feedback was injected on the first retry (carries the failing dim
    # evidence string from round 1).
    assert final.planner_critic_feedback is not None
    assert "mock evidence retry 1" in final.planner_critic_feedback


@pytest.mark.asyncio
async def test_planner_retry_max_2_no_infinite_loop() -> None:
    """死循环防护: 一直 5.0 → max 2 retry 后 continue.

    Expected: planner_retry_count == 2 (hard cap), 3 scorer calls (1 initial +
    2 retries), graph terminates without infinite loop.
    """
    graph, calls = _build_graph_with_pc_score_sequence([5.0, 5.0, 5.0])
    initial = _make_initial_state()

    result = await graph.ainvoke(initial.model_dump())
    final = ResearchState.model_validate(result)

    assert final.planner_retry_count == 2, (
        f"Expected retry_count=2 (hard cap), got {final.planner_retry_count}. "
        f"_MAX_PLANNER_RETRY enforcement broken."
    )
    assert calls == [5.0, 5.0, 5.0], f"Expected 3 scorer calls (1+2 retries), got {calls}"
    assert final.critic_report is not None
    assert final.critic_report.get_score("plan_correctness") == 5.0


@pytest.mark.asyncio
async def test_planner_no_retry_when_score_high() -> None:
    """高分零 retry: 第 1 次 9.5 → 不 retry, 直接 END.

    Expected: planner_retry_count == 0, exactly 1 scorer call,
    planner_critic_feedback stays None (never populated).
    """
    graph, calls = _build_graph_with_pc_score_sequence([9.5])
    initial = _make_initial_state()

    result = await graph.ainvoke(initial.model_dump())
    final = ResearchState.model_validate(result)

    assert final.planner_retry_count == 0, (
        f"Expected retry_count=0 (no retry needed), got {final.planner_retry_count}"
    )
    assert calls == [9.5], f"Expected 1 scorer call, got {calls}"
    assert final.critic_report is not None
    assert final.critic_report.get_score("plan_correctness") == 9.5
    assert final.planner_critic_feedback is None, (
        "planner_critic_feedback should never be set when no retry happened"
    )

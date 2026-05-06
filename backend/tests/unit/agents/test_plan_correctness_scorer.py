"""Unit tests for PlanCorrectnessScorer (Critic 第 7 scorer, v0.8.5).

Tests use a MagicMock LLM (no real network, no cassette). LLMService is bypassed
entirely by injecting MagicMock as the llm parameter, so the scorer.step() path
exercises only prompt formatting + parsed-result extraction.

spec ref: docs/superpowers/specs/2026-05-05-v0.8.5-constrained-router-design.md § 4.3
"""

from __future__ import annotations

from unittest.mock import MagicMock

from app.agents.critic_subagents.plan_correctness_scorer import (
    PlanCorrectnessScorer,
    _PlanCorrectnessScore,
)
from app.agents.schemas import (
    CriticDimensionScore,
    InvestmentObjective,
    PlanId,
    ResearchPlan,
    ResearchState,
)
from app.services.llm_response import LLMResponse


def _make_mock_llm(score: float, reasoning: str) -> MagicMock:
    """Return a MagicMock whose chat() returns an LLMResponse with parsed score."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = LLMResponse(
        content=f'{{"score": {score}, "reasoning": "{reasoning}"}}',
        parsed=_PlanCorrectnessScore(score=score, reasoning=reasoning),
        model="qwen-plus",
        tier="balanced",
        prompt_tokens=200,
        completion_tokens=50,
        total_tokens=250,
        cost_cny=0.001,
        latency_ms=100,
        request_id="req-mock-pc-001",
    )
    return mock_llm


def _make_state(
    *,
    plan_id: PlanId,
    rationale: str,
    user_msg: str | None = None,
    objective: InvestmentObjective = "balanced",
) -> ResearchState:
    """Build a ResearchState with a populated ResearchPlan for scorer testing."""
    state = ResearchState(
        user_id="test",
        session_id="sess-test",
        user_message=user_msg or "",  # ResearchState.user_message is required str
        request_id="req-test-pc-001",
        target_ts_code="600519.SH",
        target_entity="贵州茅台",
        client_total_aum=10_000_000.0,
        investment_objective=objective,
        investment_horizon="medium_term",
        risk_tolerance="moderate",
        plan=ResearchPlan(plan_id=plan_id, rationale=rationale),
    )
    return state


# ---------------------------------------------------------------------------
# Acceptance tests: high score for well-aligned plan, low score for mismatched
# ---------------------------------------------------------------------------


def test_scorer_high_score_for_well_aligned_plan() -> None:
    """plan_id 匹配 user_message override → 高分 (≥ 8.5).

    Scenario: objective=balanced but user_message contains "避险/担心下跌",
    correctly triggering override exception 2 → capital_preservation.
    Mock LLM returns score=9.0 to simulate a real judge approving the override.
    """
    mock_llm = _make_mock_llm(score=9.0, reasoning="正确触发避险 override 例外 2")
    scorer = PlanCorrectnessScorer(llm=mock_llm)
    state = _make_state(
        objective="balanced",
        plan_id="capital_preservation",
        rationale="user_message 含'避险', 触发 override 例外 2",
        user_msg="担心下跌避险",
    )

    sr = scorer.step(state)

    score_obj = sr.state_update["plan_correctness_score"]
    assert isinstance(score_obj, CriticDimensionScore)
    assert score_obj.dimension == "plan_correctness"
    assert score_obj.score == 9.0
    assert score_obj.score >= 8.5  # well-aligned threshold
    assert score_obj.evidence  # reasoning surfaces as evidence
    assert sr.span_metadata["agent"] == "PlanCorrectnessScorer"
    assert sr.span_metadata["dimension"] == "plan_correctness"


def test_scorer_low_score_for_mismatched_plan() -> None:
    """plan_id 跟 user_message 矛盾 → 低分 (< 6).

    Scenario: user_message clearly wants 避险 but planner picked aggressive_growth
    with a hand-wavy rationale. Mock LLM returns score=3.0.
    """
    mock_llm = _make_mock_llm(
        score=3.0, reasoning="user_message 说避险但选了 aggressive_growth, 完全反向"
    )
    scorer = PlanCorrectnessScorer(llm=mock_llm)
    state = _make_state(
        objective="balanced",
        plan_id="aggressive_growth",
        rationale="选 aggressive_growth 因为标的有成长性",
        user_msg="想避险, 担心下跌",
    )

    sr = scorer.step(state)

    score_obj = sr.state_update["plan_correctness_score"]
    assert isinstance(score_obj, CriticDimensionScore)
    assert score_obj.dimension == "plan_correctness"
    assert score_obj.score == 3.0
    assert score_obj.score < 6.0  # mismatched threshold
    assert score_obj.evidence


# ---------------------------------------------------------------------------
# Edge / regression tests: no-plan short-circuit + LLM call argument contract
# ---------------------------------------------------------------------------


def test_scorer_returns_zero_when_plan_is_none() -> None:
    """state.plan is None → 不调 LLM, 返 score=0.0 + evidence + skipped span.

    Locks down the short-circuit at PlanCorrectnessScorer.step() top: when
    upstream ResearchPlanner failed / was skipped, scorer must NOT consume
    tokens and must surface the skip via span_metadata for observability.
    """
    llm = MagicMock()
    scorer = PlanCorrectnessScorer(llm=llm)
    state = ResearchState(
        user_id="u",
        session_id="s",
        request_id="r",
        user_message="",
        target_ts_code="600519.SH",
        target_entity="贵州茅台",
        client_total_aum=10_000_000.0,
        investment_objective="balanced",
        investment_horizon="medium_term",
        risk_tolerance="moderate",
    )
    # plan default None — verified via schemas.py:293

    sr = scorer.step(state)

    score_obj = sr.state_update["plan_correctness_score"]
    assert isinstance(score_obj, CriticDimensionScore)
    assert score_obj.dimension == "plan_correctness"
    assert score_obj.score == 0.0
    assert score_obj.evidence == "no plan available"
    assert sr.span_metadata.get("skipped") == "no_plan"
    assert sr.span_metadata["agent"] == "PlanCorrectnessScorer"
    assert sr.span_metadata["dimension"] == "plan_correctness"
    llm.chat.assert_not_called()  # no token consumption on short-circuit


def test_scorer_calls_llm_with_correct_schema_and_tier() -> None:
    """LLM call 必须 schema=_PlanCorrectnessScore + tier='balanced' (防 regression).

    Guards against:
    - schema arg drop → silent fallback to free-text mode (parsed=None)
    - tier 漂移 → cost / latency regression vs tier_router config
    - prompt 未注入 objective → judge 评不到 override 例外
    """
    mock_llm = _make_mock_llm(score=8.0, reasoning="ok")
    scorer = PlanCorrectnessScorer(llm=mock_llm)
    state = _make_state(
        objective="balanced",
        plan_id="balanced",
        rationale="objective=balanced 默认映射",
    )

    scorer.step(state)

    chat_kwargs = mock_llm.chat.call_args.kwargs
    assert chat_kwargs["schema"] is _PlanCorrectnessScore
    assert chat_kwargs["tier"] == "balanced"
    prompt_arg = chat_kwargs["prompt"]
    assert "balanced" in prompt_arg.lower()  # objective injected into prompt

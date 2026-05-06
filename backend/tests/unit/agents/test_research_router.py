"""18 deterministic invariant tests — v0.8.5 constrained LLM router.

These tests use a MagicMock LLM that returns a pre-canned (plan_id, rationale)
response. They verify the *router shell*: prompt construction, plan
instantiation from PLAN_REGISTRY, rationale length enforcement, retry feedback
injection, and subtask hydration. Whether the real LLM actually follows the
mapping table + 5 override rules is verified separately by Task 9 cassette
eval — not here.

spec ref: docs/superpowers/specs/2026-05-04-v0.8.5-skill-bundles-and-constrained-router.md § 4.5
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from app.agents.research_planner import ResearchPlanner, build_router_prompt
from app.agents.schemas import (
    InvestmentHorizon,
    InvestmentObjective,
    PlanId,
    ResearchPlan,
    ResearchState,
    RiskTolerance,
)
from pydantic import ValidationError


def _chat_kwargs(planner: ResearchPlanner) -> dict[str, Any]:
    """Pull kwargs from the MagicMock LLM's last chat() invocation.

    mypy sees ``planner._llm.chat`` as a typed ``ChatClient.chat`` callable
    (no ``.call_args``), so we cast to MagicMock at the assertion site.
    """
    return dict(cast(MagicMock, planner._llm.chat).call_args.kwargs)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_state(
    *,
    objective: InvestmentObjective = "balanced",
    horizon: InvestmentHorizon = "medium_term",
    risk: RiskTolerance = "moderate",
    user_message: str = "",
    target_ts_code: str = "600519.SH",
    target_entity: str | None = "贵州茅台",
    critic_feedback: str | None = None,
) -> ResearchState:
    return ResearchState(
        user_id="u",
        session_id="s",
        user_message=user_message,
        request_id="req-router-test",
        target_ts_code=target_ts_code,
        target_entity=target_entity,
        client_total_aum=10_000_000.0,
        client_existing_position=500_000.0,
        investment_objective=objective,
        investment_horizon=horizon,
        risk_tolerance=risk,
        planner_critic_feedback=critic_feedback,
    )


def _make_router_with_mocked_llm(plan_id: PlanId, rationale: str = "test") -> ResearchPlanner:
    """Build a ResearchPlanner with a MagicMock LLM returning the given plan_id.

    Important: LLMService.chat returns LLMResponse with ``.parsed`` populated
    when a Pydantic schema is passed. We mimic that by setting parsed to a
    concrete ResearchPlan and content to its JSON serialization (so the
    ``isinstance(parsed, ResearchPlan)`` branch in step() is exercised).
    """
    response = MagicMock()
    plan = ResearchPlan(plan_id=plan_id, rationale=rationale)
    response.parsed = plan
    response.content = plan.model_dump_json()
    response.model = "qwen-plus"
    response.cost_cny = 0.001

    llm = MagicMock()
    llm.chat.return_value = response
    return ResearchPlanner(llm=llm)


# ---------------------------------------------------------------------------
# 1-4: Default mapping (4 objectives × default user_message=None → 4 plan_ids)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("objective", "expected_plan_id"),
    [
        ("capital_preservation", "capital_preservation"),
        ("stable_growth", "stable_growth"),
        ("balanced", "balanced"),
        ("aggressive_growth", "aggressive_growth"),
    ],
)
def test_default_mapping_no_user_message(
    objective: InvestmentObjective, expected_plan_id: PlanId
) -> None:
    """Each objective with empty user_message routes to its default plan_id.

    Router shell test: we mock the LLM to return expected_plan_id, then verify
    state_update["plan"].plan_id matches and that the prompt at least contains
    the objective so a real LLM has the signal it needs.
    """
    state = _make_state(objective=objective, user_message="")
    planner = _make_router_with_mocked_llm(expected_plan_id)

    sr = planner.step(state)

    assert sr.state_update["plan"].plan_id == expected_plan_id
    # And the prompt the LLM was called with mentions the objective.
    prompt_arg = _chat_kwargs(planner)["prompt"]
    assert isinstance(prompt_arg, str)
    assert objective in prompt_arg


# ---------------------------------------------------------------------------
# 5-8: balanced + 4 override keywords (parametrize)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("user_message", "horizon", "expected_plan_id"),
    [
        ("短期机会, 想抓热点", "short_term", "aggressive_growth"),
        ("我想避险, 不要亏", "medium_term", "capital_preservation"),
        ("长期持有, 养老配置", "long_term", "stable_growth"),
        ("高股息红利股配置", "long_term", "stable_growth"),
    ],
)
def test_balanced_objective_overrides_via_user_message(
    user_message: str, horizon: InvestmentHorizon, expected_plan_id: PlanId
) -> None:
    """Override keywords push balanced objective to a different plan_id.

    Router shell test: we mock the LLM to return the expected post-override
    plan_id, then verify the prompt contains both the objective (balanced)
    AND the override keyword text so a real LLM has the necessary signal.
    """
    state = _make_state(objective="balanced", horizon=horizon, user_message=user_message)
    planner = _make_router_with_mocked_llm(expected_plan_id)

    sr = planner.step(state)

    assert sr.state_update["plan"].plan_id == expected_plan_id
    prompt_arg = _chat_kwargs(planner)["prompt"]
    assert isinstance(prompt_arg, str)
    assert "balanced" in prompt_arg
    assert user_message in prompt_arg


# ---------------------------------------------------------------------------
# 9: aggressive_growth + 避险 → capital_preservation override
# ---------------------------------------------------------------------------


def test_aggressive_growth_with_risk_aversion_keyword() -> None:
    """Override 1 — '避险' overrides aggressive_growth → capital_preservation."""
    state = _make_state(
        objective="aggressive_growth",
        user_message="虽然激进, 但当前市场我想避险",
    )
    planner = _make_router_with_mocked_llm("capital_preservation")

    sr = planner.step(state)

    assert sr.state_update["plan"].plan_id == "capital_preservation"
    prompt_arg = _chat_kwargs(planner)["prompt"]
    assert isinstance(prompt_arg, str)
    assert "aggressive_growth" in prompt_arg
    assert "避险" in prompt_arg


# ---------------------------------------------------------------------------
# 10: capital_preservation + 长期持有 → stable_growth override
# ---------------------------------------------------------------------------


def test_capital_preservation_with_long_term_keyword() -> None:
    """Override 3 — '长期持有' + horizon=long_term overrides → stable_growth."""
    state = _make_state(
        objective="capital_preservation",
        horizon="long_term",
        user_message="希望长期持有, 养老配置",
    )
    planner = _make_router_with_mocked_llm("stable_growth")

    sr = planner.step(state)

    assert sr.state_update["plan"].plan_id == "stable_growth"
    prompt_arg = _chat_kwargs(planner)["prompt"]
    assert isinstance(prompt_arg, str)
    assert "capital_preservation" in prompt_arg
    assert "长期持有" in prompt_arg


# ---------------------------------------------------------------------------
# 11-14: Strict default — 4 objectives × user_message="" → 4 plan_ids
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("objective", "expected_plan_id"),
    [
        ("capital_preservation", "capital_preservation"),
        ("stable_growth", "stable_growth"),
        ("balanced", "balanced"),
        ("aggressive_growth", "aggressive_growth"),
    ],
)
def test_strict_default_with_empty_user_message_falls_back_to_no_message_marker(
    objective: InvestmentObjective, expected_plan_id: PlanId
) -> None:
    """Empty user_message renders as ``(无)`` in prompt and routes to default plan_id."""
    state = _make_state(objective=objective, user_message="")
    planner = _make_router_with_mocked_llm(expected_plan_id)

    sr = planner.step(state)

    assert sr.state_update["plan"].plan_id == expected_plan_id
    prompt_arg = _chat_kwargs(planner)["prompt"]
    assert isinstance(prompt_arg, str)
    assert "(无)" in prompt_arg


# ---------------------------------------------------------------------------
# 15: subtasks instantiation — 验 plan.subtasks 含 target_entity + ts_code
# ---------------------------------------------------------------------------


def test_subtasks_instantiated_with_target_entity_and_ts_code() -> None:
    """After step(), plan.subtasks must contain rendered target_name + ts_code."""
    state = _make_state(
        objective="balanced",
        target_entity="贵州茅台",
        target_ts_code="600519.SH",
    )
    planner = _make_router_with_mocked_llm("balanced")

    sr = planner.step(state)
    plan = sr.state_update["plan"]

    assert len(plan.subtasks) >= 1, "instantiate_plan must populate subtasks"
    # Every subtask description should contain both the target_name and ts_code.
    for st in plan.subtasks:
        assert "贵州茅台" in st.description, f"target_name missing in {st.description!r}"
        assert "600519.SH" in st.description, f"ts_code missing in {st.description!r}"
    # Subtask IDs are deterministic ``f"{plan_id}_{idx}"`` per plan_registry contract.
    assert plan.subtasks[0].subtask_id == "balanced_0"


# ---------------------------------------------------------------------------
# 16: rationale max_length=200 enforcement
# ---------------------------------------------------------------------------


def test_rationale_max_length_enforced() -> None:
    """ResearchPlan.rationale is capped at 200 chars; 300-char input raises."""
    with pytest.raises(ValidationError):
        ResearchPlan(plan_id="balanced", rationale="x" * 300)


# ---------------------------------------------------------------------------
# 17: retry feedback prompt injection
# ---------------------------------------------------------------------------


def test_critic_feedback_injected_into_prompt() -> None:
    """When state.planner_critic_feedback is set, prompt must contain it verbatim."""
    feedback = "上轮 plan 缺少股息分析, 与客户长期持有需求不符"
    state = _make_state(
        objective="stable_growth",
        critic_feedback=feedback,
    )

    prompt = build_router_prompt(state)

    assert feedback in prompt
    assert "Critic feedback" in prompt
    assert "上一轮 plan 被 Critic 评分 < 8.5" in prompt


# ---------------------------------------------------------------------------
# 18: target_entity fallback — when None, falls back to ts_code as target_name
# ---------------------------------------------------------------------------


def test_target_entity_fallback_to_ts_code_when_none() -> None:
    """If state.target_entity is None, instantiate_plan uses ts_code as target_name."""
    state = _make_state(
        objective="balanced",
        target_entity=None,
        target_ts_code="600519.SH",
    )
    planner = _make_router_with_mocked_llm("balanced")

    sr = planner.step(state)
    plan = sr.state_update["plan"]

    # When target_entity is None, ts_code is used in BOTH placeholder slots.
    # So every subtask description has 600519.SH at least once (typically twice).
    for st in plan.subtasks:
        assert "600519.SH" in st.description


# ---------------------------------------------------------------------------
# 19: model_copy idempotency — original r.parsed instance must NOT be mutated
# ---------------------------------------------------------------------------


def test_model_copy_does_not_mutate_original_plan() -> None:
    """Idempotency: r.parsed 实例不应被 step() 通过 model_copy mutate.

    防止未来"简化"成 plan.subtasks = subtasks (mutate) 导致 r.parsed 共享引用污染.
    """
    original_plan = ResearchPlan(plan_id="balanced", rationale="orig")
    response = MagicMock()
    response.parsed = original_plan
    response.content = original_plan.model_dump_json()
    response.model = "qwen-plus"
    response.cost_cny = 0.001
    llm = MagicMock()
    llm.chat.return_value = response
    planner = ResearchPlanner(llm=llm)

    state = _make_state(objective="balanced")
    planner.step(state)

    assert original_plan.subtasks == [], "original r.parsed instance was mutated"

"""Tests for v1.x ResearchPlanner — template-guided + validator retry loop."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from app.agents.plan_template import DD_PLAN_TEMPLATE
from app.agents.research_planner import (
    MAX_VALIDATOR_RETRY,
    ResearchPlanner,
    build_planner_prompt,
)
from app.agents.schemas import ResearchPlan, ResearchState, Subtask


def _mk_state(**kw: Any) -> ResearchState:
    base: dict[str, Any] = {
        "user_id": "u1",
        "session_id": "s1",
        "user_message": "分析贵州茅台",
        "request_id": "r1",
        "target_ts_code": "600519.SH",
        "investment_objective": "balanced",
        "investment_horizon": "medium_term",
        "risk_tolerance": "moderate",
    }
    base.update(kw)
    return ResearchState(**base)


def _mk_good_plan() -> ResearchPlan:
    return ResearchPlan(
        rationale="均衡配置 — 覆盖财务全景 / 估值 / 行业地位 / 风险底线",
        subtasks=[
            Subtask(
                subtask_id="s1",
                description="财务全景: 三表 + ROE 趋势",
                required_tools=["get_financials", "get_balance_sheet"],
                rationale="r",
            ),
            Subtask(
                subtask_id="s2",
                description="估值: PE 历史分位",
                required_tools=["get_pe_history"],
                rationale="r",
            ),
            Subtask(
                subtask_id="s3",
                description="行业地位",
                required_tools=["web_search"],
                rationale="r",
            ),
            Subtask(
                subtask_id="s4",
                description="风险底线",
                required_tools=["get_holder_change"],
                rationale="r",
            ),
        ],
    )


def _mk_bad_plan() -> ResearchPlan:
    """Missing all 4 required dims — Validator should reject."""
    return ResearchPlan(
        rationale="bad — no required dim coverage",
        subtasks=[
            Subtask(
                subtask_id="x", description="无关", required_tools=["get_financials"], rationale="r"
            )
        ],
    )


def test_max_validator_retry_constant() -> None:
    assert MAX_VALIDATOR_RETRY == 2


def test_prompt_contains_template_required_dims() -> None:
    prompt = build_planner_prompt(_mk_state(), DD_PLAN_TEMPLATE)
    for dim in DD_PLAN_TEMPLATE["required_dimensions"]:
        assert dim["name"] in prompt


def test_prompt_contains_optional_dims() -> None:
    prompt = build_planner_prompt(_mk_state(), DD_PLAN_TEMPLATE)
    for dim in DD_PLAN_TEMPLATE["optional_dimensions"]:
        assert dim["name"] in prompt


def test_prompt_contains_six_input_fields() -> None:
    state = _mk_state(
        client_total_aum=5_000_000.0,
        client_existing_position=1_500_000.0,
    )
    prompt = build_planner_prompt(state, DD_PLAN_TEMPLATE)
    # 6 fields = objective + horizon + risk + aum + existing_position + ts_code
    assert "balanced" in prompt  # investment_objective
    assert "medium_term" in prompt  # investment_horizon
    assert "moderate" in prompt  # risk_tolerance
    assert "5000000" in prompt or "5_000_000" in prompt or "5,000,000" in prompt  # aum
    assert (
        "1500000" in prompt or "1_500_000" in prompt or "1,500,000" in prompt
    )  # existing_position
    assert "600519.SH" in prompt  # target_ts_code


def test_prompt_includes_verbatim_dim_echo_instruction() -> None:
    """Prompt must tell LLM to echo dim names verbatim — pins the
    substring-match contract in plan_validator. The literal word
    'verbatim' must appear; loosening this test = loosening the contract."""
    prompt = build_planner_prompt(_mk_state(), DD_PLAN_TEMPLATE)
    assert "verbatim" in prompt
    assert "维度名" in prompt
    # Confirm the load-bearing marker is preserved
    assert "LOAD-BEARING" in prompt


def test_prompt_no_validator_feedback_when_first_attempt() -> None:
    prompt = build_planner_prompt(_mk_state(), DD_PLAN_TEMPLATE, validator_feedback=None)
    # Empty feedback should not include retry section content
    assert "首次生成" in prompt or "(无" in prompt


def test_prompt_includes_validator_feedback_on_retry() -> None:
    prompt = build_planner_prompt(
        _mk_state(),
        DD_PLAN_TEMPLATE,
        validator_feedback="missing required dim: 财务全景; tool 'foo' not in palette",
    )
    assert "财务全景" in prompt
    assert "foo" in prompt
    assert "未通过" in prompt or "errors" in prompt.lower() or "校验" in prompt


def test_planner_returns_llm_plan_when_validates() -> None:
    """LLM returns valid plan first try → no retry, no fallback."""
    llm = MagicMock()
    good = _mk_good_plan()
    llm.chat.return_value = MagicMock(parsed=good, model="m", cost_cny=0.0)

    planner = ResearchPlanner(llm)
    result = planner.step(_mk_state())

    assert llm.chat.call_count == 1
    assert result.span_metadata["validator_attempts"] == 1
    assert result.span_metadata["validator_fallback"] is False
    assert result.state_update["plan"] is good


def test_planner_retries_on_validator_fail_then_succeeds() -> None:
    """1st bad, 2nd good → 2 LLM calls, no fallback."""
    llm = MagicMock()
    llm.chat.side_effect = [
        MagicMock(parsed=_mk_bad_plan(), model="m", cost_cny=0.0),
        MagicMock(parsed=_mk_good_plan(), model="m", cost_cny=0.0),
    ]
    planner = ResearchPlanner(llm)
    result = planner.step(_mk_state())

    assert llm.chat.call_count == 2
    assert result.span_metadata["validator_attempts"] == 2
    assert result.span_metadata["validator_fallback"] is False


def test_planner_falls_back_to_safe_default_after_retry_exhausted() -> None:
    """3 bad → fallback to SAFE_DEFAULT (7 subtasks)."""
    llm = MagicMock()
    llm.chat.return_value = MagicMock(parsed=_mk_bad_plan(), model="m", cost_cny=0.0)

    planner = ResearchPlanner(llm)
    result = planner.step(_mk_state())

    assert llm.chat.call_count == 1 + MAX_VALIDATOR_RETRY  # 3
    plan = result.state_update["plan"]
    assert len(plan.subtasks) == 7  # SAFE_DEFAULT_PLAN has 7 subtasks
    assert result.span_metadata["validator_fallback"] is True
    assert "validator_last_errors" in result.span_metadata


def test_retry_prompt_includes_validator_errors() -> None:
    """The second LLM call must receive validator errors in prompt."""
    llm = MagicMock()
    llm.chat.side_effect = [
        MagicMock(parsed=_mk_bad_plan(), model="m", cost_cny=0.0),
        MagicMock(parsed=_mk_good_plan(), model="m", cost_cny=0.0),
    ]
    planner = ResearchPlanner(llm)
    planner.step(_mk_state())

    # Inspect 2nd call's prompt
    second_call_kwargs = llm.chat.call_args_list[1][1]
    second_prompt = second_call_kwargs["prompt"]
    # Should mention either the missing dim names or validator/errors keyword
    assert (
        "财务全景" in second_prompt or "校验" in second_prompt or "errors" in second_prompt.lower()
    )


def test_safe_default_plan_passes_validator_self_check() -> None:
    """Sanity: when fallback fires, SAFE_DEFAULT_PLAN must satisfy validator
    (otherwise fallback is broken). Already covered by Task 1.1 tests, but
    we also pin via a planner-level integration here using internal helper."""
    from app.agents.plan_validator import validate_plan
    from app.agents.research_planner import _build_safe_default_plan

    plan = _build_safe_default_plan("贵州茅台", "600519.SH")
    r = validate_plan(plan, DD_PLAN_TEMPLATE)
    assert r.ok, r.errors


def test_success_span_metadata_includes_model_and_cost() -> None:
    """Trace contract — model + cost_cny propagate from LLMService."""
    llm = MagicMock()
    good = _mk_good_plan()
    llm.chat.return_value = MagicMock(parsed=good, model="claude-opus-4-7", cost_cny=0.12)

    planner = ResearchPlanner(llm)
    result = planner.step(_mk_state())

    md = result.span_metadata
    assert md["model"] == "claude-opus-4-7"
    assert md["cost_cny"] == 0.12
    assert md["agent"] == "ResearchPlanner"


def test_third_attempt_receives_second_attempt_errors() -> None:
    """`last_errors` should reflect the most recent failed attempt, not the
    first. Pin this so a future refactor doesn't accidentally accumulate
    feedback or only show first-attempt feedback to LLM."""
    from app.agents.schemas import Subtask

    # 1st bad: missing 财务全景
    bad_missing_finance = ResearchPlan(
        rationale="missing finance",
        subtasks=[
            Subtask(
                subtask_id="s1",
                description="估值",
                required_tools=["get_pe_history"],
                rationale="r",
            ),
            Subtask(
                subtask_id="s2",
                description="行业地位",
                required_tools=["web_search"],
                rationale="r",
            ),
            Subtask(
                subtask_id="s3",
                description="风险底线",
                required_tools=["get_holder_change"],
                rationale="r",
            ),
        ],
    )
    # 2nd bad: missing 风险底线 (different errors than 1st)
    bad_missing_risk = ResearchPlan(
        rationale="missing risk",
        subtasks=[
            Subtask(
                subtask_id="s1",
                description="财务全景",
                required_tools=["get_financials", "get_balance_sheet"],
                rationale="r",
            ),
            Subtask(
                subtask_id="s2",
                description="估值",
                required_tools=["get_pe_history"],
                rationale="r",
            ),
            Subtask(
                subtask_id="s3",
                description="行业地位",
                required_tools=["web_search"],
                rationale="r",
            ),
        ],
    )
    llm = MagicMock()
    llm.chat.side_effect = [
        MagicMock(parsed=bad_missing_finance, model="m", cost_cny=0.0),
        MagicMock(parsed=bad_missing_risk, model="m", cost_cny=0.0),
        MagicMock(parsed=bad_missing_finance, model="m", cost_cny=0.0),  # still bad
    ]
    planner = ResearchPlanner(llm)
    result = planner.step(_mk_state())

    # 3 LLM calls made
    assert llm.chat.call_count == 3

    # 3rd call's prompt must reference the 2nd attempt's errors (风险底线), not 1st (财务全景)
    third_prompt = llm.chat.call_args_list[2][1]["prompt"]
    assert "风险底线" in third_prompt, (
        f"3rd attempt should receive 2nd attempt's errors (missing 风险底线), "
        f"but prompt does not mention 风险底线. Prompt excerpt: {third_prompt[-500:]}"
    )

    # And validator_last_plan in fallback metadata should be the 3rd attempt's plan
    # (which was bad_missing_finance again — same as 1st)
    assert result.span_metadata["validator_fallback"] is True
    # validator_last_errors should mention 财务全景 (3rd attempt missing it)
    assert "财务全景" in result.span_metadata["validator_last_errors"]


def test_prompt_includes_distilled_block_when_intent_present() -> None:
    from app.agents.plan_template import DD_PLAN_TEMPLATE
    from app.agents.research_planner import build_planner_prompt
    from app.agents.schemas import ResearchState

    s = ResearchState(
        user_id="u",
        session_id="s",
        user_message="m",
        request_id="r",
        target_ts_code="600519.SH",
        escalation_intent="客户希望对茅台做全面尽调",
    )
    prompt = build_planner_prompt(s, DD_PLAN_TEMPLATE)
    assert "客户希望对茅台做全面尽调" in prompt
    assert "核心意图" in prompt


def test_prompt_includes_focus_list_when_present() -> None:
    from app.agents.plan_template import DD_PLAN_TEMPLATE
    from app.agents.research_planner import build_planner_prompt
    from app.agents.schemas import ResearchState

    s = ResearchState(
        user_id="u",
        session_id="s",
        user_message="m",
        request_id="r",
        target_ts_code="600519.SH",
        discussion_focus=["担心负债率上升", "对比五粮液"],
    )
    prompt = build_planner_prompt(s, DD_PLAN_TEMPLATE)
    assert "担心负债率上升" in prompt
    assert "对比五粮液" in prompt
    assert "重点关注的焦点" in prompt
    assert "- 担心负债率上升" in prompt or "- 对比五粮液" in prompt


def test_prompt_includes_exclusions_when_present() -> None:
    from app.agents.plan_template import DD_PLAN_TEMPLATE
    from app.agents.research_planner import build_planner_prompt
    from app.agents.schemas import ResearchState

    s = ResearchState(
        user_id="u",
        session_id="s",
        user_message="m",
        request_id="r",
        target_ts_code="600519.SH",
        explicit_exclusions=["不关心 ESG"],
    )
    prompt = build_planner_prompt(s, DD_PLAN_TEMPLATE)
    assert "不关心 ESG" in prompt
    assert "不关注的方面" in prompt or "排除" in prompt or "不关心" in prompt


def test_prompt_omits_distilled_section_when_all_empty() -> None:
    """Default state (form-style entry) → no distilled headers in prompt."""
    from app.agents.plan_template import DD_PLAN_TEMPLATE
    from app.agents.research_planner import build_planner_prompt
    from app.agents.schemas import ResearchState

    s = ResearchState(
        user_id="u",
        session_id="s",
        user_message="m",
        request_id="r",
        target_ts_code="600519.SH",
    )
    prompt = build_planner_prompt(s, DD_PLAN_TEMPLATE)
    assert "本次尽调的核心意图" not in prompt
    assert "重点关注的焦点" not in prompt
    assert "不关注的方面" not in prompt


def test_prompt_partial_distillation_renders_only_present_fields() -> None:
    """Only intent set → no focus/exclusion sections, just intent block."""
    from app.agents.plan_template import DD_PLAN_TEMPLATE
    from app.agents.research_planner import build_planner_prompt
    from app.agents.schemas import ResearchState

    s = ResearchState(
        user_id="u",
        session_id="s",
        user_message="m",
        request_id="r",
        target_ts_code="600519.SH",
        escalation_intent="想全面看看",
    )
    prompt = build_planner_prompt(s, DD_PLAN_TEMPLATE)
    assert "想全面看看" in prompt
    assert "核心意图" in prompt
    assert "重点关注的焦点" not in prompt
    assert "不关注的方面" not in prompt


def test_prompt_distilled_block_appears_before_plan_template() -> None:
    """Order matters — distilled context before template constraints."""
    from app.agents.plan_template import DD_PLAN_TEMPLATE
    from app.agents.research_planner import build_planner_prompt
    from app.agents.schemas import ResearchState

    s = ResearchState(
        user_id="u",
        session_id="s",
        user_message="m",
        request_id="r",
        target_ts_code="600519.SH",
        escalation_intent="尽调全面",
    )
    prompt = build_planner_prompt(s, DD_PLAN_TEMPLATE)
    intent_pos = prompt.find("核心意图")
    template_pos = prompt.find("Plan Template")
    assert intent_pos > 0 and template_pos > 0
    assert intent_pos < template_pos, "distilled block must come before template block"

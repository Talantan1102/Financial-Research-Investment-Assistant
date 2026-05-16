"""ResearchPlanner — v1.x template-guided generation + validator loop.

LLM emits a full ResearchPlan (description + rationale + tool selection per
subtask) within DD_PLAN_TEMPLATE constraints. Validator (plan_validator)
enforces; retry ≤ MAX_VALIDATOR_RETRY (2) then fallback SAFE_DEFAULT_PLAN.

Replaces v0.8.5 constrained-router (4 plan_id selector → instantiate_plan
from PLAN_REGISTRY). plan_registry.py is deprecated; this module no longer
imports it.

spec ref: docs/superpowers/specs/2026-05-15-v1.x-plan-template-validator-design.md § 4

Exception policy: LLM exceptions (RateLimitError, network errors, etc.) are
NOT caught by the retry loop — they bubble up to the caller (graph node →
ResearchAgent). LLMService is expected to have its own retry layer for
transient faults. Validator failures are distinct from LLM exceptions and
ARE handled by the retry loop.
"""

from __future__ import annotations

from typing import Any

from app.agents.base import Agent
from app.agents.plan_template import (
    DD_PLAN_TEMPLATE,
    SAFE_DEFAULT_PLAN,
    PlanTemplate,
)
from app.agents.plan_validator import validate_plan
from app.agents.schemas import ResearchPlan, ResearchState, StepResult, Subtask
from app.services.llm_response import Tier

__all__ = [
    "MAX_VALIDATOR_RETRY",
    "ResearchPlanner",
    "build_planner_prompt",
]

MAX_VALIDATOR_RETRY = 2


_PLANNER_SYSTEM_PROMPT_TEMPLATE = """你是金融研究助手 research_planner。\
你的工作: 基于客户画像 + 用户消息 + 下方 plan template, 生成一份 ResearchPlan。

# 客户画像 (6 字段)
- investment_objective: {objective}
- investment_horizon: {horizon}
- risk_tolerance: {risk}
- client_total_aum (CNY): {aum}
- client_existing_position (CNY): {position}
- target_ts_code: {ts_code}

# 用户消息
{user_message}

# Plan Template — 你必须遵守

## 必填维度 (required dimensions) — 每个必须产 ≥1 个 subtask
{required_dims_block}

## 可选维度 (optional dimensions) — 根据客户画像/消息决定是否产
{optional_dims_block}

## Tool 白名单 (tool palette)
{palette_block}

## 业务约束
- max_subtasks: {max_subtasks}
- max_tool_calls_per_subtask: {max_per_sub}
- forbid_duplicate_calls: 同一个 subtask 内不要重复同名 tool。跨 subtask 重复可以(同 tool 不同分析视角)。

# Validator Feedback (上一轮失败时反馈)
{validator_feedback}

# 输出要求
仅输出 JSON, 符合 ResearchPlan schema:
{{
  "rationale": "<≤300 字>",
  "subtasks": [
    {{"subtask_id": "s1", "description": "...", "required_tools": ["..."], "rationale": "..."}}
  ]
}}

# 写作要求 (LOAD-BEARING — 校验器靠它做维度覆盖匹配)
- subtask_id 用 s1/s2/s3... 顺序
- **description 必须以对应的【维度名(verbatim)】开头**, 如 "财务全景 — 三表 + ROE" / "估值 — PE 分位"
- required_tools 只能从 tool palette 选; 不许编造工具名
- rationale 1-2 句解释
"""


def _format_required_dims(template: PlanTemplate) -> str:
    lines = []
    for d in template["required_dimensions"]:
        candidates = ", ".join(d["tool_candidates"])
        lines.append(f"- {d['name']}: tool_candidates=[{candidates}], min_tools={d['min_tools']}")
    return "\n".join(lines)


def _format_optional_dims(template: PlanTemplate) -> str:
    lines = []
    for d in template["optional_dimensions"]:
        candidates = ", ".join(d["tool_candidates"])
        lines.append(f"- {d['name']}: tool_candidates=[{candidates}]")
    return "\n".join(lines)


def build_planner_prompt(
    state: ResearchState,
    template: PlanTemplate,
    validator_feedback: str | None = None,
) -> str:
    """Assemble planner prompt from state + template + optional retry feedback."""
    user_msg = state.user_message.strip() if state.user_message else "(无)"
    feedback = (
        f"上一轮 plan 未通过 Validator 校验, errors:\n{validator_feedback}\n请修正后重试。"
        if validator_feedback
        else "(无 — 首次生成)"
    )
    return _PLANNER_SYSTEM_PROMPT_TEMPLATE.format(
        objective=state.investment_objective or "(未指定)",
        horizon=state.investment_horizon or "(未指定)",
        risk=state.risk_tolerance or "(未指定)",
        aum=state.client_total_aum if state.client_total_aum is not None else "(未指定)",
        position=(
            state.client_existing_position
            if state.client_existing_position is not None
            else "(未指定)"
        ),
        ts_code=state.target_ts_code or "(未指定)",
        user_message=user_msg,
        required_dims_block=_format_required_dims(template),
        optional_dims_block=_format_optional_dims(template),
        palette_block=", ".join(template["tool_palette"]),
        max_subtasks=template["constraints"]["max_subtasks"],
        max_per_sub=template["constraints"]["max_tool_calls_per_subtask"],
        validator_feedback=feedback,
    )


def _build_safe_default_plan(target_name: str, ts_code: str) -> ResearchPlan:
    """Instantiate SAFE_DEFAULT_PLAN templates into a concrete ResearchPlan.

    Used when Validator retry is exhausted. The 7-subtask static plan covers
    all required + optional dims; validator self-check pinned by Task 1.1's
    test_safe_default_plan_self_validates_against_template.
    """
    subtasks = [
        Subtask(
            subtask_id=f"safe_{idx}",
            description=tmpl.description_template.format(target_name=target_name, ts_code=ts_code),
            required_tools=list(tmpl.required_tools),
            rationale=tmpl.rationale,
        )
        for idx, tmpl in enumerate(SAFE_DEFAULT_PLAN)
    ]
    return ResearchPlan(
        rationale="Validator retry exhausted → SAFE_DEFAULT_PLAN fallback",
        subtasks=subtasks,
    )


class ResearchPlanner(Agent):
    """v1.x template-guided planner with validator retry loop."""

    name = "ResearchPlanner"
    model_tier: Tier = "balanced"
    template: PlanTemplate = DD_PLAN_TEMPLATE

    def step(self, state: ResearchState) -> StepResult:  # type: ignore[override]
        validator_feedback: str | None = None
        last_errors: str | None = None
        last_plan_dump: dict[str, Any] | None = None

        for attempt in range(1 + MAX_VALIDATOR_RETRY):
            prompt = build_planner_prompt(state, self.template, validator_feedback)
            r = self._llm.chat(
                prompt=prompt,
                tier=self.model_tier,
                schema=ResearchPlan,
                request_id=state.request_id,
            )
            if not isinstance(r.parsed, ResearchPlan):
                raise TypeError(
                    f"LLMService contract violated: expected ResearchPlan, "
                    f"got {type(r.parsed).__name__}"
                )
            plan: ResearchPlan = r.parsed
            v = validate_plan(plan, self.template)
            if v.ok:
                return StepResult(
                    state_update={"plan": plan},
                    span_metadata={
                        "agent": "ResearchPlanner",
                        "model": r.model,
                        "cost_cny": r.cost_cny,
                        "validator_attempts": attempt + 1,
                        "validator_fallback": False,
                    },
                )
            last_errors = "; ".join(v.errors)
            last_plan_dump = plan.model_dump()
            validator_feedback = last_errors

        # Retry exhausted — fallback to SAFE_DEFAULT_PLAN
        target_name = state.target_entity or state.target_ts_code or ""
        ts_code = state.target_ts_code or ""
        safe_plan = _build_safe_default_plan(target_name, ts_code)
        return StepResult(
            state_update={"plan": safe_plan},
            span_metadata={
                "agent": "ResearchPlanner",
                "validator_attempts": 1 + MAX_VALIDATOR_RETRY,
                "validator_fallback": True,
                "validator_last_errors": last_errors,
                "validator_last_plan": last_plan_dump,
            },
        )

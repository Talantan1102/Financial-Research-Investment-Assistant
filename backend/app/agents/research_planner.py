"""ResearchPlanner — v0.8.5 constrained LLM router.

The planner LLM picks one of 4 ``plan_id`` values from a hardcoded mapping
table and supplies a short ``rationale``. Subtasks are then instantiated
deterministically from PLAN_REGISTRY via ``instantiate_plan``.

Routing logic (in prompt):
- Default mapping: investment_objective → plan_id (1:1).
- Override exceptions: 5 user_message keyword patterns may push the
  router to a different plan_id (e.g. "避险" → capital_preservation).

spec ref: docs/superpowers/specs/2026-05-04-v0.8.5-skill-bundles-and-constrained-router.md § 4.5
"""

from __future__ import annotations

import json
from typing import Any

from app.agents.base import Agent
from app.agents.plan_registry import instantiate_plan
from app.agents.schemas import ResearchPlan, ResearchState, StepResult
from app.services.llm_response import Tier

# ---------------------------------------------------------------------------
# Constrained-router system prompt template
# ---------------------------------------------------------------------------

_PLANNER_SYSTEM_PROMPT_TEMPLATE = """你是金融研究助手 research_planner。\
你的工作: 基于 6 个客户字段 + 用户自由文本, 从下列 4 个固定 plan_id 中选择一个, \
并给出不超过 200 字的 rationale 解释为什么选这个 plan_id。

# 客户画像 (6 字段)
- investment_objective: {objective}
- investment_horizon: {horizon}
- risk_tolerance: {risk}
- client_total_aum (CNY): {aum}
- client_existing_position (CNY): {position}
- target_ts_code: {ts_code}

# 用户自由文本补充
{user_message}

# Critic feedback (如有)
{critic_feedback}

# 候选 plan_id (只能选 1 个)
- capital_preservation — 保本/防风险型, 偏重偿债/现金流/治理风险
- stable_growth — 稳健增长型, 偏重 ROE/分红/行业地位
- balanced — 均衡型, 财务/估值/行业/风险均衡
- aggressive_growth — 激进成长型, 偏重高速成长/赛道/资金博弈

# 主映射 (默认按 investment_objective 选 plan_id)
| investment_objective    | 默认 plan_id            |
|-------------------------|-------------------------|
| capital_preservation    | capital_preservation    |
| stable_growth           | stable_growth           |
| balanced                | balanced                |
| aggressive_growth       | aggressive_growth       |

# 例外 override (用户自由文本含以下关键词时, 偏离主映射)
1. user_message 含 "短期机会 / 波段 / 抓机会" + objective != capital_preservation → aggressive_growth
2. user_message 含 "避险 / 防御 / 担心下跌 / 保本" + objective != capital_preservation → capital_preservation
3. user_message 含 "长期持有 / 不在乎短期波动 / 长跑" + objective != aggressive_growth → stable_growth
4. user_message 含 "稳定收益 / 红利 / 股息" → stable_growth
5. user_message 含 "全面分析 / 综合判断" → balanced

# 输出要求
仅输出 JSON: {{"plan_id": "<one_of_4>", "rationale": "<≤200 字解释>"}}
不要输出 subtasks (后端会用 plan_id 从 registry 实例化)。
"""


def _format_chat_known_tools(results: list) -> str:
    """Render the chat-session cached tool results block for the planner prompt.

    Returns an empty string when ``results`` is empty so callers can safely
    concatenate without adding blank sections.
    """
    if not results:
        return ""
    lines = ["\n【chat 期间已查过的工具结果(已知, 不要重复调)】"]
    for r in results:
        args_str = json.dumps(
            r.tool_args if hasattr(r, "tool_args") else r["tool_args"],
            ensure_ascii=False,
            sort_keys=True,
        )
        name = r.tool_name if hasattr(r, "tool_name") else r["tool_name"]
        summary = r.result_summary if hasattr(r, "result_summary") else r["result_summary"]
        lines.append(f"- {name}({args_str}) → {summary}")
    lines.append("\n规划时如果某 tool/args 组合已在上面列表中, **跳过它**, 直接用已知结果。")
    return "\n".join(lines)


def build_router_prompt(state: ResearchState) -> str:
    """Format the constrained-router system prompt from a ResearchState.

    Resolves all 7 inputs (6 structured fields + user_message) plus an
    optional critic_feedback section that Task 9 retry edge feeds in.
    """
    user_msg = state.user_message.strip() if state.user_message else ""
    if not user_msg:
        user_msg = "(无)"

    critic_feedback = (
        f"上一轮 plan 被 Critic 评分 < 8.5, 反馈:{state.planner_critic_feedback}"
        if state.planner_critic_feedback
        else "(无 — 第一轮 router)"
    )

    base = _PLANNER_SYSTEM_PROMPT_TEMPLATE.format(
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
        critic_feedback=critic_feedback,
    )
    chat_known_block = _format_chat_known_tools(state.chat_known_tool_results)
    return base + chat_known_block


class ResearchPlanner(Agent):
    """Constrained-router LLM agent — emits (plan_id, rationale) only."""

    name = "ResearchPlanner"
    model_tier: Tier = "balanced"

    def step(self, state: ResearchState) -> StepResult:  # type: ignore[override]
        """Build router prompt, call LLM with ResearchPlan schema, instantiate subtasks."""
        prompt = build_router_prompt(state)
        r = self._llm.chat(
            prompt=prompt,
            tier=self.model_tier,
            schema=ResearchPlan,
            request_id=state.request_id,
        )
        # LLMService.chat with schema=ResearchPlan strongly types r.parsed as
        # ResearchPlan instance (or raises during validation). Assert as
        # self-documenting contract — fail-loud if LLMService ever regresses.
        parsed = r.parsed
        assert isinstance(parsed, ResearchPlan), (
            f"LLMService contract violated: expected ResearchPlan, got {type(parsed).__name__}"
        )
        plan: ResearchPlan = parsed

        # Resolve target_name: prefer state.target_entity, fall back to ts_code,
        # then empty (instantiate_plan still works — placeholders just become "").
        target_name = state.target_entity or state.target_ts_code or ""
        ts_code = state.target_ts_code or ""
        subtasks = instantiate_plan(plan.plan_id, target_name=target_name, ts_code=ts_code)

        # ResearchPlan is mutable (no frozen), but use model_copy(update=...) for
        # immutability hygiene + consistency with Pydantic v2 idioms.
        plan = plan.model_copy(update={"subtasks": subtasks})

        span_metadata: dict[str, Any] = {
            "agent": "ResearchPlanner",
            "model": r.model,
            "cost_cny": r.cost_cny,
            "plan_id": plan.plan_id,
            "retry_count": state.planner_retry_count,
        }
        return StepResult(state_update={"plan": plan}, span_metadata=span_metadata)

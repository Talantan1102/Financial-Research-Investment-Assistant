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
        critic_feedback=critic_feedback,
    )


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
        # LLMService auto-parses to ResearchPlan via Pydantic class schema.
        # Defensive: if parsed is missing (mock/cassette path that returned dict),
        # validate from raw content.
        parsed = r.parsed
        if isinstance(parsed, ResearchPlan):
            plan = parsed
        else:
            plan = ResearchPlan.model_validate_json(r.content)

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

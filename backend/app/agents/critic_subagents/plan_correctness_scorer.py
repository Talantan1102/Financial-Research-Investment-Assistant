"""Critic 第 7 scorer — plan_correctness (v0.8.5).

LLM-as-judge that evaluates whether the constrained-router ResearchPlanner
selected the correct plan_id given:
  - Default mapping: investment_objective → plan_id (1:1)
  - 5 override exceptions driven by user_message keywords

Scale: 0–10 (consistent with other 6 dimensions); acceptance threshold = 8.5
(< 8.5 will trigger Task 9's retry edge in research_graph.py).

spec ref: docs/superpowers/specs/2026-05-05-v0.8.5-constrained-router-design.md § 4.3
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agents.base import Agent
from app.agents.schemas import (
    CriticDimensionScore,
    ResearchState,
    StepResult,
)
from app.services.llm_response import Tier

_PLAN_CORRECTNESS_JUDGE_PROMPT = """你是评测员, 评判 LLM router 选的 plan_id 是否符合规则。

# 评测规则 (v0.8.5 spec β 模式)

主映射:
- objective=capital_preservation → plan_id=capital_preservation
- objective=stable_growth → plan_id=stable_growth
- objective=balanced → plan_id=balanced
- objective=aggressive_growth → plan_id=aggressive_growth

Override 例外:
1. user_message 含 "短期机会/波段/抓机会" + objective != capital_preservation → aggressive_growth
2. user_message 含 "避险/防御/担心下跌/保本" + objective != capital_preservation → capital_preservation
3. user_message 含 "长期持有/不在乎短期波动/长跑" + objective != aggressive_growth → stable_growth
4. user_message 含 "稳定收益/红利/股息" → stable_growth
5. user_message 含 "全面分析/综合判断" → balanced

# 输入

- investment_objective: {objective}
- user_message: {user_message}
- LLM 选的 plan_id: {plan_id}
- LLM 给的 rationale: {rationale}

# 输出 (0-10 评分 + reasoning)

严格 JSON:
{{
  "score": <float 0-10>,
  "reasoning": "<≤200 字符 评判理由>"
}}

评分标准:
- 10: plan_id 完美符合规则 + rationale 解释充分
- 8.5-9.5: plan_id 符合规则, rationale 有效但简洁
- 6-8.5: plan_id 选对但 rationale 模糊 / 选错且 rationale 无 override 触发解释
- < 6: plan_id 明显错误且 rationale 不能合理解释
"""


class _PlanCorrectnessScore(BaseModel):
    """Pydantic schema for the LLM-as-judge structured output."""

    score: float = Field(ge=0.0, le=10.0)
    reasoning: str = Field(max_length=300)


class PlanCorrectnessScorer(Agent):
    """LLM-as-judge that evaluates whether plan_id selection matches β rules.

    Differs from _BaseScorer: judge prompt operates on the planner's
    ``(plan_id, rationale)`` decision plus the upstream ``investment_objective``
    + ``user_message`` inputs, not on the final ``report_markdown``.
    """

    name = "PlanCorrectnessScorer"
    state_field = "plan_correctness_score"
    model_tier: Tier = "balanced"

    def step(self, state: ResearchState) -> StepResult:  # type: ignore[override]
        plan = state.plan
        if plan is None:
            score = CriticDimensionScore(
                dimension="plan_correctness",
                score=0.0,
                evidence="no plan available",
                sub_agent_request_id=state.request_id,
            )
            return StepResult(
                state_update={self.state_field: score},
                span_metadata={
                    "agent": self.name,
                    "dimension": "plan_correctness",
                    "skipped": "no_plan",
                },
            )

        prompt = _PLAN_CORRECTNESS_JUDGE_PROMPT.format(
            objective=state.investment_objective or "(未指定)",
            user_message=state.user_message or "(无)",
            plan_id=plan.plan_id,
            rationale=plan.rationale,
        )
        r = self._llm.chat(
            prompt=prompt,
            tier=self.model_tier,
            schema=_PlanCorrectnessScore,
            request_id=state.request_id,
        )
        parsed = r.parsed
        assert isinstance(parsed, _PlanCorrectnessScore), (
            f"LLMService contract violated: expected _PlanCorrectnessScore, "
            f"got {type(parsed).__name__}"
        )

        dim = CriticDimensionScore(
            dimension="plan_correctness",
            score=parsed.score,
            evidence=parsed.reasoning,
            sub_agent_request_id=r.request_id or state.request_id,
        )
        return StepResult(
            state_update={self.state_field: dim},
            span_metadata={
                "agent": self.name,
                "dimension": "plan_correctness",
                "model": r.model,
                "cost_cny": r.cost_cny,
            },
        )


__all__ = ["PlanCorrectnessScorer", "_PlanCorrectnessScore"]

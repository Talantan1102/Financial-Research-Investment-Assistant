"""Analyst — synthesizes tool_results into structured Insights."""

from __future__ import annotations

import json
import re

from app.agents.base import Agent
from app.agents.schemas import Insight, ResearchState, StepResult
from app.services.llm_response import Tier

_SYSTEM_PROMPT = """你是金融研究助手 analyst。

任务:基于 ResearchPlan 的子任务和 DataCollector 收集到的工具结果,产出 list[Insight]。
每个 Insight 关联一个 subtask_id,提炼 1-2 句关键发现 + 引用支持数据。

输出 JSON:
{
  "insights": [
    {
      "subtask_id": "...",
      "finding": "...",
      "supporting_data": [{"key": "price", "value": "1820.5"}],
      "confidence": "high|medium|low"
    }
  ]
}

注意:supporting_data 每个元素必须是 JSON 对象(dict),不能是字符串。
"""


def build_analyst_prompt(state: ResearchState) -> str:
    plan_summary = ""
    if state.plan is not None:
        for sub in state.plan.subtasks:
            plan_summary += f"- [{sub.subtask_id}] {sub.description}\n"
    tool_summary = "\n".join(
        f"- {tr.tool_name}({tr.args}) → success={tr.success} output={tr.output}"
        for tr in state.tool_results
    )
    return (
        _SYSTEM_PROMPT
        + f"\n\n# Subtasks\n{plan_summary}\n# Tool Results\n{tool_summary}\n\n请输出 JSON。"
    )


def _parse_insights(content: str) -> list[Insight]:
    cleaned = re.sub(r"^```(?:json)?\s*", "", content.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    data = json.loads(cleaned)
    return [Insight.model_validate(i) for i in data["insights"]]


class Analyst(Agent):
    name = "Analyst"
    model_tier: Tier = "balanced"

    def step(self, state: ResearchState) -> StepResult:  # type: ignore[override]
        prompt = build_analyst_prompt(state)
        r = self._llm.chat(prompt=prompt, tier=self.model_tier, request_id=state.request_id)
        insights = _parse_insights(r.content)
        return StepResult(
            state_update={"insights": insights},
            span_metadata={"agent": "Analyst", "model": r.model, "cost_cny": r.cost_cny},
        )

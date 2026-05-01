"""ResearchPlanner — decomposes user research intent into subtasks."""

from __future__ import annotations

import json
import re

from app.agents.base import Agent
from app.agents.schemas import ResearchPlan, ResearchState, StepResult
from app.services.llm_response import Tier

_SYSTEM_PROMPT = """你是金融研究助手 research_planner。

任务:把用户的研报需求拆成 2-5 个子任务,每个子任务对应一组数据收集点。

可用数据点(后续 DataCollector 会调对应工具):
- 行情数据(get_stock_quote)
- 财务数据(get_financials)
- 财经新闻(get_news)
- 网络搜索(web_search)
- 知识库搜索(mock_kb_search)

输出格式:仅输出 JSON,符合以下 schema:
{
  "subtasks": [
    {"subtask_id": "...", "description": "...", "required_tools": ["..."], "rationale": "..."}
  ],
  "target_entity": "<股票代码或公司名>",
  "research_style": "comprehensive",
  "reasoning": "<1-2 句拆分思路>"
}
"""


def build_planner_prompt(target_entity: str, user_message: str) -> str:
    return (
        _SYSTEM_PROMPT
        + f"\n\n# 目标实体\n{target_entity}\n\n# 用户研报需求\n{user_message}\n\n请输出 JSON。"
    )


def _parse_plan(content: str) -> ResearchPlan:
    """Strip code fences, json.loads, ResearchPlan validate."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", content.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    data = json.loads(cleaned)
    return ResearchPlan.model_validate(data)


def _extract_target_or_default(user_message: str) -> str:
    """Heuristic: 提取 .SH/.SZ 股票代码;否则返回空让 LLM 自己识别。"""
    m = re.search(r"\b\d{6}\.(SH|SZ)\b", user_message)
    return m.group(0) if m else ""


class ResearchPlanner(Agent):
    name = "ResearchPlanner"
    model_tier: Tier = "balanced"

    def step(self, state: ResearchState) -> StepResult:  # type: ignore[override]
        """Build a planner prompt, call LLM, parse the returned ResearchPlan JSON."""
        target = _extract_target_or_default(state.user_message)
        prompt = build_planner_prompt(target_entity=target, user_message=state.user_message)
        r = self._llm.chat(prompt=prompt, tier=self.model_tier, request_id=state.request_id)
        plan = _parse_plan(r.content)
        return StepResult(
            state_update={"plan": plan},
            span_metadata={"agent": "ResearchPlanner", "model": r.model, "cost_cny": r.cost_cny},
        )

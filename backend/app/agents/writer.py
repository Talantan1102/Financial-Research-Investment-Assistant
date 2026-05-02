"""Writer — synthesizes Insights into Markdown report with chart placeholders."""

from __future__ import annotations

import json
import re
from typing import Any

from app.agents.base import Agent
from app.agents.schemas import ChartSpec, ResearchState, StepResult
from app.services.llm_response import Tier

_SYSTEM_PROMPT = """你是金融研究助手 writer。

任务:基于 Insights 写成 Markdown 研报。可在合适位置插入图占位符 ![描述](chart://{chart_id})。
chart_id 使用 c1/c2/... 格式。

输出 JSON:
{
  "report_markdown": "...",
  "chart_specs": [
    {"chart_id":"c1","chart_type":"line|bar|pie|table","title":"...","data":[...],"x_axis":"...","y_axis":"..."}
  ]
}
"""


def build_writer_prompt(state: ResearchState) -> str:
    insights_str = "\n".join(
        f"- [{i.subtask_id}] {i.finding} (confidence={i.confidence})" for i in state.insights
    )
    return (
        _SYSTEM_PROMPT
        + f"\n\n# Insights\n{insights_str}\n# 用户原始需求\n{state.user_message}\n\n请输出 JSON。"
    )


def _parse_writer_output(content: str) -> tuple[str, list[ChartSpec]]:
    cleaned = re.sub(r"^```(?:json)?\s*", "", content.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    data: dict[str, Any] = json.loads(cleaned)
    md = str(data.get("report_markdown", ""))
    # Some LLM backends (e.g. deepseek-v3.2) emit `data` as a string instead of
    # list[dict] — a Pydantic ValidationError there must not bring down the whole
    # writer node, since chart_specs is a soft enrichment and the report markdown
    # is the load-bearing output.
    specs: list[ChartSpec] = []
    for s in data.get("chart_specs", []):
        try:
            specs.append(ChartSpec.model_validate(s))
        except Exception:
            continue
    return md, specs


class Writer(Agent):
    name = "Writer"
    model_tier: Tier = "balanced"

    def step(self, state: ResearchState) -> StepResult:  # type: ignore[override]
        prompt = build_writer_prompt(state)
        r = self._llm.chat(prompt=prompt, tier=self.model_tier, request_id=state.request_id)
        md, specs = _parse_writer_output(r.content)
        return StepResult(
            state_update={"report_markdown": md, "chart_specs": specs},
            span_metadata={"agent": "Writer", "model": r.model, "cost_cny": r.cost_cny},
        )

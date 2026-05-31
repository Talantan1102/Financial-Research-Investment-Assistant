"""Shared base for Critic dimension scorers — common prompt template + parse."""

from __future__ import annotations

import json
import re

from app.agents.base import Agent
from app.agents.schemas import (
    CriticDimension,
    CriticDimensionScore,
    ResearchState,
    StepResult,
)
from app.services.llm_response import Tier

# Hard cap on report_markdown passed to base scorers.
# The reasoning model (deepseek-v4-flash) counts thinking tokens against max_tokens=8000.
# Long reports (5000+ chars) cause completion truncation → JSONDecodeError.
# 5000 chars covers ~6-8 pages of Chinese text, sufficient for all 5 scoring dimensions.
_REPORT_CHAR_CAP = 5000

_BASE_SCORER_TEMPLATE = """你是金融研究助手 critic_{dimension}_scorer。

任务:为以下研报评分(0-10 分),仅评估 {dimension} 维度。

# 评分标准({dimension})
{rubric}

# 研报全文
{report_markdown}

# 上下文(研报子任务和 insights)
{context}

输出 JSON:
{{"score": <0-10>, "evidence": "<1-2 句话支持依据>"}}
"""


class _BaseScorer(Agent):
    """Subclass must set:
    - name (e.g. "FactualityScorer")
    - dimension: CriticDimension (e.g. "factuality")
    - rubric: str (criteria for scoring)
    - state_field: str (e.g. "factuality_score")
    """

    dimension: CriticDimension
    rubric: str
    state_field: str
    model_tier: Tier = "fast"

    def step(self, state: ResearchState) -> StepResult:  # type: ignore[override]
        raw_md = state.report_markdown or "(empty)"
        # Truncate to prevent reasoning-model token overflow (see _REPORT_CHAR_CAP comment)
        report_md = raw_md[:_REPORT_CHAR_CAP] if len(raw_md) > _REPORT_CHAR_CAP else raw_md
        prompt = _BASE_SCORER_TEMPLATE.format(
            dimension=self.dimension,
            rubric=self.rubric,
            report_markdown=report_md,
            context=_build_context(state),
        )
        r = self._llm.chat(prompt=prompt, tier=self.model_tier, request_id=state.request_id)
        score = _parse_score(
            r.content, dimension=self.dimension, request_id=r.request_id or state.request_id
        )
        return StepResult(
            state_update={self.state_field: score},
            span_metadata={
                "agent": self.name,
                "dimension": self.dimension,
                "model": r.model,
                "cost_cny": r.cost_cny,
            },
        )


def _build_context(state: ResearchState) -> str:
    parts = []
    if state.plan is not None:
        parts.append("Subtasks: " + ", ".join(s.subtask_id for s in state.plan.subtasks))
    if state.insights:
        parts.append(f"Insights count: {len(state.insights)}")
    return "\n".join(parts)


def _parse_score(
    content: str, *, dimension: CriticDimension, request_id: str
) -> CriticDimensionScore:
    """Parse LLM JSON output into a CriticDimensionScore.

    C22: Fail loud with context on any parse error rather than letting a bare
    JSONDecodeError / KeyError propagate through the LangGraph Send-API node
    and abort the entire 8-scorer subgraph.
    """
    cleaned = re.sub(r"^```(?:json)?\s*", "", content.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    try:
        data = json.loads(cleaned)
        return CriticDimensionScore(
            dimension=dimension,
            score=float(data["score"]),
            evidence=str(data.get("evidence", "")),
            sub_agent_request_id=request_id,
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            f"_parse_score failed for dimension={dimension!r} "
            f"request_id={request_id!r}: {exc!r}; raw={content!r}"
        ) from exc

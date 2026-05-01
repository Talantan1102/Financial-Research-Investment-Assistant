"""Judge — LLM-as-judge with 4-dim rubric (spec § 8 R4).

Constructs a deterministic prompt from (GoldenCase, sut_response, trace_summary,
tool_calls), calls LLMService.chat, parses the JSON response into JudgeScores.

`tool_correctness` may be null in the response — interpreted as N/A and
recorded as None on JudgeScores. The aggregate average ignores N/A dims.

Task 12: ``score()`` accepts an optional ``tool_calls`` argument.  When
provided (non-None, even if empty), the prompt includes the actual tool_calls
JSON so the judge can evaluate tool_correctness.  When absent (None), the
prompt omits the section and the judge will set tool_correctness to null
(backward-compat with Plan C bare-LLMService SUT path).
"""

from __future__ import annotations

import json
from typing import Any

from app.agents.schemas import ToolCall
from app.services.eval_models import GoldenCase, JudgeScores
from app.services.llm_response import Tier
from app.services.llm_service import LLMService

_JUDGE_TEMPLATE = """\
你是金融研究助手的输出评审员。给定:
- 用户输入: {user_input}
- 期望行为: {expected_behavior}
- 实际 trace: {trace_summary}
- 实际响应: {sut_response}{tool_calls_section}

按以下 4 维度各打 0-10 分,输出 JSON。如果某维度不适用(例如 trace 中无 tool_calls,
则 tool_correctness 不适用),将 score 设为 null,evidence 写 "N/A — <原因>"。

{{
  "factuality": {{"score": 0-10, "evidence": "1 句话"}},
  "tool_correctness": {{"score": 0-10 或 null, "evidence": "1 句话"}},
  "coverage": {{"score": 0-10, "evidence": "1 句话"}},
  "structure": {{"score": 0-10, "evidence": "1 句话"}}
}}

仅输出 JSON,无其他文字。
"""

_TOOL_CALLS_SECTION = "\n- 实际 tool_calls: {tool_calls_json}"


def build_judge_prompt(
    case: GoldenCase,
    sut_response: str,
    trace_summary: str,
    tool_calls: list[ToolCall] | None = None,
) -> str:
    if tool_calls is not None:
        tool_calls_json = json.dumps([tc.model_dump() for tc in tool_calls], ensure_ascii=False)
        tool_calls_section = _TOOL_CALLS_SECTION.format(tool_calls_json=tool_calls_json)
    else:
        tool_calls_section = ""
    return _JUDGE_TEMPLATE.format(
        user_input=case.user_input,
        expected_behavior=json.dumps(case.expected_behavior, ensure_ascii=False),
        trace_summary=trace_summary,
        sut_response=sut_response,
        tool_calls_section=tool_calls_section,
    )


class Judge:
    def __init__(self, llm: LLMService, judge_tier: Tier = "balanced") -> None:
        self._llm = llm
        self._tier = judge_tier

    def score(
        self,
        case: GoldenCase,
        sut_response: str,
        trace_summary: str,
        tool_calls: list[ToolCall] | None = None,
    ) -> tuple[JudgeScores, dict[str, Any]]:
        """Score a SUT output against a golden case.

        Args:
            case:          The golden case being evaluated.
            sut_response:  The SUT's text response.
            trace_summary: Human-readable span summary from TraceService.
            tool_calls:    Actual tool calls from SUTOutput.  When None (bare
                           LLMService SUT, Plan C path) the judge prompt omits
                           the tool_calls section and the judge scores
                           tool_correctness as null.  When provided (ChatAgent
                           SUT), the prompt includes the list so the judge can
                           evaluate tool selection/arguments.
        """
        prompt = build_judge_prompt(case, sut_response, trace_summary, tool_calls)
        r = self._llm.chat(prompt=prompt, tier=self._tier)
        raw = json.loads(r.content)
        scores = JudgeScores(
            factuality=raw["factuality"]["score"],
            factuality_evidence=raw["factuality"]["evidence"],
            tool_correctness=raw["tool_correctness"]["score"],
            tool_correctness_evidence=raw["tool_correctness"]["evidence"],
            coverage=raw["coverage"]["score"],
            coverage_evidence=raw["coverage"]["evidence"],
            structure=raw["structure"]["score"],
            structure_evidence=raw["structure"]["evidence"],
        )
        meta = {
            "model": r.model,
            "cost_cny": r.cost_cny,
            "latency_ms": r.latency_ms,
        }
        return scores, meta

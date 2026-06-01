"""Judge — LLM-as-judge with 4-dim rubric (spec § 8 R4).

Constructs a deterministic prompt from (GoldenCase, sut_response, trace_summary,
tool_calls), calls LLMService.chat, parses the JSON response into JudgeScores.

`tool_correctness` may be null in the response — interpreted as N/A and
recorded as None on JudgeScores. The aggregate average ignores N/A dims.

Task 12 (v0): ``score()`` accepts an optional ``tool_calls`` argument.  When
provided (non-None, even if empty), the prompt includes the actual tool_calls
JSON so the judge can evaluate tool_correctness.  When absent (None), the
prompt omits the section and the judge will set tool_correctness to null
(backward-compat with Plan C bare-LLMService SUT path).

Task 12 (v0.5): ``score()`` accepts an optional ``report_markdown`` argument.
When provided (non-None), the prompt includes the markdown text and a 5th
rubric dimension ``report_markdown_quality`` ∈ [0, 10].  When absent (None,
default), the prompt is identical to v0 — zero regression on Plan C/D tests.
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

_JUDGE_TEMPLATE_WITH_REPORT = """\
你是金融研究助手的输出评审员。给定:
- 用户输入: {user_input}
- 期望行为: {expected_behavior}
- 实际 trace: {trace_summary}
- 实际响应: {sut_response}{tool_calls_section}
- 研报 Markdown: {report_markdown}

按以下 5 维度各打 0-10 分,输出 JSON。如果某维度不适用,将 score 设为 null,
evidence 写 "N/A — <原因>"。report_markdown_quality 评估研报的格式规范性、
可读性、章节完整性;如果响应不是研报(过短或格式不符),设为 null。

{{
  "factuality": {{"score": 0-10, "evidence": "1 句话"}},
  "tool_correctness": {{"score": 0-10 或 null, "evidence": "1 句话"}},
  "coverage": {{"score": 0-10, "evidence": "1 句话"}},
  "structure": {{"score": 0-10, "evidence": "1 句话"}},
  "report_markdown_quality": {{"score": 0-10 或 null, "evidence": "1 句话"}}
}}

仅输出 JSON,无其他文字。
"""

_TOOL_CALLS_SECTION = "\n- 实际 tool_calls: {tool_calls_json}"


def build_judge_prompt(
    case: GoldenCase,
    sut_response: str,
    trace_summary: str,
    tool_calls: list[ToolCall] | None = None,
    report_markdown: str | None = None,
) -> str:
    if tool_calls is not None:
        tool_calls_json = json.dumps([tc.model_dump() for tc in tool_calls], ensure_ascii=False)
        tool_calls_section = _TOOL_CALLS_SECTION.format(tool_calls_json=tool_calls_json)
    else:
        tool_calls_section = ""

    if report_markdown is not None:
        return _JUDGE_TEMPLATE_WITH_REPORT.format(
            user_input=case.user_input,
            expected_behavior=json.dumps(case.expected_behavior, ensure_ascii=False),
            trace_summary=trace_summary,
            sut_response=sut_response,
            tool_calls_section=tool_calls_section,
            report_markdown=report_markdown,
        )
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
        report_markdown: str | None = None,
    ) -> tuple[JudgeScores, dict[str, Any]]:
        """Score a SUT output against a golden case.

        Args:
            case:              The golden case being evaluated.
            sut_response:      The SUT's text response.
            trace_summary:     Human-readable span summary from TraceService.
            tool_calls:        Actual tool calls from SUTOutput.  When None
                               (bare LLMService SUT, Plan C path) the judge
                               prompt omits the tool_calls section and scores
                               tool_correctness as null.  When provided
                               (ChatAgent SUT), the prompt includes the list.
            report_markdown:   v0.5 additive. When provided (non-None), prompt
                               switches to 5-dim template and judge scores
                               report_markdown_quality ∈ [0,10] or null when
                               not a proper research report.  When absent
                               (None, default), behaviour is identical to v0.
        """
        prompt = build_judge_prompt(case, sut_response, trace_summary, tool_calls, report_markdown)
        # C10: pass schema to enable JSON mode so the adapter uses response_format
        r = self._llm.chat(prompt=prompt, tier=self._tier, schema={"type": "object"})
        # C10: wrap json.loads so a non-JSON reply raises ValueError with context
        # instead of a bare JSONDecodeError that would crash the whole eval run.
        try:
            raw = json.loads(r.content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Judge LLM returned non-JSON: {r.content!r}") from exc

        # C10: wrap required-key access so a missing dim raises descriptively.
        def _get_dim(block: dict[str, Any], dim: str) -> Any:
            try:
                return block[dim]
            except (KeyError, TypeError) as exc:
                raise ValueError(
                    f"Judge response missing expected key {dim!r}; raw={r.content!r}"
                ) from exc

        rmq_block = raw.get("report_markdown_quality")
        report_markdown_quality: float | None = (
            rmq_block["score"] if rmq_block is not None else None
        )
        scores = JudgeScores(
            factuality=_get_dim(_get_dim(raw, "factuality"), "score"),
            factuality_evidence=_get_dim(_get_dim(raw, "factuality"), "evidence"),
            tool_correctness=_get_dim(_get_dim(raw, "tool_correctness"), "score"),
            tool_correctness_evidence=_get_dim(_get_dim(raw, "tool_correctness"), "evidence"),
            coverage=_get_dim(_get_dim(raw, "coverage"), "score"),
            coverage_evidence=_get_dim(_get_dim(raw, "coverage"), "evidence"),
            structure=_get_dim(_get_dim(raw, "structure"), "score"),
            structure_evidence=_get_dim(_get_dim(raw, "structure"), "evidence"),
            report_markdown_quality=report_markdown_quality,
        )
        meta = {
            "model": r.model,
            "cost_cny": r.cost_cny,
            "latency_ms": r.latency_ms,
        }
        return scores, meta

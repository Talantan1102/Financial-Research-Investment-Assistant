"""EvalRunner — orchestrates one or many GoldenCase runs.

For each case: SUT → fetch trace → Judge → write EvalResult. The SUT under
v0 is bare LLMService.chat (no agent); when the agent skeleton lands the
sut param accepts any object satisfying the ``SUT`` protocol.

Task 12: ``SUT`` Protocol added.  ``EvalRunner.__init__`` accepts either a
``SUT`` or a bare ``LLMService``; the latter is auto-wrapped via
``_LLMServiceSUT`` for Plan C backward compatibility.

``run_one`` remains sync (Plan D contract).  The async SUT is bridged via
``asyncio.run()`` — callers must NOT invoke ``run_one`` from inside a running
event loop (Pattern B per spec).  Plan C/D tests are sync; new ChatAgent eval
tests call ``run_one`` from sync context too.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from app.agents.schemas import ToolCall
from app.services.eval_models import EvalResult, GoldenCase, SUTOutput
from app.services.eval_recorder import EvalRecorder
from app.services.judge import Judge
from app.services.llm_service import LLMService
from app.services.trace_service import TraceService


@runtime_checkable
class SUT(Protocol):
    """Protocol for any System Under Test in the eval pipeline.

    Implementors: ChatAgent (v0+), _LLMServiceSUT (Plan C backward compat).
    """

    async def run(self, user_input: str, request_id: str) -> SUTOutput: ...


class _LLMServiceSUT:
    """Adapter: wraps bare LLMService as a SUT (backward compat for Plan C tests).

    tool_calls is always empty — so Judge.score receives tool_calls=None and
    sets tool_correctness to None (N/A) in JudgeScores.
    """

    def __init__(self, llm: LLMService) -> None:
        self._llm = llm

    async def run(self, user_input: str, request_id: str) -> SUTOutput:
        r = self._llm.chat(prompt=user_input, tier="balanced", request_id=request_id)
        return SUTOutput(
            request_id=r.request_id or request_id,
            response_text=r.content,
            tool_calls=[],
        )


class EvalRunner:
    def __init__(
        self,
        sut: SUT | LLMService,
        judge: Judge,
        trace_service: TraceService,
        recorder: EvalRecorder,
    ) -> None:
        """Initialise EvalRunner.

        Args:
            sut:           Either a ``SUT``-protocol object (e.g. ChatAgent) or
                           a bare ``LLMService`` which is auto-wrapped via
                           ``_LLMServiceSUT`` for Plan C backward compat.
            judge:         Judge instance for scoring.
            trace_service: TraceService for span retrieval.
            recorder:      EvalRecorder for persisting EvalResult rows.
        """
        self._sut: SUT = sut if not isinstance(sut, LLMService) else _LLMServiceSUT(sut)
        self._judge = judge
        self._trace = trace_service
        self._recorder = recorder

    def run_one(self, case: GoldenCase) -> EvalResult:
        """Run one GoldenCase through the SUT and Judge; persist and return EvalResult.

        Sync wrapper — internally bridges the async SUT via ``asyncio.run()``.
        Must NOT be called from within a running event loop.
        """
        request_id = f"eval-{case.case_id}-{uuid4().hex[:8]}"
        sut_output = asyncio.run(self._sut.run(user_input=case.user_input, request_id=request_id))

        try:
            trace = self._trace.get_trace(request_id)
            trace_summary = self._summarize_trace(trace)
        except LookupError:
            trace_summary = "spans=[] total_latency_ms=0"

        # Pass tool_calls only when SUT produced some (ChatAgent path).
        # For bare LLMService SUT (_LLMServiceSUT), tool_calls is always [],
        # and we pass None so Judge scores tool_correctness as null (Plan C compat).
        tool_calls_for_judge: list[ToolCall] | None = (
            sut_output.tool_calls if sut_output.tool_calls else None
        )

        # v0.5: pass report_markdown only when the SUT produced tool_calls
        # (i.e., agentic / research-mode SUT path). Bare LLMService SUT has no
        # tool_calls → report_markdown stays None → 4-dim judge prompt (Plan C
        # backward compat preserved). ResearchAgent always has tool_calls →
        # 5-dim judge prompt → report_markdown_quality scored.
        report_markdown_for_judge: str | None = (
            sut_output.response_text if tool_calls_for_judge is not None else None
        )
        scores, judge_meta = self._judge.score(
            case=case,
            sut_response=sut_output.response_text,
            trace_summary=trace_summary,
            tool_calls=tool_calls_for_judge,
            report_markdown=report_markdown_for_judge,
        )

        result = EvalResult(
            eval_id=f"eval-{uuid4().hex[:12]}",
            request_id=request_id,
            case_id=case.case_id,
            scores=scores,
            judge_model=judge_meta["model"],
            judge_cost_cny=float(judge_meta["cost_cny"]),
            judge_latency_ms=int(judge_meta["latency_ms"]),
            timestamp=datetime.now(UTC),
        )
        self._recorder.write(result)
        return result

    def run_many(self, cases: list[GoldenCase]) -> list[EvalResult]:
        return [self.run_one(c) for c in cases]

    @staticmethod
    def _summarize_trace(trace: Any) -> str:
        spans = [trace.root_span, *trace.root_span_children]
        names = ", ".join(s.name for s in spans)
        return f"spans=[{names}] total_latency_ms={trace.total_latency_ms}"


def compute_sanity_pass_rate(
    labeled: list[tuple[EvalResult, str]],
) -> tuple[float, list[str]]:
    """Compute sanity-check pass rate from labeled eval results.

    `labeled` is a list of (result, sanity_label) tuples where sanity_label
    is "obvious_correct" or "obvious_wrong". Per spec § 8:
    - obvious_correct must score factuality >= 8
    - obvious_wrong must score factuality <= 3

    Returns (pass_rate, failures) where failures is a list of human-readable
    strings describing each failed case.
    """
    failures: list[str] = []
    for result, label in labeled:
        f = result.scores.factuality
        if label == "obvious_correct" and f < 8:
            failures.append(f"{result.case_id}: obvious_correct but factuality={f} (< 8)")
        elif label == "obvious_wrong" and f > 3:
            failures.append(f"{result.case_id}: obvious_wrong but factuality={f} (> 3)")
    pass_rate = 1.0 - (len(failures) / len(labeled)) if labeled else 1.0
    return pass_rate, failures

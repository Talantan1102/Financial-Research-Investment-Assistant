"""EvalRunner — orchestrates one or many GoldenCase runs.

For each case: SUT → fetch trace → Judge → write EvalResult. The SUT under
v0 is bare LLMService.chat (no agent); when the agent skeleton lands the
sut param accepts any object satisfying a tiny `SUT` protocol.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.services.eval_models import EvalResult, GoldenCase
from app.services.eval_recorder import EvalRecorder
from app.services.judge import Judge
from app.services.llm_service import LLMService
from app.services.trace_service import TraceService


class EvalRunner:
    def __init__(
        self,
        sut: LLMService,
        judge: Judge,
        trace_service: TraceService,
        recorder: EvalRecorder,
    ) -> None:
        self._sut = sut
        self._judge = judge
        self._trace = trace_service
        self._recorder = recorder

    def run_one(self, case: GoldenCase) -> EvalResult:
        request_id = f"eval-{case.case_id}-{uuid4().hex[:8]}"
        sut_response = self._sut.chat(
            prompt=case.user_input,
            tier="balanced",
            request_id=request_id,
        )
        trace = self._trace.get_trace(request_id)
        trace_summary = self._summarize_trace(trace)

        scores, judge_meta = self._judge.score(
            case=case,
            sut_response=sut_response.content,
            trace_summary=trace_summary,
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

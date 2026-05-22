"""L1 — EvalRunner end-to-end against MockLLMClient SUT and MockLLMClient Judge.

One golden case → SUT → trace → Judge → EvalResult written. Verify each step.
"""

import contextlib

from app.services.eval_models import GoldenCase
from app.services.eval_recorder import EvalRecorder
from app.services.eval_runner import EvalRunner
from app.services.judge import Judge
from app.services.llm_mock_client import MockLLMClient
from app.services.llm_service import LLMService
from app.services.trace_service import TraceService


def test_run_one_case_writes_eval_result(
    mock_llm_client: MockLLMClient,
    db_session,
) -> None:
    trace = TraceService(session_factory=lambda: contextlib.nullcontext(db_session))
    recorder = EvalRecorder(session_factory=lambda: contextlib.nullcontext(db_session))

    sut_llm = LLMService(client=mock_llm_client, trace_service=trace)
    judge_llm = LLMService(client=mock_llm_client)
    judge = Judge(llm=judge_llm, judge_tier="balanced")

    case = GoldenCase(
        case_id="x",
        category="single_tool_call",
        user_input="What is the price of 600519.SH?",
        expected_behavior={"response_must_contain": ["600519"]},
        metadata={"added_by": "test", "added_at": "2026-04-30", "tags": []},
    )

    runner = EvalRunner(
        sut=sut_llm,
        judge=judge,
        trace_service=trace,
        recorder=recorder,
    )
    eval_result = runner.run_one(case)

    assert eval_result.case_id == "x"
    assert eval_result.scores.factuality is not None
    stored = recorder.read(eval_result.eval_id)
    assert stored == eval_result
    spans = trace.query_spans({"request_id": eval_result.request_id})
    assert len(spans) >= 1


def test_run_many_cases(
    mock_llm_client: MockLLMClient,
    db_session,
) -> None:
    trace = TraceService(session_factory=lambda: contextlib.nullcontext(db_session))
    recorder = EvalRecorder(session_factory=lambda: contextlib.nullcontext(db_session))
    sut_llm = LLMService(client=mock_llm_client, trace_service=trace)
    judge = Judge(llm=LLMService(client=mock_llm_client), judge_tier="balanced")
    runner = EvalRunner(sut=sut_llm, judge=judge, trace_service=trace, recorder=recorder)

    cases = [
        GoldenCase(
            case_id=f"c{i}",
            category="single_tool_call",
            user_input="What is the price of 600519.SH?",
            expected_behavior={"response_must_contain": ["600519"]},
            metadata={"added_by": "test", "added_at": "2026-04-30", "tags": []},
        )
        for i in range(3)
    ]
    results = runner.run_many(cases)
    assert len(results) == 3
    assert len({r.eval_id for r in results}) == 3

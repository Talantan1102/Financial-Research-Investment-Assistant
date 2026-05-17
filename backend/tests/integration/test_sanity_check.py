"""L1 — sanity check: with deterministic mock judge fixture, all 10 sanity
cases must pass. If they don't, the mock fixture or the prompt is wrong.

A non-100% sanity pass with mock judge means the mock fixture's scores
don't match the cases — fix the fixture.
"""

import contextlib
from pathlib import Path

from app.services.eval_models import load_golden_jsonl
from app.services.eval_recorder import EvalRecorder
from app.services.eval_runner import EvalRunner, compute_sanity_pass_rate
from app.services.judge import Judge
from app.services.llm_mock_client import MockLLMClient
from app.services.llm_service import LLMService
from app.services.trace_service import TraceService

SANITY_PATH = Path("backend/tests/fixtures/eval/sanity_obvious_cases.jsonl")


def test_mock_sanity_pass_rate_is_100(
    mock_llm_client: MockLLMClient,
    db_session,
) -> None:
    trace = TraceService(session_factory=lambda: contextlib.nullcontext(db_session))
    recorder = EvalRecorder(session_factory=lambda: contextlib.nullcontext(db_session))
    sut = LLMService(client=mock_llm_client, trace_service=trace)
    judge = Judge(llm=LLMService(client=mock_llm_client), judge_tier="balanced")
    runner = EvalRunner(sut=sut, judge=judge, trace_service=trace, recorder=recorder)

    cases = load_golden_jsonl(SANITY_PATH)
    assert len(cases) == 10
    results = runner.run_many(cases)

    labeled = [(r, c.metadata["sanity_label"]) for r, c in zip(results, cases)]
    pass_rate, failures = compute_sanity_pass_rate(labeled)
    assert pass_rate == 1.0, "Sanity failures:\n  - " + "\n  - ".join(failures)

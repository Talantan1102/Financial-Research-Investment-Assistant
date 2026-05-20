"""L0 — EvalRecorder write/read round-trip (ORM/PG path)."""

import contextlib
from datetime import UTC, datetime

from app.services.eval_models import BacktestRun, EvalResult, JudgeScores
from app.services.eval_recorder import EvalRecorder


def _result(eval_id: str, request_id: str, case_id: str) -> EvalResult:
    return EvalResult(
        eval_id=eval_id,
        request_id=request_id,
        case_id=case_id,
        scores=JudgeScores(
            factuality=8,
            factuality_evidence="ok",
            tool_correctness=None,
            tool_correctness_evidence="N/A — no tool calls",
            coverage=7,
            coverage_evidence="ok",
            structure=9,
            structure_evidence="ok",
        ),
        judge_model="deepseek-v4-flash",
        judge_cost_cny=0.001,
        judge_latency_ms=420,
        timestamp=datetime(2026, 4, 30, 12, 0, 0, tzinfo=UTC),
    )


def test_write_then_read(db_session) -> None:
    rec = EvalRecorder(session_factory=lambda: contextlib.nullcontext(db_session))
    r = _result("e1", "req-1", "v0-chat-001")
    rec.write(r)
    got = rec.read("e1")
    assert got == r


def test_query_by_case_id(db_session) -> None:
    rec = EvalRecorder(session_factory=lambda: contextlib.nullcontext(db_session))
    rec.write(_result("e1", "req-1", "v0-chat-001"))
    rec.write(_result("e2", "req-2", "v0-chat-002"))
    results = rec.query({"case_id": "v0-chat-001"})
    assert len(results) == 1
    assert results[0].eval_id == "e1"


def test_init_schema_idempotent(db_session) -> None:
    rec = EvalRecorder(session_factory=lambda: contextlib.nullcontext(db_session))
    rec.write(_result("e1", "req-1", "c1"))
    assert len(rec.query({})) == 1


# ---------------------------------------------------------------------------
# v1.x DD report eval: Phase 1+2 — backtest schema extensions (ORM path)
# ---------------------------------------------------------------------------


def test_eval_result_accepts_backtest_fields() -> None:
    """EvalResult 接受 backtest 相关可选字段 (Pydantic model test, no DB)."""
    result = EvalResult(
        eval_id="bt-eval-001",
        request_id="bt-req-001",
        case_id="bt-case-600519-20240630",
        scores=JudgeScores(
            factuality=9,
            factuality_evidence="accurate",
            tool_correctness=None,
            tool_correctness_evidence="N/A",
            coverage=8,
            coverage_evidence="good",
            structure=9,
            structure_evidence="clean",
        ),
        judge_model="gpt-4o-2024-05-13",
        judge_cost_cny=0.5,
        judge_latency_ms=2000,
        timestamp=datetime.now(UTC),
        backtest_run_id="bt-run-001",
        cut_off_date="2024-06-30",
        evaluator_llm="gpt-4o-2024-05-13",
        case_type="backtest",
    )
    assert result.backtest_run_id == "bt-run-001"
    assert result.cut_off_date == "2024-06-30"
    assert result.evaluator_llm == "gpt-4o-2024-05-13"
    assert result.case_type == "backtest"


def test_eval_recorder_persists_backtest_fields(db_session) -> None:
    """EvalRecorder ORM: 写入 5 个新 backtest 字段后能正确读回."""
    rec = EvalRecorder(session_factory=lambda: contextlib.nullcontext(db_session))

    rec.write(
        EvalResult(
            eval_id="bt-eval-002",
            request_id="bt-req-002",
            case_id="bt-case-002",
            scores=JudgeScores(
                factuality=9,
                factuality_evidence="accurate",
                tool_correctness=None,
                tool_correctness_evidence="N/A",
                coverage=8,
                coverage_evidence="good",
                structure=9,
                structure_evidence="clean",
            ),
            judge_model="qwen2.5-72b-instruct",
            judge_cost_cny=0.3,
            judge_latency_ms=1500,
            timestamp=datetime.now(UTC),
            backtest_run_id="bt-run-002",
            cut_off_date="2024-12-31",
            evaluator_llm="qwen2.5-72b-instruct",
            case_type="backtest",
            metric_scores_json='{"m1": 0.9, "m2": 0.8}',
        )
    )

    got = rec.read("bt-eval-002")
    assert got.backtest_run_id == "bt-run-002"
    assert got.cut_off_date == "2024-12-31"
    assert got.evaluator_llm == "qwen2.5-72b-instruct"
    assert got.case_type == "backtest"
    assert got.metric_scores_json == '{"m1": 0.9, "m2": 0.8}'


def test_eval_recorder_query_by_backtest_run_id(db_session) -> None:
    """query() 支持 backtest_run_id 过滤."""
    rec = EvalRecorder(session_factory=lambda: contextlib.nullcontext(db_session))

    # Write two results with different run_ids
    for i in range(3):
        rec.write(
            EvalResult(
                eval_id=f"ev-run-a-{i}",
                request_id=f"req-a-{i}",
                case_id=f"case-{i}",
                scores=JudgeScores(
                    factuality=7,
                    factuality_evidence="ok",
                    tool_correctness=None,
                    tool_correctness_evidence="N/A",
                    coverage=7,
                    coverage_evidence="ok",
                    structure=7,
                    structure_evidence="ok",
                ),
                judge_model="qwen",
                judge_cost_cny=0.0,
                judge_latency_ms=100,
                timestamp=datetime.now(UTC),
                backtest_run_id="run-aaa",
            )
        )
    rec.write(
        EvalResult(
            eval_id="ev-run-b-0",
            request_id="req-b-0",
            case_id="case-b",
            scores=JudgeScores(
                factuality=7,
                factuality_evidence="ok",
                tool_correctness=None,
                tool_correctness_evidence="N/A",
                coverage=7,
                coverage_evidence="ok",
                structure=7,
                structure_evidence="ok",
            ),
            judge_model="qwen",
            judge_cost_cny=0.0,
            judge_latency_ms=100,
            timestamp=datetime.now(UTC),
            backtest_run_id="run-bbb",
        )
    )

    results = rec.query({"backtest_run_id": "run-aaa"})
    assert len(results) == 3
    assert all(r.backtest_run_id == "run-aaa" for r in results)


def test_write_backtest_run_round_trip(db_session) -> None:
    """write_backtest_run() ORM: BacktestRun round-trip via BacktestRunRow."""
    from app.services.trace_models import BacktestRunRow

    rec = EvalRecorder(session_factory=lambda: contextlib.nullcontext(db_session))

    run = BacktestRun(
        run_id="bt-run-test-001",
        created_at="2026-05-20T10:00:00+00:00",
        case_count=5,
        metric_summary_json='{"m1": 0.85}',
        status="completed",
        git_sha="abc123def",
        ablation_variant="V2",
        llm_model="qwen2.5-72b-instruct",
    )
    rec.write_backtest_run(run)

    # Verify directly via ORM
    row = db_session.get(BacktestRunRow, "bt-run-test-001")
    assert row is not None
    assert row.run_id == "bt-run-test-001"
    assert row.case_count == 5
    assert row.status == "completed"
    assert row.git_sha == "abc123def"
    assert row.ablation_variant == "V2"
    assert row.llm_model == "qwen2.5-72b-instruct"
    assert row.metric_summary_json == '{"m1": 0.85}'


def test_write_backtest_run_idempotent(db_session) -> None:
    """write_backtest_run() on existing run_id updates status/count in-place."""
    from app.services.trace_models import BacktestRunRow

    rec = EvalRecorder(session_factory=lambda: contextlib.nullcontext(db_session))

    run = BacktestRun(
        run_id="bt-run-idem",
        created_at="2026-05-20T10:00:00+00:00",
        case_count=1,
        status="completed",
    )
    rec.write_backtest_run(run)

    # Update with new status
    run2 = BacktestRun(
        run_id="bt-run-idem",
        created_at="2026-05-20T10:00:00+00:00",
        case_count=3,
        status="failed",
    )
    rec.write_backtest_run(run2)

    row = db_session.get(BacktestRunRow, "bt-run-idem")
    assert row is not None
    assert row.case_count == 3
    assert row.status == "failed"


def test_query_filters_not_affected_by_new_columns(db_session) -> None:
    """query() by classic keys (case_id, request_id) still works after 5 new cols."""
    rec = EvalRecorder(session_factory=lambda: contextlib.nullcontext(db_session))
    rec.write(_result("q1", "req-q1", "case-classic"))
    rec.write(_result("q2", "req-q2", "case-other"))

    r = rec.query({"case_id": "case-classic"})
    assert len(r) == 1
    assert r[0].eval_id == "q1"
    # New fields should be None for classic records
    assert r[0].backtest_run_id is None
    assert r[0].metric_scores_json is None

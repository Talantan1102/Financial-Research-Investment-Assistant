"""L0 — EvalRecorder write/read round-trip."""

from datetime import datetime
from pathlib import Path

from app.services.eval_models import EvalResult, JudgeScores
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
        timestamp=datetime(2026, 4, 30, 12, 0, 0),
    )


def test_write_then_read(tmp_eval_db: Path) -> None:
    rec = EvalRecorder(db_path=tmp_eval_db)
    rec.init_schema()
    r = _result("e1", "req-1", "v0-chat-001")
    rec.write(r)
    got = rec.read("e1")
    assert got == r


def test_query_by_case_id(tmp_eval_db: Path) -> None:
    rec = EvalRecorder(db_path=tmp_eval_db)
    rec.init_schema()
    rec.write(_result("e1", "req-1", "v0-chat-001"))
    rec.write(_result("e2", "req-2", "v0-chat-002"))
    results = rec.query({"case_id": "v0-chat-001"})
    assert len(results) == 1
    assert results[0].eval_id == "e1"


def test_init_schema_idempotent(tmp_eval_db: Path) -> None:
    rec = EvalRecorder(db_path=tmp_eval_db)
    rec.init_schema()
    rec.write(_result("e1", "req-1", "c1"))
    rec.init_schema()
    assert len(rec.query({})) == 1


# ---------------------------------------------------------------------------
# v1.x DD report eval: Phase 1 Task 1.1 — backtest schema extensions
# ---------------------------------------------------------------------------


def test_eval_result_accepts_backtest_fields() -> None:
    """v1.x DD report eval: EvalResult 接受 backtest 相关可选字段."""
    from datetime import UTC, datetime

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
        # 新字段
        backtest_run_id="bt-run-001",
        cut_off_date="2024-06-30",
        evaluator_llm="gpt-4o-2024-05-13",
        case_type="backtest",
    )
    assert result.backtest_run_id == "bt-run-001"
    assert result.cut_off_date == "2024-06-30"
    assert result.evaluator_llm == "gpt-4o-2024-05-13"
    assert result.case_type == "backtest"


def test_eval_recorder_persists_backtest_fields(tmp_path: Path) -> None:
    """EvalRecorder 写入新 backtest 字段后能正确读回."""
    from datetime import UTC, datetime

    db = tmp_path / "eval.sqlite"
    rec = EvalRecorder(db_path=db)
    rec.init_schema()

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
        )
    )

    got = rec.read("bt-eval-002")
    assert got.backtest_run_id == "bt-run-002"
    assert got.cut_off_date == "2024-12-31"
    assert got.evaluator_llm == "qwen2.5-72b-instruct"
    assert got.case_type == "backtest"


def test_backtest_runs_table_schema(tmp_path: Path) -> None:
    """backtest_runs 表 schema 含决策 7-8 所需字段."""
    import sqlite3

    db = tmp_path / "eval.sqlite"
    rec = EvalRecorder(db_path=db)
    rec.init_schema()

    with sqlite3.connect(db) as con:
        cols = {row[1] for row in con.execute("PRAGMA table_info(backtest_runs)")}

    expected = {
        "run_id",
        "created_at",
        "case_count",
        "metric_summary_json",
        "status",
        "git_sha",
        "ablation_variant",
        "llm_model",
    }
    assert expected.issubset(cols), f"missing: {expected - cols}"

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
        judge_model="deepseek-v3.2",
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

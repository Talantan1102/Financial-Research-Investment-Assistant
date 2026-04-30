"""EvalRecorder — SQLite-backed eval_results writer.

Shares the file with TraceService (same .sqlite, different table) so a
single SQL JOIN on request_id retrieves "this case scored X, here's the
trace that produced it" per spec § 9.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from app.services.eval_models import EvalResult, JudgeScores

_EVAL_RESULTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS eval_results (
    eval_id            TEXT PRIMARY KEY,
    request_id         TEXT NOT NULL,
    case_id            TEXT NOT NULL,
    scores_json        TEXT NOT NULL,
    judge_model        TEXT NOT NULL,
    judge_cost_cny     REAL NOT NULL,
    judge_latency_ms   INTEGER NOT NULL,
    timestamp          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_eval_request ON eval_results(request_id);
CREATE INDEX IF NOT EXISTS idx_eval_case    ON eval_results(case_id);
"""


class EvalRecorder:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    def init_schema(self) -> None:
        with sqlite3.connect(self._db_path) as con:
            con.executescript(_EVAL_RESULTS_SCHEMA)

    def write(self, result: EvalResult) -> None:
        with sqlite3.connect(self._db_path) as con:
            con.execute(
                "INSERT OR REPLACE INTO eval_results VALUES (?,?,?,?,?,?,?,?)",
                (
                    result.eval_id,
                    result.request_id,
                    result.case_id,
                    result.scores.model_dump_json(),
                    result.judge_model,
                    result.judge_cost_cny,
                    result.judge_latency_ms,
                    result.timestamp.isoformat(),
                ),
            )

    def read(self, eval_id: str) -> EvalResult:
        with sqlite3.connect(self._db_path) as con:
            con.row_factory = sqlite3.Row
            row = con.execute("SELECT * FROM eval_results WHERE eval_id = ?", (eval_id,)).fetchone()
        if row is None:
            raise LookupError(f"no eval_result with eval_id={eval_id!r}")
        return self._row_to_result(row)

    def query(self, filters: dict[str, Any]) -> list[EvalResult]:
        if not filters:
            sql = "SELECT * FROM eval_results"
            params: tuple[Any, ...] = ()
        else:
            clauses = " AND ".join(f"{k} = ?" for k in filters)
            sql = f"SELECT * FROM eval_results WHERE {clauses}"
            params = tuple(filters.values())
        with sqlite3.connect(self._db_path) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(sql, params).fetchall()
        return [self._row_to_result(r) for r in rows]

    @staticmethod
    def _row_to_result(row: sqlite3.Row) -> EvalResult:
        return EvalResult(
            eval_id=row["eval_id"],
            request_id=row["request_id"],
            case_id=row["case_id"],
            scores=JudgeScores.model_validate_json(row["scores_json"]),
            judge_model=row["judge_model"],
            judge_cost_cny=row["judge_cost_cny"],
            judge_latency_ms=row["judge_latency_ms"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
        )

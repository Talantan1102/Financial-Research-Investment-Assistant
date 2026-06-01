"""EvalRecorder — PG-backed eval_results writer.

PR-B 2026-05-17:从 sqlite3 raw API 迁到 SQLAlchemy ORM + PG。EvalResult
Pydantic contract 保留,ORM 中间层做 EvalResult ↔ EvalResultRow 转换。

v1.x DD Report Eval Phase 1+2 扩展(PR-B ORM migration):
  - EvalResultRow 加 5 个新 column (backtest_run_id / cut_off_date / evaluator_llm /
    case_type / metric_scores_json)
  - 新增 BacktestRunRow + write_backtest_run() — 替代 backtest_runner.py 的
    原 sqlite3 _write_run_row()

Shares the PG instance with TraceService (different tables, same SessionLocal)
so a single SQL JOIN on request_id retrieves "this case scored X, here's the
trace that produced it" per spec § 9 — same contract as legacy sqlite era,
just on real PG now.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

from sqlalchemy.orm import Session

from app.services.eval_models import BacktestRun, EvalResult, JudgeScores
from app.services.trace_models import BacktestRunRow, EvalResultRow

# Whitelist allowed filter keys — 防 SQL injection
_ALLOWED_FILTER_KEYS: frozenset[str] = frozenset(
    {
        "eval_id",
        "request_id",
        "case_id",
        "judge_model",
        "backtest_run_id",
        "case_type",
    }
)


class EvalRecorder:
    """SQLAlchemy ORM persistence for EvalResult rows."""

    def __init__(self, session_factory: Callable[[], AbstractContextManager[Session]]) -> None:
        self._session_factory = session_factory

    def write(self, result: EvalResult) -> None:
        with self._session_factory() as session:
            existing = session.get(EvalResultRow, result.eval_id)
            if existing is not None:
                existing.request_id = result.request_id  # type: ignore[assignment]
                existing.case_id = result.case_id  # type: ignore[assignment]
                existing.scores_json = result.scores.model_dump()  # type: ignore[assignment]
                existing.judge_model = result.judge_model  # type: ignore[assignment]
                existing.judge_cost_cny = result.judge_cost_cny  # type: ignore[assignment]
                existing.judge_latency_ms = result.judge_latency_ms  # type: ignore[assignment]
                existing.timestamp = result.timestamp  # type: ignore[assignment]
                existing.backtest_run_id = result.backtest_run_id  # type: ignore[assignment]
                existing.cut_off_date = result.cut_off_date  # type: ignore[assignment]
                existing.evaluator_llm = result.evaluator_llm  # type: ignore[assignment]
                existing.case_type = result.case_type  # type: ignore[assignment]
                existing.metric_scores_json = result.metric_scores_json  # type: ignore[assignment]
            else:
                row = EvalResultRow(
                    eval_id=result.eval_id,
                    request_id=result.request_id,
                    case_id=result.case_id,
                    scores_json=result.scores.model_dump(),
                    judge_model=result.judge_model,
                    judge_cost_cny=result.judge_cost_cny,
                    judge_latency_ms=result.judge_latency_ms,
                    timestamp=result.timestamp,
                    backtest_run_id=result.backtest_run_id,
                    cut_off_date=result.cut_off_date,
                    evaluator_llm=result.evaluator_llm,
                    case_type=result.case_type,
                    metric_scores_json=result.metric_scores_json,
                )
                session.add(row)
            session.commit()

    def write_backtest_run(self, run: BacktestRun) -> None:
        """Write a BacktestRun record to the backtest_runs table via ORM."""
        with self._session_factory() as session:
            existing = session.get(BacktestRunRow, run.run_id)
            if existing is not None:
                existing.created_at = run.created_at  # type: ignore[assignment]
                existing.case_count = run.case_count  # type: ignore[assignment]
                existing.metric_summary_json = run.metric_summary_json  # type: ignore[assignment]
                existing.status = run.status  # type: ignore[assignment]
                existing.git_sha = run.git_sha  # type: ignore[assignment]
                existing.ablation_variant = run.ablation_variant  # type: ignore[assignment]
                existing.llm_model = run.llm_model  # type: ignore[assignment]
            else:
                row = BacktestRunRow(
                    run_id=run.run_id,
                    created_at=run.created_at,
                    case_count=run.case_count,
                    metric_summary_json=run.metric_summary_json,
                    status=run.status,
                    git_sha=run.git_sha,
                    ablation_variant=run.ablation_variant,
                    llm_model=run.llm_model,
                )
                session.add(row)
            session.commit()

    def read(self, eval_id: str) -> EvalResult:
        with self._session_factory() as session:
            row = session.get(EvalResultRow, eval_id)
            # C11: None-check + DTO conversion INSIDE the session block — row detaches
            # on `with` exit (expire_on_commit), so reads must happen while attached.
            if row is None:
                raise LookupError(f"no eval_result with eval_id={eval_id!r}")
            return self._row_to_result(row)

    def query(self, filters: dict[str, Any]) -> list[EvalResult]:
        """Query eval_results by ORM-whitelisted filter keys."""
        unknown = set(filters) - _ALLOWED_FILTER_KEYS
        if unknown:
            raise ValueError(
                f"unknown filter keys: {sorted(unknown)} (allowed: {sorted(_ALLOWED_FILTER_KEYS)})"
            )
        with self._session_factory() as session:
            stmt = session.query(EvalResultRow)
            for k, v in filters.items():
                stmt = stmt.filter(getattr(EvalResultRow, k) == v)
            rows = stmt.all()
            # C11: convert INSIDE the session block (rows detach on `with` exit).
            return [self._row_to_result(r) for r in rows]

    @staticmethod
    def _row_to_result(row: EvalResultRow) -> EvalResult:
        return EvalResult(
            eval_id=row.eval_id,  # type: ignore[arg-type]
            request_id=row.request_id,  # type: ignore[arg-type]
            case_id=row.case_id,  # type: ignore[arg-type]
            scores=JudgeScores.model_validate(row.scores_json),
            judge_model=row.judge_model,  # type: ignore[arg-type]
            judge_cost_cny=row.judge_cost_cny,  # type: ignore[arg-type]
            judge_latency_ms=row.judge_latency_ms,  # type: ignore[arg-type]
            timestamp=row.timestamp,  # type: ignore[arg-type]
            backtest_run_id=row.backtest_run_id,  # type: ignore[arg-type]
            cut_off_date=row.cut_off_date,  # type: ignore[arg-type]
            evaluator_llm=row.evaluator_llm,  # type: ignore[arg-type]
            case_type=row.case_type,  # type: ignore[arg-type]
            metric_scores_json=row.metric_scores_json,  # type: ignore[arg-type]
        )

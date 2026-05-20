"""EvalRecorder — PG-backed eval_results writer.

PR-B 2026-05-17:从 sqlite3 raw API 迁到 SQLAlchemy ORM + PG。EvalResult
Pydantic contract 保留,ORM 中间层做 EvalResult ↔ EvalResultRow 转换。

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

from app.services.eval_models import EvalResult, JudgeScores
from app.services.trace_models import EvalResultRow

# Whitelist allowed filter keys — 防 SQL injection
_ALLOWED_FILTER_KEYS: frozenset[str] = frozenset(
    {
        "eval_id",
        "request_id",
        "case_id",
        "judge_model",
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
                )
                session.add(row)
            session.commit()

    def read(self, eval_id: str) -> EvalResult:
        with self._session_factory() as session:
            row = session.get(EvalResultRow, eval_id)
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
        )

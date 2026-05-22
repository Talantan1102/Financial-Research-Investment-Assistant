"""TraceService — PG-backed span persistence + query.

PR-B 2026-05-17:从 sqlite3 raw API 迁到 SQLAlchemy ORM + PG。Span Pydantic
contract 保留(spec § 9),ORM 中间层做 Span ↔ TraceSpanRow 转换。

CodeRabbit P1 (主题 4 critical) 修复:query_spans 的 filter dict 旧版直接拼
SQL → SQL injection。新版用 SQLAlchemy whitelisted ORM column filter,
拒绝任意未声明 key。
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

from sqlalchemy.orm import Session

from app.services.trace_models import Span, TraceSpanRow, TraceTree

# Whitelist allowed filter keys — 防 SQL injection(CodeRabbit critical 主题 4)
_ALLOWED_FILTER_KEYS: frozenset[str] = frozenset(
    {
        "span_id",
        "request_id",
        "parent_id",
        "name",
        "error",
    }
)


class TraceService:
    """SQLAlchemy ORM persistence for Span rows.

    Construction:
        TraceService(session_factory)  # session_factory: () -> CM[Session]

    `session_factory` 生产环境通常是 `SessionLocal`(Session 本身是 CM),
    测试环境是 `lambda: contextlib.nullcontext(db_session)`(复用 outer fixture
    的 transaction-rollback 隔离,不让 with-block 退出时 close)。
    """

    def __init__(self, session_factory: Callable[[], AbstractContextManager[Session]]) -> None:
        self._session_factory = session_factory

    def write_span(self, span: Span) -> None:
        with self._session_factory() as session:
            # UPSERT — span_id 是 PK
            existing = session.get(TraceSpanRow, span.span_id)
            if existing is not None:
                existing.request_id = span.request_id  # type: ignore[assignment]
                existing.parent_id = span.parent_id  # type: ignore[assignment]
                existing.name = span.name  # type: ignore[assignment]
                existing.inputs = span.inputs  # type: ignore[assignment]
                existing.outputs = span.outputs  # type: ignore[assignment]
                existing.attrs_json = span.metadata  # type: ignore[assignment]
                existing.started_at = span.started_at  # type: ignore[assignment]
                existing.ended_at = span.ended_at  # type: ignore[assignment]
                existing.error = span.error  # type: ignore[assignment]
            else:
                row = TraceSpanRow(
                    span_id=span.span_id,
                    request_id=span.request_id,
                    parent_id=span.parent_id,
                    name=span.name,
                    inputs=span.inputs,
                    outputs=span.outputs,
                    attrs_json=span.metadata,
                    started_at=span.started_at,
                    ended_at=span.ended_at,
                    error=span.error,
                )
                session.add(row)
            session.commit()

    def get_trace(self, request_id: str) -> TraceTree:
        spans = self.query_spans({"request_id": request_id})
        if not spans:
            raise LookupError(f"no spans for request_id={request_id!r}")
        return TraceTree.from_spans(spans)

    def query_spans(self, filters: dict[str, Any]) -> list[Span]:
        """Query spans by ORM-whitelisted filter keys.

        Unrecognized filter keys → ValueError(不进 SQL,防 SQL injection)。
        """
        unknown = set(filters) - _ALLOWED_FILTER_KEYS
        if unknown:
            raise ValueError(
                f"unknown filter keys: {sorted(unknown)} (allowed: {sorted(_ALLOWED_FILTER_KEYS)})"
            )
        with self._session_factory() as session:
            stmt = session.query(TraceSpanRow)
            for k, v in filters.items():
                stmt = stmt.filter(getattr(TraceSpanRow, k) == v)
            rows = stmt.all()
        return [self._row_to_span(r) for r in rows]

    @staticmethod
    def _row_to_span(row: TraceSpanRow) -> Span:
        return Span(
            span_id=row.span_id,  # type: ignore[arg-type]
            request_id=row.request_id,  # type: ignore[arg-type]
            parent_id=row.parent_id,  # type: ignore[arg-type]
            name=row.name,  # type: ignore[arg-type]
            inputs=dict(row.inputs) if row.inputs else {},
            outputs=dict(row.outputs) if row.outputs else {},
            metadata=dict(row.attrs_json) if row.attrs_json else {},
            started_at=row.started_at,  # type: ignore[arg-type]
            ended_at=row.ended_at,  # type: ignore[arg-type]
            error=row.error,  # type: ignore[arg-type]
        )

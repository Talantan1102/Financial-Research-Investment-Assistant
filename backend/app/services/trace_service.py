"""TraceService — SQLite-backed span persistence + query.

Schema lives in code (`init_schema`); the .sqlite file is .gitignored and
recreated per test (via tmp_eval_db fixture) or per app start.

Decoupled from EvalRecorder by sharing only the file path — they each own
their own table and can be instantiated independently.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from app.services.trace_models import Span, TraceTree

_SPANS_SCHEMA = """
CREATE TABLE IF NOT EXISTS spans (
    span_id     TEXT PRIMARY KEY,
    request_id  TEXT NOT NULL,
    parent_id   TEXT,
    name        TEXT NOT NULL,
    inputs      TEXT NOT NULL,
    outputs     TEXT NOT NULL,
    metadata    TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    ended_at    TEXT NOT NULL,
    error       TEXT
);
CREATE INDEX IF NOT EXISTS idx_spans_request ON spans(request_id);
CREATE INDEX IF NOT EXISTS idx_spans_name    ON spans(name);
"""


class TraceService:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    def init_schema(self) -> None:
        with sqlite3.connect(self._db_path) as con:
            con.executescript(_SPANS_SCHEMA)

    def write_span(self, span: Span) -> None:
        with sqlite3.connect(self._db_path) as con:
            con.execute(
                "INSERT OR REPLACE INTO spans VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    span.span_id,
                    span.request_id,
                    span.parent_id,
                    span.name,
                    json.dumps(span.inputs, default=str),
                    json.dumps(span.outputs, default=str),
                    json.dumps(span.metadata, default=str),
                    span.started_at.isoformat(),
                    span.ended_at.isoformat(),
                    span.error,
                ),
            )

    def get_trace(self, request_id: str) -> TraceTree:
        spans = self.query_spans({"request_id": request_id})
        if not spans:
            raise LookupError(f"no spans for request_id={request_id!r}")
        return TraceTree.from_spans(spans)

    def query_spans(self, filters: dict[str, Any]) -> list[Span]:
        if not filters:
            sql = "SELECT * FROM spans"
            params: tuple[Any, ...] = ()
        else:
            clauses = " AND ".join(f"{k} = ?" for k in filters)
            sql = f"SELECT * FROM spans WHERE {clauses}"
            params = tuple(filters.values())
        with sqlite3.connect(self._db_path) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(sql, params).fetchall()
        return [self._row_to_span(r) for r in rows]

    @staticmethod
    def _row_to_span(row: sqlite3.Row) -> Span:
        return Span(
            span_id=row["span_id"],
            request_id=row["request_id"],
            parent_id=row["parent_id"],
            name=row["name"],
            inputs=json.loads(row["inputs"]),
            outputs=json.loads(row["outputs"]),
            metadata=json.loads(row["metadata"]),
            started_at=datetime.fromisoformat(row["started_at"]),
            ended_at=datetime.fromisoformat(row["ended_at"]),
            error=row["error"],
        )

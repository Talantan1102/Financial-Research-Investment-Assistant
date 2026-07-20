"""Idempotently add trace indexes required by paper-trading analytics."""

from sqlalchemy import text
from sqlalchemy.engine import Engine


def reconcile_trace_span_indexes(engine: Engine) -> None:
    with engine.begin() as connection:
        table_exists = connection.scalar(
            text("SELECT to_regclass(current_schema() || '.trace_spans') IS NOT NULL")
        )
        if not table_exists:
            return
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_trace_spans_name_started_at "
                "ON trace_spans (name, started_at)"
            )
        )

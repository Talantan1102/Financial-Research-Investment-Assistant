from __future__ import annotations

import uuid

from app.scripts.reconcile_trace_span_indexes import reconcile_trace_span_indexes
from sqlalchemy import Engine, create_engine, text


def test_legacy_trace_table_gets_composite_analytics_index_idempotently(
    pg_test_engine: Engine,
) -> None:
    schema = f"trace_index_{uuid.uuid4().hex}"
    with pg_test_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped = create_engine(
        pg_test_engine.url,
        connect_args={"options": f"-csearch_path={schema}"},
        future=True,
    )
    try:
        with scoped.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE trace_spans ("
                    "span_id VARCHAR(64) PRIMARY KEY, name VARCHAR(128) NOT NULL, "
                    "started_at TIMESTAMPTZ NOT NULL)"
                )
            )

        reconcile_trace_span_indexes(scoped)
        reconcile_trace_span_indexes(scoped)

        with scoped.connect() as connection:
            indexes = dict(
                connection.execute(
                    text(
                        "SELECT indexname, indexdef FROM pg_indexes "
                        "WHERE schemaname=current_schema() AND tablename='trace_spans'"
                    )
                ).all()
            )
        assert "idx_trace_spans_name_started_at" in indexes
        assert "(name, started_at)" in indexes["idx_trace_spans_name_started_at"]
    finally:
        scoped.dispose()
        with pg_test_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))

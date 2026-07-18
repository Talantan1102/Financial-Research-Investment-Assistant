"""Idempotent Phase 2 -> Phase 3 execution-facts schema upgrade."""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

import app.models  # noqa: F401 - register the complete metadata graph
from app.models.run_execution import RunToolExecution, RunUsageRecord


def migrate_phase3_execution_schema(engine: Engine) -> tuple[str, ...]:
    """Add Phase 3 execution facts in one serialized PostgreSQL transaction."""
    changes: list[str] = []
    with engine.begin() as connection:
        connection.execute(
            text(
                "SELECT pg_advisory_xact_lock("
                "hashtextextended('phase3_execution_schema_upgrade', 0))"
            )
        )
        existing_tables = set(inspect(connection).get_table_names())
        if "run_sessions" not in existing_tables:
            return ()

        required_tables = {"runs", "run_attempts"}
        missing_dependencies = required_tables - existing_tables
        if missing_dependencies:
            missing = ", ".join(sorted(missing_dependencies))
            raise RuntimeError(f"Phase 3 schema dependencies are missing: {missing}")

        session_columns = {
            column["name"] for column in inspect(connection).get_columns("run_sessions")
        }
        if "archived_at" not in session_columns:
            connection.execute(
                text("ALTER TABLE run_sessions ADD COLUMN archived_at timestamp without time zone")
            )
            changes.append("add run_sessions.archived_at")

        session_indexes = {
            index["name"] for index in inspect(connection).get_indexes("run_sessions")
        }
        if "ix_run_sessions_archived_at" not in session_indexes:
            connection.execute(
                text("CREATE INDEX ix_run_sessions_archived_at ON run_sessions (archived_at)")
            )
            changes.append("add ix_run_sessions_archived_at")

        existing_tables = set(inspect(connection).get_table_names())
        if "run_tool_executions" not in existing_tables:
            RunToolExecution.__table__.create(bind=connection)
            changes.append("create run_tool_executions")
        if "run_usage_records" not in existing_tables:
            RunUsageRecord.__table__.create(bind=connection)
            changes.append("create run_usage_records")

    return tuple(changes)


if __name__ == "__main__":
    from app.core.database import engine

    print(migrate_phase3_execution_schema(engine))

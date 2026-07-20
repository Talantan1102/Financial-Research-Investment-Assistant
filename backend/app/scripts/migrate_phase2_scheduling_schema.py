"""Idempotent Phase 1 -> Phase 2 scheduling schema upgrade."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DataError

import app.models  # noqa: F401 - register the complete metadata graph
from app.models.run_scheduling import RunWorker


class InvalidLegacyWorkerIdError(ValueError):
    """Raised before DDL when a legacy worker id cannot be converted to UUID."""


@contextmanager
def _migration_connection(bind: Engine | Connection) -> Iterator[Connection]:
    if isinstance(bind, Connection):
        yield bind
    else:
        with bind.begin() as connection:
            yield connection


def migrate_phase2_scheduling_schema(engine: Engine | Connection) -> tuple[str, ...]:
    """Upgrade Phase 1 run-attempt storage in one PostgreSQL transaction."""
    changes: list[str] = []
    with _migration_connection(engine) as connection:
        connection.execute(
            text(
                "SELECT pg_advisory_xact_lock("
                "hashtextextended('phase2_scheduling_schema_upgrade', 0))"
            )
        )
        existing_tables = set(inspect(connection).get_table_names())
        if "run_workers" not in existing_tables:
            RunWorker.__table__.create(bind=connection)
            changes.append("create run_workers")

        if "run_attempts" not in existing_tables:
            return tuple(changes)

        _upgrade_run_attempts(connection, changes)
    return tuple(changes)


def _upgrade_run_attempts(connection: Connection, changes: list[str]) -> None:
    inspector = inspect(connection)
    columns = {column["name"]: column for column in inspector.get_columns("run_attempts")}
    worker_type = columns["worker_id"]["type"].python_type

    if worker_type is str:
        legacy_worker_ids = connection.execute(
            text("SELECT worker_id FROM run_attempts WHERE NULLIF(worker_id, '') IS NOT NULL")
        ).scalars()
        for legacy_worker_id in legacy_worker_ids:
            try:
                with connection.begin_nested():
                    connection.execute(
                        text("SELECT CAST(:worker_id AS uuid)"),
                        {"worker_id": legacy_worker_id},
                    )
            except DataError as exc:
                raise InvalidLegacyWorkerIdError(
                    f"legacy run_attempts.worker_id is not a UUID: {legacy_worker_id}"
                ) from exc
        connection.execute(
            text(
                "ALTER TABLE run_attempts ALTER COLUMN worker_id TYPE uuid "
                "USING NULLIF(worker_id, '')::uuid"
            )
        )
        changes.append("alter run_attempts.worker_id uuid")

    backfilled = connection.execute(
        text(
            "INSERT INTO run_workers "
            "(id, worker_type, capacity, status, heartbeat_at, started_at, metadata) "
            "SELECT DISTINCT worker_id, 'chat', 1, 'offline', "
            "CURRENT_TIMESTAMP AT TIME ZONE 'UTC', "
            "CURRENT_TIMESTAMP AT TIME ZONE 'UTC', "
            '\'{"migrated_from": "phase1"}\'::jsonb '
            "FROM run_attempts WHERE worker_id IS NOT NULL "
            "ON CONFLICT (id) DO NOTHING"
        )
    ).rowcount
    if backfilled:
        changes.append(f"backfill {backfilled} legacy run_workers")

    column_ddls = {
        "claim_token": "uuid",
        "claimed_at": "timestamp without time zone",
        "last_heartbeat_at": "timestamp without time zone",
    }
    for name, column_type in column_ddls.items():
        if name not in columns:
            connection.execute(text(f"ALTER TABLE run_attempts ADD COLUMN {name} {column_type}"))
            changes.append(f"add run_attempts.{name}")

    inspector = inspect(connection)
    unique_constraints = inspector.get_unique_constraints("run_attempts")
    if not any(
        constraint["column_names"] == ["run_id", "id", "worker_id"]
        for constraint in unique_constraints
    ):
        connection.execute(
            text(
                "ALTER TABLE run_attempts ADD CONSTRAINT "
                "uq_run_attempt_worker_identity UNIQUE (run_id, id, worker_id)"
            )
        )
        changes.append("add uq_run_attempt_worker_identity")

    foreign_keys = inspect(connection).get_foreign_keys("run_attempts")
    if not any(
        fk["constrained_columns"] == ["worker_id"]
        and fk["referred_table"] == "run_workers"
        and fk["referred_columns"] == ["id"]
        for fk in foreign_keys
    ):
        connection.execute(
            text(
                "ALTER TABLE run_attempts ADD CONSTRAINT fk_run_attempts_worker "
                "FOREIGN KEY (worker_id) REFERENCES run_workers(id) ON DELETE RESTRICT"
            )
        )
        changes.append("add fk_run_attempts_worker")

    indexes = {index["name"] for index in inspect(connection).get_indexes("run_attempts")}
    if "ix_run_attempts_active_worker_lease" not in indexes:
        connection.execute(
            text(
                "CREATE INDEX ix_run_attempts_active_worker_lease ON run_attempts "
                "(worker_id, lease_expires_at) "
                "WHERE worker_id IS NOT NULL AND status IN ('assigned', 'running')"
            )
        )
        changes.append("add ix_run_attempts_active_worker_lease")

    if "ix_run_attempts_active_lease_expiry" not in indexes:
        connection.execute(
            text(
                "CREATE INDEX ix_run_attempts_active_lease_expiry ON run_attempts "
                "(lease_expires_at, id) "
                "WHERE status IN ('assigned', 'running') "
                "AND lease_expires_at IS NOT NULL"
            )
        )
        changes.append("add ix_run_attempts_active_lease_expiry")


if __name__ == "__main__":
    from app.core.database import engine

    print(migrate_phase2_scheduling_schema(engine))

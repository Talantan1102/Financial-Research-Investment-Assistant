from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from app.core.database import Base
from app.models.run import Run, RunMessage, RunSession
from app.models.tenant import Tenant
from app.models.user import User
from app.scripts.migrate_phase2_scheduling_schema import (
    InvalidLegacyWorkerIdError,
    migrate_phase2_scheduling_schema,
)
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session


@pytest.fixture
def isolated_schema_engine(pg_test_engine: Engine) -> Iterator[Engine]:
    schema = f"phase2_upgrade_{uuid.uuid4().hex}"
    with pg_test_engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    isolated = create_engine(
        pg_test_engine.url,
        connect_args={"options": f"-csearch_path={schema} -ctimezone=Asia/Shanghai"},
    )
    Base.metadata.create_all(bind=isolated)
    try:
        yield isolated
    finally:
        isolated.dispose()
        with pg_test_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def _downgrade_to_phase1(engine: Engine) -> None:
    inspector = inspect(engine)
    worker_fks = [
        fk
        for fk in inspector.get_foreign_keys("run_attempts")
        if fk["constrained_columns"] == ["worker_id"]
    ]
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX IF EXISTS ix_run_attempts_active_worker_lease"))
        connection.execute(text("DROP TABLE run_outbox"))
        for fk in worker_fks:
            connection.exec_driver_sql(f'ALTER TABLE run_attempts DROP CONSTRAINT "{fk["name"]}"')
        connection.execute(
            text(
                "ALTER TABLE run_attempts "
                "DROP CONSTRAINT uq_run_attempt_worker_identity, "
                "DROP COLUMN claim_token, "
                "DROP COLUMN claimed_at, "
                "DROP COLUMN last_heartbeat_at, "
                "ALTER COLUMN worker_id TYPE varchar(255) USING worker_id::text"
            )
        )
        connection.execute(text("DROP TABLE run_tenant_scheduling"))
        connection.execute(text("DROP TABLE run_workers"))


def _seed_legacy_worker(engine: Engine, worker_id: str) -> None:
    suffix = uuid.uuid4().hex
    with Session(engine) as session, session.begin():
        user = User(
            username=f"upgrade-{suffix}",
            email=f"upgrade-{suffix}@example.com",
            hashed_password="test-password-hash",
        )
        tenant = Tenant(name="Upgrade tenant", slug=f"upgrade-{suffix}")
        session.add_all([user, tenant])
        session.flush()
        run_session = RunSession(tenant_id=tenant.id, created_by_user_id=user.id)
        session.add(run_session)
        session.flush()
        message = RunMessage(
            tenant_id=tenant.id,
            session_id=run_session.id,
            role="user",
            content="upgrade",
            status="complete",
        )
        session.add(message)
        session.flush()
        run = Run(
            tenant_id=tenant.id,
            session_id=run_session.id,
            created_by_user_id=user.id,
            run_type="chat",
            status="completed",
            idempotency_key=f"upgrade-{suffix}",
            request_hash=uuid.uuid4().hex,
            input_message_id=message.id,
            retry_count=0,
        )
        session.add(run)
        session.flush()
        session.execute(
            text(
                "INSERT INTO run_attempts "
                "(id, run_id, attempt_no, status, worker_id) "
                "VALUES (:id, :run_id, 1, 'assigned', :worker_id)"
            ),
            {"id": uuid.uuid4(), "run_id": run.id, "worker_id": worker_id},
        )


def test_phase1_schema_upgrades_before_full_create_all_and_is_idempotent(
    isolated_schema_engine: Engine,
) -> None:
    _downgrade_to_phase1(isolated_schema_engine)
    legacy_worker_id = uuid.uuid4()
    _seed_legacy_worker(isolated_schema_engine, str(legacy_worker_id))

    changes = migrate_phase2_scheduling_schema(isolated_schema_engine)
    Base.metadata.create_all(bind=isolated_schema_engine)

    inspector = inspect(isolated_schema_engine)
    assert {"run_workers", "run_tenant_scheduling", "run_outbox"} <= set(
        inspector.get_table_names()
    )
    columns = {column["name"]: column for column in inspector.get_columns("run_attempts")}
    assert columns["worker_id"]["type"].python_type is uuid.UUID
    assert {"claim_token", "claimed_at", "last_heartbeat_at"} <= set(columns)
    uniques = {
        constraint["name"] for constraint in inspector.get_unique_constraints("run_attempts")
    }
    assert "uq_run_attempt_worker_identity" in uniques
    indexes = {index["name"]: index for index in inspector.get_indexes("run_attempts")}
    active_index = indexes["ix_run_attempts_active_worker_lease"]
    assert active_index["column_names"] == ["worker_id", "lease_expires_at"]
    predicate = str(active_index["dialect_options"]["postgresql_where"]).lower()
    assert "worker_id is not null" in predicate
    assert "assigned" in predicate and "running" in predicate
    worker_fks = [
        fk
        for fk in inspector.get_foreign_keys("run_attempts")
        if fk["constrained_columns"] == ["worker_id"]
    ]
    assert len(worker_fks) == 1
    assert worker_fks[0]["referred_table"] == "run_workers"
    with isolated_schema_engine.connect() as connection:
        migrated_worker = connection.execute(
            text("SELECT status, heartbeat_at, started_at FROM run_workers WHERE id = :id"),
            {"id": legacy_worker_id},
        ).one()
        utc_now = connection.scalar(text("SELECT CURRENT_TIMESTAMP AT TIME ZONE 'UTC'"))
    assert migrated_worker.status == "offline"
    assert abs(migrated_worker.heartbeat_at - utc_now) < timedelta(seconds=5)
    assert abs(migrated_worker.started_at - utc_now) < timedelta(seconds=5)
    assert changes
    assert migrate_phase2_scheduling_schema(isolated_schema_engine) == ()


def test_invalid_legacy_worker_fails_fast_without_partial_migration(
    isolated_schema_engine: Engine,
) -> None:
    _downgrade_to_phase1(isolated_schema_engine)
    _seed_legacy_worker(isolated_schema_engine, "not-a-uuid")

    with pytest.raises(InvalidLegacyWorkerIdError, match="not-a-uuid"):
        migrate_phase2_scheduling_schema(isolated_schema_engine)

    inspector = inspect(isolated_schema_engine)
    assert "run_workers" not in inspector.get_table_names()
    columns = {column["name"]: column for column in inspector.get_columns("run_attempts")}
    assert columns["worker_id"]["type"].python_type is str
    assert {"claim_token", "claimed_at", "last_heartbeat_at"}.isdisjoint(columns)
    assert "uq_run_attempt_worker_identity" not in {
        constraint["name"] for constraint in inspector.get_unique_constraints("run_attempts")
    }


def test_two_engines_concurrently_upgrade_the_same_phase1_schema(
    isolated_schema_engine: Engine,
) -> None:
    _downgrade_to_phase1(isolated_schema_engine)
    _seed_legacy_worker(isolated_schema_engine, str(uuid.uuid4()))
    with isolated_schema_engine.connect() as connection:
        schema = connection.scalar(text("SELECT current_schema()"))
    second_engine = create_engine(
        isolated_schema_engine.url,
        connect_args={"options": f"-csearch_path={schema} -ctimezone=Asia/Shanghai"},
    )
    barrier = threading.Barrier(2)
    first_statements: dict[Engine, str] = {}

    def synchronize_transactions(_connection: Connection) -> None:
        barrier.wait(timeout=10)

    def capture_first_statement(
        connection: Connection,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        engine = connection.engine
        first_statements.setdefault(engine, statement)

    for candidate in (isolated_schema_engine, second_engine):
        event.listen(candidate, "begin", synchronize_transactions, once=True)
        event.listen(candidate, "before_cursor_execute", capture_first_statement)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(migrate_phase2_scheduling_schema, candidate)
                for candidate in (isolated_schema_engine, second_engine)
            ]
            results = [future.result(timeout=20) for future in futures]
    finally:
        for candidate in (isolated_schema_engine, second_engine):
            event.remove(candidate, "before_cursor_execute", capture_first_statement)
        second_engine.dispose()

    assert all("pg_advisory_xact_lock" in statement for statement in first_statements.values())
    assert len(first_statements) == 2
    assert any(result for result in results)
    Base.metadata.create_all(bind=isolated_schema_engine)
    inspector = inspect(isolated_schema_engine)
    assert {"run_workers", "run_tenant_scheduling", "run_outbox"} <= set(
        inspector.get_table_names()
    )
    columns = {column["name"]: column for column in inspector.get_columns("run_attempts")}
    assert columns["worker_id"]["type"].python_type is uuid.UUID
    assert {"claim_token", "claimed_at", "last_heartbeat_at"} <= set(columns)
    assert "uq_run_attempt_worker_identity" in {
        constraint["name"] for constraint in inspector.get_unique_constraints("run_attempts")
    }
    assert "ix_run_attempts_active_worker_lease" in {
        index["name"] for index in inspector.get_indexes("run_attempts")
    }
    assert any(
        fk["constrained_columns"] == ["worker_id"] and fk["referred_table"] == "run_workers"
        for fk in inspector.get_foreign_keys("run_attempts")
    )


def test_startup_degrades_only_when_postgres_connection_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from app import app_main

    def unavailable(_engine: Engine) -> tuple[str, ...]:
        raise OperationalError("connect", {}, ConnectionError("postgres unavailable"))

    monkeypatch.setattr(app_main, "migrate_phase2_scheduling_schema", unavailable)
    with caplog.at_level(logging.WARNING):
        assert app_main._initialize_postgres_schema() is False
    assert "PostgreSQL unavailable" in caplog.text


def test_startup_logs_and_raises_schema_migration_errors(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from app import app_main

    def incompatible(_engine: Engine) -> tuple[str, ...]:
        raise InvalidLegacyWorkerIdError("legacy bad-worker")

    monkeypatch.setattr(app_main, "migrate_phase2_scheduling_schema", incompatible)
    with (
        caplog.at_level(logging.ERROR),
        pytest.raises(InvalidLegacyWorkerIdError, match="bad-worker"),
    ):
        app_main._initialize_postgres_schema()
    assert "PostgreSQL schema initialization failed" in caplog.text


def test_startup_does_not_degrade_on_connected_postgres_operational_errors(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from app import app_main

    class LockTimeoutError(Exception):
        pgcode = "55P03"

    def locked(_engine: Engine) -> tuple[str, ...]:
        raise OperationalError("ALTER TABLE", {}, LockTimeoutError("lock timeout"))

    monkeypatch.setattr(app_main, "migrate_phase2_scheduling_schema", locked)
    with caplog.at_level(logging.ERROR), pytest.raises(OperationalError):
        app_main._initialize_postgres_schema()
    assert "PostgreSQL schema initialization failed" in caplog.text


def test_startup_degrades_when_postgres_cannot_connect_now(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from app import app_main

    class CannotConnectNowError(Exception):
        pgcode = "57P03"

    def unavailable(_engine: Engine) -> tuple[str, ...]:
        raise OperationalError("connect", {}, CannotConnectNowError("cannot connect now"))

    monkeypatch.setattr(app_main, "migrate_phase2_scheduling_schema", unavailable)
    with caplog.at_level(logging.WARNING):
        assert app_main._initialize_postgres_schema() is False
    assert "PostgreSQL unavailable" in caplog.text

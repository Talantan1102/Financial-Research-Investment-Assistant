from __future__ import annotations

import threading
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest
from app.core.database import Base
from app.models.run import Run, RunMessage, RunSession
from app.models.run_execution import RunUsageRecord
from app.models.tenant import Tenant
from app.models.user import User
from app.scripts.migrate_phase3_execution_schema import (
    is_fresh_application_schema,
    migrate_phase3_execution_schema,
    verify_phase3_execution_schema,
    verify_run_control_schema,
)
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session


@pytest.fixture
def isolated_schema_engine(pg_test_engine: Engine) -> Iterator[Engine]:
    schema = f"phase3_upgrade_{uuid.uuid4().hex}"
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


@pytest.fixture
def empty_schema_engine(pg_test_engine: Engine) -> Iterator[Engine]:
    schema = f"phase3_empty_{uuid.uuid4().hex}"
    with pg_test_engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    isolated = create_engine(
        pg_test_engine.url,
        connect_args={"options": f"-csearch_path={schema} -ctimezone=Asia/Shanghai"},
    )
    try:
        yield isolated
    finally:
        isolated.dispose()
        with pg_test_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def _downgrade_to_phase2(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE run_usage_records"))
        connection.execute(text("DROP TABLE run_tool_executions"))
        connection.execute(text("ALTER TABLE run_sessions DROP COLUMN archived_at"))


def test_revision_sequence_upgrade_backfills_legacy_rows_and_repairs_indexes(
    isolated_schema_engine: Engine,
) -> None:
    with Session(isolated_schema_engine) as session, session.begin():
        user = User(
            username=f"revision-upgrade-{uuid.uuid4().hex}",
            email=f"revision-upgrade-{uuid.uuid4().hex}@example.com",
            hashed_password="hash",
        )
        tenant = Tenant(name="Revision upgrade", slug=f"revision-upgrade-{uuid.uuid4().hex}")
        session.add_all([user, tenant])
        session.flush()
        run_session = RunSession(tenant_id=tenant.id, created_by_user_id=user.id)
        session.add(run_session)
        session.flush()
        messages = [
            RunMessage(
                tenant_id=tenant.id,
                session_id=run_session.id,
                role="user",
                content=f"prompt {index}",
                status="complete",
            )
            for index in range(2)
        ]
        session.add_all(messages)
        session.flush()
        for index, message in enumerate(messages):
            session.add(
                Run(
                    id=uuid.UUID(int=2 - index),
                    tenant_id=tenant.id,
                    session_id=run_session.id,
                    created_by_user_id=user.id,
                    run_type="chat",
                    status="completed",
                    idempotency_key=f"legacy-{index}",
                    request_hash=f"{index:064d}",
                    input_message_id=message.id,
                    retry_count=0,
                    revision_seq=index + 1,
                    created_at=datetime(2026, 7, 20, 12, 0, index),
                )
            )
    with isolated_schema_engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE runs DROP CONSTRAINT uq_runs_tenant_session_revision_seq")
        )
        connection.execute(text("DROP INDEX ix_runs_replaces_run_id"))
        connection.execute(text("ALTER TABLE runs DROP COLUMN revision_seq"))

    changes = migrate_phase3_execution_schema(isolated_schema_engine)
    assert "add and backfill runs.revision_seq" in changes
    inspector = inspect(isolated_schema_engine)
    revision = {column["name"]: column for column in inspector.get_columns("runs")}["revision_seq"]
    assert revision["nullable"] is False
    indexes = {index["name"] for index in inspector.get_indexes("runs")}
    uniques = {item["name"] for item in inspector.get_unique_constraints("runs")}
    assert "uq_runs_tenant_session_revision_seq" in uniques
    assert "ix_runs_replaces_run_id" in indexes
    with isolated_schema_engine.connect() as connection:
        assert connection.execute(
            text("SELECT revision_seq FROM runs ORDER BY revision_seq")
        ).scalars().all() == [1, 2]


def test_revision_sequence_upgrade_repairs_invalid_values_before_unique_constraint(
    isolated_schema_engine: Engine,
) -> None:
    with isolated_schema_engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE runs DROP CONSTRAINT uq_runs_tenant_session_revision_seq")
        )
        connection.execute(text("ALTER TABLE runs ALTER COLUMN revision_seq DROP NOT NULL"))
    with Session(isolated_schema_engine) as session, session.begin():
        suffix = uuid.uuid4().hex
        user = User(
            username=f"revdup-{suffix}",
            email=f"revdup-{suffix}@example.com",
            hashed_password="hash",
        )
        tenant = Tenant(name="Revision duplicate", slug=f"revdup-{suffix}")
        session.add_all([user, tenant])
        session.flush()
        run_session = RunSession(tenant_id=tenant.id, created_by_user_id=user.id)
        session.add(run_session)
        session.flush()
        tenant_id = tenant.id
        run_session_id = run_session.id
        messages = [
            RunMessage(
                tenant_id=tenant.id,
                session_id=run_session.id,
                role="user",
                content=f"prompt {index}",
                status="complete",
            )
            for index in range(4)
        ]
        session.add_all(messages)
        session.flush()
        for index, (message, revision_seq) in enumerate(
            zip(messages, (1, 1, 0, None), strict=True)
        ):
            session.add(
                Run(
                    tenant_id=tenant.id,
                    session_id=run_session.id,
                    created_by_user_id=user.id,
                    run_type="chat",
                    status="completed",
                    idempotency_key=f"duplicate-{index}",
                    request_hash=f"{index:064d}",
                    input_message_id=message.id,
                    retry_count=0,
                    revision_seq=revision_seq,
                    created_at=datetime(2026, 7, 20, 12, 0, index),
                )
            )

    changes = migrate_phase3_execution_schema(isolated_schema_engine)
    assert "repair duplicate runs.revision_seq values" in changes
    assert "add uq_runs_tenant_session_revision_seq" in changes
    with isolated_schema_engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT revision_seq FROM runs "
                "WHERE tenant_id = :tenant_id AND session_id = :session_id "
                "ORDER BY revision_seq"
            ),
            {"tenant_id": tenant_id, "session_id": run_session_id},
        ).scalars().all() == [1, 2, 3, 4]
    revision_column = {
        item["name"]: item for item in inspect(isolated_schema_engine).get_columns("runs")
    }["revision_seq"]
    assert revision_column["nullable"] is False
    assert migrate_phase3_execution_schema(isolated_schema_engine) == ()
    with pytest.raises(IntegrityError), isolated_schema_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE runs SET revision_seq = 1 "
                "WHERE tenant_id = :tenant_id AND session_id = :session_id"
            ),
            {"tenant_id": tenant_id, "session_id": run_session_id},
        )


def test_rolling_startup_gate_fails_without_mutating_an_old_revision_schema(
    isolated_schema_engine: Engine,
) -> None:
    with isolated_schema_engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE runs DROP CONSTRAINT uq_runs_tenant_session_revision_seq")
        )

    with pytest.raises(RuntimeError, match="maintenance migration required"):
        verify_phase3_execution_schema(isolated_schema_engine)

    assert "uq_runs_tenant_session_revision_seq" not in {
        item["name"] for item in inspect(isolated_schema_engine).get_unique_constraints("runs")
    }


def test_operator_migration_obeys_lock_timeout(isolated_schema_engine: Engine) -> None:
    with isolated_schema_engine.begin() as setup:
        setup.execute(text("ALTER TABLE runs DROP CONSTRAINT uq_runs_tenant_session_revision_seq"))
    blocker = isolated_schema_engine.connect()
    transaction = blocker.begin()
    try:
        blocker.execute(text("LOCK TABLE runs IN ACCESS EXCLUSIVE MODE"))
        with pytest.raises(DBAPIError, match="lock timeout"):
            migrate_phase3_execution_schema(
                isolated_schema_engine,
                lock_timeout_ms=100,
                statement_timeout_ms=2_000,
            )
    finally:
        transaction.rollback()
        blocker.close()


def _assert_phase3_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    assert {"run_tool_executions", "run_usage_records"} <= set(inspector.get_table_names())
    session_columns = {column["name"]: column for column in inspector.get_columns("run_sessions")}
    assert session_columns["archived_at"]["nullable"] is True
    assert session_columns["archived_at"]["type"].timezone is False
    session_indexes = {index["name"]: index for index in inspector.get_indexes("run_sessions")}
    assert session_indexes["ix_run_sessions_archived_at"]["column_names"] == ["archived_at"]
    assert any(
        fk["constrained_columns"] == ["run_id", "attempt_id"]
        and fk["referred_table"] == "run_attempts"
        and fk["referred_columns"] == ["run_id", "id"]
        for table in ("run_tool_executions", "run_usage_records")
        for fk in inspect(engine).get_foreign_keys(table)
    )
    tool_columns = {
        column["name"]: column for column in inspector.get_columns("run_tool_executions")
    }
    assert {
        "semantic_key",
        "safe_to_retry",
        "reservation_token",
        "reservation_expires_at",
        "execution_epoch",
    } <= set(tool_columns)
    tool_indexes = {index["name"]: index for index in inspector.get_indexes("run_tool_executions")}
    assert tool_indexes["ix_run_tool_semantic_recovery"]["column_names"] == [
        "run_id",
        "semantic_key",
        "status",
    ]


def _downgrade_to_pre_reservation_fence(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX IF EXISTS ix_run_tool_semantic_recovery"))
        for column in (
            "semantic_key",
            "safe_to_retry",
            "reservation_token",
            "reservation_expires_at",
            "execution_epoch",
        ):
            connection.execute(
                text(f"ALTER TABLE run_tool_executions DROP COLUMN IF EXISTS {column}")
            )


def _check_names(engine: Engine, table: str) -> set[str]:
    return {constraint["name"] for constraint in inspect(engine).get_check_constraints(table)}


def _set_predecessor_attempt_fks(engine: Engine) -> None:
    with engine.begin() as connection:
        for table, constraint in (
            ("run_tool_executions", "ck_run_tool_execution_row_shape"),
            ("run_usage_records", "ck_run_usage_total_consistent"),
            ("run_usage_records", "ck_run_usage_cached_within_input"),
        ):
            connection.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT {constraint}"))
        for table, constraint in (
            ("run_tool_executions", "fk_run_tool_executions_attempt_provenance"),
            ("run_usage_records", "fk_run_usage_records_attempt_provenance"),
        ):
            connection.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT {constraint}"))
            connection.execute(
                text(
                    f"ALTER TABLE {table} ADD CONSTRAINT {constraint} "
                    "FOREIGN KEY (run_id, attempt_id) "
                    "REFERENCES run_attempts (run_id, id) ON DELETE CASCADE"
                )
            )


def _attempt_fk_delete_rule(engine: Engine, table: str) -> str:
    return next(
        fk["options"]["ondelete"]
        for fk in inspect(engine).get_foreign_keys(table)
        if fk["constrained_columns"] == ["run_id", "attempt_id"]
    )


def _execute_check_probe(engine: Engine, statement: str, *, accepted: bool) -> None:
    with engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        if accepted:
            connection.execute(text(statement))
        else:
            with pytest.raises(IntegrityError):
                connection.execute(text(statement))
        transaction.rollback()


def _assert_repaired_check_literal_behavior(engine: Engine, table: str, constraint: str) -> None:
    suffix = uuid.uuid4().hex
    if table == "run_usage_records":
        base = (
            "INSERT INTO run_usage_records "
            "(id, run_id, attempt_id, provider, model, input_tokens, output_tokens, "
            "cached_tokens, total_tokens, cost_cny, created_at) VALUES "
        )
        valid = base + (
            f"('{uuid.uuid4()}', '{uuid.uuid4()}', '{uuid.uuid4()}', 'p', 'm', "
            "10, 5, 3, 15, 0, now())"
        )
        invalid = base + (
            f"('{uuid.uuid4()}', '{uuid.uuid4()}', '{uuid.uuid4()}', 'p', 'm', "
            "10, 5, 3, 16, 0, now())"
        )
    else:
        base = (
            "INSERT INTO run_tool_executions "
            "(id, run_id, attempt_id, tool_call_id, idempotency_key, semantic_key, "
            "tool_name, request_summary, safe_to_retry, status, execution_epoch, "
            "result_summary, error_code, error_message, started_at, finished_at) VALUES "
        )
        valid = base + (
            f"('{uuid.uuid4()}', '{uuid.uuid4()}', '{uuid.uuid4()}', 'call-{suffix}', "
            f"'key-{suffix}', '{uuid.uuid4().hex}', 'tool', '{{}}', false, 'failed', 0, "
            "NULL, 'failed', NULL, now(), now())"
        )
        invalid_status = "unknown" if constraint.endswith("fixed_status") else "completed"
        invalid = base + (
            f"('{uuid.uuid4()}', '{uuid.uuid4()}', '{uuid.uuid4()}', 'bad-{suffix}', "
            f"'bad-key-{suffix}', '{uuid.uuid4().hex}', 'tool', '{{}}', false, "
            f"'{invalid_status}', 0, NULL, NULL, NULL, now(), now())"
        )
    _execute_check_probe(engine, valid, accepted=True)
    _execute_check_probe(engine, invalid, accepted=False)


def test_fresh_schema_is_completed_by_create_all_after_noop_upgrade(
    pg_test_engine: Engine,
) -> None:
    schema = f"phase3_fresh_{uuid.uuid4().hex}"
    with pg_test_engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    isolated = create_engine(
        pg_test_engine.url,
        connect_args={"options": f"-csearch_path={schema} -ctimezone=Asia/Shanghai"},
    )
    try:
        assert migrate_phase3_execution_schema(isolated) == ()
        Base.metadata.create_all(bind=isolated)
        _assert_phase3_schema(isolated)
    finally:
        isolated.dispose()
        with pg_test_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def test_phase2_schema_upgrades_in_dependency_order_and_is_idempotent(
    isolated_schema_engine: Engine,
) -> None:
    _downgrade_to_phase2(isolated_schema_engine)

    assert migrate_phase3_execution_schema(isolated_schema_engine) == (
        "add run_sessions.archived_at",
        "add ix_run_sessions_archived_at",
        "create run_tool_executions",
        "create run_usage_records",
    )
    _assert_phase3_schema(isolated_schema_engine)
    Base.metadata.create_all(bind=isolated_schema_engine)
    assert migrate_phase3_execution_schema(isolated_schema_engine) == ()


def test_pre_reservation_fence_schema_upgrades_and_is_idempotent(
    isolated_schema_engine: Engine,
) -> None:
    _downgrade_to_pre_reservation_fence(isolated_schema_engine)
    ids = {status: uuid.uuid4() for status in ("started", "completed", "failed")}
    with isolated_schema_engine.begin() as connection:
        connection.execute(text("ALTER TABLE run_tool_executions DISABLE TRIGGER ALL"))
        for status, row_id in ids.items():
            result = "'{\"ok\":true}'::jsonb" if status == "completed" else "NULL"
            error = "'failed'" if status == "failed" else "NULL"
            finished = "now()" if status in {"completed", "failed"} else "NULL"
            connection.exec_driver_sql(
                "INSERT INTO run_tool_executions "
                "(id, run_id, attempt_id, tool_call_id, idempotency_key, tool_name, "
                "request_summary, status, result_summary, error_code, error_message, "
                "started_at, finished_at) VALUES "
                f"('{row_id}', '{uuid.uuid4()}', '{uuid.uuid4()}', 'call-{status}', "
                f"'key-{status}', 'tool', '{{\"args\":{{\"status\":\"{status}\"}}}}', "
                f"'{status}', {result}, {error}, NULL, now(), {finished})"
            )

    changes = migrate_phase3_execution_schema(isolated_schema_engine)
    with isolated_schema_engine.begin() as connection:
        connection.execute(text("ALTER TABLE run_tool_executions ENABLE TRIGGER ALL"))

    assert "add run_tool_executions reservation ownership columns" in changes
    _assert_phase3_schema(isolated_schema_engine)
    with isolated_schema_engine.connect() as connection:
        rows = {
            str(row.id): row
            for row in connection.execute(
                text(
                    "SELECT id, status, safe_to_retry, reservation_token, "
                    "reservation_expires_at, execution_epoch, semantic_key "
                    "FROM run_tool_executions"
                )
            )
        }
    assert rows[str(ids["started"])].status == "approval_required"
    assert rows[str(ids["completed"])].status == "completed"
    assert rows[str(ids["failed"])].status == "failed"
    for row in rows.values():
        assert row.safe_to_retry is False
        assert row.reservation_token is None and row.reservation_expires_at is None
        assert row.execution_epoch == 0 and len(row.semantic_key) == 32
    assert migrate_phase3_execution_schema(isolated_schema_engine) == ()


def test_upgrade_repairs_safe_check_and_index_drift(
    isolated_schema_engine: Engine,
) -> None:
    with isolated_schema_engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE run_usage_records DROP CONSTRAINT ck_run_usage_total_consistent")
        )
        connection.execute(text("DROP INDEX ix_run_sessions_archived_at"))
        connection.execute(
            text(
                "CREATE INDEX ix_run_sessions_archived_at "
                "ON run_sessions (created_at) WHERE archived_at IS NOT NULL"
            )
        )

    changes = migrate_phase3_execution_schema(isolated_schema_engine)

    assert "repair ck_run_usage_total_consistent" in changes
    assert "repair ix_run_sessions_archived_at" in changes
    assert "ck_run_usage_total_consistent" in _check_names(
        isolated_schema_engine, "run_usage_records"
    )
    archived_index = {
        index["name"]: index
        for index in inspect(isolated_schema_engine).get_indexes("run_sessions")
    }["ix_run_sessions_archived_at"]
    assert archived_index["column_names"] == ["archived_at"]
    assert archived_index.get("dialect_options", {}).get("postgresql_where") is None
    assert migrate_phase3_execution_schema(isolated_schema_engine) == ()


def test_a47_predecessor_attempt_fks_upgrade_to_restrict_and_second_run_is_noop(
    isolated_schema_engine: Engine,
) -> None:
    _set_predecessor_attempt_fks(isolated_schema_engine)

    changes = migrate_phase3_execution_schema(isolated_schema_engine)

    assert changes.count("upgrade predecessor Attempt FK to RESTRICT") == 2
    for table in ("run_tool_executions", "run_usage_records"):
        assert _attempt_fk_delete_rule(isolated_schema_engine, table) == "RESTRICT"
    assert migrate_phase3_execution_schema(isolated_schema_engine) == ()


def test_two_engines_concurrently_upgrade_a47_predecessor_fks(
    isolated_schema_engine: Engine,
) -> None:
    _set_predecessor_attempt_fks(isolated_schema_engine)
    with isolated_schema_engine.connect() as connection:
        schema = connection.scalar(text("SELECT current_schema()"))
    second_engine = create_engine(
        isolated_schema_engine.url,
        connect_args={"options": f"-csearch_path={schema} -ctimezone=Asia/Shanghai"},
    )
    barrier = threading.Barrier(2)

    def synchronize(_connection: Connection) -> None:
        barrier.wait(timeout=10)

    for candidate in (isolated_schema_engine, second_engine):
        event.listen(candidate, "begin", synchronize, once=True)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = (
                executor.submit(migrate_phase3_execution_schema, isolated_schema_engine),
                executor.submit(migrate_phase3_execution_schema, second_engine),
            )
            results = [future.result(timeout=20) for future in futures]
    finally:
        second_engine.dispose()

    assert sum(bool(result) for result in results) == 1
    assert (
        sum(result.count("upgrade predecessor Attempt FK to RESTRICT") for result in results) == 2
    )


@pytest.mark.parametrize(
    ("table", "constraint", "injected_clause"),
    [
        (
            "run_tool_executions",
            "ck_run_tool_executions_fixed_status",
            "status IN ('started', 'completed', 'failed', 'approval_required') OR true",
        ),
        (
            "run_tool_executions",
            "ck_run_tool_executions_fixed_status",
            "status IN ('started', 'completed', 'failed', 'approval_required') "
            "AND status <> 'failed'",
        ),
        (
            "run_tool_executions",
            "ck_run_tool_execution_row_shape",
            "status IN ('started', 'completed', 'failed', 'approval_required') OR true",
        ),
        (
            "run_usage_records",
            "ck_run_usage_total_consistent",
            "total_tokens = input_tokens + output_tokens OR true",
        ),
    ],
)
def test_known_check_boolean_drift_is_repaired_from_full_canonical_expression(
    isolated_schema_engine: Engine,
    table: str,
    constraint: str,
    injected_clause: str,
) -> None:
    with isolated_schema_engine.begin() as connection:
        connection.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT {constraint}"))
        connection.execute(
            text(f"ALTER TABLE {table} ADD CONSTRAINT {constraint} CHECK ({injected_clause})")
        )

    assert f"repair {constraint}" in migrate_phase3_execution_schema(isolated_schema_engine)
    assert migrate_phase3_execution_schema(isolated_schema_engine) == ()
    _assert_repaired_check_literal_behavior(isolated_schema_engine, table, constraint)


def test_unknown_check_is_dangerous_and_rolls_back_planned_safe_repair(
    isolated_schema_engine: Engine,
) -> None:
    with isolated_schema_engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE run_usage_records DROP CONSTRAINT ck_run_usage_total_consistent")
        )
        connection.execute(
            text(
                "ALTER TABLE run_usage_records ADD CONSTRAINT custom_cost_cap "
                "CHECK (cost_cny <= 1000)"
            )
        )

    with pytest.raises(RuntimeError, match="unsafe Phase 3 schema drift"):
        migrate_phase3_execution_schema(isolated_schema_engine)

    checks = _check_names(isolated_schema_engine, "run_usage_records")
    assert "custom_cost_cap" in checks
    assert "ck_run_usage_total_consistent" not in checks


def test_predecessor_fk_upgrade_rolls_back_with_earlier_repairs_on_dangerous_drift(
    isolated_schema_engine: Engine,
) -> None:
    _set_predecessor_attempt_fks(isolated_schema_engine)
    with isolated_schema_engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE run_usage_records ALTER COLUMN provider DROP NOT NULL")
        )

    with pytest.raises(RuntimeError, match="unsafe Phase 3 schema drift"):
        migrate_phase3_execution_schema(isolated_schema_engine)

    assert "ck_run_usage_total_consistent" not in _check_names(
        isolated_schema_engine, "run_usage_records"
    )
    for table in ("run_tool_executions", "run_usage_records"):
        assert _attempt_fk_delete_rule(isolated_schema_engine, table) == "CASCADE"


@pytest.mark.parametrize("dangerous_drift", ["column", "foreign_key", "unique"])
def test_dangerous_execution_table_drift_fails_and_rolls_back_safe_repairs(
    isolated_schema_engine: Engine,
    dangerous_drift: str,
) -> None:
    with isolated_schema_engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE run_usage_records DROP CONSTRAINT ck_run_usage_total_consistent")
        )
        connection.execute(text("DROP INDEX ix_run_sessions_archived_at"))
        connection.execute(
            text("CREATE INDEX ix_run_sessions_archived_at ON run_sessions (created_at)")
        )
        if dangerous_drift == "column":
            connection.execute(
                text("ALTER TABLE run_usage_records ALTER COLUMN provider DROP NOT NULL")
            )
        elif dangerous_drift == "foreign_key":
            connection.execute(
                text(
                    "ALTER TABLE run_usage_records "
                    "DROP CONSTRAINT fk_run_usage_records_attempt_provenance"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE run_usage_records ADD CONSTRAINT "
                    "fk_run_usage_records_attempt_provenance "
                    "FOREIGN KEY (attempt_id) "
                    "REFERENCES run_attempts (id) ON DELETE CASCADE"
                )
            )
        else:
            connection.execute(
                text("ALTER TABLE run_tool_executions DROP CONSTRAINT uq_run_tool_idempotency")
            )
            connection.execute(
                text(
                    "ALTER TABLE run_tool_executions ADD CONSTRAINT "
                    "uq_run_tool_idempotency UNIQUE (run_id, tool_call_id)"
                )
            )

    with pytest.raises(RuntimeError, match="unsafe Phase 3 schema drift"):
        migrate_phase3_execution_schema(isolated_schema_engine)

    # Safe repairs happened first inside the same transaction and must be rolled back.
    assert "ck_run_usage_total_consistent" not in _check_names(
        isolated_schema_engine, "run_usage_records"
    )
    archived_index = {
        index["name"]: index
        for index in inspect(isolated_schema_engine).get_indexes("run_sessions")
    }["ix_run_sessions_archived_at"]
    assert archived_index["column_names"] == ["created_at"]


def test_phase3_upgrade_rolls_back_every_change_on_ddl_failure(
    isolated_schema_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _downgrade_to_phase2(isolated_schema_engine)

    def fail_create(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("injected usage DDL failure")

    monkeypatch.setattr(RunUsageRecord.__table__, "create", fail_create)
    with pytest.raises(RuntimeError, match="injected usage DDL failure"):
        migrate_phase3_execution_schema(isolated_schema_engine)

    inspector = inspect(isolated_schema_engine)
    assert "archived_at" not in {column["name"] for column in inspector.get_columns("run_sessions")}
    assert {"run_tool_executions", "run_usage_records"}.isdisjoint(inspector.get_table_names())


def test_two_engines_concurrently_upgrade_the_same_phase2_schema(
    isolated_schema_engine: Engine,
) -> None:
    _downgrade_to_phase2(isolated_schema_engine)
    with isolated_schema_engine.connect() as connection:
        schema = connection.scalar(text("SELECT current_schema()"))
    second_engine = create_engine(
        isolated_schema_engine.url,
        connect_args={"options": f"-csearch_path={schema} -ctimezone=Asia/Shanghai"},
    )
    barrier = threading.Barrier(2)
    statements: dict[Engine, list[str]] = {}

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
        statements.setdefault(connection.engine, []).append(statement)

    for candidate in (isolated_schema_engine, second_engine):
        event.listen(candidate, "begin", synchronize_transactions, once=True)
        event.listen(candidate, "before_cursor_execute", capture_first_statement)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(migrate_phase3_execution_schema, candidate)
                for candidate in (isolated_schema_engine, second_engine)
            ]
            results = [future.result(timeout=20) for future in futures]
    finally:
        for candidate in (isolated_schema_engine, second_engine):
            event.remove(candidate, "before_cursor_execute", capture_first_statement)
        second_engine.dispose()

    assert len(statements) == 2
    assert all("set_config('lock_timeout'" in sql[0] for sql in statements.values())
    assert all("set_config('statement_timeout'" in sql[1] for sql in statements.values())
    assert all("pg_advisory_xact_lock" in sql[2] for sql in statements.values())
    assert sum(bool(result) for result in results) == 1
    _assert_phase3_schema(isolated_schema_engine)


def _ddl_statements(engine: Engine) -> tuple[list[str], object]:
    statements: list[str] = []

    def capture_ddl(
        _connection: Connection,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        normalized = statement.lstrip().upper()
        if normalized.startswith(("CREATE ", "ALTER ", "DROP ", "TRUNCATE ")):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture_ddl)
    return statements, capture_ddl


def test_existing_phase2_database_fails_startup_before_create_all_can_fill_phase3_tables(
    isolated_schema_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import app_main

    _downgrade_to_phase2(isolated_schema_engine)
    before = set(inspect(isolated_schema_engine).get_table_names())
    statements, listener = _ddl_statements(isolated_schema_engine)
    monkeypatch.setattr(app_main, "engine", isolated_schema_engine)
    try:
        with pytest.raises(RuntimeError, match="maintenance migration required"):
            app_main._initialize_postgres_schema()
    finally:
        event.remove(isolated_schema_engine, "before_cursor_execute", listener)

    after = set(inspect(isolated_schema_engine).get_table_names())
    assert before == after
    assert {"run_tool_executions", "run_usage_records"}.isdisjoint(after)
    assert statements == []


def test_existing_execution_column_drift_fails_startup_without_ddl(
    isolated_schema_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import app_main

    with isolated_schema_engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE run_usage_records ALTER COLUMN provider DROP NOT NULL")
        )
    statements, listener = _ddl_statements(isolated_schema_engine)
    monkeypatch.setattr(app_main, "engine", isolated_schema_engine)
    try:
        with pytest.raises(RuntimeError, match=r"run_usage_records\.provider.*nullability"):
            app_main._initialize_postgres_schema()
    finally:
        event.remove(isolated_schema_engine, "before_cursor_execute", listener)

    provider = {
        column["name"]: column
        for column in inspect(isolated_schema_engine).get_columns("run_usage_records")
    }["provider"]
    assert provider["nullable"] is True
    assert statements == []


def test_fresh_database_startup_creates_and_verifies_complete_contract(
    empty_schema_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import app_main

    assert is_fresh_application_schema(empty_schema_engine) is True
    monkeypatch.setattr(app_main, "engine", empty_schema_engine)

    assert app_main._initialize_postgres_schema() is True
    assert is_fresh_application_schema(empty_schema_engine) is False
    verify_phase3_execution_schema(empty_schema_engine)


def test_existing_compatible_database_startup_is_read_only(
    isolated_schema_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import app_main

    statements, listener = _ddl_statements(isolated_schema_engine)
    monkeypatch.setattr(app_main, "engine", isolated_schema_engine)
    try:
        assert app_main._initialize_postgres_schema() is True
    finally:
        event.remove(isolated_schema_engine, "before_cursor_execute", listener)

    assert statements == []


@pytest.mark.parametrize(
    "ddl, expected",
    [
        ("DROP TABLE run_workers CASCADE", "run_workers"),
        ("ALTER TABLE run_attempts DROP COLUMN claim_token", "run_attempts"),
        (
            "DROP INDEX ix_run_attempts_active_worker_lease",
            "run_attempts",
        ),
    ],
)
def test_existing_phase2_drift_fails_startup_before_any_ddl(
    isolated_schema_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    ddl: str,
    expected: str,
) -> None:
    from app import app_main

    with isolated_schema_engine.begin() as connection:
        connection.execute(text(ddl))
    before = set(inspect(isolated_schema_engine).get_table_names())
    statements, listener = _ddl_statements(isolated_schema_engine)
    monkeypatch.setattr(app_main, "engine", isolated_schema_engine)
    assert not hasattr(app_main, "migrate_phase2_scheduling_schema")
    try:
        with pytest.raises(RuntimeError, match=expected):
            app_main._initialize_postgres_schema()
    finally:
        event.remove(isolated_schema_engine, "before_cursor_execute", listener)

    assert set(inspect(isolated_schema_engine).get_table_names()) == before
    assert statements == []


def test_existing_phase2_fk_drift_fails_startup_before_any_ddl(
    isolated_schema_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import app_main

    worker_fk = next(
        fk
        for fk in inspect(isolated_schema_engine).get_foreign_keys("run_attempts")
        if fk["constrained_columns"] == ["worker_id"]
    )
    with isolated_schema_engine.begin() as connection:
        connection.exec_driver_sql(
            f'ALTER TABLE run_attempts DROP CONSTRAINT "{worker_fk["name"]}"'
        )
    statements, listener = _ddl_statements(isolated_schema_engine)
    monkeypatch.setattr(app_main, "engine", isolated_schema_engine)
    try:
        with pytest.raises(RuntimeError, match="run_attempts foreign keys"):
            app_main._initialize_postgres_schema()
    finally:
        event.remove(isolated_schema_engine, "before_cursor_execute", listener)
    assert statements == []


def test_two_web_instances_serialize_fresh_schema_initialization(
    empty_schema_engine: Engine,
) -> None:
    from app import app_main

    with empty_schema_engine.connect() as connection:
        schema = connection.scalar(text("SELECT current_schema()"))
    second_engine = create_engine(
        empty_schema_engine.url,
        connect_args={"options": f"-csearch_path={schema} -ctimezone=Asia/Shanghai"},
    )
    barrier = threading.Barrier(2)

    def start(candidate: Engine) -> bool:
        barrier.wait(timeout=10)
        return app_main._initialize_postgres_schema(candidate)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(start, (empty_schema_engine, second_engine), timeout=30))
    finally:
        second_engine.dispose()

    assert results == [True, True]
    verify_phase3_execution_schema(empty_schema_engine)
    assert {
        "run_workers",
        "run_tenant_scheduling",
        "run_outbox",
        "run_tool_executions",
        "run_usage_records",
    } <= set(inspect(empty_schema_engine).get_table_names())


def test_full_gate_accepts_semantically_equivalent_constraint_names(
    isolated_schema_engine: Engine,
) -> None:
    worker_fk = next(
        fk
        for fk in inspect(isolated_schema_engine).get_foreign_keys("run_attempts")
        if fk["constrained_columns"] == ["worker_id"]
    )
    with isolated_schema_engine.begin() as connection:
        connection.exec_driver_sql(
            f'ALTER TABLE run_attempts RENAME CONSTRAINT "{worker_fk["name"]}" '
            "TO deployment_generated_worker_fk"
        )

    verify_run_control_schema(isolated_schema_engine)


def test_full_gate_rejects_duplicate_semantic_index(
    isolated_schema_engine: Engine,
) -> None:
    with isolated_schema_engine.begin() as connection:
        connection.execute(
            text("CREATE INDEX duplicate_run_session_tenant_index ON run_sessions (tenant_id)")
        )

    with pytest.raises(RuntimeError, match="run_sessions indexes differ"):
        verify_run_control_schema(isolated_schema_engine)


def test_operator_init_repairs_old_schema_then_full_verifies(
    isolated_schema_engine: Engine,
) -> None:
    from app.processes.run_control_init import initialize_schema

    with isolated_schema_engine.begin() as connection:
        connection.execute(text("DROP TABLE run_usage_records"))
        connection.execute(text("DROP TABLE run_tool_executions"))
        connection.execute(text("ALTER TABLE run_sessions DROP COLUMN archived_at"))
        connection.execute(text("DROP INDEX ix_run_attempts_active_worker_lease"))

    initialize_schema(isolated_schema_engine)
    verify_run_control_schema(isolated_schema_engine)


def test_schema_version_marker_is_existing_and_cannot_be_misclassified_as_fresh(
    empty_schema_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import app_main

    with empty_schema_engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num varchar(32))"))
    assert is_fresh_application_schema(empty_schema_engine) is False
    statements, listener = _ddl_statements(empty_schema_engine)
    monkeypatch.setattr(app_main, "engine", empty_schema_engine)
    try:
        with pytest.raises(RuntimeError, match="maintenance migration required"):
            app_main._initialize_postgres_schema()
    finally:
        event.remove(empty_schema_engine, "before_cursor_execute", listener)

    assert set(inspect(empty_schema_engine).get_table_names()) == {"alembic_version"}
    assert statements == []


@pytest.mark.parametrize(
    "ddl",
    [
        "DROP INDEX ix_run_sessions_archived_at",
        "DROP INDEX ix_runs_replaces_run_id",
        "DROP INDEX ix_run_tool_semantic_recovery",
        "ALTER TABLE run_usage_records DROP CONSTRAINT ck_run_usage_total_consistent",
        "ALTER TABLE run_tool_executions DROP CONSTRAINT uq_run_tool_idempotency",
        "ALTER TABLE run_usage_records DROP CONSTRAINT fk_run_usage_records_attempt_provenance",
        "ALTER TABLE run_usage_records DROP CONSTRAINT run_usage_records_pkey",
        "ALTER TABLE run_usage_records ALTER COLUMN provider SET DEFAULT 'unknown'",
    ],
)
def test_read_only_gate_rejects_execution_contract_drift_without_repair(
    isolated_schema_engine: Engine,
    ddl: str,
) -> None:
    with isolated_schema_engine.begin() as connection:
        connection.execute(text(ddl))
    before = inspect(isolated_schema_engine).get_table_names()

    with pytest.raises(RuntimeError, match="maintenance migration required"):
        verify_phase3_execution_schema(isolated_schema_engine)

    assert inspect(isolated_schema_engine).get_table_names() == before


def test_operator_migration_completes_old_schema_then_verifies_and_is_idempotent(
    isolated_schema_engine: Engine,
) -> None:
    _downgrade_to_phase2(isolated_schema_engine)

    assert migrate_phase3_execution_schema(isolated_schema_engine)
    verify_phase3_execution_schema(isolated_schema_engine)
    assert migrate_phase3_execution_schema(isolated_schema_engine) == ()


def test_operator_migration_adds_durable_action_required_outcome_contract(
    isolated_schema_engine: Engine,
) -> None:
    """Legacy runs gain the exact outcome columns and CHECKs, once only."""
    with isolated_schema_engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE runs DROP CONSTRAINT ck_runs_outcome_code_payload_pair")
        )
        connection.execute(text("ALTER TABLE runs DROP CONSTRAINT ck_runs_fixed_outcome_code"))
        connection.execute(text("ALTER TABLE runs DROP COLUMN outcome_payload"))
        connection.execute(text("ALTER TABLE runs DROP COLUMN outcome_code"))

    assert migrate_phase3_execution_schema(isolated_schema_engine)

    with isolated_schema_engine.connect() as connection:
        columns = {
            name: data_type
            for name, data_type in connection.execute(
                text(
                    "SELECT a.attname, format_type(a.atttypid, a.atttypmod) "
                    "FROM pg_attribute AS a "
                    "WHERE a.attrelid = 'runs'::regclass "
                    "AND a.attnum > 0 AND NOT a.attisdropped "
                    "AND a.attname IN ('outcome_code', 'outcome_payload')"
                )
            )
        }
        constraints = dict(
            connection.execute(
                text(
                    "SELECT conname, pg_get_constraintdef(oid, false) "
                    "FROM pg_constraint "
                    "WHERE conrelid = 'runs'::regclass "
                    "AND conname IN ("
                    "'ck_runs_outcome_code_payload_pair', 'ck_runs_fixed_outcome_code')"
                )
            ).all()
        )

    assert columns == {"outcome_code": "character varying(64)", "outcome_payload": "jsonb"}
    assert constraints == {
        "ck_runs_outcome_code_payload_pair": "CHECK (((outcome_code IS NULL) = (outcome_payload IS NULL)))",
        "ck_runs_fixed_outcome_code": "CHECK (((outcome_code IS NULL) OR ((outcome_code)::text = 'action_required'::text)))",
    }
    assert migrate_phase3_execution_schema(isolated_schema_engine) == ()


def test_run_control_gate_rejects_same_named_wrong_outcome_pair_constraint(
    isolated_schema_engine: Engine,
) -> None:
    """A matching CHECK name cannot disguise a weaker persisted business invariant."""
    with isolated_schema_engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE runs DROP CONSTRAINT ck_runs_outcome_code_payload_pair")
        )
        connection.execute(
            text(
                "ALTER TABLE runs ADD CONSTRAINT ck_runs_outcome_code_payload_pair "
                "CHECK (outcome_code IS NULL OR outcome_payload IS NOT NULL)"
            )
        )

    with pytest.raises(RuntimeError, match="runs CHECK constraints differ"):
        verify_run_control_schema(isolated_schema_engine)

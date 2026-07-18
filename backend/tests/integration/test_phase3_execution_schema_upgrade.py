from __future__ import annotations

import threading
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest
from app.core.database import Base
from app.models.run_execution import RunUsageRecord
from app.scripts.migrate_phase3_execution_schema import migrate_phase3_execution_schema
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError


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


def _downgrade_to_phase2(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE run_usage_records"))
        connection.execute(text("DROP TABLE run_tool_executions"))
        connection.execute(text("ALTER TABLE run_sessions DROP COLUMN archived_at"))


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
        first_statements.setdefault(connection.engine, statement)

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

    assert len(first_statements) == 2
    assert all("pg_advisory_xact_lock" in sql for sql in first_statements.values())
    assert sum(bool(result) for result in results) == 1
    _assert_phase3_schema(isolated_schema_engine)


def test_app_startup_runs_phase3_upgrade_before_create_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import app_main

    calls: list[str] = []

    monkeypatch.setattr(
        app_main,
        "migrate_phase2_scheduling_schema",
        lambda _engine: calls.append("phase2") or (),
    )
    monkeypatch.setattr(
        app_main,
        "migrate_phase3_execution_schema",
        lambda _engine: calls.append("phase3") or (),
    )
    monkeypatch.setattr(
        app_main.Base.metadata,
        "create_all",
        lambda **_kwargs: calls.append("create_all"),
    )
    monkeypatch.setattr("app.scripts.reconcile_schema.reconcile_columns", lambda _engine: [])

    assert app_main._initialize_postgres_schema() is True
    assert calls == ["phase2", "phase3", "create_all"]

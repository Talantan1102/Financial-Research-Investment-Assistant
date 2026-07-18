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

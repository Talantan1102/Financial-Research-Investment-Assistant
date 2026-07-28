"""Idempotent Phase 2 -> Phase 3 execution-facts schema upgrade."""

from __future__ import annotations

import argparse
import re
import uuid
from collections import Counter
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from sqlalchemy import CheckConstraint, Index, Table, UniqueConstraint, inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.schema import CreateIndex

import app.models  # noqa: F401 - register the complete metadata graph
from app.core.database import Base
from app.models.run_execution import RunToolExecution, RunUsageRecord

_EXECUTION_TABLES = (RunToolExecution.__table__, RunUsageRecord.__table__)
_PREDECESSOR_ATTEMPT_FKS = {
    "run_tool_executions": "fk_run_tool_executions_attempt_provenance",
    "run_usage_records": "fk_run_usage_records_attempt_provenance",
}
_REVISION_UNIQUE = "uq_runs_tenant_session_revision_seq"
_SCHEMA_VERSION_MARKERS = {"alembic_version", "schema_migrations"}
_RUN_CONTROL_TABLES = tuple(
    model.__table__
    for model in (
        app.models.RunSession,
        app.models.RunMessage,
        app.models.Run,
        app.models.RunAttempt,
        app.models.RunPause,
        app.models.RunEvent,
        app.models.RunWorker,
        app.models.RunTenantScheduling,
        app.models.RunOutbox,
        app.models.RunToolExecution,
        app.models.RunUsageRecord,
    )
)


def is_fresh_application_schema(engine: Engine) -> bool:
    """Return true only when the current schema has no known application footprint."""
    with engine.connect() as connection:
        existing = set(inspect(connection).get_table_names())
    application_tables = set(Base.metadata.tables)
    return not (existing & (application_tables | _SCHEMA_VERSION_MARKERS))


def is_fresh_application_schema_connection(connection: Connection) -> bool:
    """Transaction-local fresh check used while the startup advisory lock is held."""
    existing = set(inspect(connection).get_table_names())
    application_tables = set(Base.metadata.tables)
    return not (existing & (application_tables | _SCHEMA_VERSION_MARKERS))


def _revision_unique_signature(connection: Connection) -> tuple[str, ...] | None:
    for constraint in inspect(connection).get_unique_constraints("runs"):
        if constraint["name"] == _REVISION_UNIQUE:
            return tuple(constraint["column_names"])
    return None


def _repair_revision_sequences(connection: Connection, changes: list[str]) -> None:
    bad_count = int(
        connection.execute(
            text(
                "SELECT count(*) FROM ("
                " SELECT tenant_id, session_id FROM runs"
                " GROUP BY tenant_id, session_id"
                " HAVING count(*) FILTER (WHERE revision_seq IS NULL OR revision_seq <= 0) > 0"
                " OR count(*) <> count(DISTINCT revision_seq)"
                ") AS bad_sessions"
            )
        ).scalar_one()
    )
    if not bad_count:
        return
    connection.execute(
        text(
            "WITH bad_sessions AS ("
            " SELECT tenant_id, session_id FROM runs"
            " GROUP BY tenant_id, session_id"
            " HAVING count(*) FILTER (WHERE revision_seq IS NULL OR revision_seq <= 0) > 0"
            " OR count(*) <> count(DISTINCT revision_seq)"
            "), numbered AS ("
            " SELECT runs.id, row_number() OVER ("
            "  PARTITION BY runs.tenant_id, runs.session_id"
            "  ORDER BY runs.created_at, runs.id"
            " ) AS seq FROM runs JOIN bad_sessions USING (tenant_id, session_id)"
            ") UPDATE runs SET revision_seq = numbered.seq"
            " FROM numbered WHERE runs.id = numbered.id"
        )
    )
    changes.append("repair duplicate runs.revision_seq values")


def _ensure_revision_unique(connection: Connection, changes: list[str]) -> None:
    expected = ("tenant_id", "session_id", "revision_seq")
    actual = _revision_unique_signature(connection)
    if actual == expected:
        return
    if actual is not None:
        connection.execute(text(f"ALTER TABLE runs DROP CONSTRAINT {_REVISION_UNIQUE}"))
    connection.execute(
        text(
            f"ALTER TABLE runs ADD CONSTRAINT {_REVISION_UNIQUE} "
            "UNIQUE (tenant_id, session_id, revision_seq)"
        )
    )
    changes.append(f"add {_REVISION_UNIQUE}")


def _unsafe(message: str) -> RuntimeError:
    return RuntimeError(f"unsafe Phase 3 schema drift: {message}")


def _type_sql(value: Any, connection: Connection) -> str:
    return re.sub(
        r"\s+",
        " ",
        str(value.compile(dialect=connection.dialect)).strip().lower(),
    )


def _default_sql(value: Any) -> str | None:
    if value is None:
        return None
    sql = re.sub(
        r"::(?:character varying|text|numeric|integer|boolean)(?:\[\])?",
        "",
        str(value).lower().replace('"', ""),
    )
    sql = re.sub(r"[\s()]", "", sql)
    if len(sql) >= 2 and sql[0] == sql[-1] == "'":
        sql = sql[1:-1]
    return sql


def _check_sql(value: Any, connection: Connection) -> str:
    if hasattr(value, "compile"):
        value = value.compile(
            dialect=connection.dialect,
            compile_kwargs={"literal_binds": True},
        )
    sql = str(value).lower().replace('"', "")
    sql = re.sub(
        r"::(?:character varying|[a-z_][a-z0-9_]*)(?:\[\])?",
        "",
        sql,
    )
    sql = re.sub(r"=\s*any\s*\(\s*array\[(.*?)\]\s*\)", r" in (\1)", sql)
    sql = re.sub(r"[\s()]", "", sql)
    sql = re.sub(r"=anyarray\[(.*?)\]", r"in\1", sql)
    sql = re.sub(r"([a-z_][a-z0-9_.]*)<>allarray\[(.*?)\]", r"\1notin\2", sql)
    sql = re.sub(
        r"([a-z_][a-z0-9_]*)between(-?\d+)and(-?\d+)",
        r"\1>=\2and\1<=\3",
        sql,
    )
    return sql


def _expression_signature(expression: Any, connection: Connection) -> str:
    sql = str(
        expression.compile(dialect=connection.dialect, compile_kwargs={"literal_binds": True})
    )
    sql = sql.lower().replace('"', "")
    sql = re.sub(r"::(?:character varying|text|numeric)(?:\[\])?", "", sql)
    return re.sub(r"[\s()]", "", sql)


def _canonical_constraint_definitions(connection: Connection, regclass: str) -> dict[str, str]:
    rows = connection.execute(
        text(
            "SELECT conname, pg_get_constraintdef(oid, false) "
            "FROM pg_constraint "
            "WHERE conrelid = to_regclass(:regclass) AND contype = 'c'"
        ),
        {"regclass": regclass},
    )
    return {str(name): re.sub(r"\s+", " ", str(definition)).strip() for name, definition in rows}


def _expected_check_definitions(
    connection: Connection,
    table: Table,
    expected: dict[str, CheckConstraint],
) -> dict[str, str]:
    temp_name = f"phase3_check_contract_{uuid.uuid4().hex}"
    quoted_temp = connection.dialect.identifier_preparer.quote(temp_name)
    quoted_table = connection.dialect.identifier_preparer.quote(table.name)
    connection.execute(
        text(f"CREATE TEMP TABLE {quoted_temp} (LIKE {quoted_table}) ON COMMIT DROP")
    )
    for name, constraint in expected.items():
        quoted_name = connection.dialect.identifier_preparer.quote(name)
        check_sql = constraint.sqltext.compile(
            dialect=connection.dialect, compile_kwargs={"literal_binds": True}
        )
        connection.execute(
            text(f"ALTER TABLE {quoted_temp} ADD CONSTRAINT {quoted_name} CHECK ({check_sql})")
        )
    return _canonical_constraint_definitions(connection, f"pg_temp.{temp_name}")


def _index_predicate(index: Mapping[str, Any]) -> str | None:
    predicate = index.get("dialect_options", {}).get("postgresql_where")
    if predicate is None:
        return None
    return re.sub(r"[\s()]", "", str(predicate).lower().replace('"', ""))


def _expected_index_predicate(index: Index, connection: Connection) -> str | None:
    predicate = index.dialect_options["postgresql"].get("where")
    if predicate is None:
        return None
    return _expression_signature(predicate, connection)


def _repair_index(
    connection: Connection,
    *,
    expected: Index,
    actual: Mapping[str, Any] | None,
    changes: list[str],
) -> None:
    expected_columns = [column.name for column in expected.columns]
    matches = actual is not None and (
        actual["column_names"] == expected_columns
        and bool(actual.get("unique")) == bool(expected.unique)
        and _index_predicate(actual) == _expected_index_predicate(expected, connection)
    )
    if matches:
        return
    if expected.name is None:
        raise _unsafe("expected index has no name")
    quoted = connection.dialect.identifier_preparer.quote(str(expected.name))
    if actual is not None:
        connection.execute(text(f"DROP INDEX {quoted}"))
    connection.execute(CreateIndex(expected))
    changes.append(f"repair {expected.name}")


def _repair_checks(connection: Connection, table: Table, changes: list[str]) -> None:
    expected: dict[str, CheckConstraint] = {}
    for constraint in table.constraints:
        if isinstance(constraint, CheckConstraint):
            if constraint.name is None:
                raise _unsafe(f"{table.name} has an unnamed expected CHECK")
            expected[str(constraint.name)] = constraint
    actual = _canonical_constraint_definitions(connection, table.name)
    expected_definitions = _expected_check_definitions(connection, table, expected)
    table_sql = connection.dialect.identifier_preparer.quote(table.name)
    for name, constraint in expected.items():
        reflected = actual.get(name)
        matches = reflected is not None and reflected == expected_definitions[name]
        if matches:
            continue
        name_sql = connection.dialect.identifier_preparer.quote(name)
        if reflected is not None:
            connection.execute(text(f"ALTER TABLE {table_sql} DROP CONSTRAINT {name_sql}"))
        check_sql = constraint.sqltext.compile(
            dialect=connection.dialect, compile_kwargs={"literal_binds": True}
        )
        connection.execute(
            text(f"ALTER TABLE {table_sql} ADD CONSTRAINT {name_sql} CHECK ({check_sql})")
        )
        changes.append(f"repair {name}")
    for name in sorted(set(actual) - set(expected)):
        raise _unsafe(f"{table.name} has unexpected CHECK {name}")


def _validate_columns(connection: Connection, table: Table) -> None:
    actual = {column["name"]: column for column in inspect(connection).get_columns(table.name)}
    expected_names = set(table.columns.keys())
    if set(actual) != expected_names:
        raise _unsafe(
            f"{table.name} columns expected {sorted(expected_names)}, got {sorted(actual)}"
        )
    for column in table.columns:
        reflected = actual[column.name]
        if bool(reflected["nullable"]) != bool(column.nullable):
            raise _unsafe(f"{table.name}.{column.name} nullability differs")
        if _type_sql(reflected["type"], connection) != _type_sql(column.type, connection):
            raise _unsafe(
                f"{table.name}.{column.name} type differs: "
                f"{_type_sql(reflected['type'], connection)} != {_type_sql(column.type, connection)}"
            )


def _validate_foreign_keys(connection: Connection, table: Table) -> None:
    actual = inspect(connection).get_foreign_keys(table.name)
    actual_signatures = {
        (
            tuple(fk["constrained_columns"]),
            fk["referred_table"],
            tuple(fk["referred_columns"]),
            fk.get("options", {}).get("ondelete", "NO ACTION").upper(),
        ): fk["name"]
        for fk in actual
    }
    expected_signatures = {}
    for fk in table.foreign_key_constraints:
        signature = (
            tuple(column.name for column in fk.columns),
            next(iter(fk.elements)).column.table.name,
            tuple(element.column.name for element in fk.elements),
            (fk.ondelete or "NO ACTION").upper(),
        )
        expected_signatures[signature] = fk.name
    if set(actual_signatures) != set(expected_signatures):
        raise _unsafe(f"{table.name} foreign keys differ")
    for signature, expected_name in expected_signatures.items():
        if expected_name is not None and actual_signatures[signature] != expected_name:
            raise _unsafe(f"{table.name} foreign key {expected_name} is misnamed")


def _upgrade_predecessor_attempt_fk(
    connection: Connection, table: Table, changes: list[str]
) -> None:
    constraint_name = _PREDECESSOR_ATTEMPT_FKS[table.name]
    actual = {fk["name"]: fk for fk in inspect(connection).get_foreign_keys(table.name)}.get(
        constraint_name
    )
    if actual is None:
        return
    signature = (
        tuple(actual["constrained_columns"]),
        actual["referred_table"],
        tuple(actual["referred_columns"]),
        actual.get("options", {}).get("ondelete", "NO ACTION").upper(),
    )
    expected_identity = (("run_id", "attempt_id"), "run_attempts", ("run_id", "id"))
    if signature == (*expected_identity, "RESTRICT"):
        return
    if signature != (*expected_identity, "CASCADE"):
        return

    preparer = connection.dialect.identifier_preparer
    table_sql = preparer.quote(table.name)
    constraint_sql = preparer.quote(constraint_name)
    connection.execute(text(f"ALTER TABLE {table_sql} DROP CONSTRAINT {constraint_sql}"))
    connection.execute(
        text(
            f"ALTER TABLE {table_sql} ADD CONSTRAINT {constraint_sql} "
            "FOREIGN KEY (run_id, attempt_id) "
            "REFERENCES run_attempts (run_id, id) ON DELETE RESTRICT"
        )
    )
    changes.append("upgrade predecessor Attempt FK to RESTRICT")


def _upgrade_tool_reservation_columns(connection: Connection, changes: list[str]) -> None:
    columns = {column["name"] for column in inspect(connection).get_columns("run_tool_executions")}
    required = {
        "semantic_key",
        "safe_to_retry",
        "reservation_token",
        "reservation_expires_at",
        "execution_epoch",
    }
    if required <= columns:
        return
    known_predecessor = (
        set(RunToolExecution.__table__.columns.keys())
        - required
        - {
            "risk_level",
            "permission_decision",
        }
    )
    if frozenset(columns) not in {
        frozenset(known_predecessor),
        frozenset(known_predecessor | {"risk_level", "permission_decision"}),
    }:
        raise _unsafe("run_tool_executions reservation columns are partially present")
    connection.execute(text("ALTER TABLE run_tool_executions ADD COLUMN semantic_key varchar(64)"))
    connection.execute(
        text("ALTER TABLE run_tool_executions ADD COLUMN safe_to_retry boolean DEFAULT false")
    )
    connection.execute(text("ALTER TABLE run_tool_executions ADD COLUMN reservation_token uuid"))
    connection.execute(
        text("ALTER TABLE run_tool_executions ADD COLUMN reservation_expires_at timestamp")
    )
    connection.execute(
        text("ALTER TABLE run_tool_executions ADD COLUMN execution_epoch integer DEFAULT 0")
    )
    connection.execute(
        text(
            "UPDATE run_tool_executions SET semantic_key = "
            "CASE WHEN jsonb_typeof(request_summary->'args') = 'object' "
            "THEN md5(tool_name || ':' || (request_summary->'args')::text) "
            "ELSE md5(tool_name || ':' || request_summary::text || ':' || id::text) END"
        )
    )
    connection.execute(
        text(
            "UPDATE run_tool_executions SET status = 'approval_required', "
            "safe_to_retry = false, reservation_token = NULL, "
            "reservation_expires_at = NULL, execution_epoch = 0 "
            "WHERE status = 'started'"
        )
    )
    connection.execute(
        text("ALTER TABLE run_tool_executions ALTER COLUMN semantic_key SET NOT NULL")
    )
    connection.execute(
        text("ALTER TABLE run_tool_executions ALTER COLUMN safe_to_retry SET NOT NULL")
    )
    connection.execute(
        text("ALTER TABLE run_tool_executions ALTER COLUMN safe_to_retry DROP DEFAULT")
    )
    connection.execute(
        text("ALTER TABLE run_tool_executions ALTER COLUMN execution_epoch SET NOT NULL")
    )
    connection.execute(
        text("ALTER TABLE run_tool_executions ALTER COLUMN execution_epoch DROP DEFAULT")
    )
    changes.append("add run_tool_executions reservation ownership columns")


def _upgrade_tool_runtime_observation_columns(connection: Connection, changes: list[str]) -> None:
    columns = {column["name"] for column in inspect(connection).get_columns("run_tool_executions")}
    required = {"risk_level", "permission_decision"}
    present = required & columns
    if present == required:
        return
    if present:
        raise _unsafe("run_tool_executions runtime observation columns are partially present")
    connection.execute(
        text(
            "ALTER TABLE run_tool_executions "
            "ADD COLUMN risk_level varchar(16) DEFAULT 'unknown' NOT NULL"
        )
    )
    connection.execute(
        text(
            "ALTER TABLE run_tool_executions "
            "ADD COLUMN permission_decision varchar(32) DEFAULT 'unknown' NOT NULL"
        )
    )
    changes.append("add run_tool_executions runtime risk observation columns")


def _upgrade_run_outcome_contract(connection: Connection, changes: list[str]) -> None:
    """Add the durable completed-run outcome contract without inventing values.

    Pre-outcome deployments have neither nullable column.  A partially deployed
    contract is only safe to finish when its existing column already matches the
    ORM contract; otherwise fail rather than silently reinterpret persisted data.
    """
    table = app.models.Run.__table__
    expected_columns = {
        column.name: column
        for column in table.columns
        if column.name in {"outcome_code", "outcome_payload"}
    }
    actual_columns = {column["name"]: column for column in inspect(connection).get_columns("runs")}

    for name, expected in expected_columns.items():
        actual = actual_columns.get(name)
        if actual is None:
            continue
        if (
            bool(actual["nullable"]) != bool(expected.nullable)
            or _type_sql(actual["type"], connection) != _type_sql(expected.type, connection)
            or _default_sql(actual.get("default"))
            != _default_sql(getattr(expected.server_default, "arg", None))
        ):
            raise _unsafe(f"runs.{name} outcome column differs")

    if "outcome_code" not in actual_columns:
        connection.execute(text("ALTER TABLE runs ADD COLUMN outcome_code varchar(64)"))
        changes.append("add runs.outcome_code")
    if "outcome_payload" not in actual_columns:
        connection.execute(text("ALTER TABLE runs ADD COLUMN outcome_payload jsonb"))
        changes.append("add runs.outcome_payload")

    # The canonical checker compares PostgreSQL-rendered definitions rather than
    # names, so a same-named weaker CHECK is rebuilt here and rejected by the
    # read-only startup gate before an operator applies this migration.
    _repair_checks(connection, table, changes)


def _validate_uniques(connection: Connection, table: Table) -> None:
    actual = {
        (unique["name"], tuple(unique["column_names"]))
        for unique in inspect(connection).get_unique_constraints(table.name)
    }
    expected = {
        (unique.name, tuple(column.name for column in unique.columns))
        for unique in table.constraints
        if isinstance(unique, UniqueConstraint)
    }
    if actual != expected:
        raise _unsafe(f"{table.name} unique constraints differ")


def _validate_primary_key(connection: Connection, table: Table) -> None:
    actual = inspect(connection).get_pk_constraint(table.name)
    expected_columns = tuple(column.name for column in table.primary_key.columns)
    if tuple(actual["constrained_columns"]) != expected_columns:
        raise _unsafe(f"{table.name} primary key differs")


def _repair_table_indexes(connection: Connection, table: Table, changes: list[str]) -> None:
    actual = {index["name"]: index for index in inspect(connection).get_indexes(table.name)}
    expected_names = {str(index.name) for index in table.indexes if index.name is not None}
    extra = {
        str(name)
        for name, index in actual.items()
        if not index.get("duplicates_constraint") and name not in expected_names
    }
    if extra:
        raise _unsafe(f"{table.name} has unexpected indexes {sorted(extra)}")
    for expected in table.indexes:
        _repair_index(
            connection,
            expected=expected,
            actual=actual.get(expected.name),
            changes=changes,
        )


def _validate_execution_table(connection: Connection, table: Table) -> None:
    _validate_columns(connection, table)
    _validate_primary_key(connection, table)
    _validate_foreign_keys(connection, table)
    _validate_uniques(connection, table)


@contextmanager
def _migration_connection(bind: Engine | Connection) -> Iterator[Connection]:
    if isinstance(bind, Connection):
        yield bind
    else:
        with bind.begin() as connection:
            yield connection


def migrate_phase3_execution_schema(
    engine: Engine | Connection,
    *,
    lock_timeout_ms: int = 5_000,
    statement_timeout_ms: int = 300_000,
) -> tuple[str, ...]:
    """Operator-only maintenance migration in one bounded serialized transaction."""
    changes: list[str] = []
    with _migration_connection(engine) as connection:
        connection.execute(
            text("SELECT set_config('lock_timeout', :value, true)"),
            {"value": f"{lock_timeout_ms}ms"},
        )
        connection.execute(
            text("SELECT set_config('statement_timeout', :value, true)"),
            {"value": f"{statement_timeout_ms}ms"},
        )
        connection.execute(
            text(
                "SELECT pg_advisory_xact_lock("
                "hashtextextended('phase3_execution_schema_upgrade', 0))"
            )
        )
        existing_tables = set(inspect(connection).get_table_names())
        if "run_sessions" not in existing_tables:
            return ()

        missing_dependencies = {"runs", "run_attempts"} - existing_tables
        if missing_dependencies:
            missing = ", ".join(sorted(missing_dependencies))
            raise RuntimeError(f"Phase 3 schema dependencies are missing: {missing}")

        session_columns = {
            column["name"]: column for column in inspect(connection).get_columns("run_sessions")
        }
        if "archived_at" not in session_columns:
            connection.execute(
                text("ALTER TABLE run_sessions ADD COLUMN archived_at timestamp without time zone")
            )
            changes.append("add run_sessions.archived_at")

        archived_index = next(
            index
            for index in app.models.RunSession.__table__.indexes
            if index.name == "ix_run_sessions_archived_at"
        )
        session_indexes = {
            index["name"]: index for index in inspect(connection).get_indexes("run_sessions")
        }
        before = len(changes)
        _repair_index(
            connection,
            expected=archived_index,
            actual=session_indexes.get("ix_run_sessions_archived_at"),
            changes=changes,
        )
        if len(changes) > before and session_indexes.get("ix_run_sessions_archived_at") is None:
            changes[-1] = "add ix_run_sessions_archived_at"

        archived = {
            column["name"]: column for column in inspect(connection).get_columns("run_sessions")
        }["archived_at"]
        if (
            not archived["nullable"]
            or _type_sql(archived["type"], connection) != "timestamp without time zone"
        ):
            raise _unsafe("run_sessions.archived_at column differs")

        run_columns = {column["name"]: column for column in inspect(connection).get_columns("runs")}
        if "revision_seq" not in run_columns:
            connection.execute(text("ALTER TABLE runs ADD COLUMN revision_seq integer"))
            connection.execute(
                text(
                    "WITH numbered AS ("
                    " SELECT id, row_number() OVER ("
                    "  PARTITION BY tenant_id, session_id ORDER BY created_at, id"
                    " ) AS seq FROM runs"
                    ") UPDATE runs SET revision_seq = numbered.seq "
                    "FROM numbered WHERE runs.id = numbered.id"
                )
            )
            connection.execute(text("ALTER TABLE runs ALTER COLUMN revision_seq SET NOT NULL"))
            changes.append("add and backfill runs.revision_seq")
        _repair_revision_sequences(connection, changes)
        if "revision_seq" in run_columns and run_columns["revision_seq"]["nullable"]:
            connection.execute(text("ALTER TABLE runs ALTER COLUMN revision_seq SET NOT NULL"))
            changes.append("set runs.revision_seq not null")
        revision_column = {
            column["name"]: column for column in inspect(connection).get_columns("runs")
        }["revision_seq"]
        if (
            revision_column["nullable"]
            or _type_sql(revision_column["type"], connection) != "integer"
        ):
            raise _unsafe("runs.revision_seq column differs")
        run_indexes = {index["name"]: index for index in inspect(connection).get_indexes("runs")}
        if "ix_runs_tenant_session_revision_seq" in run_indexes:
            connection.execute(text("DROP INDEX ix_runs_tenant_session_revision_seq"))
            changes.append("drop redundant ix_runs_tenant_session_revision_seq")
        _ensure_revision_unique(connection, changes)
        _upgrade_run_outcome_contract(connection, changes)
        run_indexes = {index["name"]: index for index in inspect(connection).get_indexes("runs")}
        for index_name in ("ix_runs_replaces_run_id",):
            expected = next(
                index for index in app.models.Run.__table__.indexes if index.name == index_name
            )
            _repair_index(
                connection,
                expected=expected,
                actual=run_indexes.get(index_name),
                changes=changes,
            )

        existing_tables = set(inspect(connection).get_table_names())
        for table in _EXECUTION_TABLES:
            if table.name not in existing_tables:
                table.create(bind=connection)
                changes.append(f"create {table.name}")

        _upgrade_tool_reservation_columns(connection, changes)
        _upgrade_tool_runtime_observation_columns(connection, changes)

        # CHECKs and indexes are safe to rebuild. Dangerous identity/provenance
        # drift is checked afterwards so any earlier repair rolls back on failure.
        for table in _EXECUTION_TABLES:
            _repair_checks(connection, table, changes)
            _repair_table_indexes(connection, table, changes)
            _upgrade_predecessor_attempt_fk(connection, table, changes)
        for table in _EXECUTION_TABLES:
            _validate_execution_table(connection, table)

    return tuple(changes)


def _read_only_index_drift(
    connection: Connection,
    table: Table,
    *,
    required_names: set[str] | None = None,
) -> list[str]:
    expected = {
        str(index.name): index
        for index in table.indexes
        if index.name is not None and (required_names is None or str(index.name) in required_names)
    }
    actual = {
        str(index["name"]): index
        for index in inspect(connection).get_indexes(table.name)
        if not index.get("duplicates_constraint")
        and (required_names is None or str(index["name"]) in required_names)
    }
    drift: list[str] = []
    for name in sorted(set(expected) - set(actual)):
        drift.append(f"{table.name} missing index {name}")
    for name, expected_index in expected.items():
        reflected = actual.get(name)
        if reflected is None:
            continue
        if (
            reflected["column_names"] != [column.name for column in expected_index.columns]
            or bool(reflected.get("unique")) != bool(expected_index.unique)
            or _index_predicate(reflected) != _expected_index_predicate(expected_index, connection)
        ):
            drift.append(f"{table.name} index {name} differs")
    if required_names is None:
        for name in sorted(set(actual) - set(expected)):
            drift.append(f"{table.name} has unexpected index {name}")
    return drift


def _execution_table_drift(connection: Connection, table: Table) -> list[str]:
    drift: list[str] = []
    inspector = inspect(connection)
    reflected_columns = {column["name"]: column for column in inspector.get_columns(table.name)}
    expected_names = set(table.columns.keys())
    if set(reflected_columns) != expected_names:
        drift.append(
            f"{table.name} columns expected {sorted(expected_names)}, "
            f"got {sorted(reflected_columns)}"
        )
    for column in table.columns:
        reflected = reflected_columns.get(column.name)
        if reflected is None:
            continue
        if bool(reflected["nullable"]) != bool(column.nullable):
            drift.append(f"{table.name}.{column.name} nullability differs")
        actual_type = _type_sql(reflected["type"], connection)
        expected_type = _type_sql(column.type, connection)
        if actual_type != expected_type:
            drift.append(
                f"{table.name}.{column.name} type differs: {actual_type} != {expected_type}"
            )
        expected_default = _default_sql(getattr(column.server_default, "arg", None))
        actual_default = _default_sql(reflected.get("default"))
        if actual_default != expected_default:
            drift.append(
                f"{table.name}.{column.name} default differs: "
                f"{actual_default!r} != {expected_default!r}"
            )

    try:
        _validate_primary_key(connection, table)
    except RuntimeError as exc:
        drift.append(str(exc).removeprefix("unsafe Phase 3 schema drift: "))
    try:
        _validate_foreign_keys(connection, table)
    except RuntimeError as exc:
        drift.append(str(exc).removeprefix("unsafe Phase 3 schema drift: "))
    try:
        _validate_uniques(connection, table)
    except RuntimeError as exc:
        drift.append(str(exc).removeprefix("unsafe Phase 3 schema drift: "))

    actual_checks = {
        str(check["name"]): check["sqltext"]
        for check in inspector.get_check_constraints(table.name)
    }
    expected_checks = {
        str(check.name): check.sqltext
        for check in table.constraints
        if isinstance(check, CheckConstraint) and check.name is not None
    }
    for name in sorted(set(expected_checks) - set(actual_checks)):
        drift.append(f"{table.name} missing CHECK {name}")
    for name in sorted(set(actual_checks) - set(expected_checks)):
        drift.append(f"{table.name} has unexpected CHECK {name}")
    for name in sorted(set(expected_checks) & set(actual_checks)):
        if _check_sql(actual_checks[name], connection) != _check_sql(
            expected_checks[name], connection
        ):
            drift.append(f"{table.name} CHECK {name} differs")
    drift.extend(_read_only_index_drift(connection, table))
    return drift


def _semantic_foreign_key_drift(connection: Connection, table: Table) -> list[str]:
    actual = Counter(
        (
            tuple(fk["constrained_columns"]),
            str(fk["referred_table"]),
            tuple(fk["referred_columns"]),
            str(fk.get("options", {}).get("ondelete", "NO ACTION")).upper(),
        )
        for fk in inspect(connection).get_foreign_keys(table.name)
    )
    expected = Counter(
        (
            tuple(column.name for column in fk.columns),
            next(iter(fk.elements)).column.table.name,
            tuple(element.column.name for element in fk.elements),
            (fk.ondelete or "NO ACTION").upper(),
        )
        for fk in table.foreign_key_constraints
    )
    return [] if actual == expected else [f"{table.name} foreign keys differ"]


def _semantic_unique_drift(connection: Connection, table: Table) -> list[str]:
    actual = Counter(
        tuple(unique["column_names"])
        for unique in inspect(connection).get_unique_constraints(table.name)
    )
    expected = Counter(
        tuple(column.name for column in unique.columns)
        for unique in table.constraints
        if isinstance(unique, UniqueConstraint)
    )
    return [] if actual == expected else [f"{table.name} unique constraints differ"]


def _semantic_check_drift(connection: Connection, table: Table) -> list[str]:
    actual = Counter(
        _check_sql(check["sqltext"], connection)
        for check in inspect(connection).get_check_constraints(table.name)
    )
    expected = Counter(
        _check_sql(check.sqltext, connection)
        for check in table.constraints
        if isinstance(check, CheckConstraint)
    )
    return [] if actual == expected else [f"{table.name} CHECK constraints differ"]


def _semantic_index_drift(connection: Connection, table: Table) -> list[str]:
    def actual_predicate(index: Mapping[str, Any]) -> str | None:
        predicate = index.get("dialect_options", {}).get("postgresql_where")
        return None if predicate is None else _check_sql(predicate, connection)

    def expected_predicate(index: Index) -> str | None:
        predicate = index.dialect_options["postgresql"].get("where")
        return None if predicate is None else _check_sql(predicate, connection)

    actual = Counter(
        (
            tuple(index["column_names"]),
            bool(index.get("unique")),
            actual_predicate(index),
        )
        for index in inspect(connection).get_indexes(table.name)
        if not index.get("duplicates_constraint")
    )
    expected = Counter(
        (
            tuple(column.name for column in index.columns),
            bool(index.unique),
            expected_predicate(index),
        )
        for index in table.indexes
    )
    return [] if actual == expected else [f"{table.name} indexes differ"]


def canonical_table_drift(connection: Connection, table: Table) -> list[str]:
    """Return canonical column/constraint/index drift for one PostgreSQL table."""
    inspector = inspect(connection)
    reflected_columns = {column["name"]: column for column in inspector.get_columns(table.name)}
    expected_names = set(table.columns.keys())
    drift: list[str] = []
    if set(reflected_columns) != expected_names:
        drift.append(
            f"{table.name} columns expected {sorted(expected_names)}, "
            f"got {sorted(reflected_columns)}"
        )
    for column in table.columns:
        reflected = reflected_columns.get(column.name)
        if reflected is None:
            continue
        if bool(reflected["nullable"]) != bool(column.nullable):
            drift.append(f"{table.name}.{column.name} nullability differs")
        actual_type = _type_sql(reflected["type"], connection)
        expected_type = _type_sql(column.type, connection)
        if actual_type != expected_type:
            drift.append(
                f"{table.name}.{column.name} type differs: {actual_type} != {expected_type}"
            )
        actual_default = _default_sql(reflected.get("default"))
        expected_default = _default_sql(getattr(column.server_default, "arg", None))
        if actual_default != expected_default:
            drift.append(
                f"{table.name}.{column.name} default differs: "
                f"{actual_default!r} != {expected_default!r}"
            )
    expected_pk = tuple(column.name for column in table.primary_key.columns)
    actual_pk = tuple(inspector.get_pk_constraint(table.name)["constrained_columns"])
    if actual_pk != expected_pk:
        drift.append(f"{table.name} primary key differs")
    drift.extend(_semantic_foreign_key_drift(connection, table))
    drift.extend(_semantic_unique_drift(connection, table))
    drift.extend(_semantic_check_drift(connection, table))
    drift.extend(_semantic_index_drift(connection, table))
    return drift


def verify_run_control_schema_connection(connection: Connection) -> None:
    """Verify the complete Phase 2+3 control-plane contract without issuing DDL."""
    existing = set(inspect(connection).get_table_names())
    missing = {table.name for table in _RUN_CONTROL_TABLES} - existing
    drift = [f"missing tables {sorted(missing)}"] if missing else []
    for table in _RUN_CONTROL_TABLES:
        if table.name in existing:
            drift.extend(canonical_table_drift(connection, table))
    if drift:
        raise _unsafe(
            "maintenance migration required: "
            + "; ".join(drift)
            + "; run python -m app.processes.run_control_init"
        )


def verify_run_control_schema(engine: Engine) -> None:
    """Engine wrapper for the complete read-only control-plane startup gate."""
    with engine.connect() as connection:
        verify_run_control_schema_connection(connection)


def verify_phase3_execution_schema(engine: Engine) -> None:
    """Read-only rolling-startup gate; instruct operators instead of running DDL."""
    with engine.connect() as connection:
        existing_tables = set(inspect(connection).get_table_names())
        missing = {
            "run_sessions",
            "runs",
            "run_attempts",
            *[table.name for table in _EXECUTION_TABLES],
        } - existing_tables
        if missing:
            raise _unsafe(
                f"maintenance migration required; missing tables {sorted(missing)}; "
                "run python -m app.scripts.migrate_phase3_execution_schema"
            )
        drift: list[str] = []
        session_columns = {
            column["name"]: column for column in inspect(connection).get_columns("run_sessions")
        }
        archived = session_columns.get("archived_at")
        if (
            archived is None
            or not archived["nullable"]
            or _type_sql(archived["type"], connection) != "timestamp without time zone"
        ):
            drift.append("run_sessions.archived_at type/nullability differs")
        drift.extend(
            _read_only_index_drift(
                connection,
                app.models.RunSession.__table__,
                required_names={"ix_run_sessions_archived_at"},
            )
        )

        columns = {column["name"]: column for column in inspect(connection).get_columns("runs")}
        revision = columns.get("revision_seq")
        if (
            revision is None
            or revision["nullable"]
            or _type_sql(revision["type"], connection) != "integer"
        ):
            drift.append("runs.revision_seq type/nullability differs")
        if _revision_unique_signature(connection) != ("tenant_id", "session_id", "revision_seq"):
            drift.append(f"runs unique constraint {_REVISION_UNIQUE} differs")
        if revision is not None:
            duplicate = connection.execute(
                text(
                    "SELECT 1 FROM runs GROUP BY tenant_id, session_id, revision_seq "
                    "HAVING count(*) > 1 LIMIT 1"
                )
            ).first()
            if duplicate is not None:
                drift.append("duplicate runs.revision_seq values")
        drift.extend(
            _read_only_index_drift(
                connection,
                app.models.Run.__table__,
                required_names={"ix_runs_replaces_run_id"},
            )
        )
        for table in _EXECUTION_TABLES:
            drift.extend(_execution_table_drift(connection, table))
        if drift:
            details = "; ".join(drift)
            raise _unsafe(
                f"maintenance migration required: {details}; "
                "run python -m app.scripts.migrate_phase3_execution_schema"
            )


if __name__ == "__main__":
    from app.core.database import engine

    parser = argparse.ArgumentParser(description="Apply the Phase 3 maintenance schema migration")
    parser.add_argument("--lock-timeout-ms", type=int, default=5_000)
    parser.add_argument("--statement-timeout-ms", type=int, default=300_000)
    args = parser.parse_args()
    print(
        migrate_phase3_execution_schema(
            engine,
            lock_timeout_ms=args.lock_timeout_ms,
            statement_timeout_ms=args.statement_timeout_ms,
        )
    )

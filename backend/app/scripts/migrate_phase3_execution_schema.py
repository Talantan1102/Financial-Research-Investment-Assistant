"""Idempotent Phase 2 -> Phase 3 execution-facts schema upgrade."""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import CheckConstraint, Index, Table, UniqueConstraint, inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.schema import CreateIndex

import app.models  # noqa: F401 - register the complete metadata graph
from app.models.run_execution import RunToolExecution, RunUsageRecord

_EXECUTION_TABLES = (RunToolExecution.__table__, RunUsageRecord.__table__)
_PREDECESSOR_ATTEMPT_FKS = {
    "run_tool_executions": "fk_run_tool_executions_attempt_provenance",
    "run_usage_records": "fk_run_usage_records_attempt_provenance",
}


def _unsafe(message: str) -> RuntimeError:
    return RuntimeError(f"unsafe Phase 3 schema drift: {message}")


def _type_sql(value: Any, connection: Connection) -> str:
    return re.sub(
        r"\s+",
        " ",
        str(value.compile(dialect=connection.dialect)).strip().lower(),
    )


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
    known_predecessor = set(RunToolExecution.__table__.columns.keys()) - required
    if columns != known_predecessor:
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


def migrate_phase3_execution_schema(engine: Engine) -> tuple[str, ...]:
    """Add or verify Phase 3 execution facts in one serialized transaction."""
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

        existing_tables = set(inspect(connection).get_table_names())
        for table in _EXECUTION_TABLES:
            if table.name not in existing_tables:
                table.create(bind=connection)
                changes.append(f"create {table.name}")

        _upgrade_tool_reservation_columns(connection, changes)

        # CHECKs and indexes are safe to rebuild. Dangerous identity/provenance
        # drift is checked afterwards so any earlier repair rolls back on failure.
        for table in _EXECUTION_TABLES:
            _repair_checks(connection, table, changes)
            _repair_table_indexes(connection, table, changes)
            _upgrade_predecessor_attempt_fk(connection, table, changes)
        for table in _EXECUTION_TABLES:
            _validate_execution_table(connection, table)

    return tuple(changes)


if __name__ == "__main__":
    from app.core.database import engine

    print(migrate_phase3_execution_schema(engine))

"""Idempotent Phase 2 -> Phase 3 execution-facts schema upgrade."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy import CheckConstraint, Index, Table, UniqueConstraint, inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.schema import CreateIndex

import app.models  # noqa: F401 - register the complete metadata graph
from app.models.run_execution import RunToolExecution, RunUsageRecord

_EXECUTION_TABLES = (RunToolExecution.__table__, RunUsageRecord.__table__)


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


def _check_signature(name: str, expression: Any, connection: Connection) -> object:
    sql = str(expression)
    if name == "ck_run_tool_executions_fixed_status":
        lowered = sql.lower()
        operator = (
            "allowed"
            if " not " not in f" {lowered} " and (" in " in f" {lowered} " or "= any" in lowered)
            else "other"
        )
        return operator, frozenset(re.findall(r"'([^']+)'", sql))
    return _expression_signature(text(sql), connection)


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
    inspector = inspect(connection)
    actual = {
        str(constraint["name"]): constraint
        for constraint in inspector.get_check_constraints(table.name)
        if constraint["name"] is not None
    }
    expected: dict[str, CheckConstraint] = {}
    for constraint in table.constraints:
        if isinstance(constraint, CheckConstraint):
            if constraint.name is None:
                raise _unsafe(f"{table.name} has an unnamed expected CHECK")
            expected[str(constraint.name)] = constraint
    table_sql = connection.dialect.identifier_preparer.quote(table.name)
    for name, constraint in expected.items():
        reflected = actual.get(name)
        matches = reflected is not None and _check_signature(
            name, reflected["sqltext"], connection
        ) == _check_signature(name, constraint.sqltext, connection)
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
        name_sql = connection.dialect.identifier_preparer.quote(str(name))
        connection.execute(text(f"ALTER TABLE {table_sql} DROP CONSTRAINT {name_sql}"))
        changes.append(f"remove unexpected {name}")


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

        # CHECKs and indexes are safe to rebuild. Dangerous identity/provenance
        # drift is checked afterwards so any earlier repair rolls back on failure.
        for table in _EXECUTION_TABLES:
            _repair_checks(connection, table, changes)
            _repair_table_indexes(connection, table, changes)
        for table in _EXECUTION_TABLES:
            _validate_execution_table(connection, table)

    return tuple(changes)


if __name__ == "__main__":
    from app.core.database import engine

    print(migrate_phase3_execution_schema(engine))

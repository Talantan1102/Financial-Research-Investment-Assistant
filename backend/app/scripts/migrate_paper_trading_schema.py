"""Idempotent upgrade from the manual-portfolio schema to paper trading."""

from __future__ import annotations

import argparse
import re
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Table, inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.schema import AddConstraint, CreateIndex

import app.models  # noqa: F401 - register the complete metadata graph
from app.core.database import Base
from app.models.paper_account import (
    PaperAccount,
    PaperAccountResetAudit,
    PaperCashLedger,
    PaperHoldingLot,
)
from app.models.paper_order import (
    PaperActionAudit,
    PaperDispatchRecoveryState,
    PaperFill,
    PaperLotReservation,
    PaperMatchPass,
    PaperOrder,
)
from app.models.position import Position
from app.models.trade import Trade
from app.models.watchlist import (
    WATCHLIST_AUDIT_FUNCTION_BODY,
    WATCHLIST_AUDIT_FUNCTION_DDL,
    WATCHLIST_AUDIT_FUNCTION_NAME,
    WATCHLIST_AUDIT_TRIGGER_DDL,
    WATCHLIST_AUDIT_TRIGGER_NAME,
    WatchlistAudit,
    WatchlistItem,
)
from app.scripts.migrate_phase3_execution_schema import canonical_table_drift

_DOMAIN_TABLES = tuple(
    model.__table__
    for model in (
        PaperAccount,
        PaperOrder,
        PaperFill,
        PaperHoldingLot,
        PaperCashLedger,
        PaperLotReservation,
        PaperMatchPass,
        PaperDispatchRecoveryState,
        PaperActionAudit,
        PaperAccountResetAudit,
        WatchlistItem,
        WatchlistAudit,
    )
)
_LEGACY_EXTENSIONS = (Position.__table__, Trade.__table__)
_EXPECTED_TABLES = _DOMAIN_TABLES + _LEGACY_EXTENSIONS


def _unsafe(message: str) -> RuntimeError:
    return RuntimeError(
        "paper trading schema maintenance required: "
        f"{message}; run python -m app.processes.run_control_init"
    )


@contextmanager
def _migration_connection(bind: Engine | Connection) -> Iterator[Connection]:
    if isinstance(bind, Connection):
        yield bind
    else:
        with bind.begin() as connection:
            yield connection


def _quote(connection: Connection, identifier: str) -> str:
    return connection.dialect.identifier_preparer.quote(identifier)


def _named_constraint_names(connection: Connection, table_name: str) -> set[str]:
    inspector = inspect(connection)
    reflected = (
        inspector.get_foreign_keys(table_name)
        + inspector.get_unique_constraints(table_name)
        + inspector.get_check_constraints(table_name)
    )
    return {str(item["name"]) for item in reflected if item.get("name")}


def _actual_index_names(connection: Connection, table_name: str) -> set[str]:
    return {
        str(index["name"])
        for index in inspect(connection).get_indexes(table_name)
        if not index.get("duplicates_constraint")
    }


def _add_missing_constraint(
    connection: Connection,
    table: Table,
    constraint_name: str,
    changes: list[str],
) -> None:
    existing = _named_constraint_names(connection, table.name)
    if constraint_name in existing:
        return
    constraint = next(
        constraint for constraint in table.constraints if constraint.name == constraint_name
    )
    # The default AddConstraint constructor isolates the object from subsequent
    # CREATE TABLE statements. Keep the shared ORM metadata immutable because
    # tests and fresh-schema startup can run after an in-process legacy upgrade.
    connection.execute(AddConstraint(constraint, isolate_from_table=False))
    changes.append(f"add {constraint_name}")


def _add_missing_index(
    connection: Connection,
    table: Table,
    index_name: str,
    changes: list[str],
) -> None:
    if index_name in _actual_index_names(connection, table.name):
        return
    index = next(index for index in table.indexes if index.name == index_name)
    connection.execute(CreateIndex(index))
    changes.append(f"add {index_name}")


def _upgrade_position_scope(connection: Connection, changes: list[str]) -> None:
    columns = {column["name"] for column in inspect(connection).get_columns("positions")}
    if "paper_account_id" not in columns:
        connection.execute(text("ALTER TABLE positions ADD COLUMN paper_account_id UUID"))
        changes.append("add positions.paper_account_id")
    if "paper_account_generation" not in columns:
        connection.execute(
            text("ALTER TABLE positions ADD COLUMN paper_account_generation INTEGER")
        )
        changes.append("add positions.paper_account_generation")

    for unique in inspect(connection).get_unique_constraints("positions"):
        if tuple(unique["column_names"]) != ("user_id", "ts_code"):
            continue
        name = str(unique["name"])
        connection.exec_driver_sql(
            f"ALTER TABLE positions DROP CONSTRAINT {_quote(connection, name)}"
        )
        changes.append(f"drop {name}")

    for name in (
        "fk_positions_paper_account_scope",
        "ck_positions_paper_scope_all_or_none",
        "uq_positions_paper_scope_tscode",
    ):
        _add_missing_constraint(connection, Position.__table__, name, changes)
    for name in (
        "ix_positions_paper_account_id",
        "uq_positions_manual_user_tscode",
    ):
        _add_missing_index(connection, Position.__table__, name, changes)


def _upgrade_trade_scope(connection: Connection, changes: list[str]) -> None:
    columns = {column["name"] for column in inspect(connection).get_columns("trades")}
    if "paper_account_id" not in columns:
        connection.execute(text("ALTER TABLE trades ADD COLUMN paper_account_id UUID"))
        changes.append("add trades.paper_account_id")
    if "paper_account_generation" not in columns:
        connection.execute(text("ALTER TABLE trades ADD COLUMN paper_account_generation INTEGER"))
        changes.append("add trades.paper_account_generation")

    for name in (
        "fk_trades_paper_account_scope",
        "ck_trades_paper_scope_all_or_none",
    ):
        _add_missing_constraint(connection, Trade.__table__, name, changes)
    _add_missing_index(
        connection,
        Trade.__table__,
        "ix_trades_paper_account_id",
        changes,
    )


def _normalize_sql(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _watchlist_guard_drift(connection: Connection) -> list[str]:
    schema = str(connection.scalar(text("SELECT current_schema()")))
    functions = (
        connection.execute(
            text(
                "SELECT p.oid, p.prorettype = 'trigger'::regtype AS returns_trigger, "
                "l.lanname, p.prosrc, p.prosecdef, p.provolatile, p.proconfig "
                "FROM pg_proc p "
                "JOIN pg_namespace n ON n.oid = p.pronamespace "
                "JOIN pg_language l ON l.oid = p.prolang "
                "WHERE n.nspname = :schema AND p.proname = :name AND p.pronargs = 0"
            ),
            {"schema": schema, "name": WATCHLIST_AUDIT_FUNCTION_NAME},
        )
        .mappings()
        .all()
    )
    drift: list[str] = []
    if len(functions) != 1:
        drift.append(f"watchlist append-only function count differs: {len(functions)}")
        function_oid = None
    else:
        function = functions[0]
        function_oid = int(function["oid"])
        if (
            not bool(function["returns_trigger"])
            or function["lanname"] != "plpgsql"
            or _normalize_sql(str(function["prosrc"]))
            != _normalize_sql(WATCHLIST_AUDIT_FUNCTION_BODY)
            or bool(function["prosecdef"])
            or function["provolatile"] != "v"
            or function["proconfig"] is not None
        ):
            drift.append("watchlist append-only function definition differs")

    triggers = (
        connection.execute(
            text(
                "SELECT t.tgfoid, t.tgtype, t.tgenabled, t.tgqual, t.tgnargs, "
                "t.tgattr::text AS tgattr "
                "FROM pg_trigger t "
                "JOIN pg_class c ON c.oid = t.tgrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = :schema AND c.relname = 'watchlist_audits' "
                "AND t.tgname = :name AND NOT t.tgisinternal"
            ),
            {"schema": schema, "name": WATCHLIST_AUDIT_TRIGGER_NAME},
        )
        .mappings()
        .all()
    )
    if len(triggers) != 1:
        drift.append(f"watchlist append-only trigger count differs: {len(triggers)}")
    else:
        trigger = triggers[0]
        if (
            function_oid is None
            or int(trigger["tgfoid"]) != function_oid
            or int(trigger["tgtype"]) != 27  # ROW | BEFORE | DELETE | UPDATE
            or trigger["tgenabled"] != "O"
            or trigger["tgqual"] is not None
            or int(trigger["tgnargs"]) != 0
            or str(trigger["tgattr"]) != ""
        ):
            drift.append("watchlist append-only trigger definition differs")
    return drift


def _repair_watchlist_guard(connection: Connection, changes: list[str]) -> None:
    if not _watchlist_guard_drift(connection):
        return
    connection.exec_driver_sql(
        f"DROP TRIGGER IF EXISTS {WATCHLIST_AUDIT_TRIGGER_NAME} ON watchlist_audits"
    )
    connection.exec_driver_sql(f"DROP FUNCTION IF EXISTS {WATCHLIST_AUDIT_FUNCTION_NAME}()")
    connection.exec_driver_sql(WATCHLIST_AUDIT_FUNCTION_DDL)
    connection.exec_driver_sql(WATCHLIST_AUDIT_TRIGGER_DDL)
    changes.append("repair watchlist append-only guard")


def _schema_drift(connection: Connection) -> list[str]:
    inspector = inspect(connection)
    existing = set(inspector.get_table_names())
    missing = {table.name for table in _EXPECTED_TABLES} - existing
    drift = [f"missing tables {sorted(missing)}"] if missing else []
    for table in _EXPECTED_TABLES:
        if table.name not in existing:
            continue
        drift.extend(canonical_table_drift(connection, table))
    if "watchlist_audits" in existing:
        drift.extend(_watchlist_guard_drift(connection))
    return drift


def verify_paper_trading_schema_connection(connection: Connection) -> None:
    """Read-only startup gate for all paper-trading and watchlist tables."""
    drift = _schema_drift(connection)
    if drift:
        raise _unsafe("; ".join(drift))


def verify_paper_trading_schema(engine: Engine) -> None:
    with engine.connect() as connection:
        verify_paper_trading_schema_connection(connection)


def migrate_paper_trading_schema(
    bind: Engine | Connection,
    *,
    lock_timeout_ms: int = 5_000,
    statement_timeout_ms: int = 300_000,
) -> tuple[str, ...]:
    """Upgrade an existing mainline schema without rewriting manual rows."""
    changes: list[str] = []
    with _migration_connection(bind) as connection:
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
                "SELECT pg_advisory_xact_lock(hashtextextended('paper_trading_schema_upgrade', 0))"
            )
        )
        existing = set(inspect(connection).get_table_names())
        if not ({"users", "positions", "trades"} <= existing):
            # A truly fresh database is completed by the caller's create_all().
            return ()

        Base.metadata.create_all(bind=connection, tables=_DOMAIN_TABLES)
        created = {table.name for table in _DOMAIN_TABLES} - existing
        changes.extend(f"create {table_name}" for table_name in sorted(created))
        _upgrade_position_scope(connection, changes)
        _upgrade_trade_scope(connection, changes)
        _repair_watchlist_guard(connection, changes)
        verify_paper_trading_schema_connection(connection)
    return tuple(changes)


if __name__ == "__main__":
    from app.core.database import engine

    parser = argparse.ArgumentParser(description="Apply paper-trading schema migration")
    parser.add_argument("--lock-timeout-ms", type=int, default=5_000)
    parser.add_argument("--statement-timeout-ms", type=int, default=300_000)
    args = parser.parse_args()
    print(
        migrate_paper_trading_schema(
            engine,
            lock_timeout_ms=args.lock_timeout_ms,
            statement_timeout_ms=args.statement_timeout_ms,
        )
    )

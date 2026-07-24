"""Idempotent upgrade from the manual-portfolio schema to paper trading."""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Table,
    UniqueConstraint,
    inspect,
    text,
)
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
from app.models.watchlist import WatchlistAudit, WatchlistItem

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


def _expected_constraint_names(table: Table) -> set[str]:
    return {
        str(constraint.name)
        for constraint in table.constraints
        if constraint.name is not None
        and (
            isinstance(
                constraint,
                (CheckConstraint, ForeignKeyConstraint, UniqueConstraint),
            )
        )
    }


def _expected_index_names(table: Table) -> set[str]:
    return {str(index.name) for index in table.indexes if index.name is not None}


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


def _schema_drift(connection: Connection) -> list[str]:
    inspector = inspect(connection)
    existing = set(inspector.get_table_names())
    missing = {table.name for table in _EXPECTED_TABLES} - existing
    drift = [f"missing tables {sorted(missing)}"] if missing else []
    for table in _EXPECTED_TABLES:
        if table.name not in existing:
            continue
        expected_columns = set(table.columns.keys())
        actual_columns = {column["name"] for column in inspector.get_columns(table.name)}
        if actual_columns != expected_columns:
            drift.append(
                f"{table.name} columns expected {sorted(expected_columns)}, "
                f"got {sorted(actual_columns)}"
            )
        missing_constraints = _expected_constraint_names(table) - _named_constraint_names(
            connection, table.name
        )
        if missing_constraints:
            drift.append(f"{table.name} missing constraints {sorted(missing_constraints)}")
        missing_indexes = _expected_index_names(table) - _actual_index_names(connection, table.name)
        if missing_indexes:
            drift.append(f"{table.name} missing indexes {sorted(missing_indexes)}")
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

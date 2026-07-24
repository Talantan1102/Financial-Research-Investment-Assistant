from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from app.core.database import Base
from app.models.user import User
from app.processes.run_control_init import initialize_schema
from app.scripts.migrate_paper_trading_schema import migrate_paper_trading_schema
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

_PAPER_TABLES = (
    "paper_lot_reservations",
    "paper_match_passes",
    "paper_holding_lots",
    "paper_cash_ledger",
    "paper_account_reset_audits",
    "paper_dispatch_recovery_states",
    "paper_action_audits",
    "paper_fills",
    "paper_orders",
    "paper_accounts",
)
_WATCHLIST_TABLES = ("watchlist_audits", "watchlist_items")


@pytest.fixture
def legacy_application_engine(pg_test_engine: Engine) -> Iterator[Engine]:
    schema = f"paper_upgrade_{uuid.uuid4().hex}"
    with pg_test_engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    isolated = create_engine(
        pg_test_engine.url,
        connect_args={"options": f"-csearch_path={schema} -ctimezone=Asia/Shanghai"},
    )
    Base.metadata.create_all(bind=isolated)
    try:
        with isolated.begin() as connection:
            for table_name in (*_PAPER_TABLES, *_WATCHLIST_TABLES):
                connection.exec_driver_sql(f'DROP TABLE IF EXISTS "{table_name}" CASCADE')
            connection.execute(text("DROP INDEX IF EXISTS uq_positions_manual_user_tscode"))
            connection.execute(
                text(
                    "ALTER TABLE positions "
                    "DROP COLUMN paper_account_generation CASCADE, "
                    "DROP COLUMN paper_account_id CASCADE, "
                    "ADD CONSTRAINT uq_positions_user_tscode UNIQUE (user_id, ts_code)"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE trades "
                    "DROP COLUMN paper_account_generation CASCADE, "
                    "DROP COLUMN paper_account_id CASCADE"
                )
            )
        yield isolated
    finally:
        isolated.dispose()
        with pg_test_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def _seed_legacy_manual_rows(engine: Engine) -> tuple[uuid.UUID, str, str]:
    suffix = uuid.uuid4().hex
    position_id = str(uuid.uuid4())
    trade_id = str(uuid.uuid4())
    with Session(engine) as session, session.begin():
        user = User(
            username=f"paper-upgrade-{suffix}",
            email=f"paper-upgrade-{suffix}@example.com",
            hashed_password="test-password-hash",
        )
        session.add(user)
        session.flush()
        user_id = user.id
        session.execute(
            text(
                "INSERT INTO positions "
                "(id, user_id, ts_code, name, quantity, avg_cost, total_cost, "
                "realized_pnl, is_silenced, asset_class, updated_at) "
                "VALUES (:id, :user_id, '600519.SH', '贵州茅台', 100, 1500, "
                "150000, 0, false, 'stock', now())"
            ),
            {"id": position_id, "user_id": user_id},
        )
        session.execute(
            text(
                "INSERT INTO trades "
                "(id, user_id, ts_code, name, type, quantity, price, trade_date, created_at) "
                "VALUES (:id, :user_id, '600519.SH', '贵州茅台', 'BUY', 100, "
                "1500, current_date, now())"
            ),
            {"id": trade_id, "user_id": user_id},
        )
    return user_id, position_id, trade_id


def _constraint_names(engine: Engine, table_name: str) -> set[str]:
    inspector = inspect(engine)
    return {
        str(item["name"])
        for item in (
            inspector.get_foreign_keys(table_name)
            + inspector.get_unique_constraints(table_name)
            + inspector.get_check_constraints(table_name)
        )
        if item.get("name")
    }


def test_operator_init_upgrades_main_legacy_schema_without_losing_manual_rows(
    legacy_application_engine: Engine,
) -> None:
    user_id, position_id, trade_id = _seed_legacy_manual_rows(legacy_application_engine)

    initialize_schema(legacy_application_engine)

    inspector = inspect(legacy_application_engine)
    tables = set(inspector.get_table_names())
    assert set(_PAPER_TABLES + _WATCHLIST_TABLES) <= tables
    for table_name in ("positions", "trades"):
        columns = {column["name"]: column for column in inspector.get_columns(table_name)}
        assert columns["paper_account_id"]["nullable"] is True
        assert columns["paper_account_generation"]["nullable"] is True

    assert "uq_positions_user_tscode" not in _constraint_names(
        legacy_application_engine, "positions"
    )
    assert {
        "fk_positions_paper_account_scope",
        "ck_positions_paper_scope_all_or_none",
        "uq_positions_paper_scope_tscode",
    } <= _constraint_names(legacy_application_engine, "positions")
    assert {
        "fk_trades_paper_account_scope",
        "ck_trades_paper_scope_all_or_none",
    } <= _constraint_names(legacy_application_engine, "trades")

    with legacy_application_engine.connect() as connection:
        position = connection.execute(
            text(
                "SELECT user_id, paper_account_id, paper_account_generation "
                "FROM positions WHERE id = :id"
            ),
            {"id": position_id},
        ).one()
        trade = connection.execute(
            text(
                "SELECT user_id, paper_account_id, paper_account_generation "
                "FROM trades WHERE id = :id"
            ),
            {"id": trade_id},
        ).one()
    assert position == (user_id, None, None)
    assert trade == (user_id, None, None)


def test_existing_legacy_schema_fails_startup_with_operator_migration_instruction(
    legacy_application_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import app_main

    monkeypatch.setattr(app_main, "engine", legacy_application_engine)

    with pytest.raises(RuntimeError, match="paper trading schema.*run_control_init"):
        app_main._initialize_postgres_schema()


def test_operator_init_paper_schema_upgrade_is_idempotent(
    legacy_application_engine: Engine,
) -> None:
    _seed_legacy_manual_rows(legacy_application_engine)

    changes = migrate_paper_trading_schema(legacy_application_engine)
    assert {
        "add positions.paper_account_id",
        "add positions.paper_account_generation",
        "add trades.paper_account_id",
        "add trades.paper_account_generation",
    } <= set(changes)
    assert migrate_paper_trading_schema(legacy_application_engine) == ()

    columns = {
        column["name"]: column
        for column in inspect(legacy_application_engine).get_columns("positions")
    }
    assert {"paper_account_id", "paper_account_generation"} <= set(columns)
    with legacy_application_engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM positions")) == 1
        assert connection.scalar(text("SELECT count(*) FROM trades")) == 1

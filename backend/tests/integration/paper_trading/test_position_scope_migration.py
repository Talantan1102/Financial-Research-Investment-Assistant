from __future__ import annotations

import uuid

import pytest
from app.scripts.reconcile_paper_position_scope import reconcile_paper_position_scope
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import IntegrityError


def test_legacy_position_scope_migration_is_idempotent(pg_test_engine: Engine) -> None:
    schema = f"paper_scope_{uuid.uuid4().hex}"
    with pg_test_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped = create_engine(
        pg_test_engine.url,
        connect_args={"options": f"-csearch_path={schema}"},
        future=True,
    )
    user_id, account1, account2 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    try:
        with scoped.begin() as connection:
            connection.execute(text("CREATE TABLE users (id UUID PRIMARY KEY)"))
            connection.execute(
                text(
                    "CREATE TABLE paper_accounts (id UUID NOT NULL, user_id UUID NOT NULL, "
                    "generation INTEGER NOT NULL, PRIMARY KEY (id), UNIQUE (id,user_id,generation))"
                )
            )
            connection.execute(
                text(
                    "CREATE TABLE trades (id VARCHAR(36) PRIMARY KEY, user_id UUID NOT NULL, "
                    "ts_code VARCHAR(10) NOT NULL, price NUMERIC(12,4) NOT NULL)"
                )
            )
            connection.execute(
                text(
                    "CREATE TABLE positions (id VARCHAR(36) PRIMARY KEY, user_id UUID NOT NULL, "
                    "ts_code VARCHAR(10) NOT NULL, avg_cost NUMERIC(12,4) NOT NULL, "
                    "total_cost NUMERIC(14,2) NOT NULL, realized_pnl NUMERIC(14,2) NOT NULL, "
                    "CONSTRAINT uq_positions_user_tscode UNIQUE(user_id,ts_code))"
                )
            )
            connection.execute(text("INSERT INTO users VALUES (:u)"), {"u": user_id})
            connection.execute(
                text("INSERT INTO paper_accounts VALUES (:a,:u,1),(:b,:u,2)"),
                {"a": account1, "b": account2, "u": user_id},
            )
            connection.execute(
                text("INSERT INTO positions VALUES ('manual',:u,'600519.SH',10,1000,0)"),
                {"u": user_id},
            )

        reconcile_paper_position_scope(scoped)
        reconcile_paper_position_scope(scoped)
        with scoped.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO positions (id,user_id,ts_code,avg_cost,total_cost,realized_pnl,"
                    "paper_account_id,paper_account_generation) VALUES "
                    "('g1',:u,'600519.SH',10,1000,0,:a,1),"
                    "('g2',:u,'600519.SH',10,2000,0,:b,2)"
                ),
                {"u": user_id, "a": account1, "b": account2},
            )
            assert connection.scalar(text("SELECT count(*) FROM positions")) == 3
            widths = connection.execute(
                text(
                    "SELECT column_name,numeric_precision,numeric_scale FROM information_schema.columns "
                    "WHERE table_schema=current_schema() AND table_name='positions' "
                    "AND column_name IN ('avg_cost','total_cost','realized_pnl')"
                )
            ).all()
            assert {row[0]: (row[1], row[2]) for row in widths} == {
                "avg_cost": (18, 4),
                "total_cost": (20, 2),
                "realized_pnl": (20, 2),
            }
        with pytest.raises(IntegrityError), scoped.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO positions (id,user_id,ts_code,avg_cost,total_cost,realized_pnl,"
                    "paper_account_id,paper_account_generation) VALUES "
                    "('bad',:u,'000001.SZ',10,10,0,:a,2)"
                ),
                {"u": user_id, "a": account1},
            )
    finally:
        scoped.dispose()
        with pg_test_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))

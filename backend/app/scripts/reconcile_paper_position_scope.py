"""Idempotently upgrade legacy Trade/Position tables for paper-account scope."""

from sqlalchemy import text
from sqlalchemy.engine import Engine


def reconcile_paper_position_scope(engine: Engine) -> None:
    statements = (
        "ALTER TABLE trades ADD COLUMN IF NOT EXISTS paper_account_id UUID",
        "ALTER TABLE trades ADD COLUMN IF NOT EXISTS paper_account_generation INTEGER",
        "ALTER TABLE positions ADD COLUMN IF NOT EXISTS paper_account_id UUID",
        "ALTER TABLE positions ADD COLUMN IF NOT EXISTS paper_account_generation INTEGER",
        "ALTER TABLE positions DROP CONSTRAINT IF EXISTS uq_positions_user_tscode",
        "DROP INDEX IF EXISTS uq_positions_user_tscode",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_positions_manual_user_tscode ON positions (user_id, ts_code) WHERE paper_account_id IS NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_positions_paper_scope_tscode ON positions (paper_account_id, paper_account_generation, ts_code) WHERE paper_account_id IS NOT NULL",
    )
    numeric_columns = {
        ("trades", "price"): (18, 4),
        ("positions", "avg_cost"): (18, 4),
        ("positions", "total_cost"): (20, 2),
        ("positions", "realized_pnl"): (20, 2),
    }
    constraints = {
        "ck_trades_paper_scope_all_or_none": "ALTER TABLE trades ADD CONSTRAINT ck_trades_paper_scope_all_or_none CHECK ((paper_account_id IS NULL) = (paper_account_generation IS NULL))",
        "ck_positions_paper_scope_all_or_none": "ALTER TABLE positions ADD CONSTRAINT ck_positions_paper_scope_all_or_none CHECK ((paper_account_id IS NULL) = (paper_account_generation IS NULL))",
        "fk_trades_paper_account_scope": "ALTER TABLE trades ADD CONSTRAINT fk_trades_paper_account_scope FOREIGN KEY (paper_account_id, user_id, paper_account_generation) REFERENCES paper_accounts (id, user_id, generation) ON DELETE RESTRICT",
        "fk_positions_paper_account_scope": "ALTER TABLE positions ADD CONSTRAINT fk_positions_paper_account_scope FOREIGN KEY (paper_account_id, user_id, paper_account_generation) REFERENCES paper_accounts (id, user_id, generation) ON DELETE RESTRICT",
    }
    with engine.begin() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = current_schema()")
            )
        }
        if not {"trades", "positions", "paper_accounts"}.issubset(tables):
            return
        for statement in statements:
            connection.execute(text(statement))
        for (table, column), expected in numeric_columns.items():
            current = connection.execute(
                text(
                    "SELECT numeric_precision, numeric_scale FROM information_schema.columns "
                    "WHERE table_schema=current_schema() AND table_name=:table AND column_name=:column"
                ),
                {"table": table, "column": column},
            ).one()
            if tuple(current) != expected:
                connection.execute(
                    text(
                        f"ALTER TABLE {table} ALTER COLUMN {column} "
                        f"TYPE NUMERIC({expected[0]},{expected[1]})"
                    )
                )
        existing_constraints = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT conname FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid "
                    "JOIN pg_namespace n ON n.oid=t.relnamespace WHERE n.nspname=current_schema()"
                )
            )
        }
        for name, ddl in constraints.items():
            if name not in existing_constraints:
                connection.execute(text(ddl))

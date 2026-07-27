"""Operator-only maintenance initialization for the run-control schema."""

from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.core.database import Base
from app.core.database import engine as sync_engine
from app.models.run import Run, RunAttempt, RunEvent, RunMessage, RunPause, RunSession
from app.models.run_execution import RunToolExecution, RunUsageRecord
from app.models.run_scheduling import RunOutbox, RunTenantScheduling, RunWorker
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.scripts.migrate_paper_trading_schema import (
    migrate_paper_trading_schema,
    verify_paper_trading_schema_connection,
)
from app.scripts.migrate_phase2_scheduling_schema import migrate_phase2_scheduling_schema
from app.scripts.migrate_phase3_execution_schema import (
    migrate_phase3_execution_schema,
    verify_run_control_schema_connection,
)

_MODELS = (
    User,
    Tenant,
    TenantMembership,
    RunSession,
    RunMessage,
    Run,
    RunAttempt,
    RunPause,
    RunEvent,
    RunToolExecution,
    RunUsageRecord,
    RunWorker,
    RunTenantScheduling,
    RunOutbox,
)


def initialize_schema(database_engine: Engine = sync_engine) -> None:
    """Apply maintenance migrations and verify under one global lock order."""
    with database_engine.begin() as connection:
        connection.execute(text("SELECT set_config('lock_timeout', '5000ms', true)"))
        connection.execute(text("SELECT set_config('statement_timeout', '300000ms', true)"))
        connection.execute(
            text(
                "SELECT pg_advisory_xact_lock("
                "hashtextextended('run_control_schema_maintenance', 0))"
            )
        )
        migrate_phase2_scheduling_schema(connection)
        migrate_phase3_execution_schema(connection)
        migrate_paper_trading_schema(connection)
        Base.metadata.create_all(bind=connection)
        verify_run_control_schema_connection(connection)
        verify_paper_trading_schema_connection(connection)


async def initialize() -> None:
    initialize_schema()


def main() -> None:
    asyncio.run(initialize())


if __name__ == "__main__":
    main()

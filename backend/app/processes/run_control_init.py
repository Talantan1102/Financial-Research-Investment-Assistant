"""Create the isolated run-control schema before Compose processes start."""

from __future__ import annotations

import asyncio

from app.core.async_database import build_async_database
from app.core.database import Base
from app.core.database import engine as sync_engine
from app.models.run import Run, RunAttempt, RunEvent, RunMessage, RunPause, RunSession
from app.models.run_execution import RunToolExecution, RunUsageRecord
from app.models.run_scheduling import RunOutbox, RunTenantScheduling, RunWorker
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.scripts.migrate_phase2_scheduling_schema import migrate_phase2_scheduling_schema
from app.scripts.migrate_phase3_execution_schema import migrate_phase3_execution_schema

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


async def initialize() -> None:
    migrate_phase2_scheduling_schema(sync_engine)
    migrate_phase3_execution_schema(sync_engine)
    engine, _factory = build_async_database()
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(initialize())


if __name__ == "__main__":
    main()

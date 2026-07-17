"""Create the isolated run-control schema before Compose processes start."""

from __future__ import annotations

import asyncio

from app.core.async_database import build_async_database
from app.core.database import Base
from app.models.run import Run, RunAttempt, RunEvent, RunMessage, RunPause, RunSession
from app.models.run_scheduling import RunOutbox, RunTenantScheduling, RunWorker
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User

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
    RunWorker,
    RunTenantScheduling,
    RunOutbox,
)


async def initialize() -> None:
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

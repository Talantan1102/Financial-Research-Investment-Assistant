from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import timedelta
from typing import Any, cast

import pytest
from app.chatloop.continuation import ContinuationV1, PendingActionV1
from app.chatloop.run_executor import PauseResult, RunUsage
from app.chatloop.state import ChatLoopState
from app.models.run import Run, RunAttempt, RunPause
from app.models.run_scheduling import RunWorker
from app.services.attempt_service import AttemptService
from app.services.run_service import RunService
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Reuse the real-PG assignment fixture that seeds a fully authoritative claimed
# Attempt.  Importing it here registers the fixture in this module as well.
from backend.tests.integration.test_run_chat_worker_pg import (  # noqa: F401
    claimed,
)


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


@pytest.mark.asyncio
async def test_resolved_pause_resumes_on_a_different_worker_without_retry(
    claimed: tuple[AttemptService, Any, uuid.UUID],  # noqa: F811
    pg_async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service, first_assignment, user_id = claimed
    loaded = await service.load_chat_execution(first_assignment)
    state = ChatLoopState(
        user_id=str(user_id),
        session_id=str(loaded.session_id),
        request_id=str(first_assignment.run_id),
        messages=[{"role": "user", "content": loaded.original_prompt}],
    )
    continuation = ContinuationV1.from_state(
        state,
        PendingActionV1(
            pause_type="input",
            tool_name="ask_user",
            request={"question": "成本价是多少？"},
        ),
        key_id="test",
        signature="0" * 64,
    ).model_dump(mode="json")
    await service.pause_chat(
        first_assignment,
        PauseResult(
            first_assignment.run_id,
            first_assignment.attempt_id,
            loaded.session_id,
            "input",
            {"question": "成本价是多少？"},
            continuation,
            RunUsage("test", "scripted", 0, 0, 0, 0, 0.0),
            (),
            (),
        ),
    )

    async with pg_async_session_factory() as session:
        run = await session.get(Run, first_assignment.run_id)
        tenant_id = cast(uuid.UUID, run.tenant_id)
    resumed = await RunService(pg_async_session_factory).resume_run(
        tenant_id,
        first_assignment.run_id,
        user_id,
        response={"text": "1500 元"},
    )
    assert resumed.retry_count == 0

    async with pg_async_session_factory() as session, session.begin():
        run = await session.get(Run, first_assignment.run_id, with_for_update=True)
        second_worker = RunWorker(
            worker_type="chat",
            capacity=1,
            status="online",
            heartbeat_at=func.timezone("UTC", func.statement_timestamp()),
            started_at=func.timezone("UTC", func.statement_timestamp()),
            metadata_payload={},
        )
        session.add(second_worker)
        await session.flush()
        second_attempt = RunAttempt(
            run_id=run.id,
            attempt_no=2,
            status="assigned",
            worker_id=second_worker.id,
            lease_expires_at=func.timezone("UTC", func.statement_timestamp())
            + timedelta(seconds=30),
        )
        session.add(second_attempt)
        run.status = "assigned"
        await session.flush()
        second_attempt_id = cast(uuid.UUID, second_attempt.id)
        second_worker_id = cast(uuid.UUID, second_worker.id)

    second_claim = await service.claim(second_attempt_id, second_worker_id)
    assert second_claim.claimed and second_claim.assignment is not None
    assert second_claim.assignment.worker_id != first_assignment.worker_id
    resumed_input = await service.load_chat_execution(second_claim.assignment)

    assert resumed_input.continuation == continuation
    assert resumed_input.prompt == '{"text":"1500 元"}'
    async with pg_async_session_factory() as session:
        run = await session.get(Run, first_assignment.run_id)
        pause = await session.scalar(
            select(RunPause).where(RunPause.run_id == first_assignment.run_id)
        )
    assert run.retry_count == 0
    assert pause is not None and pause.resolved_at is not None

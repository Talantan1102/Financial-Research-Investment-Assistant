from __future__ import annotations

import asyncio
import uuid
from dataclasses import FrozenInstanceError
from typing import Any, cast

import pytest
from app.models.run import Run, RunAttempt, RunEvent
from app.models.run_scheduling import RunOutbox
from app.services.attempt_service import AttemptCommandRejected, AttemptService
from app.services.scheduling_service import RecoveryResult, SchedulingService
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.unit.services.test_attempt_service import (
    TwoPartyBarrier,
    _assigned_graph,
    attempt_factory,
    cleanup_attempt_rows,
    event_loop_policy,
)

__all__ = ["attempt_factory", "cleanup_attempt_rows", "event_loop_policy"]


class RecoveryBarrierSchedulingService(SchedulingService):
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        barrier: TwoPartyBarrier,
    ) -> None:
        super().__init__(factory)
        self._barrier = barrier

    async def _before_recovery_select(self) -> None:
        await self._barrier.wait()


class TerminalBarrierAttemptService(AttemptService):
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        barrier: TwoPartyBarrier,
    ) -> None:
        super().__init__(factory)
        self._barrier = barrier

    async def _before_attempt_lock(self) -> None:
        await self._barrier.wait()


async def _expire(factory: async_sessionmaker[AsyncSession], attempt_id: uuid.UUID) -> None:
    async with factory() as session, session.begin():
        await session.execute(
            update(RunAttempt)
            .where(RunAttempt.id == attempt_id)
            .values(lease_expires_at=func.timezone("UTC", func.statement_timestamp()))
        )


@pytest.mark.asyncio
async def test_cancel_requested_expiry_cancels_attempt_and_run(
    attempt_factory: async_sessionmaker[AsyncSession],
) -> None:
    run, attempt, _worker = await _assigned_graph(attempt_factory)
    async with attempt_factory() as session, session.begin():
        await session.execute(update(Run).where(Run.id == run.id).values(status="cancel_requested"))
        session.add(
            RunOutbox(
                event_type="attempt.cancel",
                tenant_id=run.tenant_id,
                run_id=run.id,
                attempt_id=attempt.id,
                worker_id=attempt.worker_id,
                payload={},
                dedupe_key=f"attempt.cancel:{run.id}",
            )
        )
    await _expire(attempt_factory, attempt.id)

    results = await SchedulingService(attempt_factory).recover_expired_attempts(limit=10)

    assert [(item.attempt_id, item.decision.value) for item in results] == [(attempt.id, "cancel")]
    async with attempt_factory() as session:
        persisted_run = await session.get(Run, run.id)
        persisted_attempt = await session.get(RunAttempt, attempt.id)
        cancel = await session.scalar(
            select(RunOutbox).where(RunOutbox.event_type == "attempt.cancel")
        )
    assert persisted_run is not None and persisted_run.status == "cancelled"
    assert persisted_attempt is not None and persisted_attempt.status == "cancelled"
    assert cancel is not None and cancel.acknowledged_at is not None


@pytest.mark.asyncio
async def test_first_crash_requeues_once_and_writes_atomic_wake(
    attempt_factory: async_sessionmaker[AsyncSession],
) -> None:
    run, attempt, _worker = await _assigned_graph(attempt_factory)
    await _expire(attempt_factory, attempt.id)

    results = await SchedulingService(attempt_factory).recover_expired_attempts(limit=1)

    assert len(results) == 1 and results[0].decision.value == "retry"
    with pytest.raises(FrozenInstanceError):
        cast(Any, results[0]).decision = "fail"
    async with attempt_factory() as session:
        persisted_run = await session.get(Run, run.id)
        persisted_attempt = await session.get(RunAttempt, attempt.id)
        wake = await session.scalar(
            select(RunOutbox).where(RunOutbox.event_type == "schedule.wake")
        )
        event = await session.scalar(
            select(RunEvent).where(RunEvent.run_id == run.id, RunEvent.event_type == "run.requeued")
        )
    assert persisted_run is not None
    assert (persisted_run.status, persisted_run.retry_count, persisted_run.queue_reason) == (
        "queued",
        1,
        "retry",
    )
    assert persisted_attempt is not None and persisted_attempt.status == "lost"
    assert persisted_attempt.claim_token is None
    assert wake is not None and event is not None


@pytest.mark.asyncio
async def test_second_crash_exhausts_retry_and_fails_run(
    attempt_factory: async_sessionmaker[AsyncSession],
) -> None:
    run, attempt, _worker = await _assigned_graph(attempt_factory)
    async with attempt_factory() as session, session.begin():
        await session.execute(update(Run).where(Run.id == run.id).values(retry_count=1))
    await _expire(attempt_factory, attempt.id)

    results = await SchedulingService(attempt_factory).recover_expired_attempts(limit=1)

    assert len(results) == 1 and results[0].decision.value == "fail"
    async with attempt_factory() as session:
        persisted_run = await session.get(Run, run.id)
        persisted_attempt = await session.get(RunAttempt, attempt.id)
    assert persisted_run is not None and persisted_run.status == "failed"
    assert persisted_run.error_code == "worker_lease_expired"
    assert persisted_attempt is not None and persisted_attempt.status == "lost"


@pytest.mark.asyncio
async def test_resume_attempt_crash_still_has_full_crash_retry_budget(
    attempt_factory: async_sessionmaker[AsyncSession],
) -> None:
    run, attempt, _worker = await _assigned_graph(attempt_factory)
    async with attempt_factory() as session, session.begin():
        await session.execute(
            update(Run).where(Run.id == run.id).values(queue_reason="resume", retry_count=0)
        )
    await _expire(attempt_factory, attempt.id)

    result = await SchedulingService(attempt_factory).recover_expired_attempts(limit=1)

    assert result[0].decision.value == "retry"
    async with attempt_factory() as session:
        persisted = await session.get(Run, run.id)
    assert persisted is not None and persisted.retry_count == 1


@pytest.mark.asyncio
async def test_two_recovery_batches_with_real_barrier_process_attempt_once(
    attempt_factory: async_sessionmaker[AsyncSession],
) -> None:
    _run, attempt, _worker = await _assigned_graph(attempt_factory)
    await _expire(attempt_factory, attempt.id)
    barrier = TwoPartyBarrier()

    first, second = await asyncio.wait_for(
        asyncio.gather(
            RecoveryBarrierSchedulingService(attempt_factory, barrier).recover_expired_attempts(1),
            RecoveryBarrierSchedulingService(attempt_factory, barrier).recover_expired_attempts(1),
        ),
        timeout=2,
    )

    assert sorted(len(item) for item in (first, second)) == [0, 1]


@pytest.mark.asyncio
async def test_completion_recovery_barrier_has_one_terminal_winner_and_fences_old_token(
    attempt_factory: async_sessionmaker[AsyncSession],
) -> None:
    run, attempt, worker = await _assigned_graph(attempt_factory)
    initial = AttemptService(attempt_factory)
    claimed = await initial.claim(attempt.id, worker.id)
    assert claimed.assignment is not None
    await _expire(attempt_factory, attempt.id)
    barrier = TwoPartyBarrier()
    completing = TerminalBarrierAttemptService(attempt_factory, barrier)
    recovering = RecoveryBarrierSchedulingService(attempt_factory, barrier)

    complete_result, recovery_result = await asyncio.wait_for(
        asyncio.gather(
            completing.complete_simulated(
                attempt.id,
                worker.id,
                claimed.assignment.claim_token,
                {"answer": "boundary"},
            ),
            recovering.recover_expired_attempts(1),
            return_exceptions=True,
        ),
        timeout=2,
    )

    assert isinstance(complete_result, AttemptCommandRejected)
    assert isinstance(recovery_result, tuple) and len(recovery_result) == 1
    async with attempt_factory() as session:
        persisted_run = await session.get(Run, run.id)
        persisted_attempt = await session.get(RunAttempt, attempt.id)
    assert persisted_run is not None and persisted_run.status == "queued"
    assert persisted_attempt is not None and persisted_attempt.status == "lost"
    with pytest.raises(AttemptCommandRejected):
        await initial.fail(
            attempt.id,
            worker.id,
            claimed.assignment.claim_token,
            "zombie",
            "must be fenced",
        )


def test_recovery_result_projection_is_frozen() -> None:
    assert cast(Any, RecoveryResult).__dataclass_params__.frozen

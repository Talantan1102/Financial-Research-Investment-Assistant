"""PostgreSQL-authoritative fair scheduling and atomic Run allocation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from app.models.run import Run, RunAttempt, RunPause
from app.models.run_scheduling import RunOutbox, RunTenantScheduling, RunWorker
from app.models.tenant import Tenant
from app.run_control.mutations import RunMutationStore
from app.run_control.scheduling_policy import (
    EligibilityCandidate,
    EligibilityReason,
    WorkerCandidate,
    eligibility_reason,
    rank_workers,
)
from app.run_control.types import AttemptStatus, OutboxType, RunStatus, WorkerStatus
from app.services.worker_registry import load_schedulable_workers

_TENANT_CAPACITY_STATUSES = (
    RunStatus.ASSIGNED.value,
    RunStatus.RUNNING.value,
    RunStatus.CANCEL_REQUESTED.value,
)
_SESSION_ACTIVE_STATUSES = tuple(
    status.value
    for status in RunStatus
    if status not in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}
)


@dataclass(frozen=True)
class Assignment:
    run_id: UUID
    attempt_id: UUID
    worker_id: UUID
    lease_expires_at: datetime


def _database_utc_now() -> Any:
    return func.timezone("UTC", func.statement_timestamp())


class SchedulingService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        heartbeat_ttl: timedelta = timedelta(seconds=30),
        lease_duration: timedelta = timedelta(seconds=45),
        resume_priority_boost_seconds: int = 30,
    ) -> None:
        if heartbeat_ttl <= timedelta(0):
            raise ValueError("heartbeat_ttl must be positive")
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        if resume_priority_boost_seconds < 0:
            raise ValueError("resume_priority_boost_seconds must be non-negative")
        self._session_factory = session_factory
        self._heartbeat_ttl = heartbeat_ttl
        self._lease_duration = lease_duration
        self._resume_priority_boost_seconds = resume_priority_boost_seconds

    async def schedule_once(self) -> Assignment | None:
        """Allocate at most one Run, committing every durable fact together."""

        try:
            async with self._session_factory() as session, session.begin():
                return await self._schedule_in_transaction(session)
        except IntegrityError as error:
            # A competing Scheduler may win a uniqueness race. The context
            # manager has already rolled the failed transaction back. CHECK,
            # FK, and other integrity failures are implementation errors and
            # must remain visible.
            if getattr(error.orig, "sqlstate", None) == "23505":
                return None
            raise

    async def _schedule_in_transaction(self, session: AsyncSession) -> Assignment | None:
        await self._ensure_tenant_cursors(session)
        if not await load_schedulable_workers(session, heartbeat_ttl=self._heartbeat_ttl):
            return None

        cursor = await self._lock_next_tenant_cursor(session)
        if cursor is None:
            return None

        run = await self._lock_next_run(session, cast(UUID, cursor.tenant_id))
        if run is None:
            return None

        workers = await load_schedulable_workers(session, heartbeat_ttl=self._heartbeat_ttl)
        ranked_workers = rank_workers(
            [
                WorkerCandidate(
                    id=item.id,
                    capacity=item.capacity,
                    active_attempts=item.active_attempts,
                    last_assigned_at=item.last_assigned_at,
                )
                for item in workers
            ]
        )
        if not ranked_workers:
            return None

        if await self._locked_run_ineligibility(session, run) is not EligibilityReason.ELIGIBLE:
            return None

        worker_and_load = await self._lock_eligible_worker(session, ranked_workers)
        if worker_and_load is None:
            return None
        worker, _active_attempts = worker_and_load

        clock = (
            await session.execute(
                select(
                    _database_utc_now().label("allocated_at"),
                    (_database_utc_now() + self._lease_duration).label("lease_expires_at"),
                )
            )
        ).one()
        allocated_at = cast(datetime, clock.allocated_at)
        lease_expires_at = cast(datetime, clock.lease_expires_at)
        attempt_no = (
            int(
                await session.scalar(
                    select(func.coalesce(func.max(RunAttempt.attempt_no), 0)).where(
                        RunAttempt.run_id == run.id
                    )
                )
                or 0
            )
            + 1
        )
        attempt_id = uuid4()
        attempt = RunAttempt(
            id=attempt_id,
            run_id=run.id,
            attempt_no=attempt_no,
            status=AttemptStatus.ASSIGNED.value,
            worker_id=worker.id,
            lease_expires_at=lease_expires_at,
        )
        session.add(attempt)
        await session.flush()

        store = RunMutationStore(session)
        await store.transition(
            run,
            RunStatus.ASSIGNED,
            "run.assigned",
            {
                "worker_id": str(worker.id),
                "lease_expires_at": lease_expires_at.isoformat(),
            },
            attempt_id=attempt_id,
        )
        cast(Any, run).assigned_at = allocated_at
        cast(Any, cursor).last_dispatched_at = allocated_at
        cast(Any, cursor).updated_at = allocated_at
        cast(Any, worker).last_assigned_at = allocated_at
        session.add(
            RunOutbox(
                event_type=OutboxType.ATTEMPT_ASSIGNED.value,
                tenant_id=run.tenant_id,
                run_id=run.id,
                attempt_id=attempt_id,
                worker_id=worker.id,
                payload={
                    "attempt_id": str(attempt_id),
                    "run_id": str(run.id),
                    "tenant_id": str(run.tenant_id),
                    "worker_id": str(worker.id),
                },
                dedupe_key=f"attempt-assigned:{attempt_id}",
                available_at=allocated_at,
                created_at=allocated_at,
            )
        )
        return Assignment(
            run_id=cast(UUID, run.id),
            attempt_id=attempt_id,
            worker_id=cast(UUID, worker.id),
            lease_expires_at=lease_expires_at,
        )

    async def _ensure_tenant_cursors(self, session: AsyncSession) -> None:
        tenant_ids = tuple(
            (
                await session.scalars(
                    select(Run.tenant_id)
                    .where(Run.status == RunStatus.QUEUED.value)
                    .distinct()
                    .order_by(Run.tenant_id)
                )
            ).all()
        )
        for tenant_id in tenant_ids:
            await session.execute(
                postgresql_insert(RunTenantScheduling)
                .values(
                    tenant_id=tenant_id,
                    last_dispatched_at=None,
                    updated_at=_database_utc_now(),
                )
                .on_conflict_do_nothing(index_elements=[RunTenantScheduling.tenant_id])
            )

    async def _lock_next_tenant_cursor(self, session: AsyncSession) -> RunTenantScheduling | None:
        candidate_run = aliased(Run)
        unresolved_pause = (
            select(RunPause.id)
            .where(
                RunPause.run_id == candidate_run.id,
                RunPause.resolved_at.is_(None),
            )
            .exists()
        )
        eligible_run = (
            select(candidate_run.id)
            .where(
                candidate_run.tenant_id == RunTenantScheduling.tenant_id,
                candidate_run.status == RunStatus.QUEUED.value,
                candidate_run.cancel_requested_at.is_(None),
                ~unresolved_pause,
            )
            .exists()
        )
        active_runs = (
            select(func.count())
            .select_from(Run)
            .where(
                Run.tenant_id == RunTenantScheduling.tenant_id,
                Run.status.in_(_TENANT_CAPACITY_STATUSES),
            )
            .scalar_subquery()
        )
        return await session.scalar(
            select(RunTenantScheduling)
            .join(Tenant, Tenant.id == RunTenantScheduling.tenant_id)
            .where(eligible_run, active_runs < Tenant.max_running_runs)
            .order_by(
                RunTenantScheduling.last_dispatched_at.asc().nulls_first(),
                RunTenantScheduling.tenant_id,
            )
            .limit(1)
            .with_for_update(skip_locked=True, of=RunTenantScheduling)
        )

    async def _lock_next_run(self, session: AsyncSession, tenant_id: UUID) -> Run | None:
        unresolved_pause = (
            select(RunPause.id)
            .where(RunPause.run_id == Run.id, RunPause.resolved_at.is_(None))
            .exists()
        )
        effective_queued_at = case(
            (
                Run.queue_reason == "resume",
                Run.queued_at - timedelta(seconds=self._resume_priority_boost_seconds),
            ),
            else_=Run.queued_at,
        )
        return await session.scalar(
            select(Run)
            .where(
                Run.tenant_id == tenant_id,
                Run.status == RunStatus.QUEUED.value,
                Run.cancel_requested_at.is_(None),
                ~unresolved_pause,
            )
            .order_by(effective_queued_at, Run.id)
            .limit(1)
            .with_for_update()
        )

    async def _locked_run_ineligibility(self, session: AsyncSession, run: Run) -> EligibilityReason:
        unresolved_pause = bool(
            await session.scalar(
                select(RunPause.id)
                .where(RunPause.run_id == run.id, RunPause.resolved_at.is_(None))
                .limit(1)
            )
        )
        other_active_run = aliased(Run)
        session_busy = bool(
            await session.scalar(
                select(other_active_run.id)
                .where(
                    other_active_run.session_id == run.session_id,
                    other_active_run.id != run.id,
                    other_active_run.status.in_(_SESSION_ACTIVE_STATUSES),
                )
                .limit(1)
            )
        )
        tenant = await session.get(Tenant, run.tenant_id)
        if tenant is None:
            return EligibilityReason.TENANT_AT_CAPACITY
        tenant_active_runs = int(
            await session.scalar(
                select(func.count())
                .select_from(Run)
                .where(
                    Run.tenant_id == run.tenant_id,
                    Run.status.in_(_TENANT_CAPACITY_STATUSES),
                )
            )
            or 0
        )
        return eligibility_reason(
            EligibilityCandidate(
                run_is_queued=cast(str, run.status) == RunStatus.QUEUED.value,
                cancel_requested=run.cancel_requested_at is not None,
                has_unresolved_pause=unresolved_pause,
                session_has_other_active_run=session_busy,
                tenant_active_runs=tenant_active_runs,
                tenant_max_running_runs=cast(int, tenant.max_running_runs),
                has_worker_capacity=True,
            )
        )

    async def _lock_eligible_worker(
        self,
        session: AsyncSession,
        candidates: tuple[WorkerCandidate, ...],
    ) -> tuple[RunWorker, int] | None:
        for candidate in candidates:
            worker = await session.scalar(
                select(RunWorker).where(RunWorker.id == candidate.id).with_for_update()
            )
            if worker is None:
                continue
            database_now = _database_utc_now()
            active_attempts = int(
                await session.scalar(
                    select(func.count())
                    .select_from(RunAttempt)
                    .where(
                        RunAttempt.worker_id == worker.id,
                        RunAttempt.status.in_(
                            (AttemptStatus.ASSIGNED.value, AttemptStatus.RUNNING.value)
                        ),
                        RunAttempt.lease_expires_at.is_not(None),
                        RunAttempt.lease_expires_at > database_now,
                    )
                )
                or 0
            )
            is_live = bool(
                await session.scalar(
                    select(
                        (RunWorker.status == WorkerStatus.ONLINE.value)
                        & (RunWorker.heartbeat_at >= database_now - self._heartbeat_ttl)
                        & (RunWorker.capacity > active_attempts)
                    ).where(RunWorker.id == worker.id)
                )
            )
            if is_live:
                return worker, active_attempts
        return None

"""Durable chat-worker registration and capacity snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.run import RunAttempt
from app.models.run_scheduling import RunWorker
from app.run_control.types import AttemptStatus, ResourceNotFound, WorkerStatus


@dataclass(frozen=True)
class WorkerSnapshot:
    id: UUID
    capacity: int
    active_attempts: int
    heartbeat_at: datetime
    worker_type: str
    status: str
    metadata: Mapping[str, Any]
    started_at: datetime
    last_assigned_at: datetime | None


def _database_utc_now() -> Any:
    return func.timezone("UTC", func.current_timestamp())


def _active_attempt_count(database_now: Any) -> Any:
    return (
        select(func.count(RunAttempt.id))
        .where(
            RunAttempt.worker_id == RunWorker.id,
            RunAttempt.status.in_((AttemptStatus.ASSIGNED.value, AttemptStatus.RUNNING.value)),
            RunAttempt.lease_expires_at.is_not(None),
            RunAttempt.lease_expires_at > database_now,
        )
        .correlate(RunWorker)
        .scalar_subquery()
    )


def _snapshot(worker: RunWorker, active_attempts: int) -> WorkerSnapshot:
    return WorkerSnapshot(
        id=cast(UUID, worker.id),
        capacity=cast(int, worker.capacity),
        active_attempts=active_attempts,
        heartbeat_at=cast(datetime, worker.heartbeat_at),
        worker_type=cast(str, worker.worker_type),
        status=cast(str, worker.status),
        metadata=dict(worker.metadata_payload),
        started_at=cast(datetime, worker.started_at),
        last_assigned_at=cast(datetime | None, worker.last_assigned_at),
    )


async def load_worker_snapshot(session: AsyncSession, worker_id: UUID) -> WorkerSnapshot | None:
    """Read one worker using the caller's transaction without committing it."""

    database_now = _database_utc_now()
    active_attempts = _active_attempt_count(database_now)
    row = (
        await session.execute(
            select(RunWorker, active_attempts.label("active_attempts")).where(
                RunWorker.id == worker_id
            )
        )
    ).one_or_none()
    if row is None:
        return None
    return _snapshot(row[0], int(row.active_attempts))


async def load_schedulable_workers(
    session: AsyncSession,
    *,
    heartbeat_ttl: timedelta,
) -> tuple[WorkerSnapshot, ...]:
    """Read live workers with spare capacity using the caller's transaction."""

    if heartbeat_ttl <= timedelta(0):
        raise ValueError("heartbeat_ttl must be positive")
    database_now = _database_utc_now()
    active_attempts = _active_attempt_count(database_now)
    rows = (
        await session.execute(
            select(RunWorker, active_attempts.label("active_attempts"))
            .where(
                RunWorker.status == WorkerStatus.ONLINE.value,
                RunWorker.heartbeat_at >= database_now - heartbeat_ttl,
                active_attempts < RunWorker.capacity,
            )
            .order_by(RunWorker.id)
        )
    ).all()
    return tuple(_snapshot(worker, int(active)) for worker, active in rows)


class WorkerRegistry:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        heartbeat_ttl: timedelta = timedelta(seconds=30),
    ) -> None:
        if heartbeat_ttl <= timedelta(0):
            raise ValueError("heartbeat_ttl must be positive")
        self._session_factory = session_factory
        self._heartbeat_ttl = heartbeat_ttl

    async def register(
        self,
        capacity: int,
        metadata: Mapping[str, Any],
    ) -> WorkerSnapshot:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        database_now = _database_utc_now()
        async with self._session_factory() as session, session.begin():
            worker = RunWorker(
                worker_type="chat",
                capacity=capacity,
                status=WorkerStatus.ONLINE.value,
                heartbeat_at=database_now,
                started_at=database_now,
                metadata_payload=dict(metadata),
            )
            session.add(worker)
            await session.flush()
            snapshot = await load_worker_snapshot(session, cast(UUID, worker.id))
            assert snapshot is not None
            return snapshot

    async def heartbeat(self, worker_id: UUID) -> None:
        await self._set_fields(worker_id, heartbeat_at=_database_utc_now())

    async def drain(self, worker_id: UUID) -> None:
        await self._set_fields(worker_id, status=WorkerStatus.DRAINING.value)

    async def mark_offline(self, worker_id: UUID) -> None:
        await self._set_fields(worker_id, status=WorkerStatus.OFFLINE.value)

    async def get(self, worker_id: UUID) -> WorkerSnapshot:
        async with self._session_factory() as session:
            snapshot = await load_worker_snapshot(session, worker_id)
        if snapshot is None:
            raise ResourceNotFound(f"worker not found: {worker_id}")
        return snapshot

    async def list_schedulable(self) -> tuple[WorkerSnapshot, ...]:
        async with self._session_factory() as session:
            return await load_schedulable_workers(
                session,
                heartbeat_ttl=self._heartbeat_ttl,
            )

    async def _set_fields(self, worker_id: UUID, **values: Any) -> None:
        async with self._session_factory() as session, session.begin():
            result = await session.execute(
                update(RunWorker)
                .where(RunWorker.id == worker_id)
                .values(**values)
                .returning(RunWorker.id)
            )
            if result.scalar_one_or_none() is None:
                raise ResourceNotFound(f"worker not found: {worker_id}")

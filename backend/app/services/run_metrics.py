"""Read-only aggregate metrics for the Run control plane.

The service deliberately works from PostgreSQL facts and never calls a scheduler
or mutates a row.  Values are returned as plain dictionaries so this module can
be used by both the HTTP endpoint and a future Prometheus adapter.
"""

from __future__ import annotations

import contextvars
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, true
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.run import Run, RunAttempt
from app.models.run_execution import RunUsageRecord
from app.models.run_scheduling import RunOutbox, RunWorker
from app.run_control.types import AttemptStatus, RunStatus

_run_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("run_id", default=None)
_attempt_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("attempt_id", default=None)
_worker_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("worker_id", default=None)


@contextmanager
def run_log_context(
    *,
    run_id: UUID | str | None = None,
    attempt_id: UUID | str | None = None,
    worker_id: UUID | str | None = None,
) -> Iterator[None]:
    """Bind safe correlation IDs to logs for the current async task.

    Only opaque identifiers are bound; callers must never put prompts, API keys,
    bearer tokens or model output into a log message.
    """
    tokens = (
        _run_id.set(None if run_id is None else str(run_id)),
        _attempt_id.set(None if attempt_id is None else str(attempt_id)),
        _worker_id.set(None if worker_id is None else str(worker_id)),
    )
    try:
        yield
    finally:
        _run_id.reset(tokens[0])
        _attempt_id.reset(tokens[1])
        _worker_id.reset(tokens[2])


def log_context() -> dict[str, str]:
    """Return non-sensitive fields suitable for ``logger.*(..., extra=...)``."""
    return {
        k: v
        for k, v in {
            "run_id": _run_id.get(),
            "attempt_id": _attempt_id.get(),
            "worker_id": _worker_id.get(),
        }.items()
        if v is not None
    }


class CorrelationIdFilter(logging.Filter):
    """Add correlation fields to every record without copying request data."""

    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in log_context().items():
            setattr(record, key, value)
        return True


@dataclass(frozen=True)
class RunMetricsService:
    session_factory: async_sessionmaker[AsyncSession]

    async def snapshot(self, tenant_id: UUID | None = None) -> dict[str, Any]:
        async with self.session_factory() as session:
            return await self._snapshot(session, tenant_id)

    async def _snapshot(self, session: AsyncSession, tenant_id: UUID | None) -> dict[str, Any]:
        scope = Run.tenant_id == tenant_id if tenant_id is not None else true()
        run_counts = {
            status: int(count)
            for status, count in (
                await session.execute(
                    select(Run.status, func.count()).where(scope).group_by(Run.status)
                )
            ).all()
        }
        queue = (
            await session.execute(
                select(
                    func.count().label("depth"),
                    func.min(Run.queued_at).label("oldest"),
                    func.extract("epoch", func.now() - func.min(Run.queued_at)).label("wait"),
                ).where(scope, Run.status == RunStatus.QUEUED.value)
            )
        ).one()
        latency = (
            await session.execute(
                select(
                    func.avg(func.extract("epoch", Run.assigned_at - Run.queued_at)).label(
                        "scheduling"
                    ),
                    func.count()
                    .filter(Run.queue_reason.in_(("no_slot", "no_worker", "capacity")))
                    .label("no_slot"),
                ).where(scope)
            )
        ).one()
        attempts = (
            await session.execute(
                select(
                    RunAttempt.status,
                    func.count(),
                )
                .join(Run, Run.id == RunAttempt.run_id)
                .where(scope)
                .group_by(RunAttempt.status)
            )
        ).all()
        attempt_outcomes = {status: int(count) for status, count in attempts}
        workers = (
            await session.execute(
                select(
                    RunWorker.status,
                    func.count().label("workers"),
                    func.coalesce(func.sum(RunWorker.capacity), 0).label("capacity"),
                    func.max(RunWorker.heartbeat_at).label("last_heartbeat"),
                ).group_by(RunWorker.status)
            )
        ).all()
        worker_load = {
            str(status): {
                "workers": int(count),
                "capacity": int(capacity),
                "last_heartbeat": _iso(heartbeat),
            }
            for status, count, capacity, heartbeat in workers
        }
        active = (
            await session.execute(
                select(
                    RunAttempt.worker_id,
                    func.count().label("active"),
                )
                .join(Run, Run.id == RunAttempt.run_id)
                .where(
                    scope,
                    RunAttempt.status.in_(
                        (AttemptStatus.ASSIGNED.value, AttemptStatus.RUNNING.value)
                    ),
                )
                .group_by(RunAttempt.worker_id)
            )
        ).all()
        loads = {str(worker): int(count) for worker, count in active if worker is not None}
        lease = (
            await session.execute(
                select(func.count())
                .select_from(RunAttempt)
                .join(Run, Run.id == RunAttempt.run_id)
                .where(
                    scope,
                    RunAttempt.lease_expires_at.is_not(None),
                    RunAttempt.lease_expires_at < func.now(),
                    RunAttempt.status.in_(
                        (AttemptStatus.ASSIGNED.value, AttemptStatus.RUNNING.value)
                    ),
                )
            )
        ).scalar_one()
        outbox = (
            await session.execute(
                select(
                    func.count().label("backlog"),
                    func.coalesce(func.sum(RunOutbox.delivery_attempts), 0).label("retries"),
                ).where(
                    RunOutbox.delivered_at.is_(None),
                    *([RunOutbox.tenant_id == tenant_id] if tenant_id is not None else []),
                )
            )
        ).one()
        waiting = (
            await session.execute(
                select(Run.status, func.count())
                .where(
                    scope,
                    Run.status.in_(
                        (RunStatus.WAITING_APPROVAL.value, RunStatus.WAITING_INPUT.value)
                    ),
                )
                .group_by(Run.status)
            )
        ).all()
        usage = (
            await session.execute(
                select(
                    func.coalesce(func.sum(RunUsageRecord.total_tokens), 0),
                    func.coalesce(func.sum(RunUsageRecord.cost_cny), 0),
                )
                .join(Run, Run.id == RunUsageRecord.run_id)
                .where(scope)
            )
        ).one()
        duration = (
            await session.execute(
                select(
                    func.avg(func.extract("epoch", Run.finished_at - Run.started_at)),
                ).where(scope, Run.finished_at.is_not(None), Run.started_at.is_not(None))
            )
        ).scalar_one()
        return {
            "runs": {
                "counts": run_counts,
                "queue_depth": int(queue.depth or 0),
                "oldest_wait_seconds": _num(queue.wait),
                "oldest_queued_at": _iso(queue.oldest),
                "waiting": {str(k): int(v) for k, v in waiting},
            },
            "scheduling": {
                "latency_seconds": _num(latency.scheduling),
                "no_slot": int(latency.no_slot or 0),
                "fair_allocations": sum(attempt_outcomes.values()),
            },
            "workers": {"load": loads, "by_status": worker_load, "lease_expired": int(lease or 0)},
            "attempts": {"outcomes": attempt_outcomes, "duration_seconds": _num(duration)},
            "outbox": {"backlog": int(outbox.backlog or 0), "retries": int(outbox.retries or 0)},
            "usage": {"total_tokens": int(usage[0] or 0), "cost_cny": float(usage[1] or 0)},
        }


def _num(value: Any) -> float:
    return 0.0 if value is None else round(float(value), 6)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None

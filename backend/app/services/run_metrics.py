"""Read-only aggregate metrics for the Run control plane.

The service deliberately works from PostgreSQL facts and never calls a scheduler
or mutates a row.  Values are returned as plain dictionaries so this module can
be used by both the HTTP endpoint and a future Prometheus adapter.
"""

from __future__ import annotations

import contextvars
import logging
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select, text, true
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.run import Run, RunAttempt, RunEvent
from app.models.run_execution import RunUsageRecord
from app.models.run_scheduling import RunOutbox, RunWorker
from app.run_control.scheduling_policy import EligibilityReason
from app.run_control.types import AttemptStatus, RunStatus

_run_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("run_id", default=None)
_attempt_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("attempt_id", default=None)
_worker_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("worker_id", default=None)
_tenant_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("tenant_id", default=None)
_session_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("session_id", default=None)
_correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)


@contextmanager
def run_log_context(
    *,
    run_id: UUID | str | None = None,
    attempt_id: UUID | str | None = None,
    worker_id: UUID | str | None = None,
    tenant_id: UUID | str | None = None,
    session_id: UUID | str | None = None,
    correlation_id: UUID | str | None = None,
) -> Iterator[None]:
    """Bind safe correlation IDs to logs for the current async task.

    Only opaque identifiers are bound; callers must never put prompts, API keys,
    bearer tokens or model output into a log message.
    """
    tokens = (
        _run_id.set(None if run_id is None else str(run_id)),
        _attempt_id.set(None if attempt_id is None else str(attempt_id)),
        _worker_id.set(None if worker_id is None else str(worker_id)),
        _tenant_id.set(None if tenant_id is None else str(tenant_id)),
        _session_id.set(None if session_id is None else str(session_id)),
        _correlation_id.set(None if correlation_id is None else str(correlation_id)),
    )
    try:
        yield
    finally:
        _run_id.reset(tokens[0])
        _attempt_id.reset(tokens[1])
        _worker_id.reset(tokens[2])
        _tenant_id.reset(tokens[3])
        _session_id.reset(tokens[4])
        _correlation_id.reset(tokens[5])


def log_context() -> dict[str, str]:
    """Return non-sensitive fields suitable for ``logger.*(..., extra=...)``."""
    return {
        k: v
        for k, v in {
            "tenant_id": _tenant_id.get(),
            "session_id": _session_id.get(),
            "run_id": _run_id.get(),
            "attempt_id": _attempt_id.get(),
            "worker_id": _worker_id.get(),
            "correlation_id": _correlation_id.get(),
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

    async def snapshot(
        self, tenant_id: UUID | None = None, *, window: timedelta = timedelta(minutes=15)
    ) -> dict[str, Any]:
        if window <= timedelta(0):
            raise ValueError("window must be positive")
        async with self.session_factory() as session:
            return await self._snapshot(session, tenant_id, window)

    async def _snapshot(
        self, session: AsyncSession, tenant_id: UUID | None, window: timedelta
    ) -> dict[str, Any]:
        # Every metric in this projection documents its own fact timestamp.  A
        # Run can be created before the requested window and still be assigned,
        # completed, or charged inside it, so lifecycle facts must not inherit
        # ``Run.created_at`` as a universal filter.  The interval is half-open
        # in spirit: facts at/after ``cutoff`` are included; future-dated rows
        # are naturally excluded by the database clock on normal writes.
        cutoff = datetime.now(UTC).replace(tzinfo=None) - window
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
                ).where(scope, Run.assigned_at >= cutoff)
            )
        ).one()
        queue_reason = text("run_events.payload ->> 'reason'")
        no_slot_rows = (
            await session.execute(
                select(queue_reason, func.count())
                .select_from(RunEvent)
                .join(Run, Run.id == RunEvent.run_id)
                .where(
                    scope,
                    RunEvent.event_type == "run.queue_blocked",
                    RunEvent.created_at >= cutoff,
                    RunEvent.payload["reason"].astext.is_not(None),
                )
                .group_by(queue_reason)
            )
        ).all()
        attempts = (
            await session.execute(
                select(
                    RunAttempt.status,
                    func.count(),
                )
                .join(Run, Run.id == RunAttempt.run_id)
                .where(
                    scope,
                    or_(
                        RunAttempt.finished_at >= cutoff,
                        RunAttempt.finished_at.is_(None) & (Run.assigned_at >= cutoff),
                    ),
                )
                .group_by(RunAttempt.status)
            )
        ).all()
        attempt_outcomes = {status: int(count) for status, count in attempts}
        fair_rows = (
            await session.execute(
                select(Run.tenant_id, func.count())
                .join(RunAttempt, Run.id == RunAttempt.run_id)
                .where(
                    scope,
                    RunAttempt.worker_id.is_not(None),
                    Run.assigned_at >= cutoff,
                )
                .group_by(Run.tenant_id)
            )
        ).all()
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
        if tenant_id is not None:
            worker_projection: dict[str, Any] = {
                "load": {"active_attempts": sum(loads.values())},
                "availability": any(
                    str(status) == "online" and int(capacity) > 0
                    for status, _count, capacity, _heartbeat in workers
                ),
                "lease_expired": int(lease or 0),
            }
        else:
            worker_projection = {
                "load": loads,
                "by_status": worker_load,
                "lease_expired": int(lease or 0),
            }
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
        waiting_status = text("run_events.payload ->> 'status'")
        waiting = (
            await session.execute(
                select(waiting_status, func.count())
                .select_from(RunEvent)
                .join(Run, Run.id == RunEvent.run_id)
                .where(
                    scope,
                    RunEvent.created_at >= cutoff,
                    RunEvent.event_type.like("run.%"),
                    RunEvent.payload["status"].astext.in_(
                        (RunStatus.WAITING_APPROVAL.value, RunStatus.WAITING_INPUT.value)
                    ),
                )
                .group_by(waiting_status)
            )
        ).all()
        usage = (
            await session.execute(
                select(
                    func.coalesce(func.sum(RunUsageRecord.total_tokens), 0),
                    func.coalesce(func.sum(RunUsageRecord.cost_cny), 0),
                )
                .join(Run, Run.id == RunUsageRecord.run_id)
                .where(scope, RunUsageRecord.created_at >= cutoff)
            )
        ).one()
        duration = (
            await session.execute(
                select(
                    func.avg(func.extract("epoch", Run.finished_at - Run.started_at)),
                ).where(
                    scope,
                    Run.finished_at >= cutoff,
                    Run.finished_at.is_not(None),
                    Run.started_at.is_not(None),
                )
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
                "no_slot": count_no_slot_reasons(no_slot_rows),
                "fair_allocations": sum(int(count) for _tenant, count in fair_rows),
                "fair_allocations_by_tenant": {
                    str(tenant): int(count) for tenant, count in fair_rows
                },
            },
            "workers": worker_projection,
            "attempts": {"outcomes": attempt_outcomes, "duration_seconds": _num(duration)},
            "outbox": {"backlog": int(outbox.backlog or 0), "retries": int(outbox.retries or 0)},
            "usage": {"total_tokens": int(usage[0] or 0), "cost_cny": float(usage[1] or 0)},
            "window": {"since": cutoff.isoformat(), "seconds": int(window.total_seconds())},
        }


def _num(value: Any) -> float:
    return 0.0 if value is None else round(float(value), 6)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def count_no_slot_reasons(rows: Iterable[Any]) -> int:
    """Count queue facts blocked by the scheduler's real eligibility reasons."""
    reasons = {
        EligibilityReason.NO_WORKER_CAPACITY.value,
        EligibilityReason.TENANT_AT_CAPACITY.value,
    }
    return sum(int(count) for reason, count in rows if str(reason) in reasons)

"""Pure scheduling decisions shared by PostgreSQL orchestration and tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from fractions import Fraction
from uuid import UUID


class EligibilityReason(StrEnum):
    ELIGIBLE = "eligible"
    RUN_NOT_QUEUED = "run_not_queued"
    CANCEL_REQUESTED = "cancel_requested"
    UNRESOLVED_PAUSE = "unresolved_pause"
    SESSION_BUSY = "session_busy"
    TENANT_AT_CAPACITY = "tenant_at_capacity"
    NO_WORKER_CAPACITY = "no_worker_capacity"


class RecoveryDecision(StrEnum):
    CANCEL = "cancel"
    RETRY = "retry"
    FAIL = "fail"


@dataclass(frozen=True)
class EligibilityCandidate:
    run_is_queued: bool
    cancel_requested: bool
    has_unresolved_pause: bool
    session_has_other_active_run: bool
    tenant_active_runs: int
    tenant_max_running_runs: int
    has_worker_capacity: bool


@dataclass(frozen=True)
class TenantCandidate:
    id: UUID
    last_dispatched_at: datetime | None


@dataclass(frozen=True)
class RunCandidate:
    id: UUID
    queued_at: datetime
    queue_reason: str | None


@dataclass(frozen=True)
class WorkerCandidate:
    id: UUID
    capacity: int
    active_attempts: int
    last_assigned_at: datetime | None


def eligibility_reason(candidate: EligibilityCandidate) -> EligibilityReason:
    if not candidate.run_is_queued:
        return EligibilityReason.RUN_NOT_QUEUED
    if candidate.cancel_requested:
        return EligibilityReason.CANCEL_REQUESTED
    if candidate.has_unresolved_pause:
        return EligibilityReason.UNRESOLVED_PAUSE
    if candidate.session_has_other_active_run:
        return EligibilityReason.SESSION_BUSY
    if candidate.tenant_active_runs >= candidate.tenant_max_running_runs:
        return EligibilityReason.TENANT_AT_CAPACITY
    if not candidate.has_worker_capacity:
        return EligibilityReason.NO_WORKER_CAPACITY
    return EligibilityReason.ELIGIBLE


def choose_tenant(candidates: list[TenantCandidate]) -> TenantCandidate | None:
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda item: (
            item.last_dispatched_at is not None,
            item.last_dispatched_at or datetime.min,
            item.id,
        ),
    )


def effective_queued_at(candidate: RunCandidate, *, boost_seconds: int) -> datetime:
    if boost_seconds < 0:
        raise ValueError("boost_seconds must be non-negative")
    if candidate.queue_reason == "resume":
        return candidate.queued_at - timedelta(seconds=boost_seconds)
    return candidate.queued_at


def choose_run(candidates: list[RunCandidate], *, boost_seconds: int) -> RunCandidate | None:
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda item: (effective_queued_at(item, boost_seconds=boost_seconds), item.id),
    )


def rank_workers(candidates: list[WorkerCandidate]) -> tuple[WorkerCandidate, ...]:
    for candidate in candidates:
        if candidate.capacity <= 0:
            raise ValueError("worker capacity must be positive")
        if candidate.active_attempts < 0:
            raise ValueError("worker active_attempts must be non-negative")
    return tuple(
        sorted(
            candidates,
            key=lambda item: (
                Fraction(item.active_attempts, item.capacity),
                item.last_assigned_at is not None,
                item.last_assigned_at or datetime.min,
                item.id,
            ),
        )
    )


def choose_worker(candidates: list[WorkerCandidate]) -> WorkerCandidate | None:
    ranked = rank_workers(candidates)
    return ranked[0] if ranked else None


def retry_decision(*, cancel_requested: bool, retry_count: int) -> RecoveryDecision:
    if retry_count < 0:
        raise ValueError("retry_count must be non-negative")
    if cancel_requested:
        return RecoveryDecision.CANCEL
    if retry_count < 1:
        return RecoveryDecision.RETRY
    return RecoveryDecision.FAIL

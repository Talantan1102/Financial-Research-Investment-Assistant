"""Lease-fenced Attempt commands backed by PostgreSQL row locks."""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.run import Run, RunAttempt
from app.models.run_scheduling import RunOutbox
from app.run_control.mutations import RunMutationStore
from app.run_control.types import AttemptStatus, OutboxType, RunControlError, RunStatus

MAX_RESULT_BYTES = 64 * 1024
MAX_ERROR_CODE_LENGTH = 64
MAX_ERROR_MESSAGE_LENGTH = 2000


class AttemptCommandRejected(RunControlError):  # noqa: N818 - public domain error
    """Raised when a fenced Attempt command is no longer authoritative."""


@dataclass(frozen=True)
class ClaimedAssignment:
    tenant_id: UUID
    run_id: UUID
    attempt_id: UUID
    worker_id: UUID
    claim_token: UUID
    lease_expires_at: datetime


@dataclass(frozen=True)
class ClaimResult:
    claimed: bool
    assignment: ClaimedAssignment | None


def _database_utc_now() -> Any:
    return func.timezone("UTC", func.statement_timestamp())


class AttemptService:
    """Own complete transactions for Worker claim, lease, and terminal commands."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        lease_duration: timedelta = timedelta(seconds=45),
    ) -> None:
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        self._session_factory = session_factory
        self._lease_duration = lease_duration

    async def claim(self, attempt_id: UUID, worker_id: UUID) -> ClaimResult:
        async with self._session_factory() as session, session.begin():
            attempt = await self._lock_attempt(session, attempt_id)
            if attempt is None:
                return ClaimResult(claimed=False, assignment=None)
            run = await self._lock_run(session, cast(UUID, attempt.run_id))
            if run is None:
                return ClaimResult(claimed=False, assignment=None)
            clock = (
                await session.execute(
                    select(
                        _database_utc_now().label("claimed_at"),
                        (_database_utc_now() + self._lease_duration).label("lease_expires_at"),
                    )
                )
            ).one()
            claimed_at = cast(datetime, clock.claimed_at)
            lease_expires_at = cast(datetime, clock.lease_expires_at)
            if not self._claimable(attempt, run, worker_id, claimed_at):
                return ClaimResult(claimed=False, assignment=None)

            claim_token = uuid4()
            cast(Any, attempt).status = AttemptStatus.RUNNING.value
            cast(Any, attempt).claim_token = claim_token
            cast(Any, attempt).claimed_at = claimed_at
            cast(Any, attempt).last_heartbeat_at = claimed_at
            cast(Any, attempt).lease_expires_at = lease_expires_at
            cast(Any, attempt).started_at = claimed_at
            await RunMutationStore(session).transition(
                run,
                RunStatus.RUNNING,
                "run.running",
                {"worker_id": str(worker_id)},
                attempt_id=cast(UUID, attempt.id),
            )
            cast(Any, run).started_at = claimed_at
            await self._acknowledge_outbox(
                session,
                attempt_id=cast(UUID, attempt.id),
                event_type=OutboxType.ATTEMPT_ASSIGNED,
                acknowledged_at=claimed_at,
            )
            return ClaimResult(
                claimed=True,
                assignment=ClaimedAssignment(
                    tenant_id=cast(UUID, run.tenant_id),
                    run_id=cast(UUID, run.id),
                    attempt_id=cast(UUID, attempt.id),
                    worker_id=worker_id,
                    claim_token=claim_token,
                    lease_expires_at=lease_expires_at,
                ),
            )

    async def renew(
        self,
        attempt_id: UUID,
        worker_id: UUID,
        token: UUID,
    ) -> datetime:
        async with self._session_factory() as session, session.begin():
            attempt, run = await self._lock_command_context(session, attempt_id)
            clock = (
                await session.execute(
                    select(
                        _database_utc_now().label("heartbeat_at"),
                        (_database_utc_now() + self._lease_duration).label("lease_expires_at"),
                    )
                )
            ).one()
            heartbeat_at = cast(datetime, clock.heartbeat_at)
            lease_expires_at = cast(datetime, clock.lease_expires_at)
            self._require_authoritative(
                attempt,
                run,
                worker_id,
                token,
                heartbeat_at,
                required_run_status=RunStatus.RUNNING,
            )
            cast(Any, attempt).last_heartbeat_at = heartbeat_at
            cast(Any, attempt).lease_expires_at = lease_expires_at
            return lease_expires_at

    async def complete_simulated(
        self,
        attempt_id: UUID,
        worker_id: UUID,
        token: UUID,
        result: Mapping[str, Any],
    ) -> None:
        safe_result = self._bounded_result(result)
        async with self._session_factory() as session, session.begin():
            attempt, run = await self._lock_command_context(session, attempt_id)
            now = cast(datetime, await session.scalar(select(_database_utc_now())))
            self._require_authoritative(
                attempt,
                run,
                worker_id,
                token,
                now,
                required_run_status=RunStatus.RUNNING,
            )
            await self._after_authority_check()
            self._finish_attempt(attempt, AttemptStatus.COMPLETED, now)
            await RunMutationStore(session).transition(
                run,
                RunStatus.COMPLETED,
                "run.completed",
                {"result": safe_result},
                attempt_id=cast(UUID, attempt.id),
            )
            cast(Any, run).finished_at = now

    async def fail(
        self,
        attempt_id: UUID,
        worker_id: UUID,
        token: UUID,
        error_code: str,
        error_message: str,
    ) -> None:
        if not error_code or len(error_code) > MAX_ERROR_CODE_LENGTH:
            raise ValueError(f"error_code must be 1..{MAX_ERROR_CODE_LENGTH} characters")
        safe_message = error_message[:MAX_ERROR_MESSAGE_LENGTH]
        async with self._session_factory() as session, session.begin():
            attempt, run = await self._lock_command_context(session, attempt_id)
            now = cast(datetime, await session.scalar(select(_database_utc_now())))
            self._require_authoritative(
                attempt,
                run,
                worker_id,
                token,
                now,
                required_run_status=RunStatus.RUNNING,
            )
            self._finish_attempt(attempt, AttemptStatus.FAILED, now)
            cast(Any, attempt).error_code = error_code
            cast(Any, attempt).error_message = safe_message
            cast(Any, run).error_code = error_code
            cast(Any, run).error_message = safe_message
            await RunMutationStore(session).transition(
                run,
                RunStatus.FAILED,
                "run.failed",
                {"error_code": error_code, "error_message": safe_message},
                attempt_id=cast(UUID, attempt.id),
            )
            cast(Any, run).finished_at = now

    async def acknowledge_cancel(
        self,
        attempt_id: UUID,
        worker_id: UUID,
        token: UUID,
    ) -> None:
        async with self._session_factory() as session, session.begin():
            attempt, run = await self._lock_command_context(session, attempt_id)
            now = cast(datetime, await session.scalar(select(_database_utc_now())))
            self._require_authoritative(
                attempt,
                run,
                worker_id,
                token,
                now,
                required_run_status=RunStatus.CANCEL_REQUESTED,
            )
            self._finish_attempt(attempt, AttemptStatus.CANCELLED, now)
            await RunMutationStore(session).transition(
                run,
                RunStatus.CANCELLED,
                "run.cancelled",
                {},
                attempt_id=cast(UUID, attempt.id),
            )
            cast(Any, run).finished_at = now
            await self._acknowledge_outbox(
                session,
                attempt_id=cast(UUID, attempt.id),
                event_type=OutboxType.ATTEMPT_CANCEL,
                acknowledged_at=now,
            )

    async def _before_attempt_lock(self) -> None:
        """Deterministic concurrency seam; production performs no work here."""

    async def _lock_attempt(self, session: AsyncSession, attempt_id: UUID) -> RunAttempt | None:
        await self._before_attempt_lock()
        attempt = await session.scalar(
            select(RunAttempt).where(RunAttempt.id == attempt_id).with_for_update()
        )
        if attempt is not None:
            await self._after_attempt_lock(attempt)
        return attempt

    async def _after_attempt_lock(self, attempt: RunAttempt) -> None:
        """Deterministic concurrency seam; production performs no work here."""

    async def _after_authority_check(self) -> None:
        """Deterministic terminal-race seam; production performs no work here."""

    @staticmethod
    async def _lock_run(session: AsyncSession, run_id: UUID) -> Run | None:
        return await session.scalar(select(Run).where(Run.id == run_id).with_for_update())

    async def _lock_command_context(
        self,
        session: AsyncSession,
        attempt_id: UUID,
    ) -> tuple[RunAttempt, Run]:
        attempt = await self._lock_attempt(session, attempt_id)
        if attempt is None:
            raise AttemptCommandRejected("attempt command is no longer authoritative")
        run = await self._lock_run(session, cast(UUID, attempt.run_id))
        if run is None:
            raise AttemptCommandRejected("attempt command is no longer authoritative")
        return attempt, run

    @staticmethod
    def _claimable(
        attempt: RunAttempt,
        run: Run,
        worker_id: UUID,
        now: datetime,
    ) -> bool:
        return bool(
            cast(str, attempt.status) == AttemptStatus.ASSIGNED.value
            and attempt.worker_id == worker_id
            and attempt.claim_token is None
            and attempt.lease_expires_at is not None
            and cast(datetime, attempt.lease_expires_at) > now
            and cast(str, run.status) == RunStatus.ASSIGNED.value
            and run.cancel_requested_at is None
        )

    @staticmethod
    def _require_authoritative(
        attempt: RunAttempt,
        run: Run,
        worker_id: UUID,
        token: UUID,
        now: datetime,
        *,
        required_run_status: RunStatus,
    ) -> None:
        if not (
            cast(str, attempt.status) == AttemptStatus.RUNNING.value
            and attempt.worker_id == worker_id
            and attempt.claim_token == token
            and attempt.lease_expires_at is not None
            and cast(datetime, attempt.lease_expires_at) > now
            and cast(str, run.status) == required_run_status.value
        ):
            raise AttemptCommandRejected("attempt command is no longer authoritative")

    @staticmethod
    def _finish_attempt(
        attempt: RunAttempt,
        status: AttemptStatus,
        finished_at: datetime,
    ) -> None:
        cast(Any, attempt).status = status.value
        cast(Any, attempt).finished_at = finished_at
        cast(Any, attempt).claim_token = None

    @staticmethod
    async def _acknowledge_outbox(
        session: AsyncSession,
        *,
        attempt_id: UUID,
        event_type: OutboxType,
        acknowledged_at: datetime,
    ) -> None:
        await session.execute(
            update(RunOutbox)
            .where(
                RunOutbox.attempt_id == attempt_id,
                RunOutbox.event_type == event_type.value,
                RunOutbox.acknowledged_at.is_(None),
            )
            .values(acknowledged_at=acknowledged_at)
        )

    @staticmethod
    def _bounded_result(result: Mapping[str, Any]) -> dict[str, Any]:
        safe_result = deepcopy(dict(result))
        try:
            encoded = json.dumps(
                safe_result,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("result must be a JSON object") from exc
        if len(encoded) > MAX_RESULT_BYTES:
            raise ValueError(f"result exceeds {MAX_RESULT_BYTES} UTF-8 bytes")
        return safe_result

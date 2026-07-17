"""PostgreSQL-authoritative claiming and delivery state for run notifications."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from types import MappingProxyType
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.run_scheduling import RunOutbox
from app.run_control.types import OutboxType

SAFE_DELIVERY_ERROR_CODES = frozenset(
    {
        "delivery_failed",
        "redis_connection_error",
        "redis_delivery_error",
        "redis_timeout",
    }
)


def _database_utc_now() -> Any:
    return func.timezone("UTC", func.statement_timestamp())


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze_json(item) for item in value)
    return value


@dataclass(frozen=True)
class OutboxItem:
    """Immutable projection passed across the PostgreSQL/Redis boundary."""

    id: UUID
    event_type: OutboxType
    tenant_id: UUID
    run_id: UUID
    attempt_id: UUID | None
    worker_id: UUID | None
    payload: Mapping[str, Any]
    delivery_attempts: int

    @property
    def claim_generation(self) -> int:
        return self.delivery_attempts


class OutboxClaimRejected(RuntimeError):  # noqa: N818 - domain rejection, not fault
    """Raised when a stale Dispatcher tries to mutate a newer claim generation."""


def _safe_error_code(error_code: str) -> str:
    if len(error_code) > 32:
        return "delivery_failed"
    if error_code in SAFE_DELIVERY_ERROR_CODES:
        return error_code
    return "delivery_failed"


class RunOutboxService:
    """Own complete transactions for at-least-once Outbox delivery state."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        lock_timeout: timedelta = timedelta(seconds=30),
        retry_base: timedelta = timedelta(seconds=1),
        retry_cap: timedelta = timedelta(minutes=1),
    ) -> None:
        if lock_timeout <= timedelta(0):
            raise ValueError("lock_timeout must be positive")
        if retry_base <= timedelta(0):
            raise ValueError("retry_base must be positive")
        if retry_cap < retry_base:
            raise ValueError("retry_cap must be at least retry_base")
        self._session_factory = session_factory
        self._lock_timeout = lock_timeout
        self._retry_base = retry_base
        self._retry_cap = retry_cap

    async def claim_batch(self, dispatcher_id: UUID, limit: int) -> tuple[OutboxItem, ...]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        async with self._session_factory() as session, session.begin():
            now = cast(Any, await session.scalar(select(_database_utc_now())))
            await self._before_claim_selection()
            rows = (
                await session.scalars(
                    select(RunOutbox)
                    .where(
                        RunOutbox.acknowledged_at.is_(None),
                        RunOutbox.available_at <= now,
                        or_(
                            RunOutbox.next_attempt_at.is_(None),
                            RunOutbox.next_attempt_at <= now,
                        ),
                        or_(
                            RunOutbox.claimed_at.is_(None),
                            RunOutbox.claimed_at <= now - self._lock_timeout,
                        ),
                    )
                    .order_by(
                        func.coalesce(RunOutbox.next_attempt_at, RunOutbox.available_at),
                        RunOutbox.created_at,
                        RunOutbox.id,
                    )
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            items: list[OutboxItem] = []
            for row in rows:
                cast(Any, row).claimed_at = now
                cast(Any, row).claimed_by = str(dispatcher_id)
                cast(Any, row).delivery_attempts = cast(int, row.delivery_attempts) + 1
                items.append(self._project(row))
            return tuple(items)

    async def mark_delivered(
        self,
        item_id: UUID,
        dispatcher_id: UUID,
        expected_delivery_attempts: int,
    ) -> None:
        async with self._session_factory() as session, session.begin():
            row = await self._lock_owned_item(
                session,
                item_id,
                dispatcher_id,
                expected_delivery_attempts,
            )
            now = cast(Any, await session.scalar(select(_database_utc_now())))
            cast(Any, row).delivered_at = now
            cast(Any, row).claimed_at = None
            cast(Any, row).claimed_by = None
            cast(Any, row).last_error = None
            if cast(str, row.event_type) == OutboxType.SCHEDULE_WAKE.value:
                cast(Any, row).acknowledged_at = now
                cast(Any, row).next_attempt_at = None
            elif row.acknowledged_at is None:
                cast(Any, row).next_attempt_at = now + self._retry_delay(
                    cast(int, row.delivery_attempts)
                )

    async def mark_failed(
        self,
        item_id: UUID,
        dispatcher_id: UUID,
        expected_delivery_attempts: int,
        error_code: str,
    ) -> None:
        safe_error = _safe_error_code(error_code)
        async with self._session_factory() as session, session.begin():
            row = await self._lock_owned_item(
                session,
                item_id,
                dispatcher_id,
                expected_delivery_attempts,
            )
            now = cast(Any, await session.scalar(select(_database_utc_now())))
            cast(Any, row).claimed_at = None
            cast(Any, row).claimed_by = None
            cast(Any, row).last_error = safe_error
            cast(Any, row).next_attempt_at = now + self._retry_delay(
                cast(int, row.delivery_attempts)
            )

    async def _before_claim_selection(self) -> None:
        """Deterministic concurrency seam; production performs no work here."""

    @staticmethod
    async def _lock_owned_item(
        session: AsyncSession,
        item_id: UUID,
        dispatcher_id: UUID,
        expected_delivery_attempts: int,
    ) -> RunOutbox:
        row = await session.scalar(
            select(RunOutbox).where(RunOutbox.id == item_id).with_for_update()
        )
        if not (
            row is not None
            and row.claimed_at is not None
            and cast(str | None, row.claimed_by) == str(dispatcher_id)
            and cast(int, row.delivery_attempts) == expected_delivery_attempts
        ):
            raise OutboxClaimRejected("outbox claim is no longer authoritative")
        return row

    def _retry_delay(self, delivery_attempts: int) -> timedelta:
        exponent = max(delivery_attempts - 1, 0)
        max_whole_multiplier = max(self._retry_cap // self._retry_base, 1)
        max_uncapped_exponent = max_whole_multiplier.bit_length() - 1
        if exponent > max_uncapped_exponent:
            return self._retry_cap
        return min(self._retry_base * (1 << exponent), self._retry_cap)

    @staticmethod
    def _project(row: RunOutbox) -> OutboxItem:
        payload = _freeze_json(cast(Mapping[str, Any], row.payload))
        return OutboxItem(
            id=cast(UUID, row.id),
            event_type=OutboxType(cast(str, row.event_type)),
            tenant_id=cast(UUID, row.tenant_id),
            run_id=cast(UUID, row.run_id),
            attempt_id=cast(UUID | None, row.attempt_id),
            worker_id=cast(UUID | None, row.worker_id),
            payload=cast(Mapping[str, Any], payload),
            delivery_attempts=cast(int, row.delivery_attempts),
        )

"""PostgreSQL-authoritative claiming and delivery state for run notifications."""

from __future__ import annotations

import re
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

MAX_ERROR_BYTES = 1000


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


_URL_CREDENTIALS = re.compile(r"(?i)([a-z][a-z0-9+.-]*://)[^\s/@:]*:[^\s/@]+@")
_AUTHORIZATION = re.compile(r"(?i)\b(?:authorization\s*:\s*)?bearer\s+[^\s,;]+")
_CONNECTION_URL = re.compile(
    r"(?i)(?<![A-Z0-9_])[\"']?"
    r"(?:REDIS_URL|DATABASE_URL|POSTGRES_URL|CELERY_(?:BROKER|RESULT_BACKEND))[\"']?"
    r"\s*[:=]\s*(?:[\"'][^\"']*[\"']|[^\s,;}\]]+)"
)
_NAMED_CREDENTIAL = re.compile(
    r"(?i)(?<![A-Z0-9_])[\"']?"
    r"(?:[A-Z0-9_]*(?:PASSWORD|TOKEN|SECRET|API[_-]?KEY)[A-Z0-9_]*)[\"']?"
    r"\s*[:=]\s*(?:[\"'][^\"']*[\"']|[^\s,;}\]]+)"
)
_OPENAI_STYLE_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")


def _safe_error(error: str) -> str:
    sanitized = _URL_CREDENTIALS.sub(r"\1[REDACTED]@", str(error))
    sanitized = _AUTHORIZATION.sub("Authorization: [REDACTED]", sanitized)
    sanitized = _CONNECTION_URL.sub("[connection-url]=[REDACTED]", sanitized)
    sanitized = _NAMED_CREDENTIAL.sub("[credential]=[REDACTED]", sanitized)
    sanitized = _OPENAI_STYLE_KEY.sub("[REDACTED]", sanitized)
    encoded = sanitized.encode("utf-8")
    if len(encoded) <= MAX_ERROR_BYTES:
        return sanitized
    return encoded[:MAX_ERROR_BYTES].decode("utf-8", errors="ignore")


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

    async def mark_delivered(self, item_id: UUID) -> None:
        async with self._session_factory() as session, session.begin():
            row = await self._lock_item(session, item_id)
            if row is None:
                return
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

    async def mark_failed(self, item_id: UUID, error: str) -> None:
        safe_error = _safe_error(error)
        async with self._session_factory() as session, session.begin():
            row = await self._lock_item(session, item_id)
            if row is None:
                return
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
    async def _lock_item(session: AsyncSession, item_id: UUID) -> RunOutbox | None:
        return await session.scalar(
            select(RunOutbox).where(RunOutbox.id == item_id).with_for_update()
        )

    def _retry_delay(self, delivery_attempts: int) -> timedelta:
        exponent = max(delivery_attempts - 1, 0)
        delay = self._retry_base * (2**exponent)
        return min(delay, self._retry_cap)

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

"""Thin, signal-aware loop dispatching durable Outbox notifications to Redis."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any
from uuid import UUID, uuid4

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.processes.runtime import BoundedBackoff, ProcessHealth, is_transient_error
from app.run_control.redis_transport import RedisTransport
from app.services.run_metrics import log_context, run_log_context
from app.services.run_outbox import OutboxClaimRejected, RunOutboxService

logger = logging.getLogger(__name__)


class RunDispatcher:
    def __init__(
        self,
        outbox: RunOutboxService,
        transport: RedisTransport,
        *,
        dispatcher_id: UUID | None = None,
        batch_size: int = 100,
        poll_interval: float = 0.5,
        health: ProcessHealth | None = None,
        health_probe: Callable[[], Awaitable[Any]] | None = None,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if poll_interval <= 0:
            raise ValueError("poll_interval must be positive")
        self._outbox = outbox
        self._transport = transport
        self._dispatcher_id = dispatcher_id or uuid4()
        self._batch_size = batch_size
        self._poll_interval = poll_interval
        self._shutdown = asyncio.Event()
        self._health = health or ProcessHealth()
        self._backoff = BoundedBackoff()
        self._health_probe = health_probe

    async def dispatch_once(self) -> int:
        items = await self._outbox.claim_batch(self._dispatcher_id, self._batch_size)
        delivered = 0
        for item in items:
            with run_log_context(
                run_id=item.run_id, attempt_id=item.attempt_id, worker_id=item.worker_id
            ):
                logger.info(
                    "dispatching run outbox event type=%s", item.event_type, extra=log_context()
                )
                try:
                    await self._transport.publish(item)
                except (
                    RedisConnectionError,
                    RedisTimeoutError,
                    ResponseError,
                    ConnectionError,
                    TimeoutError,
                    OSError,
                ) as exc:
                    with suppress(OutboxClaimRejected):
                        await self._outbox.mark_failed(
                            item.id,
                            self._dispatcher_id,
                            item.claim_generation,
                            self._delivery_error_code(exc),
                        )
                    continue
            # Deliberately outside the Redis exception handler. If the process or
            # database fails after XADD, the claim expires and the item is sent again.
            try:
                await self._outbox.mark_delivered(
                    item.id,
                    self._dispatcher_id,
                    item.claim_generation,
                )
            except OutboxClaimRejected:
                continue
            delivered += 1
        return delivered

    async def run_forever(self) -> None:
        while not self._shutdown.is_set():
            try:
                if self._health_probe is not None:
                    await self._health_probe()
                    self._health.dependency_succeeded("redis")
                await self.dispatch_once()
                self._health.dependency_succeeded("postgres")
            except Exception as exc:
                if not is_transient_error(exc):
                    raise
                self._health.unhealthy()
                await self._backoff.wait(self._shutdown)
                continue
            self._backoff.reset()
            with suppress(TimeoutError):
                await asyncio.wait_for(self._shutdown.wait(), timeout=self._poll_interval)

    def request_shutdown(self) -> None:
        self._shutdown.set()

    def install_signal_handlers(self) -> None:
        def stop(_signum: int, _frame: object) -> None:
            self.request_shutdown()

        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)

    @staticmethod
    def _delivery_error_code(exc: Exception) -> str:
        if isinstance(exc, RedisTimeoutError | TimeoutError):
            return "redis_timeout"
        if isinstance(exc, RedisConnectionError | ConnectionError | OSError):
            return "redis_connection_error"
        return "redis_delivery_error"


async def _async_main() -> None:
    from redis.asyncio import Redis

    from app.core.async_database import build_async_database

    engine, factory = build_async_database()
    redis: Any = Redis.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=False
    )
    dispatcher = RunDispatcher(
        RunOutboxService(factory),
        RedisTransport(redis),
        batch_size=int(os.getenv("RUN_DISPATCH_BATCH_SIZE", "100")),
        poll_interval=float(os.getenv("RUN_POLL_INTERVAL_SECONDS", "0.5")),
        health_probe=redis.ping,
    )
    dispatcher.install_signal_handlers()
    try:
        await redis.ping()
        await dispatcher.run_forever()
    finally:
        dispatcher._health.unhealthy()
        with suppress(Exception):
            await redis.aclose()
        with suppress(Exception):
            await engine.dispose()


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()

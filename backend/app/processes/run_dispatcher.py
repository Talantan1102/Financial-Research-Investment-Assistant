"""Thin, signal-aware loop dispatching durable Outbox notifications to Redis."""

from __future__ import annotations

import asyncio
import os
import signal
from contextlib import suppress
from typing import Any
from uuid import UUID, uuid4

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.run_control.redis_transport import RedisTransport
from app.services.run_outbox import OutboxClaimRejected, RunOutboxService


class RunDispatcher:
    def __init__(
        self,
        outbox: RunOutboxService,
        transport: RedisTransport,
        *,
        dispatcher_id: UUID | None = None,
        batch_size: int = 100,
        poll_interval: float = 0.5,
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

    async def dispatch_once(self) -> int:
        items = await self._outbox.claim_batch(self._dispatcher_id, self._batch_size)
        delivered = 0
        for item in items:
            try:
                await self._transport.publish(item)
            except Exception as exc:
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
            await self.dispatch_once()
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
    from pathlib import Path

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
    )
    dispatcher.install_signal_handlers()
    try:
        await redis.ping()
        Path("/tmp/run-control-ready").touch()
        await dispatcher.run_forever()
    finally:
        await redis.aclose()
        await engine.dispose()


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()

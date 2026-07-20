"""Thin, signal-aware Scheduler process loop."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from contextlib import suppress
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.processes.runtime import BoundedBackoff, ProcessHealth, is_transient_error
from app.services.run_metrics import log_context, run_log_context
from app.services.scheduling_service import SchedulingService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SchedulerCycle:
    recovered: int
    scheduled: int


class RunScheduler:
    """Drive only the public SchedulingService API; PostgreSQL remains authoritative."""

    WAKE_STREAM = "run:scheduler:wake"

    def __init__(
        self,
        scheduling: SchedulingService,
        redis: Any | None,
        *,
        recovery_batch_size: int = 100,
        poll_interval: float = 0.5,
        health: ProcessHealth | None = None,
    ) -> None:
        if recovery_batch_size <= 0:
            raise ValueError("recovery_batch_size must be positive")
        if poll_interval <= 0:
            raise ValueError("poll_interval must be positive")
        self._scheduling = scheduling
        self._redis = redis
        self._recovery_batch_size = recovery_batch_size
        self._poll_interval = poll_interval
        self._shutdown = asyncio.Event()
        self._last_wake_id = "$"
        self._health = health or ProcessHealth()
        self._backoff = BoundedBackoff()

    async def run_cycle(self) -> SchedulerCycle:
        recovered = await self._scheduling.recover_expired_attempts(self._recovery_batch_size)
        scheduled = 0
        while not self._shutdown.is_set():
            assignment = await self._scheduling.schedule_once()
            if assignment is None:
                break
            with run_log_context(
                tenant_id=assignment.tenant_id,
                run_id=assignment.run_id,
                session_id=assignment.session_id,
                attempt_id=assignment.attempt_id,
                worker_id=assignment.worker_id,
                correlation_id=uuid4(),
            ):
                logger.info("scheduler assigned run", extra=log_context())
            scheduled += 1
        with run_log_context(correlation_id=uuid4()):
            logger.info(
                "scheduler cycle completed recovered=%d scheduled=%d",
                len(recovered),
                scheduled,
                extra=log_context(),
            )
        return SchedulerCycle(recovered=len(recovered), scheduled=scheduled)

    async def run_forever(self) -> None:
        while not self._shutdown.is_set():
            try:
                await self.run_cycle()
                self._health.dependency_succeeded("postgres")
                await self._wait_for_wake_or_poll()
                if self._redis is not None:
                    self._health.dependency_succeeded("redis")
                else:
                    self._health.healthy()
            except Exception as exc:
                if not is_transient_error(exc):
                    raise
                self._health.unhealthy()
                await self._backoff.wait(self._shutdown)
                continue
            self._backoff.reset()

    async def _wait_for_wake_or_poll(self) -> None:
        if self._redis is None:
            with suppress(TimeoutError):
                await asyncio.wait_for(self._shutdown.wait(), timeout=self._poll_interval)
            return
        try:
            response = await self._redis.xread(
                {self.WAKE_STREAM: self._last_wake_id},
                count=1,
                block=max(1, int(self._poll_interval * 1000)),
            )
            if response and response[0][1]:
                entry_id = response[0][1][-1][0]
                self._last_wake_id = (
                    entry_id.decode("ascii") if isinstance(entry_id, bytes) else str(entry_id)
                )
        except (RedisConnectionError, RedisTimeoutError, ResponseError, OSError):
            raise

    def request_shutdown(self) -> None:
        self._shutdown.set()

    def install_signal_handlers(self) -> None:
        def stop(_signum: int, _frame: object) -> None:
            self.request_shutdown()

        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)


async def _async_main() -> None:
    from redis.asyncio import Redis

    from app.core.async_database import build_async_database

    engine, factory = build_async_database()
    redis: Any = Redis.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=False
    )
    scheduler = RunScheduler(
        SchedulingService(
            factory,
            heartbeat_ttl=__import__("datetime").timedelta(
                seconds=float(os.getenv("RUN_HEARTBEAT_TTL_SECONDS", "30"))
            ),
            lease_duration=__import__("datetime").timedelta(
                seconds=float(os.getenv("RUN_LEASE_SECONDS", "45"))
            ),
        ),
        redis,
        recovery_batch_size=int(os.getenv("RUN_RECOVERY_BATCH_SIZE", "100")),
        poll_interval=float(os.getenv("RUN_POLL_INTERVAL_SECONDS", "0.5")),
    )
    scheduler.install_signal_handlers()
    try:
        await redis.ping()
        await scheduler.run_forever()
    finally:
        scheduler._health.unhealthy()
        with suppress(Exception):
            await redis.aclose()
        with suppress(Exception):
            await engine.dispose()


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()

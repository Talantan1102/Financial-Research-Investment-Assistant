"""Thin Redis consumer and lease-fenced Run Worker process loop."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
from contextlib import suppress
from typing import Any, Protocol
from uuid import UUID, uuid4

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.run_control.redis_transport import (
    InvalidRedisEnvelopeError,
    RedisTransport,
    parse_stream_envelope,
)
from app.run_control.types import OutboxType
from app.services.attempt_service import AttemptService, ClaimedAssignment
from app.services.run_outbox import OutboxItem
from app.services.worker_registry import WorkerRegistry


class RunExecutor(Protocol):
    async def execute(self, assignment: ClaimedAssignment) -> None: ...


class RunWorker:
    GROUP = "run-worker-assignments-v1"

    def __init__(
        self,
        registry: WorkerRegistry,
        attempts: AttemptService,
        redis: Any,
        transport: RedisTransport,
        executor: RunExecutor,
        *,
        capacity: int = 1,
        heartbeat_interval: float = 10.0,
        poll_interval: float = 0.5,
        pending_idle_ms: int = 1_000,
    ) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        if heartbeat_interval <= 0 or poll_interval <= 0:
            raise ValueError("worker intervals must be positive")
        if pending_idle_ms < 0:
            raise ValueError("pending_idle_ms must be nonnegative")
        self._registry = registry
        self._attempts = attempts
        self._redis = redis
        self._transport = transport
        self._executor = executor
        self._capacity = capacity
        self._heartbeat_interval = heartbeat_interval
        self._poll_interval = poll_interval
        self._pending_idle_ms = pending_idle_ms
        self._shutdown = asyncio.Event()
        self._worker_id: UUID | None = None
        self._stream_key: str | None = None
        self._consumer = str(uuid4())
        self._heartbeat_task: asyncio.Task[None] | None = None

    @property
    def worker_id(self) -> UUID | None:
        return self._worker_id

    async def start(self) -> UUID:
        if self._worker_id is not None:
            return self._worker_id
        snapshot = await self._registry.register(
            self._capacity,
            {"pid": os.getpid(), "hostname": socket.gethostname()},
        )
        self._worker_id = snapshot.id
        self._stream_key = f"run:worker:{snapshot.id}:assignments"
        await self._ensure_group()
        await self._recover_pending()
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        return snapshot.id

    async def run_forever(self) -> None:
        await self.start()
        assert self._stream_key is not None
        while not self._shutdown.is_set():
            try:
                response = await self._redis.xreadgroup(
                    self.GROUP,
                    self._consumer,
                    {self._stream_key: ">"},
                    count=self._capacity,
                    block=max(1, int(self._poll_interval * 1000)),
                )
            except (RedisConnectionError, RedisTimeoutError, OSError):
                await self._wait_poll()
                continue
            except ResponseError:
                await self._ensure_group()
                await self._recover_pending()
                continue
            for _key, entries in response:
                for raw_id, fields in entries:
                    entry_id = self._text(raw_id)
                    try:
                        item = parse_stream_envelope(fields)
                    except InvalidRedisEnvelopeError:
                        await self._transport.acknowledge_and_delete(
                            self._stream_key, self.GROUP, entry_id
                        )
                        continue
                    await self.handle_assignment(entry_id, item)
        await self.stop()

    async def handle_assignment(self, entry_id: str, item: OutboxItem) -> None:
        assert self._worker_id is not None and self._stream_key is not None
        if (
            item.event_type is not OutboxType.ATTEMPT_ASSIGNED
            or item.attempt_id is None
            or item.worker_id != self._worker_id
        ):
            await self._transport.acknowledge_and_delete(self._stream_key, self.GROUP, entry_id)
            return
        claim = await self._attempts.claim(item.attempt_id, self._worker_id)
        if claim.claimed and claim.assignment is not None:
            await self._executor.execute(claim.assignment)
        await self._transport.acknowledge_and_delete(self._stream_key, self.GROUP, entry_id)

    async def stop(self) -> None:
        if self._worker_id is None or self._stream_key is None:
            return
        self._shutdown.set()
        await self._registry.drain(self._worker_id)
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._heartbeat_task
            self._heartbeat_task = None
        await self._registry.mark_offline(self._worker_id)
        await self._transport.delete_stream(self._stream_key)

    async def _heartbeat_loop(self) -> None:
        assert self._worker_id is not None
        while not self._shutdown.is_set():
            await self._registry.heartbeat(self._worker_id)
            with suppress(TimeoutError):
                await asyncio.wait_for(self._shutdown.wait(), timeout=self._heartbeat_interval)

    async def _ensure_group(self) -> None:
        assert self._stream_key is not None
        try:
            await self._redis.xgroup_create(self._stream_key, self.GROUP, id="0-0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def _recover_pending(self) -> None:
        assert self._stream_key is not None
        start_id = "0-0"
        while True:
            recovery = await self._transport.recover_pending(
                self._stream_key,
                self.GROUP,
                self._consumer,
                min_idle_ms=self._pending_idle_ms,
                start_id=start_id,
            )
            for message in recovery.messages:
                await self.handle_assignment(message.entry_id, message.item)
            if recovery.next_start_id == "0-0" or recovery.next_start_id == start_id:
                break
            start_id = recovery.next_start_id

    async def _wait_poll(self) -> None:
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
    def _text(value: Any) -> str:
        return value.decode("ascii") if isinstance(value, bytes) else str(value)


async def _async_main() -> None:
    from pathlib import Path

    from redis.asyncio import Redis
    from tests.helpers.simulated_run_executor import SimulatedExecution, SimulatedRunExecutor

    from app.core.async_database import build_async_database

    engine, factory = build_async_database()
    redis: Any = Redis.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=False
    )
    attempts = AttemptService(
        factory,
        lease_duration=__import__("datetime").timedelta(
            seconds=float(os.getenv("RUN_LEASE_SECONDS", "45"))
        ),
    )
    instruction = SimulatedExecution(
        delay_seconds=float(os.getenv("RUN_SIMULATED_DELAY_SECONDS", "0")),
        result=json.loads(os.getenv("RUN_SIMULATED_RESULT_JSON", '{"simulated":true}')),
        crash=os.getenv("RUN_SIMULATED_CRASH", "0") == "1",
    )
    worker = RunWorker(
        WorkerRegistry(
            factory,
            heartbeat_ttl=__import__("datetime").timedelta(
                seconds=float(os.getenv("RUN_HEARTBEAT_TTL_SECONDS", "30"))
            ),
        ),
        attempts,
        redis,
        RedisTransport(redis),
        SimulatedRunExecutor(
            attempts,
            instruction=instruction,
            renew_interval=float(os.getenv("RUN_RENEW_INTERVAL_SECONDS", "10")),
        ),
        capacity=int(os.getenv("RUN_WORKER_CAPACITY", "1")),
        heartbeat_interval=float(os.getenv("RUN_HEARTBEAT_INTERVAL_SECONDS", "10")),
        poll_interval=float(os.getenv("RUN_POLL_INTERVAL_SECONDS", "0.5")),
        pending_idle_ms=int(os.getenv("RUN_PENDING_IDLE_MS", "1000")),
    )
    worker.install_signal_handlers()
    try:
        await redis.ping()
        await worker.start()
        Path("/tmp/run-control-ready").touch()
        await worker.run_forever()
    finally:
        await worker.stop()
        await redis.aclose()
        await engine.dispose()


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()

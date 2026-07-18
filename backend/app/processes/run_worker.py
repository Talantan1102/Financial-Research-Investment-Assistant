"""Thin Redis consumer and lease-fenced Run Worker process loop."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any, Protocol
from uuid import UUID, uuid4

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.processes.runtime import BoundedBackoff, ProcessHealth, is_transient_error
from app.run_control.redis_transport import (
    InvalidRedisEnvelopeError,
    RedisTransport,
    parse_stream_envelope,
)
from app.run_control.types import OutboxType
from app.services.attempt_service import AttemptCommandRejected, AttemptService, ClaimedAssignment
from app.services.run_outbox import OutboxItem
from app.services.run_stream_bus import RunStreamBus
from app.services.worker_registry import WorkerRegistry


def build_run_stream_event_sink(redis: Any) -> Callable[[Any], Awaitable[None]]:
    bus = RunStreamBus(redis)

    async def publish(event: Any) -> None:
        await bus.publish(event)

    return publish


class RunExecutor(Protocol):
    async def execute(self, assignment: ClaimedAssignment) -> None: ...


class RunWorker:
    GROUP = "run-worker-assignments-v1"
    CONTROL_GROUP = "run-worker-control-v1"

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
        shutdown_grace_seconds: float = 10.0,
        health: ProcessHealth | None = None,
    ) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        if heartbeat_interval <= 0 or poll_interval <= 0:
            raise ValueError("worker intervals must be positive")
        if pending_idle_ms < 0:
            raise ValueError("pending_idle_ms must be nonnegative")
        if shutdown_grace_seconds <= 0:
            raise ValueError("shutdown_grace_seconds must be positive")
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
        self._inflight: set[asyncio.Task[None]] = set()
        self._shutdown_grace_seconds = shutdown_grace_seconds
        self._health = health or ProcessHealth()
        self._backoff = BoundedBackoff()
        self._draining = False

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
        self._health.dependency_succeeded("postgres")
        self._stream_key = f"run:worker:{snapshot.id}:assignments"
        await self._ensure_group()
        await self._recover_pending()
        self._health.dependency_succeeded("redis")
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        return snapshot.id

    async def run_forever(self) -> None:
        await self.start()
        assert self._stream_key is not None
        while not self._shutdown.is_set():
            await self._monitor_heartbeat()
            available = self._capacity - len(self._inflight)
            if available <= 0:
                try:
                    await self._redis.ping()
                except (RedisConnectionError, RedisTimeoutError, ResponseError, OSError):
                    self._health.dependency_failed("redis")
                    await self._backoff.wait(self._shutdown)
                    await self._reconnect_assignment_stream()
                    continue
                self._health.dependency_succeeded("redis")
                await self._wait_for_inflight()
                continue
            try:
                response = await self._redis.xreadgroup(
                    self.GROUP,
                    self._consumer,
                    {self._stream_key: ">"},
                    count=available,
                    block=max(1, int(self._poll_interval * 1000)),
                )
            except (RedisConnectionError, RedisTimeoutError, OSError):
                self._health.dependency_failed("redis")
                await self._backoff.wait(self._shutdown)
                await self._reconnect_assignment_stream()
                continue
            except ResponseError as exc:
                if not is_transient_error(exc) and "NOGROUP" not in str(exc):
                    raise
                self._health.dependency_failed("redis")
                await self._backoff.wait(self._shutdown)
                await self._reconnect_assignment_stream()
                continue
            self._backoff.reset()
            self._health.dependency_succeeded("redis")
            if self._shutdown.is_set() or self._draining:
                break
            for _key, entries in response:
                for raw_id, fields in entries:
                    if self._shutdown.is_set() or self._draining:
                        break
                    entry_id = self._text(raw_id)
                    try:
                        item = parse_stream_envelope(fields)
                    except InvalidRedisEnvelopeError:
                        await self._transport.acknowledge_and_delete(
                            self._stream_key, self.GROUP, entry_id
                        )
                        continue
                    task = asyncio.create_task(self.handle_assignment(entry_id, item))
                    self._inflight.add(task)
        await self.stop()

    async def handle_assignment(self, entry_id: str, item: OutboxItem) -> None:
        assert self._worker_id is not None and self._stream_key is not None
        if self._shutdown.is_set() or self._draining:
            return
        if (
            item.event_type is not OutboxType.ATTEMPT_ASSIGNED
            or item.attempt_id is None
            or item.worker_id != self._worker_id
        ):
            await self._transport.acknowledge_and_delete(self._stream_key, self.GROUP, entry_id)
            return
        if self._shutdown.is_set() or self._draining:
            return
        claim = await self._attempts.claim(item.attempt_id, self._worker_id)
        if claim.claimed and claim.assignment is not None:
            await self._execute_with_cancel_control(claim.assignment)
        await self._transport.acknowledge_and_delete(self._stream_key, self.GROUP, entry_id)

    async def stop(self) -> None:
        if self._worker_id is None or self._stream_key is None:
            return
        self._shutdown.set()
        if not self._draining:
            self._draining = True
            with suppress(Exception):
                await self._registry.drain(self._worker_id)
        if self._inflight:
            done, pending = await asyncio.wait(self._inflight, timeout=self._shutdown_grace_seconds)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._heartbeat_task
            self._heartbeat_task = None
        with suppress(Exception):
            await self._registry.mark_offline(self._worker_id)
        # Never delete a Worker stream wholesale: unread assignments and its PEL
        # are durable acceleration state and must survive process replacement.
        self._health.unhealthy()

    async def _heartbeat_loop(self) -> None:
        assert self._worker_id is not None
        while not self._shutdown.is_set():
            await self._registry.heartbeat(self._worker_id)
            self._health.dependency_succeeded("postgres")
            with suppress(TimeoutError):
                await asyncio.wait_for(self._shutdown.wait(), timeout=self._heartbeat_interval)

    async def _monitor_heartbeat(self) -> None:
        if self._heartbeat_task is None or not self._heartbeat_task.done():
            return
        exc = self._heartbeat_task.exception()
        if exc is None:
            return
        if not is_transient_error(exc):
            raise exc
        self._health.dependency_failed("postgres")
        await self._backoff.wait(self._shutdown)
        if not self._shutdown.is_set():
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _wait_for_inflight(self) -> None:
        if not self._inflight:
            await self._wait_poll()
            return
        done, _pending = await asyncio.wait(
            self._inflight, timeout=self._poll_interval, return_when=asyncio.FIRST_COMPLETED
        )
        for task in done:
            self._inflight.discard(task)
            task.result()

    async def _reconnect_assignment_stream(self) -> None:
        try:
            await self._ensure_group()
            await self._recover_pending()
            self._health.dependency_succeeded("redis")
            if self._heartbeat_task is not None and self._heartbeat_task.done():
                with suppress(Exception):
                    self._heartbeat_task.exception()
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        except (RedisConnectionError, RedisTimeoutError, ResponseError, OSError):
            self._health.dependency_failed("redis")
            return

    async def _execute_with_cancel_control(self, assignment: ClaimedAssignment) -> None:
        control_key = f"run:attempt:{assignment.attempt_id}:control"
        await self._ensure_group_for(control_key, self.CONTROL_GROUP)
        if await self._recover_control_pending(control_key, assignment):
            with suppress(AttemptCommandRejected):
                await self._attempts.acknowledge_cancel(
                    assignment.attempt_id, assignment.worker_id, assignment.claim_token
                )
            return
        execution = asyncio.create_task(self._execute_assignment(assignment))
        control = asyncio.create_task(self._wait_for_cancel(control_key, assignment))
        done, _ = await asyncio.wait({execution, control}, return_when=asyncio.FIRST_COMPLETED)
        if execution in done:
            control.cancel()
            with suppress(asyncio.CancelledError):
                await control
            await execution
            return
        if control in done and control.result():
            requested = False
            request_cancel = getattr(self._executor, "request_cancel", None)
            if request_cancel is not None:
                requested = bool(request_cancel(assignment.attempt_id))
            if requested:
                try:
                    await asyncio.wait_for(execution, timeout=self._shutdown_grace_seconds)
                except TimeoutError:
                    execution.cancel()
                    with suppress(asyncio.CancelledError):
                        await execution
                    with suppress(AttemptCommandRejected):
                        await self._attempts.acknowledge_cancel(
                            assignment.attempt_id, assignment.worker_id, assignment.claim_token
                        )
            else:
                execution.cancel()
                with suppress(asyncio.CancelledError):
                    await execution
                with suppress(AttemptCommandRejected):
                    await self._attempts.acknowledge_cancel(
                        assignment.attempt_id, assignment.worker_id, assignment.claim_token
                    )
            return
        control.cancel()
        with suppress(asyncio.CancelledError):
            await control
        await execution

    async def _execute_assignment(self, assignment: ClaimedAssignment) -> None:
        execute_assignment = getattr(self._executor, "execute_assignment", None)
        if execute_assignment is not None:
            await execute_assignment(assignment)
            return
        await self._executor.execute(assignment)

    async def _wait_for_cancel(self, key: str, assignment: ClaimedAssignment) -> bool:
        while not self._shutdown.is_set():
            try:
                response = await self._redis.xreadgroup(
                    self.CONTROL_GROUP,
                    self._consumer,
                    {key: ">"},
                    count=1,
                    block=max(1, int(self._poll_interval * 1000)),
                )
            except (RedisConnectionError, RedisTimeoutError, OSError):
                await self._wait_poll()
                if await self._reconnect_control(key, assignment):
                    return True
                continue
            except ResponseError:
                if await self._reconnect_control(key, assignment):
                    return True
                continue
            for _stream, entries in response:
                for raw_id, fields in entries:
                    entry_id = self._text(raw_id)
                    try:
                        item = parse_stream_envelope(fields)
                    except InvalidRedisEnvelopeError:
                        await self._transport.acknowledge_and_delete(
                            key, self.CONTROL_GROUP, entry_id
                        )
                        continue
                    matches = (
                        item.event_type is OutboxType.ATTEMPT_CANCEL
                        and item.attempt_id == assignment.attempt_id
                        and item.worker_id == assignment.worker_id
                    )
                    await self._transport.acknowledge_and_delete(key, self.CONTROL_GROUP, entry_id)
                    if matches:
                        return True
        return False

    async def _ensure_group_for(self, key: str, group: str) -> None:
        try:
            await self._redis.xgroup_create(key, group, id="0-0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def _reconnect_control(self, key: str, assignment: ClaimedAssignment) -> bool:
        try:
            await self._ensure_group_for(key, self.CONTROL_GROUP)
            return await self._recover_control_pending(key, assignment)
        except (RedisConnectionError, RedisTimeoutError, ResponseError, OSError):
            return False

    async def _recover_control_pending(self, key: str, assignment: ClaimedAssignment) -> bool:
        recovery = await self._transport.recover_pending(
            key,
            self.CONTROL_GROUP,
            self._consumer,
            min_idle_ms=self._pending_idle_ms,
        )
        cancelled = False
        for message in recovery.messages:
            item = message.item
            matches = (
                item.event_type is OutboxType.ATTEMPT_CANCEL
                and item.attempt_id == assignment.attempt_id
                and item.worker_id == assignment.worker_id
            )
            await self._transport.acknowledge_and_delete(key, self.CONTROL_GROUP, message.entry_id)
            cancelled = cancelled or matches
        return cancelled

    async def _ensure_group(self) -> None:
        assert self._stream_key is not None
        await self._ensure_group_for(self._stream_key, self.GROUP)

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
    from redis.asyncio import Redis

    from app.core.async_database import build_async_database
    from app.run_control.simulated_executor import SimulatedExecution, SimulatedRunExecutor

    engine, factory = build_async_database()
    redis: Any = Redis.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=False
    )
    lease_seconds = float(os.getenv("RUN_LEASE_SECONDS", "45"))
    renew_seconds = float(os.getenv("RUN_RENEW_INTERVAL_SECONDS", "10"))
    if renew_seconds >= lease_seconds:
        raise ValueError("RUN_RENEW_INTERVAL_SECONDS must be shorter than RUN_LEASE_SECONDS")
    attempts = AttemptService(
        factory,
        lease_duration=__import__("datetime").timedelta(seconds=lease_seconds),
        history_limit=int(os.getenv("RUN_CHAT_HISTORY_LIMIT", "100")),
    )
    executor_mode = os.getenv("RUN_EXECUTOR_MODE", "simulated")
    mcp_context: Any = None
    if executor_mode == "chat":
        from app.chatloop.worker_wiring import build_heavy_singletons
        from app.services.mcp_client import MCPClient
        from app.services.run_chat_worker import (
            RunChatWorker,
            build_chat_executor_builder,
            load_continuation_keyring,
            load_tool_risk_policy,
            resolve_llm_identity,
        )

        continuation_keys = load_continuation_keyring(os.environ)
        mcp_context = MCPClient.from_subprocess(profile="chat_tools")
        mcp_client = await mcp_context.__aenter__()
        singletons = await build_heavy_singletons(
            session_factory=factory,
            mcp_client=mcp_client,
        )
        provider, model = resolve_llm_identity(singletons.llm)
        executor: RunExecutor = RunChatWorker(
            attempts=attempts,
            executor_builder=build_chat_executor_builder(
                singletons,
                provider=provider,
                model=model,
                risk_policy=load_tool_risk_policy(os.environ),
            ),
            continuation_keys=continuation_keys,
            renew_interval=renew_seconds,
            event_sink=build_run_stream_event_sink(redis),
        )
    elif executor_mode == "simulated":
        instruction = SimulatedExecution(
            delay_seconds=float(os.getenv("RUN_SIMULATED_DELAY_SECONDS", "0")),
            result=json.loads(os.getenv("RUN_SIMULATED_RESULT_JSON", '{"simulated":true}')),
            crash=os.getenv("RUN_SIMULATED_CRASH", "0") == "1",
        )
        executor = SimulatedRunExecutor(
            attempts,
            instruction=instruction,
            renew_interval=renew_seconds,
            lease_duration=lease_seconds,
        )
    else:
        raise ValueError("RUN_EXECUTOR_MODE must be 'chat' or 'simulated'")
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
        executor,
        capacity=int(os.getenv("RUN_WORKER_CAPACITY", "1")),
        heartbeat_interval=float(os.getenv("RUN_HEARTBEAT_INTERVAL_SECONDS", "10")),
        poll_interval=float(os.getenv("RUN_POLL_INTERVAL_SECONDS", "0.5")),
        pending_idle_ms=int(os.getenv("RUN_PENDING_IDLE_MS", "1000")),
    )
    worker.install_signal_handlers()
    try:
        await redis.ping()
        await worker.start()
        await worker.run_forever()
    finally:
        with suppress(Exception):
            await worker.stop()
        with suppress(Exception):
            await redis.aclose()
        if mcp_context is not None:
            with suppress(Exception):
                await mcp_context.__aexit__(None, None, None)
        with suppress(Exception):
            await engine.dispose()


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()

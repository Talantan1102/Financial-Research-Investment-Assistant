"""Evaluator-owned in-process scheduler and worker for disposable Run tests."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from app.services.attempt_service import AttemptService
from app.services.run_chat_worker import (
    ContinuationKeyring,
    ExecutorBuilder,
    RunChatWorker,
)
from app.services.scheduling_service import SchedulingService
from app.services.worker_registry import WorkerRegistry

AsyncCleanup = Callable[[], Awaitable[None]]
DurableResourceFactory = Callable[[], Awaitable[tuple[ExecutorBuilder, AsyncCleanup]]]


async def _noop_cleanup() -> None:
    return None


class InProcessDurableDriver:
    """Lazily advance real Runs through scheduler, claim, and RunChatWorker."""

    def __init__(
        self,
        session_factory: Any,
        *,
        resource_factory: DurableResourceFactory,
    ) -> None:
        self._session_factory = session_factory
        self._resource_factory = resource_factory
        self._registry = WorkerRegistry(session_factory)
        self._scheduler = SchedulingService(session_factory)
        self._attempts = AttemptService(session_factory)
        self._worker: RunChatWorker | None = None
        self._worker_id: UUID | None = None
        self._worker_needs_offline = False
        self._resource_cleanup: AsyncCleanup | None = None
        self._start_lock = asyncio.Lock()
        self._closed = False
        self._start_error: BaseException | None = None
        self.completed_advances = 0

    @classmethod
    def lazy(
        cls,
        session_factory: Any,
        *,
        resource_factory: DurableResourceFactory,
    ) -> InProcessDurableDriver:
        """Bind a driver synchronously; worker resources start on first advance."""
        return cls(session_factory, resource_factory=resource_factory)

    @classmethod
    async def create(
        cls,
        session_factory: Any,
        *,
        executor_builder: ExecutorBuilder,
    ) -> InProcessDurableDriver:
        """Backward-compatible eager construction for existing callers."""

        async def resources() -> tuple[ExecutorBuilder, AsyncCleanup]:
            return executor_builder, _noop_cleanup

        driver = cls.lazy(session_factory, resource_factory=resources)
        await driver.start()
        return driver

    @property
    def session_factory(self) -> Any:
        return self._session_factory

    @property
    def is_open(self) -> bool:
        return not self._closed and self._start_error is None

    @property
    def is_started(self) -> bool:
        return self._worker is not None and self._worker_id is not None

    @property
    def worker_id(self) -> UUID:
        if self._worker_id is None:
            raise RuntimeError("durable eval driver has not started")
        return self._worker_id

    async def start(self) -> None:
        """Initialize resources and register exactly one worker, safe under races."""
        async with self._start_lock:
            if self._closed:
                raise RuntimeError("durable eval driver is closed")
            if self._start_error is not None:
                raise RuntimeError("durable eval driver failed to start") from self._start_error
            if self.is_started:
                return

            cleanup: AsyncCleanup | None = None
            registered_worker_id: UUID | None = None
            worker: RunChatWorker | None = None
            try:
                executor_builder, cleanup = await self._resource_factory()
                if not callable(executor_builder) or not callable(cleanup):
                    raise TypeError(
                        "durable resource factory must return executor builder and async cleanup"
                    )
                worker_snapshot = await self._registry.register(
                    capacity=1,
                    metadata={"owner": "conversation-agent-eval", "mode": "in-process"},
                )
                registered_worker_id = worker_snapshot.id
                worker = RunChatWorker(
                    attempts=self._attempts,
                    executor_builder=executor_builder,
                    continuation_keys=ContinuationKeyring(
                        active_key_id="eval-v1",
                        keys={"eval-v1": b"eval-only-continuation-secret-32b"},
                    ),
                )
            except BaseException as exc:
                self._start_error = exc
                if registered_worker_id is not None:
                    self._worker_id = registered_worker_id
                    self._worker_needs_offline = True
                if cleanup is not None:
                    self._resource_cleanup = cleanup
                cleanup_errors = await self._release_resources()
                cancellation = (
                    exc
                    if isinstance(exc, asyncio.CancelledError)
                    else next(
                        (
                            failure
                            for failure in cleanup_errors
                            if isinstance(failure, asyncio.CancelledError)
                        ),
                        None,
                    )
                )
                if cancellation is not None:
                    if cancellation is not exc:
                        cancellation.add_note(f"durable start failed: {type(exc).__name__}: {exc}")
                    for cleanup_failure in cleanup_errors:
                        if cleanup_failure is cancellation:
                            continue
                        cancellation.add_note(
                            "additional durable cleanup failure: "
                            f"{type(cleanup_failure).__name__}: {cleanup_failure}"
                        )
                    raise cancellation
                for cleanup_failure in cleanup_errors:
                    exc.add_note(
                        "durable start cleanup failed: "
                        f"{type(cleanup_failure).__name__}: {cleanup_failure}"
                    )
                raise

            assert worker is not None
            assert registered_worker_id is not None
            self._worker_id = registered_worker_id
            self._worker_needs_offline = True
            self._worker = worker
            self._resource_cleanup = cleanup

    async def advance(self) -> bool:
        """Execute at most one assignment; repeated calls support resumed Runs."""
        if not self.is_open:
            if self._start_error is not None:
                raise RuntimeError("durable eval driver failed to start") from self._start_error
            raise RuntimeError("durable eval driver is closed")
        await self.start()
        worker = self._worker
        assert worker is not None
        await self._registry.heartbeat(self.worker_id)
        scheduled = await self._scheduler.schedule_once()
        if scheduled is None:
            return False
        if scheduled.worker_id != self.worker_id:
            raise RuntimeError(
                "durable eval scheduler assigned Run to an unexpected worker: "
                f"{scheduled.worker_id}"
            )
        claimed = await self._attempts.claim(scheduled.attempt_id, self.worker_id)
        if not claimed.claimed or claimed.assignment is None:
            raise RuntimeError("durable eval worker could not claim its scheduled attempt")
        if claimed.assignment.run_id != scheduled.run_id:
            raise RuntimeError("durable eval claim does not match the scheduled Run")
        await worker.execute_assignment(claimed.assignment)
        self.completed_advances += 1
        return True

    async def aclose(self) -> None:
        async with self._start_lock:
            if self._closed and not self._worker_needs_offline and self._resource_cleanup is None:
                return
            self._closed = True
            failures = await self._release_resources()
            self._worker = None
            if failures:
                primary = next(
                    (
                        failure
                        for failure in failures
                        if isinstance(failure, asyncio.CancelledError)
                    ),
                    failures[0],
                )
                for failure in failures:
                    if failure is primary:
                        continue
                    primary.add_note(
                        f"additional durable cleanup failure: {type(failure).__name__}: {failure}"
                    )
                raise primary

    async def _release_resources(self) -> list[BaseException]:
        """Try every pending cleanup inline and retain only failed handles."""
        failures: list[BaseException] = []
        if self._worker_needs_offline and self._worker_id is not None:
            try:
                await self._registry.mark_offline(self._worker_id)
            except BaseException as exc:
                failures.append(exc)
            else:
                self._worker_needs_offline = False
        cleanup = self._resource_cleanup
        if cleanup is not None:
            try:
                await cleanup()
            except BaseException as exc:
                failures.append(exc)
            else:
                self._resource_cleanup = None
        return failures


__all__ = [
    "AsyncCleanup",
    "DurableResourceFactory",
    "InProcessDurableDriver",
]

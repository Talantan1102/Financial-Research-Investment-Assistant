"""Evaluator-owned in-process scheduler and worker for disposable Run tests."""

from __future__ import annotations

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


class InProcessDurableDriver:
    """Advance one real queued Run through scheduler, claim, and RunChatWorker."""

    def __init__(
        self,
        session_factory: Any,
        *,
        registry: WorkerRegistry,
        scheduler: SchedulingService,
        attempts: AttemptService,
        worker: RunChatWorker,
        worker_id: UUID,
    ) -> None:
        self._session_factory = session_factory
        self._registry = registry
        self._scheduler = scheduler
        self._attempts = attempts
        self._worker = worker
        self.worker_id = worker_id
        self._closed = False
        self.completed_advances = 0

    @classmethod
    async def create(
        cls,
        session_factory: Any,
        *,
        executor_builder: ExecutorBuilder,
    ) -> InProcessDurableDriver:
        registry = WorkerRegistry(session_factory)
        worker_snapshot = await registry.register(
            capacity=1,
            metadata={"owner": "conversation-agent-eval", "mode": "in-process"},
        )
        attempts = AttemptService(session_factory)
        worker = RunChatWorker(
            attempts=attempts,
            executor_builder=executor_builder,
            continuation_keys=ContinuationKeyring(
                active_key_id="eval-v1",
                keys={"eval-v1": b"eval-only-continuation-secret-32b"},
            ),
        )
        return cls(
            session_factory,
            registry=registry,
            scheduler=SchedulingService(session_factory),
            attempts=attempts,
            worker=worker,
            worker_id=worker_snapshot.id,
        )

    @property
    def session_factory(self) -> Any:
        return self._session_factory

    @property
    def is_open(self) -> bool:
        return not self._closed

    async def advance(self) -> bool:
        """Execute at most one assignment; repeated calls support resumed Runs."""
        if self._closed:
            raise RuntimeError("durable eval driver is closed")
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
        await self._worker.execute_assignment(claimed.assignment)
        self.completed_advances += 1
        return True

    async def aclose(self) -> None:
        if self._closed:
            return
        await self._registry.mark_offline(self.worker_id)
        self._closed = True


__all__ = ["InProcessDurableDriver"]

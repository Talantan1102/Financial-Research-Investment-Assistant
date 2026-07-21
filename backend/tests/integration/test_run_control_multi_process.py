from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from app.processes.run_scheduler import RunScheduler
from app.processes.run_worker import RunWorker
from app.run_control.redis_transport import serialize_envelope
from app.run_control.types import OutboxType
from app.services.attempt_service import ClaimedAssignment, ClaimResult
from app.services.run_outbox import OutboxItem
from redis import Redis
from redis.exceptions import ResponseError

from tests.helpers.run_control_compose_harness import ComposeRunControlHarness
from tests.helpers.simulated_run_executor import (
    SimulatedExecution,
    SimulatedRunCrash,
    SimulatedRunExecutor,
)


class FakeSchedulingService:
    def __init__(self) -> None:
        self.recoveries = 0
        self.scheduled = [self._assignment(), self._assignment(), None]

    @staticmethod
    def _assignment() -> SimpleNamespace:
        return SimpleNamespace(
            tenant_id=uuid4(),
            run_id=uuid4(),
            session_id=uuid4(),
            attempt_id=uuid4(),
            worker_id=uuid4(),
        )

    async def recover_expired_attempts(self, limit: int) -> tuple[object, ...]:
        assert limit == 7
        self.recoveries += 1
        return (object(),)

    async def schedule_once(self) -> object | None:
        return self.scheduled.pop(0)


async def test_scheduler_recovers_then_drains_immediate_work() -> None:
    service = FakeSchedulingService()
    scheduler = RunScheduler(service, redis=None, recovery_batch_size=7, poll_interval=0.01)

    cycle = await scheduler.run_cycle()

    assert cycle.recovered == 1
    assert cycle.scheduled == 2
    assert service.recoveries == 1
    assert service.scheduled == []


class FakeAttemptService:
    def __init__(self, *, claimed: bool = True) -> None:
        self.claimed = claimed
        self.claim_calls = 0
        self.renew_calls = 0
        self.completed: list[dict[str, Any]] = []
        self.cancelled: list[UUID] = []

    async def claim(self, attempt_id: UUID, worker_id: UUID) -> ClaimResult:
        self.claim_calls += 1
        assignment = ClaimedAssignment(
            tenant_id=uuid4(),
            run_id=uuid4(),
            attempt_id=attempt_id,
            worker_id=worker_id,
            claim_token=uuid4(),
            lease_expires_at=datetime.now(UTC) + timedelta(seconds=30),
        )
        return ClaimResult(claimed=self.claimed, assignment=assignment if self.claimed else None)

    async def renew(self, attempt_id: UUID, worker_id: UUID, token: UUID) -> datetime:
        self.renew_calls += 1
        return datetime.now(UTC) + timedelta(seconds=30)

    async def complete_simulated(
        self,
        attempt_id: UUID,
        worker_id: UUID,
        token: UUID,
        result: dict[str, Any],
    ) -> None:
        self.completed.append(result)

    async def acknowledge_cancel(self, attempt_id: UUID, worker_id: UUID, token: UUID) -> None:
        self.cancelled.append(attempt_id)


async def test_simulated_executor_renews_long_work_and_completes_via_attempt_service() -> None:
    attempts = FakeAttemptService()
    assignment = (await attempts.claim(uuid4(), uuid4())).assignment
    assert assignment is not None
    executor = SimulatedRunExecutor(attempts, renew_interval=0.01)

    await executor.execute(
        assignment,
        SimulatedExecution(delay_seconds=0.035, result={"answer": 42}),
    )

    assert attempts.renew_calls >= 2
    assert attempts.completed == [{"answer": 42}]


async def test_simulated_executor_crash_leaves_attempt_for_lease_recovery() -> None:
    attempts = FakeAttemptService()
    assignment = (await attempts.claim(uuid4(), uuid4())).assignment
    assert assignment is not None
    executor = SimulatedRunExecutor(attempts, renew_interval=0.01)

    with pytest.raises(SimulatedRunCrash):
        await executor.execute(assignment, SimulatedExecution(crash=True))

    assert attempts.completed == []


@dataclass
class FakeWorkerSnapshot:
    id: UUID


class FakeWorkerRegistry:
    def __init__(self) -> None:
        self.worker_id = uuid4()
        self.register_calls = 0
        self.heartbeats = 0
        self.drained = False
        self.offline = False

    async def register(self, capacity: int, metadata: dict[str, Any]) -> FakeWorkerSnapshot:
        assert capacity == 1
        assert "pid" in metadata
        self.register_calls += 1
        return FakeWorkerSnapshot(self.worker_id)

    async def heartbeat(self, worker_id: UUID) -> None:
        assert worker_id == self.worker_id
        self.heartbeats += 1

    async def drain(self, worker_id: UUID) -> None:
        assert worker_id == self.worker_id
        self.drained = True

    async def mark_offline(self, worker_id: UUID) -> None:
        assert worker_id == self.worker_id
        self.offline = True


class FakeRedis:
    def __init__(self) -> None:
        self.group_created = False

    async def xgroup_create(self, key: str, group: str, *, id: str, mkstream: bool) -> bool:
        assert key.endswith(":assignments") or key.endswith(":control")
        assert id == "0-0"
        assert mkstream is True
        self.group_created = True
        return True

    async def xreadgroup(self, *args: Any, **kwargs: Any) -> list[Any]:
        await __import__("asyncio").sleep(3600)
        return []


class FakeTransport:
    def __init__(self) -> None:
        self.acked: list[str] = []
        self.deleted: list[str] = []

    async def recover_pending(self, *args: Any, **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(messages=(), next_start_id="0-0")

    async def acknowledge_and_delete(self, key: str, group: str, entry_id: str) -> None:
        self.acked.append(entry_id)

    async def delete_stream(self, key: str) -> int:
        self.deleted.append(key)
        return 1


class FakeExecutor:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, assignment: ClaimedAssignment) -> None:
        self.calls += 1


class BlockingExecutor:
    def __init__(self) -> None:
        self.started = __import__("asyncio").Event()
        self.cancelled = False

    async def execute(self, assignment: ClaimedAssignment) -> None:
        self.started.set()
        try:
            await __import__("asyncio").sleep(3600)
        except __import__("asyncio").CancelledError:
            self.cancelled = True
            raise


class CancelRedis(FakeRedis):
    def __init__(self, item: OutboxItem) -> None:
        super().__init__()
        self.item = item
        self.sent = False

    async def xreadgroup(self, *args: Any, **kwargs: Any) -> list[Any]:
        if not self.sent:
            self.sent = True
            return [(b"control", [(b"1-0", {b"data": serialize_envelope(self.item)})])]
        await __import__("asyncio").sleep(3600)
        return []


class ReconnectRedis(FakeRedis):
    async def xreadgroup(self, *args: Any, **kwargs: Any) -> list[Any]:
        raise ResponseError("NOGROUP after reconnect")


class ShutdownAfterReadRedis(FakeRedis):
    def __init__(self, item: OutboxItem) -> None:
        super().__init__()
        self.item = item
        self.worker: RunWorker | None = None

    async def xreadgroup(self, *args: Any, **kwargs: Any) -> list[Any]:
        assert self.worker is not None
        self.worker.request_shutdown()
        return [(b"assignments", [(b"3-0", {b"data": serialize_envelope(self.item)})])]


class GraceExecutor:
    def __init__(self) -> None:
        self.started = __import__("asyncio").Event()
        self.release = __import__("asyncio").Event()

    async def execute(self, assignment: ClaimedAssignment) -> None:
        self.started.set()
        await self.release.wait()


class RecoveringCancelTransport(FakeTransport):
    def __init__(self, item: OutboxItem) -> None:
        super().__init__()
        self.item = item
        self.recoveries = 0

    async def recover_pending(self, *args: Any, **kwargs: Any) -> SimpleNamespace:
        self.recoveries += 1
        messages = ()
        if self.recoveries >= 3:
            messages = (SimpleNamespace(entry_id="2-0", item=self.item),)
        return SimpleNamespace(messages=messages, next_start_id="0-0")


async def test_worker_duplicate_assignment_claims_and_executes_only_once() -> None:
    registry = FakeWorkerRegistry()
    attempts = FakeAttemptService()
    redis = FakeRedis()
    transport = FakeTransport()
    executor = FakeExecutor()
    worker = RunWorker(
        registry,
        attempts,
        redis,
        transport,
        executor,
        capacity=1,
        heartbeat_interval=0.01,
        poll_interval=0.01,
    )
    await worker.start()
    attempt_id = uuid4()
    item = SimpleNamespace(
        event_type=OutboxType.ATTEMPT_ASSIGNED,
        tenant_id=uuid4(),
        run_id=uuid4(),
        attempt_id=attempt_id,
        worker_id=registry.worker_id,
    )

    await worker.handle_assignment("1-0", item)
    attempts.claimed = False
    await worker.handle_assignment("2-0", item)
    await worker.stop()

    assert attempts.claim_calls == 2
    assert executor.calls == 1
    assert transport.acked == ["1-0", "2-0"]
    assert registry.drained and registry.offline
    assert transport.deleted == []


async def test_worker_consumes_cancel_control_and_aborts_executor() -> None:
    registry = FakeWorkerRegistry()
    attempts = FakeAttemptService()
    attempt_id = uuid4()
    item = OutboxItem(
        id=uuid4(),
        event_type=OutboxType.ATTEMPT_CANCEL,
        tenant_id=uuid4(),
        run_id=uuid4(),
        attempt_id=attempt_id,
        worker_id=registry.worker_id,
        payload={},
        delivery_attempts=1,
    )
    redis = CancelRedis(item)
    transport = FakeTransport()
    executor = BlockingExecutor()
    worker = RunWorker(registry, attempts, redis, transport, executor, poll_interval=0.01)
    await worker.start()
    assignment = (await attempts.claim(attempt_id, registry.worker_id)).assignment
    assert assignment is not None

    await worker._execute_with_cancel_control(assignment)
    await worker.stop()

    assert executor.cancelled is True
    assert attempts.cancelled == [attempt_id]
    assert transport.acked == ["1-0"]


async def test_worker_completed_result_wins_when_cancel_control_finishes_simultaneously() -> None:
    registry = FakeWorkerRegistry()
    attempts = FakeAttemptService()
    executor = FakeExecutor()
    worker = RunWorker(
        registry,
        attempts,
        FakeRedis(),
        FakeTransport(),
        executor,
        poll_interval=0.01,
    )
    await worker.start()
    assignment = (await attempts.claim(uuid4(), registry.worker_id)).assignment
    assert assignment is not None

    async def immediate_cancel(_key: str, _assignment: ClaimedAssignment) -> bool:
        return True

    worker._wait_for_cancel = immediate_cancel  # type: ignore[method-assign]
    await worker._execute_with_cancel_control(assignment)
    await worker.stop()

    assert executor.calls == 1
    assert attempts.cancelled == []


async def test_worker_recovers_pending_cancel_after_nested_response_error() -> None:
    registry = FakeWorkerRegistry()
    attempts = FakeAttemptService()
    attempt_id = uuid4()
    item = OutboxItem(
        id=uuid4(),
        event_type=OutboxType.ATTEMPT_CANCEL,
        tenant_id=uuid4(),
        run_id=uuid4(),
        attempt_id=attempt_id,
        worker_id=registry.worker_id,
        payload={},
        delivery_attempts=1,
    )
    transport = RecoveringCancelTransport(item)
    executor = BlockingExecutor()
    worker = RunWorker(
        registry,
        attempts,
        ReconnectRedis(),
        transport,
        executor,
        poll_interval=0.01,
    )
    await worker.start()
    assignment = (await attempts.claim(attempt_id, registry.worker_id)).assignment
    assert assignment is not None

    await worker._execute_with_cancel_control(assignment)
    await worker.stop()

    assert executor.cancelled is True
    assert attempts.cancelled == [attempt_id]
    assert transport.acked == ["2-0"]


async def test_worker_does_not_claim_xread_result_after_shutdown() -> None:
    registry = FakeWorkerRegistry()
    attempts = FakeAttemptService()
    item = OutboxItem(
        id=uuid4(),
        event_type=OutboxType.ATTEMPT_ASSIGNED,
        tenant_id=uuid4(),
        run_id=uuid4(),
        attempt_id=uuid4(),
        worker_id=registry.worker_id,
        payload={},
        delivery_attempts=1,
    )
    redis = ShutdownAfterReadRedis(item)
    transport = FakeTransport()
    worker = RunWorker(registry, attempts, redis, transport, FakeExecutor(), poll_interval=0.01)
    redis.worker = worker

    await worker.run_forever()

    assert attempts.claim_calls == 0
    assert transport.acked == []
    assert registry.drained and registry.offline
    print("claims_after_shutdown=0")


async def test_worker_sigterm_drains_before_waiting_for_inflight_then_offlines() -> None:
    registry = FakeWorkerRegistry()
    attempts = FakeAttemptService()
    transport = FakeTransport()
    executor = GraceExecutor()
    worker = RunWorker(
        registry,
        attempts,
        FakeRedis(),
        transport,
        executor,
        poll_interval=0.01,
        shutdown_grace_seconds=1,
    )
    await worker.start()
    item = SimpleNamespace(
        event_type=OutboxType.ATTEMPT_ASSIGNED,
        tenant_id=uuid4(),
        run_id=uuid4(),
        attempt_id=uuid4(),
        worker_id=registry.worker_id,
    )
    inflight = __import__("asyncio").create_task(worker.handle_assignment("4-0", item))
    await executor.started.wait()
    worker._inflight.add(inflight)

    worker.request_shutdown()  # same state transition used by the SIGTERM handler
    stopping = __import__("asyncio").create_task(worker.stop())
    for _ in range(100):
        if registry.drained:
            break
        await __import__("asyncio").sleep(0.001)
    assert registry.drained is True
    assert registry.offline is False
    assert transport.deleted == []
    executor.release.set()
    await stopping

    assert registry.offline is True
    assert transport.acked == ["4-0"]


@pytest.mark.skipif(
    "RUN_CONTROL_ACCEPTANCE_IDS" not in os.environ,
    reason="opt-in Compose L2.5 fact audit",
)
def test_compose_l25_processes_and_postgres_facts() -> None:
    """Audit facts produced by real Compose processes, never coroutine stand-ins."""

    ids = json.loads(os.environ["RUN_CONTROL_ACCEPTANCE_IDS"])
    database_url = os.environ["RUN_CONTROL_ACCEPTANCE_DATABASE_URL"]
    project = os.getenv("RUN_CONTROL_COMPOSE_PROJECT", "rcp-phase2-task6")
    result = subprocess.run(
        ["docker", "compose", "-p", project, "ps", "--format", "json"],
        check=True,
        capture_output=True,
        encoding="utf-8",
        text=True,
    )
    processes = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    expected = {
        "run-scheduler-a",
        "run-scheduler-b",
        "run-dispatcher",
        "run-worker-a",
        "run-worker-b",
    }
    actual = {
        item["Service"]
        for item in processes
        if item["State"] == "running" and item["Health"] == "healthy"
    }
    assert expected <= actual

    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT runs.status, run_attempts.worker_id, runs.started_at, runs.finished_at "
            "FROM runs JOIN run_attempts ON run_attempts.run_id = runs.id "
            "WHERE runs.id = ANY(%s::uuid[]) ORDER BY runs.id",
            (ids["parallel"],),
        )
        parallel = cursor.fetchall()
        assert [row[0] for row in parallel] == ["completed", "completed"]
        assert len({row[1] for row in parallel}) == 2
        assert max(row[2] for row in parallel) < min(row[3] for row in parallel)

        cursor.execute(
            "SELECT status, retry_count, error_code FROM runs WHERE id = %s",
            (ids["crash"],),
        )
        assert cursor.fetchone() == ("failed", 1, "worker_lease_expired")
        cursor.execute(
            "SELECT attempt_no, status FROM run_attempts WHERE run_id = %s ORDER BY attempt_no",
            (ids["crash"],),
        )
        assert cursor.fetchall() == [(1, "lost"), (2, "lost")]

        cursor.execute(
            "SELECT status FROM runs WHERE id = %s",
            (ids["redis_restart"],),
        )
        assert cursor.fetchone() == ("completed",)
        cursor.execute(
            "SELECT delivery_attempts, delivered_at IS NOT NULL, "
            "acknowledged_at IS NOT NULL FROM run_outbox "
            "WHERE run_id = %s AND event_type = 'attempt.assigned'",
            (ids["redis_restart"],),
        )
        assert cursor.fetchone() == (1, True, True)

        cursor.execute(
            "SELECT started_at, finished_at FROM runs "
            "WHERE id = ANY(%s::uuid[]) ORDER BY started_at",
            (ids["serial"],),
        )
        serial = cursor.fetchall()
        assert len(serial) == 2
        assert serial[0][1] <= serial[1][0]

        cursor.execute(
            "SELECT worker_id FROM run_attempts WHERE run_id = %s",
            (ids["duplicate"],),
        )
        duplicate_worker = cursor.fetchone()[0]
        cursor.execute(
            "SELECT count(*), max(seq), "
            "count(*) FILTER (WHERE event_type = 'run.completed') "
            "FROM run_events WHERE run_id = %s",
            (ids["duplicate"],),
        )
        assert cursor.fetchone() == (4, 4, 1)
        cursor.execute(
            "SELECT count(*) FROM run_attempts WHERE run_id = %s",
            (ids["duplicate"],),
        )
        assert cursor.fetchone() == (1,)

    redis = Redis.from_url(os.environ["RUN_CONTROL_ACCEPTANCE_REDIS_URL"])
    try:
        key = f"run:worker:{duplicate_worker}:assignments"
        assert redis.xlen(key) == 0
    finally:
        redis.close()


@pytest.mark.skipif(
    os.getenv("RUN_CONTROL_COMPOSE_SELF_BOOTSTRAP") != "1",
    reason="opt-in self-bootstrapping Compose L2.5 scenario",
)
def test_compose_l25_self_bootstraps_all_failure_scenarios() -> None:
    repo_root = Path(__file__).resolve().parents[3]

    result = ComposeRunControlHarness(repo_root).run()

    assert len(set(result.parallel_runs)) == 2
    assert result.crash_run not in result.parallel_runs
    assert result.redis_restart_run not in result.parallel_runs
    assert len(set(result.serial_runs)) == 2
    assert result.cancel_run not in result.parallel_runs
    assert len(set(result.capacity_runs)) == 2
    assert result.postgres_restart_run not in result.parallel_runs
    assert result.full_capacity_run not in result.parallel_runs


@pytest.mark.skipif(
    os.getenv("RUN_CONTROL_COMPOSE_CLEANUP_FAILURE_INJECTION") != "1",
    reason="opt-in fresh Compose cleanup failure injection",
)
def test_compose_cleanup_is_verified_after_injected_scenario_failure() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    previous = os.environ.get("RUN_CONTROL_INJECT_FAILURE_AFTER_UP")
    os.environ["RUN_CONTROL_INJECT_FAILURE_AFTER_UP"] = "1"
    try:
        with pytest.raises(RuntimeError, match="injected failure after Compose up"):
            ComposeRunControlHarness(repo_root).run()
    finally:
        if previous is None:
            os.environ.pop("RUN_CONTROL_INJECT_FAILURE_AFTER_UP", None)
        else:
            os.environ["RUN_CONTROL_INJECT_FAILURE_AFTER_UP"] = previous

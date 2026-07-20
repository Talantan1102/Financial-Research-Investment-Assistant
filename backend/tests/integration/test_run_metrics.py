"""Contract tests for the read-only Run metrics projection.

The production fixture runs these queries against PostgreSQL; this focused test
keeps the contract fast and deterministic by supplying aggregate result rows.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.models.run import Run, RunAttempt, RunEvent, RunMessage, RunSession
from app.models.run_execution import RunUsageRecord
from app.models.run_scheduling import RunWorker
from app.models.tenant import Tenant
from app.models.user import User
from app.run_control.scheduling_policy import EligibilityReason
from app.run_control.types import AttemptStatus, RunStatus, WorkerStatus
from app.services.run_metrics import RunMetricsService, count_no_slot_reasons


@pytest.fixture
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    if hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


class _Result:
    def __init__(self, rows=(), scalar=None):
        self._rows = rows
        self._scalar = scalar

    def all(self):
        return self._rows

    def one(self):
        return self._rows[0]

    def scalar_one(self):
        return self._scalar


class _Session:
    def __init__(self):
        self.statements = []
        self._results = iter(
            [
                _Result([("completed", 2), ("queued", 1)]),
                _Result([SimpleNamespace(depth=1, oldest=None, wait=4.5)]),
                _Result([SimpleNamespace(scheduling=1.2)]),
                _Result([(EligibilityReason.NO_WORKER_CAPACITY.value, 1)]),
                _Result([("completed", 2)]),
                _Result([("tenant-a", 2), ("tenant-b", 1)]),
                _Result([("online", 1, 2, None)]),
                _Result([(uuid4(), 1)]),
                _Result(scalar=0),
                _Result([SimpleNamespace(backlog=1, retries=2)]),
                _Result([("waiting_input", 1)]),
                _Result([(15, 0.25)]),
                _Result(scalar=3.0),
            ]
        )

    async def execute(self, statement):
        self.statements.append(statement)
        return next(self._results)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


@pytest.mark.asyncio
async def test_metrics_are_aggregate_read_only_projection():
    session = _Session()

    class _Factory:
        def __call__(self):
            return session

    result = await RunMetricsService(_Factory()).snapshot(uuid4())
    assert result["runs"]["counts"] == {"completed": 2, "queued": 1}
    assert result["runs"]["queue_depth"] == 1
    assert result["scheduling"]["no_slot"] == 1
    assert result["outbox"] == {"backlog": 1, "retries": 2}
    assert result["usage"] == {"total_tokens": 15, "cost_cny": 0.25}
    assert result["scheduling"]["fair_allocations"] == 3
    assert result["scheduling"]["fair_allocations_by_tenant"] == {"tenant-a": 2, "tenant-b": 1}
    assert len(session.statements) == 13
    assert not any(getattr(statement, "is_update", False) for statement in session.statements)


@pytest.mark.asyncio
async def test_tenant_metrics_do_not_expose_global_worker_pool_details():
    session = _Session()

    class _Factory:
        def __call__(self):
            return session

    result = await RunMetricsService(_Factory()).snapshot(uuid4())
    workers = result["workers"]
    assert "by_status" not in workers
    assert "capacity" not in str(workers)
    assert "last_heartbeat" not in str(workers)


def test_no_slot_metric_uses_scheduler_eligibility_reason_values():
    rows = [
        (EligibilityReason.NO_WORKER_CAPACITY.value, 2),
        (EligibilityReason.TENANT_AT_CAPACITY.value, 1),
        ("resume", 99),
    ]
    assert count_no_slot_reasons(rows) == 3


@pytest.mark.asyncio
async def test_fact_window_counts_long_running_run_created_before_window(
    pg_async_session_factory,
) -> None:
    """Each aggregate uses its fact timestamp, not Run.created_at as a proxy."""
    now = datetime.utcnow()
    old = now - timedelta(days=2)
    fact = now - timedelta(minutes=5)
    tenant_id = uuid4()
    user_id = uuid4()
    session_id = uuid4()
    run_id = uuid4()
    attempt_id = uuid4()
    worker_id = uuid4()
    message_id = uuid4()
    async with pg_async_session_factory() as session:
        session.add_all(
            [
                User(
                    id=user_id,
                    username=f"metrics-{user_id}",
                    email=f"metrics-{user_id}@example.com",
                    hashed_password="test",
                ),
                Tenant(id=tenant_id, name="metrics", slug=f"metrics-{tenant_id}"),
                RunWorker(
                    id=worker_id,
                    worker_type="chat",
                    capacity=1,
                    status=WorkerStatus.ONLINE.value,
                    heartbeat_at=fact,
                    started_at=old,
                ),
            ]
        )
        await session.flush()
        session.add(RunSession(id=session_id, tenant_id=tenant_id, created_by_user_id=user_id))
        await session.flush()
        session.add(
            RunMessage(
                id=message_id,
                tenant_id=tenant_id,
                session_id=session_id,
                role="user",
                content="metrics fixture",
                status="complete",
                created_at=old,
            )
        )
        await session.flush()
        session.add(
            Run(
                id=run_id,
                tenant_id=tenant_id,
                session_id=session_id,
                created_by_user_id=user_id,
                run_type="chat",
                status=RunStatus.COMPLETED.value,
                idempotency_key=f"metrics-{run_id}",
                request_hash="0" * 64,
                input_message_id=message_id,
                revision_seq=1,
                created_at=old,
                queued_at=old,
                assigned_at=fact,
                started_at=fact,
                finished_at=fact + timedelta(seconds=12),
            )
        )
        await session.flush()
        session.add(
            RunAttempt(
                id=attempt_id,
                run_id=run_id,
                attempt_no=1,
                status=AttemptStatus.COMPLETED.value,
                worker_id=worker_id,
                started_at=fact,
                finished_at=fact + timedelta(seconds=12),
            )
        )
        session.add_all(
            [
                RunEvent(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    seq=1,
                    event_type="run.queue_blocked",
                    payload={"reason": EligibilityReason.NO_WORKER_CAPACITY.value},
                    created_at=fact,
                ),
                RunEvent(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    seq=2,
                    event_type="run.waiting",
                    payload={"status": RunStatus.WAITING_INPUT.value},
                    created_at=fact,
                ),
                RunUsageRecord(
                    run_id=run_id,
                    attempt_id=attempt_id,
                    provider="test",
                    model="test-model",
                    input_tokens=7,
                    output_tokens=5,
                    cached_tokens=0,
                    total_tokens=12,
                    cost_cny=0.5,
                    created_at=fact,
                ),
            ]
        )
        await session.commit()

    result = await RunMetricsService(pg_async_session_factory).snapshot(
        tenant_id, window=timedelta(hours=1)
    )
    assert result["scheduling"]["latency_seconds"] == (fact - old).total_seconds()
    assert result["scheduling"]["no_slot"] == 1
    assert result["scheduling"]["fair_allocations"] == 1
    assert result["attempts"]["outcomes"] == {AttemptStatus.COMPLETED.value: 1}
    assert result["attempts"]["duration_seconds"] == 12.0
    assert result["usage"] == {"total_tokens": 12, "cost_cny": 0.5}
    assert result["runs"]["waiting"] == {RunStatus.WAITING_INPUT.value: 1}

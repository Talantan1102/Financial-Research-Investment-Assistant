"""Contract tests for the read-only Run metrics projection.

The production fixture runs these queries against PostgreSQL; this focused test
keeps the contract fast and deterministic by supplying aggregate result rows.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from app.models.run import Run, RunAttempt, RunEvent, RunMessage, RunSession
from app.models.run_execution import RunUsageRecord
from app.models.run_scheduling import RunWorker
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.router.auth_router import get_current_user_required
from app.router.run_observability import router as observability_router
from app.run_control.scheduling_policy import EligibilityReason
from app.run_control.types import AttemptStatus, RunStatus, WorkerStatus
from app.services.run_metrics import RunMetricsService, count_no_slot_reasons
from fastapi import FastAPI, HTTPException, status
from sqlalchemy import func, select


@pytest.fixture
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    if hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture
async def observability_context(pg_async_session_factory):
    suffix = uuid4().hex
    tenant = Tenant(name="metrics-api", slug=f"metrics-api-{suffix}")
    member = User(
        username=f"metrics-member-{suffix}",
        email=f"metrics-member-{suffix}@example.com",
        hashed_password="test",
    )
    outsider = User(
        username=f"metrics-outsider-{suffix}",
        email=f"metrics-outsider-{suffix}@example.com",
        hashed_password="test",
    )
    async with pg_async_session_factory() as session, session.begin():
        session.add_all([tenant, member, outsider])
        await session.flush()
        session.add(TenantMembership(tenant_id=tenant.id, user_id=member.id, role="member"))
    return tenant, member, outsider


ClientFactory = Callable[[User | None], AsyncIterator[httpx.AsyncClient]]


@pytest.fixture
def observability_client(pg_async_session_factory, observability_context) -> ClientFactory:
    tenant, _member, _outsider = observability_context

    @asynccontextmanager
    async def build(user: User | None) -> AsyncIterator[httpx.AsyncClient]:
        app = FastAPI()
        app.state.async_session_factory = pg_async_session_factory
        app.include_router(observability_router)
        if user is None:

            async def reject() -> User:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

            app.dependency_overrides[get_current_user_required] = reject
        else:
            app.dependency_overrides[get_current_user_required] = lambda: user
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            yield client

    return build


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
                _Result(scalar=datetime(2026, 7, 20, 12, 0, 0)),
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
    assert len(session.statements) == 14
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
                status=RunStatus.WAITING_INPUT.value,
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
                    event_type="run.paused",
                    # AttemptService emits pause facts without duplicating the
                    # authoritative Run.status in the event payload.
                    payload={"pause_type": "input"},
                    created_at=fact,
                ),
                RunEvent(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    seq=3,
                    event_type="run.resumed",
                    payload={},
                    created_at=fact + timedelta(seconds=1),
                ),
                RunEvent(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    seq=4,
                    event_type="run.paused",
                    payload={"pause_type": "input"},
                    created_at=fact + timedelta(seconds=2),
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
                # Future-dated facts must not leak into the requested window.
                RunEvent(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    seq=5,
                    event_type="run.queue_blocked",
                    payload={"reason": EligibilityReason.NO_WORKER_CAPACITY.value},
                    created_at=now + timedelta(hours=1),
                ),
                RunUsageRecord(
                    run_id=run_id,
                    attempt_id=attempt_id,
                    provider="future",
                    model="future-model",
                    input_tokens=2,
                    output_tokens=2,
                    cached_tokens=0,
                    total_tokens=4,
                    cost_cny=1.0,
                    created_at=now + timedelta(hours=1),
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


@pytest.mark.asyncio
async def test_current_waiting_projection_counts_waiting_run_when_pause_event_predates_window(
    pg_async_session_factory,
) -> None:
    """Current waiting state is a snapshot, even when its pause fact is old."""
    now = datetime.utcnow()
    old = now - timedelta(hours=2)
    tenant_id = uuid4()
    user_id = uuid4()
    session_id = uuid4()
    future_session_id = uuid4()
    run_id = uuid4()
    future_run_id = uuid4()
    message_id = uuid4()
    future_message_id = uuid4()
    async with pg_async_session_factory() as session:
        session.add_all(
            [
                User(
                    id=user_id,
                    username=f"waiting-{user_id}",
                    email=f"waiting-{user_id}@example.com",
                    hashed_password="test",
                ),
                Tenant(id=tenant_id, name="waiting", slug=f"waiting-{tenant_id}"),
            ]
        )
        await session.flush()
        session.add_all(
            [
                RunSession(id=session_id, tenant_id=tenant_id, created_by_user_id=user_id),
                RunSession(id=future_session_id, tenant_id=tenant_id, created_by_user_id=user_id),
            ]
        )
        await session.flush()
        session.add(
            RunMessage(
                id=message_id,
                tenant_id=tenant_id,
                session_id=session_id,
                role="user",
                content="waiting fixture",
                status="complete",
                created_at=old,
            )
        )
        session.add(
            RunMessage(
                id=future_message_id,
                tenant_id=tenant_id,
                session_id=future_session_id,
                role="user",
                content="future waiting fixture",
                status="complete",
                created_at=now + timedelta(hours=1),
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
                status=RunStatus.WAITING_INPUT.value,
                idempotency_key=f"waiting-{run_id}",
                request_hash="1" * 64,
                input_message_id=message_id,
                revision_seq=1,
                created_at=old,
                queued_at=old,
            )
        )
        session.add(
            Run(
                id=future_run_id,
                tenant_id=tenant_id,
                session_id=future_session_id,
                created_by_user_id=user_id,
                run_type="chat",
                status=RunStatus.WAITING_APPROVAL.value,
                idempotency_key=f"waiting-future-{future_run_id}",
                request_hash="2" * 64,
                input_message_id=future_message_id,
                revision_seq=2,
                created_at=now + timedelta(hours=1),
                queued_at=now + timedelta(hours=1),
            )
        )
        await session.flush()
        session.add(
            RunEvent(
                tenant_id=tenant_id,
                run_id=run_id,
                seq=1,
                event_type="run.paused",
                payload={"pause_type": "input"},
                created_at=old,
            )
        )
        await session.commit()

    result = await RunMetricsService(pg_async_session_factory).snapshot(
        tenant_id, window=timedelta(hours=1), as_of=now
    )
    assert result["runs"]["waiting"] == {RunStatus.WAITING_INPUT.value: 1}


@pytest.mark.asyncio
async def test_observability_router_auth_scope_window_and_read_only(
    observability_context,
    observability_client: ClientFactory,
    pg_async_session_factory,
) -> None:
    tenant, member, outsider = observability_context
    path = f"/api/v1/tenants/{tenant.id}/observability/metrics"
    async with pg_async_session_factory() as session:
        event_count_before = await session.scalar(select(func.count()).select_from(RunEvent))

    async with observability_client(None) as client:
        assert (await client.get(path)).status_code == 401
    async with observability_client(outsider) as client:
        assert (await client.get(path)).status_code == 404
    async with observability_client(member) as client:
        assert (await client.get(f"{path}?window_minutes=0")).status_code == 400
        assert (await client.get(f"{path}?window_minutes=1441")).status_code == 400
        before = await client.get(path, params={"window_minutes": 60})
        assert before.status_code == 200
        payload = before.json()
        assert payload["window"]["seconds"] == 3600
        assert "by_status" not in payload["workers"]
        assert "capacity" not in str(payload["workers"])
        assert "last_heartbeat" not in str(payload["workers"])
        after = await client.get(f"{path[:-7]}runs", params={"window_minutes": 60})
        assert after.status_code == 200
        after_payload = after.json()
        assert after_payload["window"]["seconds"] == payload["window"]["seconds"]
        assert {key: value for key, value in after_payload.items() if key != "window"} == {
            key: value for key, value in payload.items() if key != "window"
        }

    async with pg_async_session_factory() as session:
        assert (
            await session.scalar(select(func.count()).select_from(RunEvent))
        ) == event_count_before


@pytest.mark.asyncio
async def test_snapshot_normalizes_aware_as_of_and_excludes_future_current_facts(
    pg_async_session_factory,
) -> None:
    """A caller-provided aware instant is compared as UTC-naive DB time."""
    result = await RunMetricsService(pg_async_session_factory).snapshot(
        uuid4(), as_of=datetime(2026, 7, 20, 20, 0, tzinfo=UTC)
    )
    assert result["window"]["since"] == "2026-07-20T19:45:00"

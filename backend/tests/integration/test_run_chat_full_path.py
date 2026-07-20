"""Phase 3 acceptance: HTTP Run creation through durable scheduling and workers."""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from app.chatloop.run_executor import CompletedResult, ExecuteChatRun, RunUsage
from app.models.run import Run, RunAttempt, RunMessage
from app.models.run_execution import RunUsageRecord
from app.models.run_scheduling import RunWorker as RunWorkerRow
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.processes.run_dispatcher import RunDispatcher
from app.processes.run_scheduler import RunScheduler
from app.processes.run_worker import RunWorker
from app.router.auth_router import get_current_user_required
from app.router.runs import router
from app.run_control.redis_transport import RedisTransport, parse_stream_envelope
from app.services.attempt_service import AttemptService
from app.services.run_chat_worker import ContinuationKeyring, RunChatWorker
from app.services.run_outbox import RunOutboxService
from app.services.scheduling_service import SchedulingService
from app.services.trace_models import TraceSpanRow
from app.services.worker_registry import WorkerRegistry
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy import Engine, delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


class _CompletingAttemptExecutor:
    async def execute(self, command: ExecuteChatRun) -> CompletedResult:
        return CompletedResult(
            run_id=command.run_id,
            attempt_id=command.attempt_id,
            session_id=command.session_id,
            final_text=f"accepted run {command.run_id}",
            usage=RunUsage("scripted", "phase3-acceptance", 3, 2, 1, 5, 0.01),
            tools=(),
            events=(),
        )


def _chat_worker(attempts: AttemptService) -> RunChatWorker:
    return RunChatWorker(
        attempts=attempts,
        executor_builder=lambda *_args: _CompletingAttemptExecutor(),
        continuation_keys=ContinuationKeyring(
            active_key_id="acceptance", keys={"acceptance": b"k" * 32}
        ),
        renew_interval=0.1,
    )


async def _seed_actor(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[Tenant, User]:
    suffix = uuid.uuid4().hex[:10]
    tenant = Tenant(name=f"Phase 3 {suffix}", slug=f"phase3-{suffix}")
    user = User(
        username=f"phase3-{suffix}",
        email=f"phase3-{suffix}@example.com",
        hashed_password="test",
    )
    async with factory() as session, session.begin():
        session.add_all([tenant, user])
        await session.flush()
        session.add(TenantMembership(tenant_id=tenant.id, user_id=user.id, role="owner"))
    return tenant, user


async def _assignment(
    redis: Redis,
    worker: RunWorker,
) -> tuple[str, Any]:
    assert worker.worker_id is not None
    key = f"run:worker:{worker.worker_id}:assignments"
    response = await redis.xreadgroup(
        RunWorker.GROUP,
        f"acceptance-{worker.worker_id}",
        {key: ">"},
        count=1,
        block=1_000,
    )
    assert response and response[0][1]
    entry_id, fields = response[0][1][0]
    return worker._text(entry_id), parse_stream_envelope(fields)


@pytest.mark.asyncio
async def test_post_run_reaches_two_capacity_one_workers_and_durable_chat_facts(
    pg_async_session_factory: async_sessionmaker[AsyncSession],
    pg_test_engine: Engine,
    redis_url: str,
) -> None:
    del pg_test_engine
    factory = pg_async_session_factory
    tenant, user = await _seed_actor(factory)
    redis = Redis.from_url(redis_url, decode_responses=False)
    attempts = AttemptService(factory, lease_duration=timedelta(seconds=30))
    workers = [
        RunWorker(
            WorkerRegistry(factory),
            attempts,
            redis,
            RedisTransport(redis),
            _chat_worker(attempts),
            capacity=1,
            heartbeat_interval=1,
            poll_interval=0.05,
        )
        for _ in range(2)
    ]
    app = FastAPI()
    app.state.async_session_factory = factory
    app.include_router(router)
    app.dependency_overrides[get_current_user_required] = lambda: user
    run_ids: list[uuid.UUID] = []

    try:
        await asyncio.gather(*(worker.start() for worker in workers))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://acceptance"
        ) as client:
            created = await asyncio.gather(
                *(
                    client.post(
                        f"/api/v1/tenants/{tenant.id}/runs",
                        headers={"Idempotency-Key": f"phase3-{index}-{uuid.uuid4().hex}"},
                        json={"prompt": f"acceptance prompt {index}"},
                    )
                    for index in range(2)
                )
            )
            assert [response.status_code for response in created] == [201, 201]
            created_payloads = [response.json() for response in created]
            run_ids = [uuid.UUID(payload["id"]) for payload in created_payloads]
            session_ids = [uuid.UUID(payload["session_id"]) for payload in created_payloads]
            assert len(set(run_ids)) == 2
            assert len(set(session_ids)) == 2

            cycle = await RunScheduler(
                SchedulingService(factory, lease_duration=timedelta(seconds=30)),
                redis,
            ).run_cycle()
            assert cycle.scheduled == 2
            async with factory() as session:
                assigned_workers = set(
                    await session.scalars(
                        select(RunAttempt.worker_id).where(RunAttempt.run_id.in_(run_ids))
                    )
                )
            assert assigned_workers == {worker.worker_id for worker in workers}
            delivered = await RunDispatcher(
                RunOutboxService(factory), RedisTransport(redis)
            ).dispatch_once()
            assert delivered >= 2

            entries = await asyncio.gather(*(_assignment(redis, worker) for worker in workers))
            await asyncio.gather(
                *(
                    worker.handle_assignment(entry_id, item)
                    for worker, (entry_id, item) in zip(workers, entries, strict=True)
                )
            )

            run_responses = await asyncio.gather(
                *(client.get(f"/api/v1/tenants/{tenant.id}/runs/{run_id}") for run_id in run_ids)
            )
            assert [response.json()["status"] for response in run_responses] == [
                "completed",
                "completed",
            ]
            event_responses = await asyncio.gather(
                *(
                    client.get(f"/api/v1/tenants/{tenant.id}/runs/{run_id}/events")
                    for run_id in run_ids
                )
            )
            assert all("event: run.completed" in response.text for response in event_responses)
            assert all("accepted run" in response.text for response in event_responses)
            trace_responses = await asyncio.gather(
                *(
                    client.get(f"/api/v1/tenants/{tenant.id}/runs/{run_id}/trace")
                    for run_id in run_ids
                )
            )
            assert all(response.json()["items"] for response in trace_responses)

        async with factory() as session:
            runs = (
                await session.scalars(select(Run).where(Run.id.in_(run_ids)).order_by(Run.id))
            ).all()
            attempts_rows = (
                await session.scalars(select(RunAttempt).where(RunAttempt.run_id.in_(run_ids)))
            ).all()
            messages = (
                await session.scalars(
                    select(RunMessage).where(
                        RunMessage.id.in_([cast(uuid.UUID, run.final_message_id) for run in runs])
                    )
                )
            ).all()
            usage = (
                await session.scalars(
                    select(RunUsageRecord).where(RunUsageRecord.run_id.in_(run_ids))
                )
            ).all()
            traces = (
                await session.scalars(
                    select(TraceSpanRow).where(TraceSpanRow.request_id.in_(map(str, run_ids)))
                )
            ).all()
        assert len({row.worker_id for row in attempts_rows}) == 2
        assert {row.id: row.session_id for row in runs} == dict(
            zip(run_ids, session_ids, strict=True)
        )
        assert all(row.status == "completed" for row in attempts_rows)
        assert len(messages) == len(usage) == len(traces) == 2
        assert all(row.total_tokens == 5 and row.model == "phase3-acceptance" for row in usage)
    finally:
        worker_ids = [worker.worker_id for worker in workers]
        await asyncio.gather(*(worker.stop() for worker in workers), return_exceptions=True)
        for worker_id in worker_ids:
            if worker_id is not None:
                await redis.delete(f"run:worker:{worker_id}:assignments")
        wake_entries = await redis.xrange("run:scheduler:wake")
        owned_wakes = [
            entry_id
            for entry_id, fields in wake_entries
            if parse_stream_envelope(fields).run_id in run_ids
        ]
        if owned_wakes:
            await redis.xdel("run:scheduler:wake", *owned_wakes)
        await redis.aclose()
        async with factory() as session, session.begin():
            await session.execute(delete(Tenant).where(Tenant.id == tenant.id))
            await session.execute(delete(User).where(User.id == user.id))
            await session.execute(delete(RunWorkerRow).where(RunWorkerRow.id.in_(worker_ids)))


def test_compose_exposes_explicit_switch_for_chat_workers() -> None:
    compose = (Path(__file__).resolve().parents[3] / "docker-compose.yml").read_text(
        encoding="utf-8"
    )
    assert "RUN_EXECUTOR_MODE: ${RUN_EXECUTOR_MODE:-simulated}" in compose

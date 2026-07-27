"""End-to-end boundary for a completed ``action_required`` Run.

An action-required outcome is deliberately not a pause: the originating Run is
terminal, has no unresolved pause record, and the resume endpoint must refuse
to revive it.  A user who returns after finishing the external task starts a
new Run instead.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
import pytest_asyncio
from app.models.run import Run, RunPause
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.router.auth_router import get_current_user_required
from app.router.runs import router
from app.run_control.types import RunStatus
from app.services.run_service import CreateRunCommand, RunService
from fastapi import FastAPI
from sqlalchemy import Engine, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    if __import__("sys").platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture
async def async_session_factory(
    pg_test_engine: Engine,
    pg_test_container: dict[str, object],
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    del pg_test_engine
    url = str(pg_test_container["url"]).replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_async_engine(url, future=True)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_action_required_run_is_terminal_without_pause_and_cannot_resume(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A normal terminal outcome cannot be converted back into a paused Run."""
    suffix = uuid.uuid4().hex[:10]
    actor = User(
        username=f"action-required-{suffix}",
        email=f"action-required-{suffix}@example.test",
        hashed_password="test-password-hash",
    )
    tenant = Tenant(name="Action required e2e", slug=f"action-required-{suffix}")
    async with async_session_factory() as session, session.begin():
        session.add_all([actor, tenant])
        await session.flush()
        session.add(TenantMembership(tenant_id=tenant.id, user_id=actor.id, role="member"))

    service = RunService(async_session_factory)
    created = await service.create_run(
        CreateRunCommand(
            tenant_id=tenant.id,
            actor_id=actor.id,
            session_id=None,
            prompt="开通科创板权限后继续买入",
            idempotency_key=f"action-required-{suffix}",
            replaces_run_id=None,
        )
    )
    run_id = created.run.id
    await service.transition_run(
        tenant.id, run_id, actor.id, RunStatus.ASSIGNED, event_type="run.assigned"
    )
    await service.transition_run(
        tenant.id, run_id, actor.id, RunStatus.RUNNING, event_type="run.running"
    )
    await service.transition_run(
        tenant.id, run_id, actor.id, RunStatus.COMPLETED, event_type="run.completed"
    )
    async with async_session_factory() as session, session.begin():
        run = await session.get(Run, run_id, with_for_update=True)
        assert run is not None
        run.outcome_code = "action_required"
        run.outcome_payload = {
            "code": "action_required",
            "action_type": "apply_market_permission",
            "action_url": "/market-permissions/star/apply",
            "action_label": "申请科创板权限",
            "resume_hint": "完成申请后回来继续下单",
            "intent_summary": "买入中芯国际 100 股",
        }

    async with async_session_factory() as session:
        stored = await session.get(Run, run_id)
        assert stored is not None
        assert stored.status == RunStatus.COMPLETED.value
        assert stored.outcome_code == "action_required"
        unresolved_pauses = await session.scalar(
            select(func.count(RunPause.id)).where(
                RunPause.run_id == run_id,
                RunPause.resolved_at.is_(None),
            )
        )
        assert unresolved_pauses == 0

    app = FastAPI()
    app.state.async_session_factory = async_session_factory
    app.include_router(router)
    app.dependency_overrides[get_current_user_required] = lambda: actor

    @asynccontextmanager
    async def client() -> AsyncIterator[httpx.AsyncClient]:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as value:
            yield value

    async with client() as http_client:
        response = await http_client.post(
            f"/api/v1/tenants/{tenant.id}/runs/{run_id}/resume",
            json={"pause_id": str(uuid.uuid4()), "response": {"text": "继续"}},
        )

    assert response.status_code == 409
    async with async_session_factory() as session:
        stored = await session.get(Run, run_id)
        assert stored is not None
        assert stored.status == RunStatus.COMPLETED.value

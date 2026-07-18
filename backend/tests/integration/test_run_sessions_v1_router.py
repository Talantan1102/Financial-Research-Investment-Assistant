"""ASGI contract tests for the v1 Session read-model resource."""

from __future__ import annotations

import asyncio
import sys
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from datetime import datetime

import httpx
import pytest
import pytest_asyncio
from app.models.run import Run, RunMessage, RunSession
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.router.auth_router import get_current_user_required
from app.router.run_sessions import router as run_sessions_router
from app.router.runs import router as runs_router
from app.run_control.types import ResourceNotFound
from app.services.run_session_service import RunSessionService
from fastapi import FastAPI, HTTPException, status
from sqlalchemy import Engine, delete, event, func, select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    if sys.platform == "win32":
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


@pytest_asyncio.fixture
async def session_api_context(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> tuple[Tenant, dict[str, User], dict[str, RunSession], Run]:
    suffix = uuid.uuid4().hex[:10]
    users = {
        role: User(
            username=f"session-api-{role}-{suffix}",
            email=f"session-api-{role}-{suffix}@example.com",
            hashed_password="test-password-hash",
        )
        for role in ("owner", "admin", "member", "other_member", "outsider")
    }
    tenant = Tenant(name="Session API tenant", slug=f"session-api-{suffix}")
    async with async_session_factory() as session, session.begin():
        session.add_all([*users.values(), tenant])
        await session.flush()
        sessions = {
            "owner": RunSession(tenant_id=tenant.id, created_by_user_id=users["owner"].id),
            "member": RunSession(
                tenant_id=tenant.id,
                created_by_user_id=users["member"].id,
                title="Member session",
            ),
            "member_archived": RunSession(
                tenant_id=tenant.id,
                created_by_user_id=users["member"].id,
                title="Archived member session",
                archived_at=datetime(2026, 7, 17, 12, 0, 0),
            ),
            "other_member": RunSession(
                tenant_id=tenant.id,
                created_by_user_id=users["other_member"].id,
                title="Other member session",
            ),
        }
        session.add_all(
            [
                TenantMembership(tenant_id=tenant.id, user_id=users["owner"].id, role="owner"),
                TenantMembership(tenant_id=tenant.id, user_id=users["admin"].id, role="admin"),
                TenantMembership(tenant_id=tenant.id, user_id=users["member"].id, role="member"),
                TenantMembership(
                    tenant_id=tenant.id,
                    user_id=users["other_member"].id,
                    role="member",
                ),
                *sessions.values(),
            ]
        )
        await session.flush()
        message = RunMessage(
            tenant_id=tenant.id,
            session_id=sessions["member"].id,
            role="user",
            content="Keep this history",
            status="complete",
        )
        session.add(message)
        await session.flush()
        run = Run(
            tenant_id=tenant.id,
            session_id=sessions["member"].id,
            created_by_user_id=users["member"].id,
            run_type="chat",
            status="completed",
            idempotency_key=f"session-api-{suffix}",
            request_hash="a" * 64,
            input_message_id=message.id,
        )
        session.add(run)
        await session.flush()
    return tenant, users, sessions, run


ClientFactory = Callable[[User | None], AsyncIterator[httpx.AsyncClient]]


@pytest.fixture
def client_for(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> ClientFactory:
    @asynccontextmanager
    async def build(user: User | None) -> AsyncIterator[httpx.AsyncClient]:
        app = FastAPI()
        app.state.async_session_factory = async_session_factory
        app.include_router(runs_router)
        app.include_router(run_sessions_router)
        if user is None:

            async def reject_unauthenticated() -> User:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

            app.dependency_overrides[get_current_user_required] = reject_unauthenticated
        else:
            app.dependency_overrides[get_current_user_required] = lambda: user
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            yield client

    return build


def _sessions_url(tenant_id: uuid.UUID) -> str:
    return f"/api/v1/tenants/{tenant_id}/sessions"


@pytest.mark.asyncio
async def test_openapi_contains_exactly_six_run_and_four_session_operations(
    session_api_context: tuple[Tenant, dict[str, User], dict[str, RunSession], Run],
    client_for: ClientFactory,
) -> None:
    _tenant, users, _sessions, _run = session_api_context
    async with client_for(users["owner"]) as client:
        paths = (await client.get("/openapi.json")).json()["paths"]

    operations = {
        (method.upper(), path)
        for path, path_operations in paths.items()
        for method in path_operations
        if method in {"get", "post", "put", "patch", "delete"}
    }
    assert operations == {
        ("POST", "/api/v1/tenants/{tenant_id}/runs"),
        ("GET", "/api/v1/tenants/{tenant_id}/runs/{run_id}"),
        ("GET", "/api/v1/tenants/{tenant_id}/runs/{run_id}/events"),
        ("GET", "/api/v1/tenants/{tenant_id}/runs/{run_id}/trace"),
        ("POST", "/api/v1/tenants/{tenant_id}/runs/{run_id}/cancel"),
        ("POST", "/api/v1/tenants/{tenant_id}/runs/{run_id}/resume"),
        ("GET", "/api/v1/tenants/{tenant_id}/sessions"),
        ("GET", "/api/v1/tenants/{tenant_id}/sessions/{session_id}"),
        ("PATCH", "/api/v1/tenants/{tenant_id}/sessions/{session_id}"),
        ("DELETE", "/api/v1/tenants/{tenant_id}/sessions/{session_id}"),
    }
    execution_posts = {
        path for method, path in operations if method == "POST" and path.endswith("/runs")
    }
    assert execution_posts == {"/api/v1/tenants/{tenant_id}/runs"}
    assert not any(method == "POST" and "/sessions" in path for method, path in operations)


@pytest.mark.asyncio
async def test_list_enforces_member_and_privileged_scope_and_excludes_archived(
    session_api_context: tuple[Tenant, dict[str, User], dict[str, RunSession], Run],
    client_for: ClientFactory,
) -> None:
    tenant, users, sessions, _run = session_api_context
    async with client_for(users["member"]) as client:
        member_response = await client.get(_sessions_url(tenant.id))
    assert member_response.status_code == 200
    assert [item["id"] for item in member_response.json()] == [str(sessions["member"].id)]

    expected = {str(sessions[name].id) for name in ("owner", "member", "other_member")}
    for role in ("owner", "admin"):
        async with client_for(users[role]) as client:
            response = await client.get(_sessions_url(tenant.id))
        assert response.status_code == 200
        assert {item["id"] for item in response.json()} == expected

    async with client_for(users["outsider"]) as client:
        outsider_response = await client.get(_sessions_url(tenant.id))
    assert outsider_response.status_code == 404


@pytest.mark.asyncio
async def test_detail_hides_other_member_but_allows_authorized_archived_lookup(
    session_api_context: tuple[Tenant, dict[str, User], dict[str, RunSession], Run],
    client_for: ClientFactory,
) -> None:
    tenant, users, sessions, _run = session_api_context
    base = _sessions_url(tenant.id)
    async with client_for(users["member"]) as client:
        archived = await client.get(f"{base}/{sessions['member_archived'].id}")
        hidden = await client.get(f"{base}/{sessions['other_member'].id}")
    assert archived.status_code == 200
    assert archived.json()["archived_at"] is not None
    assert hidden.status_code == 404

    async with client_for(users["outsider"]) as client:
        outsider = await client.get(f"{base}/{sessions['member'].id}")
    assert outsider.status_code == 404


@pytest.mark.asyncio
async def test_patch_updates_only_a_strict_non_blank_title(
    session_api_context: tuple[Tenant, dict[str, User], dict[str, RunSession], Run],
    client_for: ClientFactory,
) -> None:
    tenant, users, sessions, _run = session_api_context
    url = f"{_sessions_url(tenant.id)}/{sessions['member'].id}"
    async with client_for(users["member"]) as client:
        updated = await client.patch(url, json={"title": "  Renamed session  "})
        blank = await client.patch(url, json={"title": "   "})
        too_long = await client.patch(url, json={"title": "x" * 256})
        extra = await client.patch(url, json={"title": "Valid", "archived_at": None})
    assert updated.status_code == 200
    assert updated.json()["title"] == "Renamed session"
    assert blank.status_code == 422
    assert too_long.status_code == 422
    assert extra.status_code == 422


@pytest.mark.asyncio
async def test_privileged_mutations_cross_member_scope_and_member_mutations_are_hidden(
    session_api_context: tuple[Tenant, dict[str, User], dict[str, RunSession], Run],
    client_for: ClientFactory,
) -> None:
    tenant, users, sessions, _run = session_api_context
    member_url = f"{_sessions_url(tenant.id)}/{sessions['member'].id}"
    other_member_url = f"{_sessions_url(tenant.id)}/{sessions['other_member'].id}"

    async with client_for(users["other_member"]) as client:
        hidden_patch = await client.patch(member_url, json={"title": "Not allowed"})
        hidden_delete = await client.delete(member_url)
    assert hidden_patch.status_code == 404
    assert hidden_delete.status_code == 404

    async with client_for(users["owner"]) as client:
        owner_patch = await client.patch(member_url, json={"title": "Owner renamed"})
    assert owner_patch.status_code == 200
    assert owner_patch.json()["title"] == "Owner renamed"

    async with client_for(users["admin"]) as client:
        admin_delete = await client.delete(other_member_url)
        archived_detail = await client.get(other_member_url)
    assert admin_delete.status_code == 204
    assert archived_detail.status_code == 200
    assert archived_detail.json()["archived_at"] is not None


@pytest.mark.asyncio
async def test_archive_is_idempotent_soft_delete_and_retains_run_history(
    session_api_context: tuple[Tenant, dict[str, User], dict[str, RunSession], Run],
    client_for: ClientFactory,
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant, users, sessions, run = session_api_context
    url = f"{_sessions_url(tenant.id)}/{sessions['member'].id}"
    async with client_for(users["member"]) as client:
        first = await client.delete(url)
        second = await client.delete(url)
        detail = await client.get(url)
        listed = await client.get(_sessions_url(tenant.id))

    assert first.status_code == 204
    assert second.status_code == 204
    assert detail.status_code == 200
    assert detail.json()["archived_at"] is not None
    assert str(sessions["member"].id) not in {item["id"] for item in listed.json()}
    async with async_session_factory() as session:
        assert await session.get(RunSession, sessions["member"].id) is not None
        assert await session.get(Run, run.id) is not None
        message_count = await session.scalar(
            select(func.count(RunMessage.id)).where(RunMessage.session_id == sessions["member"].id)
        )
    assert message_count == 1


@pytest.mark.asyncio
async def test_unauthenticated_session_request_is_401(
    session_api_context: tuple[Tenant, dict[str, User], dict[str, RunSession], Run],
    client_for: ClientFactory,
) -> None:
    tenant, _users, _sessions, _run = session_api_context
    async with client_for(None) as client:
        response = await client.get(_sessions_url(tenant.id))
    assert response.status_code == 401


async def _mutate_session(
    service: RunSessionService,
    operation: str,
    tenant_id: uuid.UUID,
    session_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> None:
    if operation == "title":
        await service.update_title(tenant_id, session_id, actor_id, "Revocation race")
        return
    await service.archive_session(tenant_id, session_id, actor_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["title", "archive"])
async def test_revocation_that_locks_first_fences_session_mutation(
    operation: str,
    session_api_context: tuple[Tenant, dict[str, User], dict[str, RunSession], Run],
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant, users, sessions, _run = session_api_context
    run_session = sessions["member"]
    service = RunSessionService(async_session_factory)
    revoker = async_session_factory()
    await revoker.begin()
    await revoker.execute(
        delete(TenantMembership).where(
            TenantMembership.tenant_id == tenant.id,
            TenantMembership.user_id == users["member"].id,
        )
    )
    mutation = asyncio.create_task(
        _mutate_session(
            service,
            operation,
            tenant.id,
            run_session.id,
            users["member"].id,
        )
    )
    try:
        await asyncio.sleep(0.1)
        assert not mutation.done(), "mutation bypassed the in-flight membership revocation"
        await revoker.commit()
        with pytest.raises(ResourceNotFound):
            await mutation
    finally:
        if revoker.in_transaction():
            await revoker.rollback()
        await revoker.close()
        if not mutation.done():
            mutation.cancel()
            with suppress(asyncio.CancelledError):
                await mutation

    async with async_session_factory() as check:
        stored = await check.get(RunSession, run_session.id)
        assert stored is not None
        assert stored.title == "Member session"
        assert stored.archived_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["title", "archive"])
async def test_session_mutation_lock_linearizes_before_revocation(
    operation: str,
    session_api_context: tuple[Tenant, dict[str, User], dict[str, RunSession], Run],
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant, users, sessions, _run = session_api_context
    run_session = sessions["member"]
    bind = async_session_factory.kw["bind"]
    assert isinstance(bind, AsyncEngine)
    membership_locked = asyncio.Event()

    def observe_membership_lock(
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        normalized = statement.upper()
        if "TENANT_MEMBERSHIPS" in normalized and "FOR UPDATE" in normalized:
            membership_locked.set()

    event.listen(bind.sync_engine, "after_cursor_execute", observe_membership_lock)
    blocker = async_session_factory()
    await blocker.begin()
    await blocker.scalar(
        select(RunSession).where(RunSession.id == run_session.id).with_for_update()
    )
    service = RunSessionService(async_session_factory)
    mutation = asyncio.create_task(
        _mutate_session(
            service,
            operation,
            tenant.id,
            run_session.id,
            users["member"].id,
        )
    )
    revocation_started = asyncio.Event()
    revoker_pid: list[int] = []

    async def revoke() -> None:
        async with async_session_factory() as session, session.begin():
            revoker_pid.append(int(await session.scalar(text("SELECT pg_backend_pid()"))))
            revocation_started.set()
            await session.execute(
                delete(TenantMembership).where(
                    TenantMembership.tenant_id == tenant.id,
                    TenantMembership.user_id == users["member"].id,
                )
            )

    revocation: asyncio.Task[None] | None = None
    try:
        await asyncio.wait_for(membership_locked.wait(), timeout=2)
        revocation = asyncio.create_task(revoke())
        await asyncio.wait_for(revocation_started.wait(), timeout=2)

        saw_lock_wait = False
        for _attempt in range(200):
            async with async_session_factory() as observer:
                wait_type = await observer.scalar(
                    text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"),
                    {"pid": revoker_pid[0]},
                )
            if wait_type == "Lock":
                saw_lock_wait = True
                break
            await asyncio.sleep(0.01)
        assert saw_lock_wait, "revocation did not wait on the mutation membership lock"

        await blocker.rollback()
        await mutation
        await asyncio.wait_for(revocation, timeout=2)
    finally:
        event.remove(bind.sync_engine, "after_cursor_execute", observe_membership_lock)
        if blocker.in_transaction():
            await blocker.rollback()
        await blocker.close()
        if not mutation.done():
            mutation.cancel()
            with suppress(asyncio.CancelledError):
                await mutation
        if revocation is not None and not revocation.done():
            revocation.cancel()
            with suppress(asyncio.CancelledError):
                await revocation

    async with async_session_factory() as check:
        assert (
            await check.scalar(
                select(TenantMembership).where(
                    TenantMembership.tenant_id == tenant.id,
                    TenantMembership.user_id == users["member"].id,
                )
            )
            is None
        )
        stored = await check.get(RunSession, run_session.id)
        assert stored is not None
        if operation == "title":
            assert stored.title == "Revocation race"
            assert stored.archived_at is None
        else:
            assert stored.title == "Member session"
            assert stored.archived_at is not None

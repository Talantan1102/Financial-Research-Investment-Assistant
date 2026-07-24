from __future__ import annotations

import asyncio
import sys
from uuid import UUID, uuid4

import httpx
import pytest
from app.core.security import create_access_token
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.processes.run_api import app
from eval.chatloop.sut_runner import DurableRunHttpTransport
from sqlalchemy import delete

EVAL_USER_ID = UUID("00000000-0000-4000-8000-000000000001")


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


@pytest.mark.asyncio
async def test_run_api_identity_preflight_uses_real_jwt_and_pg_membership(
    monkeypatch: pytest.MonkeyPatch,
    pg_async_session_factory,
) -> None:
    suffix = uuid4().hex
    other_user_id = uuid4()
    eval_tenant_id = uuid4()
    other_tenant_id = uuid4()
    nonmember_tenant_id = uuid4()
    async with pg_async_session_factory() as session, session.begin():
        await session.execute(
            delete(TenantMembership).where(
                TenantMembership.user_id == EVAL_USER_ID
            )
        )
        eval_user = await session.get(User, EVAL_USER_ID)
        if eval_user is None:
            eval_user = User(
                id=EVAL_USER_ID,
                username=f"eval-identity-{suffix}",
                email=f"eval-identity-{suffix}@example.com",
                hashed_password="test-password-hash",
            )
            session.add(eval_user)
        session.add_all(
            [
                User(
                    id=other_user_id,
                    username=f"other-identity-{suffix}",
                    email=f"other-identity-{suffix}@example.com",
                    hashed_password="test-password-hash",
                ),
                Tenant(id=eval_tenant_id, name="Eval", slug=f"eval-{suffix}"),
                Tenant(id=other_tenant_id, name="Other", slug=f"other-{suffix}"),
                Tenant(
                    id=nonmember_tenant_id,
                    name="No member",
                    slug=f"nonmember-{suffix}",
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                TenantMembership(
                    tenant_id=eval_tenant_id,
                    user_id=EVAL_USER_ID,
                    role="member",
                ),
                TenantMembership(
                    tenant_id=other_tenant_id,
                    user_id=other_user_id,
                    role="member",
                ),
            ]
        )

    eval_token = create_access_token(
        {"sub": str(EVAL_USER_ID), "username": f"eval-identity-{suffix}"}
    )
    other_token = create_access_token(
        {"sub": str(other_user_id), "username": f"other-identity-{suffix}"}
    )
    monkeypatch.setenv("CHATLOOP_EVAL_RUN_BASE_URL", "http://run-api")
    monkeypatch.setenv("CHATLOOP_EVAL_TENANT_ID", str(eval_tenant_id))
    monkeypatch.setenv("CHATLOOP_EVAL_AUTH_TOKEN", eval_token)
    monkeypatch.setenv("CHATLOOP_EVAL_USER_ID", str(EVAL_USER_ID))
    transport = DurableRunHttpTransport(pg_async_session_factory)

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://run-api",
        ) as client,
    ):
        for path in ("/auth/me", "/api/v1/tenants"):
            assert (await client.get(path)).status_code == 401
            assert (
                await client.get(path, headers={"Authorization": "Bearer invalid"})
            ).status_code == 401

        eval_headers = {"Authorization": f"Bearer {eval_token}"}
        me = await client.get("/auth/me", headers=eval_headers)
        tenants = await client.get("/api/v1/tenants", headers=eval_headers)
        assert me.status_code == tenants.status_code == 200
        assert me.json() == {"id": transport.user_id}
        assert tenants.json() == [{"id": transport.tenant_id}]
        assert str(nonmember_tenant_id) not in {row["id"] for row in tenants.json()}

        other_headers = {"Authorization": f"Bearer {other_token}"}
        other_me = await client.get("/auth/me", headers=other_headers)
        other_tenants = await client.get("/api/v1/tenants", headers=other_headers)
        assert other_me.status_code == other_tenants.status_code == 200
        assert other_me.json() == {"id": str(other_user_id)}
        assert other_tenants.json() == [{"id": str(other_tenant_id)}]
        assert transport.tenant_id not in {
            row["id"] for row in other_tenants.json()
        }
        assert all(set(row) == {"id"} for row in tenants.json() + other_tenants.json())

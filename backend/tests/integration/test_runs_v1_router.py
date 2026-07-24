"""ASGI contract tests for the six v1 Run endpoints."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.router.auth_router import get_current_user_required
from app.router.runs import get_run_service, router
from app.run_control.types import PauseType, RunStatus
from app.services.run_service import RunService
from app.services.trace_models import TraceSpanRow
from fastapi import FastAPI, HTTPException, status
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


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
async def api_context(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> tuple[Tenant, dict[str, User]]:
    suffix = uuid.uuid4().hex[:10]
    users = {
        role: User(
            username=f"run-api-{role}-{suffix}",
            email=f"run-api-{role}-{suffix}@example.com",
            hashed_password="test-password-hash",
        )
        for role in ("owner", "admin", "member", "other_member", "outsider")
    }
    tenant = Tenant(name="Run API tenant", slug=f"run-api-{suffix}")
    async with async_session_factory() as session, session.begin():
        session.add_all([*users.values(), tenant])
        await session.flush()
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
            ]
        )
    return tenant, users


ClientFactory = Callable[[User | None], AsyncIterator[httpx.AsyncClient]]


@pytest.fixture
def client_for(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> ClientFactory:
    @asynccontextmanager
    async def build(user: User | None) -> AsyncIterator[httpx.AsyncClient]:
        app = FastAPI()
        app.state.async_session_factory = async_session_factory
        app.include_router(router)
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


def _run_url(tenant_id: uuid.UUID) -> str:
    return f"/api/v1/tenants/{tenant_id}/runs"


async def _create_run(
    client: httpx.AsyncClient,
    tenant_id: uuid.UUID,
    *,
    key: str | None = None,
    prompt: str = "分析贵州茅台",
    session_id: str | None = None,
) -> httpx.Response:
    body: dict[str, object] = {"prompt": prompt}
    if session_id is not None:
        body["session_id"] = session_id
    return await client.post(
        _run_url(tenant_id),
        headers={"Idempotency-Key": key or f"web-{uuid.uuid4().hex}"},
        json=body,
    )


@pytest.mark.asyncio
async def test_openapi_contains_exactly_six_run_operations_without_steering(
    api_context: tuple[Tenant, dict[str, User]],
    client_for: ClientFactory,
) -> None:
    _tenant, users = api_context
    async with client_for(users["owner"]) as client:
        paths = (await client.get("/openapi.json")).json()["paths"]

    run_operations = {
        (method.upper(), path)
        for path, operations in paths.items()
        if "/runs" in path
        for method in operations
        if method in {"get", "post", "put", "patch", "delete"}
    }
    assert run_operations == {
        ("POST", "/api/v1/tenants/{tenant_id}/runs"),
        ("GET", "/api/v1/tenants/{tenant_id}/runs/{run_id}"),
        ("GET", "/api/v1/tenants/{tenant_id}/runs/{run_id}/events"),
        ("GET", "/api/v1/tenants/{tenant_id}/runs/{run_id}/trace"),
        ("POST", "/api/v1/tenants/{tenant_id}/runs/{run_id}/cancel"),
        ("POST", "/api/v1/tenants/{tenant_id}/runs/{run_id}/resume"),
    }
    assert all("steer" not in path for path in paths)


@pytest.mark.asyncio
async def test_unauthenticated_request_is_401(
    api_context: tuple[Tenant, dict[str, User]], client_for: ClientFactory
) -> None:
    tenant, _users = api_context
    async with client_for(None) as client:
        response = await client.get(f"{_run_url(tenant.id)}/{uuid.uuid4()}")
    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Idempotency-Key": ""},
        {"Idempotency-Key": " "},
        {"Idempotency-Key": "x" * 129},
    ],
)
async def test_post_rejects_missing_blank_or_over_128_byte_idempotency_key(
    headers: dict[str, str],
    api_context: tuple[Tenant, dict[str, User]],
    client_for: ClientFactory,
) -> None:
    tenant, users = api_context
    async with client_for(users["member"]) as client:
        response = await client.post(
            _run_url(tenant.id), headers=headers, json={"prompt": "分析茅台"}
        )
    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"prompt": ""}, {"prompt": "   "}])
async def test_post_validates_prompt(
    body: dict[str, object],
    api_context: tuple[Tenant, dict[str, User]],
    client_for: ClientFactory,
) -> None:
    tenant, users = api_context
    async with client_for(users["member"]) as client:
        response = await client.post(
            _run_url(tenant.id), headers={"Idempotency-Key": "validate-prompt"}, json=body
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_returns_201_and_idempotent_replay_returns_200(
    api_context: tuple[Tenant, dict[str, User]], client_for: ClientFactory
) -> None:
    tenant, users = api_context
    async with client_for(users["member"]) as client:
        first = await _create_run(client, tenant.id, key="web-replay")
        second = await _create_run(client, tenant.id, key="web-replay")

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert first.json()["created_by_user_id"] == str(users["member"].id)
    assert first.json()["tenant_id"] == str(tenant.id)


@pytest.mark.asyncio
async def test_idempotency_conflict_and_busy_session_are_409(
    api_context: tuple[Tenant, dict[str, User]], client_for: ClientFactory
) -> None:
    tenant, users = api_context
    async with client_for(users["member"]) as client:
        first = await _create_run(client, tenant.id, key="conflict", prompt="first")
        conflict = await _create_run(client, tenant.id, key="conflict", prompt="different")
        busy = await _create_run(
            client,
            tenant.id,
            key="busy",
            session_id=first.json()["session_id"],
        )

    assert first.status_code == 201
    assert conflict.status_code == 409
    assert busy.status_code == 409


@pytest.mark.asyncio
async def test_queue_quota_is_409(
    api_context: tuple[Tenant, dict[str, User]],
    client_for: ClientFactory,
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant, users = api_context
    async with async_session_factory() as session, session.begin():
        stored = await session.get(Tenant, tenant.id)
        assert stored is not None
        stored.max_queued_runs = 1

    async with client_for(users["member"]) as client:
        first = await _create_run(client, tenant.id, key="quota-1")
        second = await _create_run(client, tenant.id, key="quota-2")

    assert first.status_code == 201
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_run_reads_enforce_member_owner_admin_and_outsider_visibility(
    api_context: tuple[Tenant, dict[str, User]], client_for: ClientFactory
) -> None:
    tenant, users = api_context
    async with client_for(users["member"]) as client:
        created = await _create_run(client, tenant.id)
    run_id = created.json()["id"]

    expected = {
        "member": 200,
        "owner": 200,
        "admin": 200,
        "other_member": 404,
        "outsider": 404,
    }
    for actor, expected_status in expected.items():
        async with client_for(users[actor]) as client:
            response = await client.get(f"{_run_url(tenant.id)}/{run_id}")
        assert response.status_code == expected_status, actor


@pytest.mark.asyncio
async def test_cancel_is_idempotent_and_invalid_resume_is_409(
    api_context: tuple[Tenant, dict[str, User]], client_for: ClientFactory
) -> None:
    tenant, users = api_context
    async with client_for(users["member"]) as client:
        created = await _create_run(client, tenant.id)
        run_url = f"{_run_url(tenant.id)}/{created.json()['id']}"
        missing_identity = await client.post(
            f"{run_url}/resume", json={"response": {"text": "x"}}
        )
        invalid_resume = await client.post(
            f"{run_url}/resume",
            json={"pause_id": str(uuid.uuid4()), "response": {"text": "x"}},
        )
        first_cancel = await client.post(f"{run_url}/cancel")
        second_cancel = await client.post(f"{run_url}/cancel")

    assert missing_identity.status_code == 422
    assert invalid_resume.status_code == 409
    assert first_cancel.status_code == second_cancel.status_code == 200
    assert first_cancel.json()["status"] == second_cancel.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_resume_uses_authenticated_actor_and_keeps_same_run(
    api_context: tuple[Tenant, dict[str, User]],
    client_for: ClientFactory,
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant, users = api_context
    async with client_for(users["member"]) as client:
        created = await _create_run(client, tenant.id)
    run_id = uuid.UUID(created.json()["id"])
    service = RunService(async_session_factory)
    await service.transition_run(
        tenant.id,
        run_id,
        users["member"].id,
        RunStatus.ASSIGNED,
        event_type="run.assigned",
    )
    await service.transition_run(
        tenant.id,
        run_id,
        users["member"].id,
        RunStatus.RUNNING,
        event_type="run.running",
    )
    pause = await service.record_pause(
        tenant.id,
        run_id,
        users["member"].id,
        PauseType.INPUT,
        request_payload={"question": "成本价？"},
        continuation_payload={"checkpoint": "ask-cost"},
    )

    async with client_for(users["member"]) as client:
        response = await client.post(
            f"{_run_url(tenant.id)}/{run_id}/resume",
            json={"pause_id": str(pause.id), "response": {"text": "1500"}},
        )
        replay = await client.post(
            f"{_run_url(tenant.id)}/{run_id}/resume",
            json={"pause_id": str(pause.id), "response": {"text": "1500"}},
        )
        conflict = await client.post(
            f"{_run_url(tenant.id)}/{run_id}/resume",
            json={"pause_id": str(pause.id), "response": {"text": "1600"}},
        )

    assert response.status_code == 200
    assert response.json()["id"] == str(run_id)
    assert response.json()["status"] == "queued"
    assert replay.status_code == 200
    assert conflict.status_code == 409
    assert "different response" in conflict.json()["detail"]


@pytest.mark.parametrize(
    ("pause_kind", "pause_request", "stale_response"),
    [
        pytest.param("input", {"question": "second?"}, {"text": "stale"}, id="input"),
        pytest.param(
            "approval", {"action": "send_notice"}, {"approved": True}, id="approve"
        ),
        pytest.param(
            "approval", {"action": "send_notice"}, {"approved": False}, id="reject"
        ),
        pytest.param(
            "approval",
            {
                "tool_calls": [
                    {
                        "id": "trade-1",
                        "name": "place_paper_order",
                        "arguments": '{"quantity":100}',
                    }
                ],
                "editable_tool_call_ids": ["trade-1"],
            },
            {
                "approved": True,
                "edited_arguments": {"trade-1": {"quantity": 200}},
            },
            id="editable",
        ),
    ],
)
@pytest.mark.asyncio
async def test_resume_route_rejects_stale_pause_identity_without_mutation(
    api_context: tuple[Tenant, dict[str, User]],
    client_for: ClientFactory,
    async_session_factory: async_sessionmaker[AsyncSession],
    pause_kind: str,
    pause_request: dict[str, object],
    stale_response: dict[str, object],
) -> None:
    tenant, users = api_context
    actor = users["member"]
    async with client_for(actor) as client:
        created = await _create_run(client, tenant.id)
    run_id = uuid.UUID(created.json()["id"])
    service = RunService(async_session_factory)
    await service.transition_run(
        tenant.id, run_id, actor.id, RunStatus.ASSIGNED, event_type="run.assigned"
    )
    await service.transition_run(
        tenant.id, run_id, actor.id, RunStatus.RUNNING, event_type="run.running"
    )
    first_pause = await service.record_pause(
        tenant.id,
        run_id,
        actor.id,
        PauseType.INPUT,
        request_payload={"question": "first?"},
        continuation_payload={"checkpoint": "first"},
    )
    async with client_for(actor) as client:
        first_resume = await client.post(
            f"{_run_url(tenant.id)}/{run_id}/resume",
            json={"pause_id": str(first_pause.id), "response": {"text": "first"}},
        )
    assert first_resume.status_code == 200

    await service.transition_run(
        tenant.id, run_id, actor.id, RunStatus.ASSIGNED, event_type="run.assigned"
    )
    await service.transition_run(
        tenant.id, run_id, actor.id, RunStatus.RUNNING, event_type="run.running"
    )
    second_pause = await service.record_pause(
        tenant.id,
        run_id,
        actor.id,
        PauseType(pause_kind),
        request_payload=pause_request,
        continuation_payload={"checkpoint": "second"},
    )
    run_before = await service.get_run(tenant.id, run_id, actor.id)
    old_before = await service.get_pause(tenant.id, run_id, actor.id, first_pause.id)
    current_before = await service.get_pause(tenant.id, run_id, actor.id, second_pause.id)
    events_before = await service.list_events(tenant.id, run_id, actor.id)

    async with client_for(actor) as client:
        stale = await client.post(
            f"{_run_url(tenant.id)}/{run_id}/resume",
            json={"pause_id": str(first_pause.id), "response": stale_response},
        )

    assert stale.status_code == 409
    assert "pause identity" in stale.json()["detail"]
    run_after = await service.get_run(tenant.id, run_id, actor.id)
    old_after = await service.get_pause(tenant.id, run_id, actor.id, first_pause.id)
    current_after = await service.get_pause(tenant.id, run_id, actor.id, second_pause.id)
    events_after = await service.list_events(tenant.id, run_id, actor.id)
    assert run_after.status == run_before.status
    assert run_after.queue_reason == run_before.queue_reason
    assert run_after.queued_at == run_before.queued_at
    assert old_after.response_payload == old_before.response_payload
    assert old_after.resolved_at == old_before.resolved_at
    assert old_after.continuation_payload == old_before.continuation_payload
    assert current_after.response_payload == current_before.response_payload is None
    assert current_after.resolved_at == current_before.resolved_at is None
    assert current_after.continuation_payload == current_before.continuation_payload
    assert [
        (event.seq, event.event_type, event.payload) for event in events_after
    ] == [
        (event.seq, event.event_type, event.payload) for event in events_before
    ]


def _sse_frames(body: str) -> list[dict[str, object]]:
    frames = []
    for raw_frame in body.strip().split("\n\n") if body.strip() else []:
        fields = dict(line.split(": ", 1) for line in raw_frame.splitlines())
        frames.append(
            {
                "id": int(fields["id"]),
                "event": fields["event"],
                "data": json.loads(fields["data"]),
            }
        )
    return frames


@pytest.mark.asyncio
async def test_sse_frames_reconnect_without_duplicates_and_terminal_stream_ends(
    api_context: tuple[Tenant, dict[str, User]], client_for: ClientFactory
) -> None:
    tenant, users = api_context
    async with client_for(users["member"]) as client:
        created = await _create_run(client, tenant.id)
        run_url = f"{_run_url(tenant.id)}/{created.json()['id']}"
        await client.post(f"{run_url}/cancel")
        first = await client.get(f"{run_url}/events")
        reconnected = await client.get(f"{run_url}/events", headers={"Last-Event-ID": "1"})
        after_query = await client.get(f"{run_url}/events", params={"after_seq": 2})

    assert first.status_code == 200
    assert first.headers["content-type"].startswith("text/event-stream")
    assert [(item["id"], item["event"]) for item in _sse_frames(first.text)] == [
        (1, "run.created"),
        (2, "run.cancelled"),
    ]
    assert [item["id"] for item in _sse_frames(reconnected.text)] == [2]
    assert after_query.text == ""


@pytest.mark.asyncio
async def test_sse_drains_terminal_event_committed_between_event_and_status_reads(
    api_context: tuple[Tenant, dict[str, User]],
) -> None:
    tenant, users = api_context
    run_id = uuid.uuid4()
    created = SimpleNamespace(seq=1, event_type="run.created", payload={"status": "queued"})
    completed = SimpleNamespace(
        seq=2,
        event_type="run.completed",
        payload={"status": "completed"},
    )

    class TerminalRaceService:
        def __init__(self) -> None:
            self.events = (created,)

        async def list_events(
            self,
            tenant_id: uuid.UUID,
            requested_run_id: uuid.UUID,
            actor_id: uuid.UUID,
            *,
            after_seq: int = 0,
        ) -> tuple[object, ...]:
            assert (tenant_id, requested_run_id, actor_id) == (
                tenant.id,
                run_id,
                users["member"].id,
            )
            return tuple(event for event in self.events if event.seq > after_seq)

        async def get_run(
            self,
            tenant_id: uuid.UUID,
            requested_run_id: uuid.UUID,
            actor_id: uuid.UUID,
        ) -> object:
            assert (tenant_id, requested_run_id, actor_id) == (
                tenant.id,
                run_id,
                users["member"].id,
            )
            self.events = (created, completed)
            return SimpleNamespace(status="completed")

        async def get_final_message(
            self,
            tenant_id: uuid.UUID,
            requested_run_id: uuid.UUID,
            actor_id: uuid.UUID,
        ) -> None:
            assert (tenant_id, requested_run_id, actor_id) == (
                tenant.id,
                run_id,
                users["member"].id,
            )
            return None

    fake_service = TerminalRaceService()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user_required] = lambda: users["member"]
    app.dependency_overrides[get_run_service] = lambda: fake_service
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(f"{_run_url(tenant.id)}/{run_id}/events")

    assert [item["id"] for item in _sse_frames(response.text)] == [1, 2]


@pytest.mark.asyncio
async def test_phase1_sse_closes_after_initial_durable_snapshot(
    api_context: tuple[Tenant, dict[str, User]],
) -> None:
    tenant, users = api_context
    run_id = uuid.uuid4()
    created = SimpleNamespace(seq=1, event_type="run.created", payload={"status": "queued"})

    class SnapshotService:
        def __init__(self) -> None:
            self.event_reads = 0
            self.run_reads = 0

        async def list_events(
            self,
            tenant_id: uuid.UUID,
            requested_run_id: uuid.UUID,
            actor_id: uuid.UUID,
            *,
            after_seq: int = 0,
        ) -> tuple[object, ...]:
            del tenant_id, requested_run_id, actor_id
            self.event_reads += 1
            return (created,) if after_seq < 1 else ()

        async def get_run(
            self,
            tenant_id: uuid.UUID,
            requested_run_id: uuid.UUID,
            actor_id: uuid.UUID,
        ) -> object:
            del tenant_id, requested_run_id, actor_id
            self.run_reads += 1
            return SimpleNamespace(status="queued")

    fake_service = SnapshotService()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user_required] = lambda: users["member"]
    app.dependency_overrides[get_run_service] = lambda: fake_service
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(f"{_run_url(tenant.id)}/{run_id}/events")

    assert response.status_code == 200
    assert [item["id"] for item in _sse_frames(response.text)] == [1]
    assert fake_service.event_reads == 1
    assert fake_service.run_reads == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("last_event_id", ["not-a-number", "-1"])
async def test_sse_rejects_invalid_last_event_id(
    last_event_id: str,
    api_context: tuple[Tenant, dict[str, User]],
    client_for: ClientFactory,
) -> None:
    tenant, users = api_context
    async with client_for(users["member"]) as client:
        created = await _create_run(client, tenant.id)
        response = await client.get(
            f"{_run_url(tenant.id)}/{created.json()['id']}/events",
            headers={"Last-Event-ID": last_event_id},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_trace_returns_typed_items_and_conceals_invisible_run(
    api_context: tuple[Tenant, dict[str, User]],
    client_for: ClientFactory,
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant, users = api_context
    async with client_for(users["member"]) as client:
        created = await _create_run(client, tenant.id)
    run_id = created.json()["id"]

    async with client_for(users["member"]) as client:
        empty = await client.get(f"{_run_url(tenant.id)}/{run_id}/trace")
    assert empty.status_code == 200
    assert empty.json() == {"items": []}

    started = datetime.now(UTC)
    async with async_session_factory() as session, session.begin():
        session.add(
            TraceSpanRow(
                span_id=f"span-{uuid.uuid4().hex}",
                request_id=run_id,
                parent_id=None,
                name="planner",
                inputs={"prompt": "secret"},
                outputs={"route": "direct"},
                attrs_json={"model": "mock"},
                started_at=started,
                ended_at=started + timedelta(milliseconds=5),
                error=None,
            )
        )

    async with client_for(users["member"]) as client:
        visible = await client.get(f"{_run_url(tenant.id)}/{run_id}/trace")
    async with client_for(users["other_member"]) as client:
        concealed = await client.get(f"{_run_url(tenant.id)}/{run_id}/trace")

    assert visible.status_code == 200
    assert visible.json()["items"][0]["name"] == "planner"
    assert visible.json()["items"][0]["metadata"] == {"model": "mock"}
    assert concealed.status_code == 404

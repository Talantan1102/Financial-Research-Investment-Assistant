from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from app.models.run import Run, RunEvent, RunMessage, RunSession
from app.models.run_scheduling import RunOutbox
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.run_control.types import (
    IdempotencyConflict,
    ResourceNotFound,
    SessionBusy,
    TenantQueueFull,
)
from app.services.run_service import CreateRunCommand, RunService
from app.services.trace_models import TraceSpanRow
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture
async def seeded_run_tenant(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> tuple[Tenant, User, User, User]:
    suffix = uuid.uuid4().hex
    owner = User(
        username=f"run-owner-{suffix}",
        email=f"run-owner-{suffix}@example.com",
        hashed_password="test-password-hash",
    )
    member = User(
        username=f"run-member-{suffix}",
        email=f"run-member-{suffix}@example.com",
        hashed_password="test-password-hash",
    )
    outsider = User(
        username=f"run-outsider-{suffix}",
        email=f"run-outsider-{suffix}@example.com",
        hashed_password="test-password-hash",
    )
    tenant = Tenant(name="Run service tenant", slug=f"run-service-{suffix}")
    async with async_session_factory() as session, session.begin():
        session.add_all([owner, member, outsider, tenant])
        await session.flush()
        session.add_all(
            [
                TenantMembership(tenant_id=tenant.id, user_id=owner.id, role="owner"),
                TenantMembership(tenant_id=tenant.id, user_id=member.id, role="member"),
            ]
        )
    return tenant, owner, member, outsider


@pytest.fixture
def run_service(async_session_factory: async_sessionmaker[AsyncSession]) -> RunService:
    return RunService(async_session_factory)


@pytest.fixture
def command(seeded_run_tenant: tuple[Tenant, User, User, User]) -> CreateRunCommand:
    tenant, _owner, member, _outsider = seeded_run_tenant
    return CreateRunCommand(
        tenant_id=tenant.id,
        actor_id=member.id,
        session_id=None,
        prompt="分析贵州茅台最近三年的现金流。",
        idempotency_key=f"request-{uuid.uuid4().hex}",
        replaces_run_id=None,
    )


@pytest.mark.asyncio
async def test_create_is_atomic(run_service: RunService, command: CreateRunCommand) -> None:
    result = await run_service.create_run(command)

    assert result.run.status == "queued"
    assert result.message.content == command.prompt
    assert result.run.input_message_id == result.message.id
    assert [event.event_type for event in result.events] == ["run.created"]
    assert result.events[0].seq == 1


@pytest.mark.asyncio
async def test_create_writes_one_stable_schedule_wake_and_replay_does_not_duplicate_it(
    run_service: RunService,
    command: CreateRunCommand,
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first = await run_service.create_run(command)
    replay = await run_service.create_run(command)

    async with async_session_factory() as session:
        outboxes = tuple(
            (await session.scalars(select(RunOutbox).where(RunOutbox.run_id == first.run.id))).all()
        )
    assert replay.replayed is True
    assert len(outboxes) == 1
    assert outboxes[0].event_type == "schedule.wake"
    assert outboxes[0].tenant_id == command.tenant_id
    assert outboxes[0].attempt_id is None
    assert outboxes[0].worker_id is None
    assert outboxes[0].payload == {"run_id": str(first.run.id), "reason": "created"}
    assert outboxes[0].dedupe_key == f"schedule.wake:{first.run.id}:created"


@pytest.mark.asyncio
async def test_create_persists_canonical_request_hash(
    run_service: RunService, command: CreateRunCommand
) -> None:
    result = await run_service.create_run(command)
    canonical = json.dumps(
        {
            "prompt": command.prompt,
            "replaces_run_id": None,
            "session_id": None,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()

    assert result.run.request_hash == hashlib.sha256(canonical).hexdigest()


@pytest.mark.asyncio
async def test_idempotency_returns_same_run(
    run_service: RunService, command: CreateRunCommand
) -> None:
    first = await run_service.create_run(command)
    second = await run_service.create_run(command)

    assert second.run.id == first.run.id
    assert second.message.id == first.message.id
    assert [event.id for event in second.events] == [event.id for event in first.events]


@pytest.mark.asyncio
async def test_idempotency_conflict_rejects_different_payload(
    run_service: RunService, command: CreateRunCommand
) -> None:
    await run_service.create_run(command)

    with pytest.raises(IdempotencyConflict):
        await run_service.create_run(replace(command, prompt="改成分析利润质量。"))


@pytest.mark.asyncio
async def test_idempotency_replay_requires_current_membership(
    run_service: RunService,
    command: CreateRunCommand,
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await run_service.create_run(command)
    async with async_session_factory() as session, session.begin():
        membership = await session.get(TenantMembership, (command.tenant_id, command.actor_id))
        assert membership is not None
        await session.delete(membership)

    with pytest.raises(ResourceNotFound):
        await run_service.create_run(command)


@pytest.mark.asyncio
async def test_concurrent_same_idempotency_key_creates_one_run(
    run_service: RunService,
    command: CreateRunCommand,
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first, second = await asyncio.gather(
        run_service.create_run(command),
        run_service.create_run(command),
    )

    async with async_session_factory() as session:
        count = await session.scalar(
            select(func.count(Run.id)).where(
                Run.tenant_id == command.tenant_id,
                Run.created_by_user_id == command.actor_id,
                Run.idempotency_key == command.idempotency_key,
            )
        )
    assert first.run.id == second.run.id
    assert count == 1


@pytest.mark.asyncio
async def test_session_busy(run_service: RunService, command: CreateRunCommand) -> None:
    first = await run_service.create_run(command)

    with pytest.raises(SessionBusy):
        await run_service.create_run(
            replace(
                command,
                idempotency_key=f"request-{uuid.uuid4().hex}",
                session_id=first.run.session_id,
            )
        )


@pytest.mark.asyncio
async def test_concurrent_same_session_creates_only_one_active_run(
    run_service: RunService,
    command: CreateRunCommand,
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    created = await run_service.create_run(command)
    async with async_session_factory() as session, session.begin():
        await session.execute(
            update(Run).where(Run.id == created.run.id).values(status="completed")
        )

    first_command = replace(
        command,
        session_id=created.run.session_id,
        idempotency_key=f"request-{uuid.uuid4().hex}",
        prompt="并发请求 A",
    )
    second_command = replace(
        first_command,
        idempotency_key=f"request-{uuid.uuid4().hex}",
        prompt="并发请求 B",
    )
    results = await asyncio.gather(
        run_service.create_run(first_command),
        run_service.create_run(second_command),
        return_exceptions=True,
    )

    successes = [result for result in results if not isinstance(result, BaseException)]
    failures = [result for result in results if isinstance(result, BaseException)]
    async with async_session_factory() as session:
        active_count = await session.scalar(
            select(func.count(Run.id)).where(
                Run.session_id == created.run.session_id,
                Run.status.in_(
                    (
                        "queued",
                        "assigned",
                        "running",
                        "waiting_approval",
                        "waiting_input",
                        "cancel_requested",
                    )
                ),
            )
        )
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], SessionBusy)
    assert active_count == 1


@pytest.mark.asyncio
async def test_queue_quota_rolls_back_without_partial_rows(
    run_service: RunService,
    command: CreateRunCommand,
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with async_session_factory() as session, session.begin():
        await session.execute(
            update(Tenant).where(Tenant.id == command.tenant_id).values(max_queued_runs=1)
        )
    await run_service.create_run(command)
    rejected = replace(
        command,
        idempotency_key=f"request-{uuid.uuid4().hex}",
        prompt="第二个排队请求",
    )

    with pytest.raises(TenantQueueFull):
        await run_service.create_run(rejected)

    async with async_session_factory() as session:
        assert (
            await session.scalar(
                select(func.count(Run.id)).where(Run.tenant_id == command.tenant_id)
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count(RunMessage.id)).where(RunMessage.tenant_id == command.tenant_id)
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count(RunEvent.id)).where(RunEvent.tenant_id == command.tenant_id)
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count(RunSession.id)).where(RunSession.tenant_id == command.tenant_id)
            )
            == 1
        )


@pytest.mark.asyncio
async def test_active_replaced_run_is_rejected_as_session_busy(
    run_service: RunService, command: CreateRunCommand
) -> None:
    first = await run_service.create_run(command)

    with pytest.raises(SessionBusy):
        await run_service.create_run(
            replace(
                command,
                session_id=first.run.session_id,
                idempotency_key=f"request-{uuid.uuid4().hex}",
                replaces_run_id=first.run.id,
            )
        )


@pytest.mark.asyncio
async def test_replaces_run_must_match_session(
    run_service: RunService,
    command: CreateRunCommand,
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first = await run_service.create_run(command)
    async with async_session_factory() as session, session.begin():
        await session.execute(update(Run).where(Run.id == first.run.id).values(status="completed"))
        other_session = RunSession(
            tenant_id=command.tenant_id,
            created_by_user_id=command.actor_id,
        )
        session.add(other_session)
        await session.flush()
        other_session_id = other_session.id

    with pytest.raises(ResourceNotFound):
        await run_service.create_run(
            replace(
                command,
                session_id=other_session_id,
                idempotency_key=f"request-{uuid.uuid4().hex}",
                replaces_run_id=first.run.id,
            )
        )


@pytest.mark.asyncio
async def test_replaces_terminal_run_in_same_session(
    run_service: RunService,
    command: CreateRunCommand,
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first = await run_service.create_run(command)
    async with async_session_factory() as session, session.begin():
        await session.execute(update(Run).where(Run.id == first.run.id).values(status="completed"))

    replacement = await run_service.create_run(
        replace(
            command,
            session_id=first.run.session_id,
            idempotency_key=f"request-{uuid.uuid4().hex}",
            replaces_run_id=first.run.id,
            prompt="修订后的分析请求",
        )
    )

    assert replacement.run.replaces_run_id == first.run.id


@pytest.mark.asyncio
async def test_replacement_chain_cannot_fork_from_an_already_replaced_run(
    run_service: RunService,
    command: CreateRunCommand,
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first = await run_service.create_run(command)
    async with async_session_factory() as session, session.begin():
        await session.execute(update(Run).where(Run.id == first.run.id).values(status="completed"))
    second = await run_service.create_run(
        replace(
            command,
            session_id=first.run.session_id,
            idempotency_key=f"request-{uuid.uuid4().hex}",
            replaces_run_id=first.run.id,
            prompt="第二版分析请求",
        )
    )
    async with async_session_factory() as session, session.begin():
        await session.execute(update(Run).where(Run.id == second.run.id).values(status="completed"))

    with pytest.raises(ResourceNotFound):
        await run_service.create_run(
            replace(
                command,
                session_id=first.run.session_id,
                idempotency_key=f"request-{uuid.uuid4().hex}",
                replaces_run_id=first.run.id,
                prompt="错误地从第一版分叉",
            )
        )


@pytest.mark.asyncio
async def test_member_cannot_create_in_another_members_session(
    run_service: RunService,
    command: CreateRunCommand,
    seeded_run_tenant: tuple[Tenant, User, User, User],
) -> None:
    _tenant, owner, _member, _outsider = seeded_run_tenant
    owner_run = await run_service.create_run(replace(command, actor_id=owner.id))

    with pytest.raises(ResourceNotFound):
        await run_service.create_run(
            replace(
                command,
                session_id=owner_run.run.session_id,
                idempotency_key=f"request-{uuid.uuid4().hex}",
            )
        )


@pytest.mark.asyncio
async def test_outsider_get_is_404_domain_error(
    run_service: RunService,
    command: CreateRunCommand,
    seeded_run_tenant: tuple[Tenant, User, User, User],
) -> None:
    _tenant, _owner, _member, outsider = seeded_run_tenant
    created = await run_service.create_run(command)

    with pytest.raises(ResourceNotFound):
        await run_service.get_run(command.tenant_id, created.run.id, outsider.id)


@pytest.mark.asyncio
async def test_member_cannot_get_another_members_run(
    run_service: RunService,
    command: CreateRunCommand,
    seeded_run_tenant: tuple[Tenant, User, User, User],
) -> None:
    _tenant, owner, _member, _outsider = seeded_run_tenant
    created = await run_service.create_run(replace(command, actor_id=owner.id))

    with pytest.raises(ResourceNotFound):
        await run_service.get_run(command.tenant_id, created.run.id, command.actor_id)


@pytest.mark.asyncio
async def test_owner_can_get_member_run(
    run_service: RunService,
    command: CreateRunCommand,
    seeded_run_tenant: tuple[Tenant, User, User, User],
) -> None:
    _tenant, owner, _member, _outsider = seeded_run_tenant
    created = await run_service.create_run(command)

    result = await run_service.get_run(command.tenant_id, created.run.id, owner.id)

    assert result.id == created.run.id


@pytest.mark.asyncio
async def test_list_events_filters_after_seq(
    run_service: RunService,
    command: CreateRunCommand,
) -> None:
    created = await run_service.create_run(command)

    assert [
        event.seq
        for event in await run_service.list_events(
            command.tenant_id, created.run.id, command.actor_id, after_seq=0
        )
    ] == [1]
    assert (
        await run_service.list_events(
            command.tenant_id, created.run.id, command.actor_id, after_seq=1
        )
        == ()
    )


@pytest.mark.asyncio
async def test_get_trace_returns_ordered_rows_and_empty_when_absent(
    run_service: RunService,
    command: CreateRunCommand,
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    created = await run_service.create_run(command)
    assert await run_service.get_trace(command.tenant_id, created.run.id, command.actor_id) == ()
    started = datetime.now(UTC)
    async with async_session_factory() as session, session.begin():
        session.add_all(
            [
                TraceSpanRow(
                    span_id=f"span-b-{uuid.uuid4().hex}",
                    request_id=str(created.run.id),
                    parent_id=None,
                    name="second",
                    inputs={},
                    outputs={},
                    attrs_json={},
                    started_at=started + timedelta(seconds=1),
                    ended_at=started + timedelta(seconds=2),
                ),
                TraceSpanRow(
                    span_id=f"span-a-{uuid.uuid4().hex}",
                    request_id=str(created.run.id),
                    parent_id=None,
                    name="first",
                    inputs={},
                    outputs={},
                    attrs_json={},
                    started_at=started,
                    ended_at=started + timedelta(seconds=1),
                ),
            ]
        )

    trace = await run_service.get_trace(command.tenant_id, created.run.id, command.actor_id)

    assert [row.name for row in trace] == ["first", "second"]

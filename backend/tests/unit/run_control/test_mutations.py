from __future__ import annotations

import asyncio
import sys
import uuid

import pytest
import pytest_asyncio
from app.models.run import Run, RunEvent
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.run_control.mutations import RunMutationStore
from app.run_control.types import ResourceNotFound, RunStatus
from app.services.run_service import CreateRunCommand, RunService
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture
async def mutation_run(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> Run:
    suffix = uuid.uuid4().hex[:12]
    user = User(
        username=f"mutation-{suffix}",
        email=f"mutation-{suffix}@example.com",
        hashed_password="test-password-hash",
    )
    tenant = Tenant(name="Mutation tenant", slug=f"mutation-{suffix}")
    async with async_session_factory() as session, session.begin():
        session.add_all([user, tenant])
        await session.flush()
        session.add(TenantMembership(tenant_id=tenant.id, user_id=user.id, role="member"))

    service = RunService(async_session_factory)
    created = await service.create_run(
        CreateRunCommand(
            tenant_id=tenant.id,
            actor_id=user.id,
            session_id=None,
            prompt="mutation contract",
            idempotency_key=f"mutation-{uuid.uuid4().hex}",
            replaces_run_id=None,
        )
    )
    return created.run


async def _reload_status(factory: async_sessionmaker[AsyncSession], run_id: uuid.UUID) -> str:
    async with factory() as session:
        status = await session.scalar(select(Run.status).where(Run.id == run_id))
    assert status is not None
    return status


@pytest.mark.asyncio
async def test_transition_uses_callers_transaction_and_rolls_back(
    async_session_factory: async_sessionmaker[AsyncSession],
    mutation_run: Run,
) -> None:
    async with async_session_factory() as session, session.begin():
        store = RunMutationStore(session)
        run = await store.lock_run(mutation_run.tenant_id, mutation_run.id)
        event = await store.transition(
            run,
            RunStatus.ASSIGNED,
            "run.assigned",
            {"worker": "worker-a"},
        )
        assert event.seq == 2
        await session.rollback()

    assert await _reload_status(async_session_factory, mutation_run.id) == "queued"
    async with async_session_factory() as session:
        event_types = tuple(
            (
                await session.scalars(
                    select(RunEvent.event_type)
                    .where(RunEvent.run_id == mutation_run.id)
                    .order_by(RunEvent.seq)
                )
            ).all()
        )
    assert event_types == ("run.created",)


@pytest.mark.asyncio
async def test_transition_does_not_commit_before_caller_finishes_transaction(
    async_session_factory: async_sessionmaker[AsyncSession],
    mutation_run: Run,
) -> None:
    async with async_session_factory() as writer, writer.begin():
        store = RunMutationStore(writer)
        run = await store.lock_run(mutation_run.tenant_id, mutation_run.id)
        await store.transition(run, RunStatus.ASSIGNED, "run.assigned", {})

        assert await _reload_status(async_session_factory, mutation_run.id) == "queued"

    assert await _reload_status(async_session_factory, mutation_run.id) == "assigned"


@pytest.mark.asyncio
async def test_transition_event_overrides_spoofed_authoritative_status_fields(
    async_session_factory: async_sessionmaker[AsyncSession],
    mutation_run: Run,
) -> None:
    async with async_session_factory() as session, session.begin():
        store = RunMutationStore(session)
        run = await store.lock_run(mutation_run.tenant_id, mutation_run.id)
        event = await store.transition(
            run,
            RunStatus.ASSIGNED,
            "run.assigned",
            {"from_status": "failed", "status": "completed", "worker": "worker-b"},
        )

    assert event.payload == {
        "from_status": "queued",
        "status": "assigned",
        "worker": "worker-b",
    }
    assert run.assigned_at is not None


@pytest.mark.asyncio
async def test_two_callers_allocate_unique_monotonic_event_seq_under_run_lock(
    async_session_factory: async_sessionmaker[AsyncSession],
    mutation_run: Run,
) -> None:
    async def append(event_type: str) -> None:
        async with async_session_factory() as session, session.begin():
            store = RunMutationStore(session)
            run = await store.lock_run(mutation_run.tenant_id, mutation_run.id)
            await store.append_event(run, event_type, {})

    await asyncio.gather(append("test.first"), append("test.second"))

    async with async_session_factory() as session:
        events = tuple(
            (
                await session.scalars(
                    select(RunEvent)
                    .where(RunEvent.run_id == mutation_run.id)
                    .order_by(RunEvent.seq)
                )
            ).all()
        )
    assert [event.seq for event in events] == [1, 2, 3]
    assert {event.event_type for event in events[1:]} == {"test.first", "test.second"}


@pytest.mark.asyncio
async def test_lock_run_requires_matching_tenant(
    async_session_factory: async_sessionmaker[AsyncSession],
    mutation_run: Run,
) -> None:
    async with async_session_factory() as session, session.begin():
        with pytest.raises(ResourceNotFound):
            await RunMutationStore(session).lock_run(uuid.uuid4(), mutation_run.id)


@pytest.mark.asyncio
async def test_creator_filter_hides_run_without_locking_another_members_row(
    async_session_factory: async_sessionmaker[AsyncSession],
    mutation_run: Run,
) -> None:
    async with async_session_factory() as hidden_session, hidden_session.begin():
        with pytest.raises(ResourceNotFound):
            await RunMutationStore(hidden_session).lock_run(
                mutation_run.tenant_id,
                mutation_run.id,
                created_by_user_id=uuid.uuid4(),
            )

        async with async_session_factory() as owner_session, owner_session.begin():
            await owner_session.execute(text("SET LOCAL lock_timeout = '250ms'"))
            locked = await RunMutationStore(owner_session).lock_run(
                mutation_run.tenant_id,
                mutation_run.id,
                created_by_user_id=mutation_run.created_by_user_id,
            )
            assert locked.id == mutation_run.id

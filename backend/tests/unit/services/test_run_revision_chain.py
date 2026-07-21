from __future__ import annotations

import asyncio
import sys
import uuid
from dataclasses import replace
from datetime import datetime

import pytest
import pytest_asyncio
from app.models.run import Run, RunMessage
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.run_control.types import ResourceNotFound
from app.services.attempt_service import AttemptService
from app.services.run_service import CreateRunCommand, RunService
from app.services.run_session_service import RunSessionService
from sqlalchemy import event, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture
async def revision_command(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> CreateRunCommand:
    suffix = uuid.uuid4().hex
    user = User(
        username=f"revision-{suffix}",
        email=f"revision-{suffix}@example.com",
        hashed_password="hash",
    )
    outsider = User(
        username=f"revision-outsider-{suffix}",
        email=f"revision-outsider-{suffix}@example.com",
        hashed_password="hash",
    )
    tenant = Tenant(name=f"Revision {suffix}", slug=f"revision-{suffix}")
    async with async_session_factory() as session, session.begin():
        session.add_all([user, outsider, tenant])
        await session.flush()
        session.add(TenantMembership(tenant_id=tenant.id, user_id=user.id, role="member"))
    return CreateRunCommand(
        tenant_id=tenant.id,
        actor_id=user.id,
        session_id=None,
        prompt="prompt A",
        idempotency_key=f"revision-{uuid.uuid4().hex}",
        replaces_run_id=None,
    )


async def _complete(
    factory: async_sessionmaker[AsyncSession],
    run: Run,
    summary: str,
) -> None:
    async with factory() as session, session.begin():
        final = RunMessage(
            tenant_id=run.tenant_id,
            session_id=run.session_id,
            role="assistant",
            content=summary,
            status="complete",
        )
        session.add(final)
        await session.flush()
        await session.execute(
            update(Run)
            .where(Run.id == run.id)
            .values(status="completed", final_message_id=final.id)
        )


@pytest.mark.asyncio
async def test_revision_chain_is_linear_and_old_rows_remain_immutable(
    async_session_factory: async_sessionmaker[AsyncSession],
    revision_command: CreateRunCommand,
) -> None:
    service = RunService(async_session_factory)
    first = await service.create_run(revision_command)
    await _complete(async_session_factory, first.run, "answer A")
    second = await service.create_run(
        replace(
            revision_command,
            session_id=first.run.session_id,
            prompt="prompt B",
            idempotency_key=f"revision-{uuid.uuid4().hex}",
            replaces_run_id=first.run.id,
        )
    )
    await _complete(async_session_factory, second.run, "answer B")
    third = await service.create_run(
        replace(
            revision_command,
            session_id=first.run.session_id,
            prompt="prompt C",
            idempotency_key=f"revision-{uuid.uuid4().hex}",
            replaces_run_id=second.run.id,
        )
    )
    await _complete(async_session_factory, third.run, "answer C")

    with pytest.raises(ResourceNotFound, match="latest revision"):
        await service.create_run(
            replace(
                revision_command,
                session_id=first.run.session_id,
                prompt="fork from A",
                idempotency_key=f"revision-{uuid.uuid4().hex}",
                replaces_run_id=first.run.id,
            )
        )

    async with async_session_factory() as session:
        rows = tuple(
            (
                await session.scalars(
                    select(Run)
                    .where(Run.session_id == first.run.session_id)
                    .order_by(Run.created_at)
                )
            ).all()
        )
        inputs = tuple(
            (
                await session.scalars(
                    select(RunMessage)
                    .where(RunMessage.id.in_([row.input_message_id for row in rows]))
                    .order_by(RunMessage.created_at)
                )
            ).all()
        )
    assert [row.replaces_run_id for row in rows] == [None, first.run.id, second.run.id]
    assert [message.content for message in inputs] == ["prompt A", "prompt B", "prompt C"]


@pytest.mark.asyncio
async def test_session_projection_selects_latest_and_preserves_revision_summaries(
    async_session_factory: async_sessionmaker[AsyncSession],
    revision_command: CreateRunCommand,
) -> None:
    runs = RunService(async_session_factory)
    first = await runs.create_run(revision_command)
    await _complete(async_session_factory, first.run, "answer A")
    second = await runs.create_run(
        replace(
            revision_command,
            session_id=first.run.session_id,
            prompt="prompt B",
            idempotency_key=f"revision-{uuid.uuid4().hex}",
        )
    )
    await _complete(async_session_factory, second.run, "answer B")
    third = await runs.create_run(
        replace(
            revision_command,
            session_id=first.run.session_id,
            prompt="prompt B revised",
            idempotency_key=f"revision-{uuid.uuid4().hex}",
            replaces_run_id=second.run.id,
        )
    )

    detail = await RunSessionService(async_session_factory).get_session_detail(
        revision_command.tenant_id,
        first.run.session_id,
        revision_command.actor_id,
        limit=100,
    )

    assert detail.latest_run_id == third.run.id
    assert [message.content for message in detail.messages] == [
        "prompt A",
        "answer A",
        "prompt B revised",
    ]
    assert detail.has_more is False
    assert [
        (item.run.id, item.prompt, item.final_message_summary) for item in detail.revisions
    ] == [
        (first.run.id, "prompt A", "answer A"),
        (second.run.id, "prompt B", "answer B"),
        (third.run.id, "prompt B revised", None),
    ]
    assert detail.revisions[2].run.replaces_run_id == second.run.id

    paged = await RunSessionService(async_session_factory).get_session_detail(
        revision_command.tenant_id,
        first.run.session_id,
        revision_command.actor_id,
        limit=2,
    )
    assert [message.content for message in paged.messages] == [
        "answer A",
        "prompt B revised",
    ]
    assert paged.has_more is True


@pytest.mark.asyncio
async def test_model_history_excludes_superseded_prompt_messages(
    async_session_factory: async_sessionmaker[AsyncSession],
    revision_command: CreateRunCommand,
) -> None:
    runs = RunService(async_session_factory)
    first = await runs.create_run(revision_command)
    await _complete(async_session_factory, first.run, "answer A")
    second = await runs.create_run(
        replace(
            revision_command,
            session_id=first.run.session_id,
            prompt="prompt B",
            idempotency_key=f"revision-{uuid.uuid4().hex}",
        )
    )
    await _complete(async_session_factory, second.run, "answer B")
    third = await runs.create_run(
        replace(
            revision_command,
            session_id=first.run.session_id,
            prompt="prompt B revised",
            idempotency_key=f"revision-{uuid.uuid4().hex}",
            replaces_run_id=second.run.id,
        )
    )

    async with async_session_factory() as session:
        history = await AttemptService._load_model_history(session, third.run, limit=100)

    assert "prompt B" not in [item["content"] for item in history]
    assert "answer B" not in [item["content"] for item in history]
    assert [item["content"] for item in history] == ["prompt A", "answer A"]

    await _complete(async_session_factory, third.run, "answer B revised")
    fourth = await runs.create_run(
        replace(
            revision_command,
            session_id=first.run.session_id,
            prompt="prompt C",
            idempotency_key=f"revision-{uuid.uuid4().hex}",
        )
    )
    async with async_session_factory() as session:
        later_history = await AttemptService._load_model_history(session, fourth.run, limit=100)
    assert [item["content"] for item in later_history] == [
        "prompt A",
        "answer A",
        "prompt B revised",
        "answer B revised",
    ]


@pytest.mark.asyncio
async def test_superseded_run_without_final_message_does_not_poison_history_or_projection(
    async_session_factory: async_sessionmaker[AsyncSession],
    revision_command: CreateRunCommand,
) -> None:
    runs = RunService(async_session_factory)
    first = await runs.create_run(revision_command)
    async with async_session_factory() as session, session.begin():
        await session.execute(update(Run).where(Run.id == first.run.id).values(status="failed"))
    replacement = await runs.create_run(
        replace(
            revision_command,
            session_id=first.run.session_id,
            prompt="replacement prompt",
            idempotency_key=f"revision-{uuid.uuid4().hex}",
            replaces_run_id=first.run.id,
        )
    )

    async with async_session_factory() as session:
        history = await AttemptService._load_model_history(session, replacement.run, limit=100)
    detail = await RunSessionService(async_session_factory).get_session_detail(
        revision_command.tenant_id,
        first.run.session_id,
        revision_command.actor_id,
        limit=100,
    )

    assert history == ()
    assert [message.content for message in detail.messages] == ["replacement prompt"]
    assert [revision.prompt for revision in detail.revisions] == [
        "prompt A",
        "replacement prompt",
    ]


@pytest.mark.asyncio
async def test_revision_projection_requires_tenant_membership(
    async_session_factory: async_sessionmaker[AsyncSession],
    revision_command: CreateRunCommand,
) -> None:
    created = await RunService(async_session_factory).create_run(revision_command)
    async with async_session_factory() as session:
        outsider_id = await session.scalar(
            select(User.id).where(User.username.like("revision-outsider-%"))
        )
    assert outsider_id is not None
    with pytest.raises(ResourceNotFound):
        await RunSessionService(async_session_factory).get_session_detail(
            revision_command.tenant_id, created.run.session_id, outsider_id, limit=100
        )


@pytest.mark.asyncio
async def test_replacement_must_target_latest_session_run_even_without_an_existing_child(
    async_session_factory: async_sessionmaker[AsyncSession],
    revision_command: CreateRunCommand,
) -> None:
    service = RunService(async_session_factory)
    first = await service.create_run(revision_command)
    await _complete(async_session_factory, first.run, "answer A")
    later_turn = await service.create_run(
        replace(
            revision_command,
            session_id=first.run.session_id,
            prompt="later ordinary turn",
            idempotency_key=f"revision-{uuid.uuid4().hex}",
        )
    )
    await _complete(async_session_factory, later_turn.run, "later answer")

    with pytest.raises(ResourceNotFound, match="latest revision"):
        await service.create_run(
            replace(
                revision_command,
                session_id=first.run.session_id,
                prompt="stale leaf edit",
                idempotency_key=f"revision-{uuid.uuid4().hex}",
                replaces_run_id=first.run.id,
            )
        )


@pytest.mark.asyncio
async def test_revision_sequence_not_uuid_orders_runs_with_identical_timestamps(
    async_session_factory: async_sessionmaker[AsyncSession],
    revision_command: CreateRunCommand,
) -> None:
    service = RunService(async_session_factory)
    ids = iter([uuid.UUID(int=(1 << 128) - 2), uuid.UUID(int=1)])

    def assign_id(_mapper: object, _connection: object, target: Run) -> None:
        target.id = next(ids)

    event.listen(Run, "before_insert", assign_id)
    try:
        first = await service.create_run(revision_command)
        await _complete(async_session_factory, first.run, "answer A")
        second = await service.create_run(
            replace(
                revision_command,
                session_id=first.run.session_id,
                prompt="newer prompt",
                idempotency_key=f"revision-{uuid.uuid4().hex}",
            )
        )
    finally:
        event.remove(Run, "before_insert", assign_id)
    await _complete(async_session_factory, second.run, "answer B")
    same_time = datetime(2026, 7, 20, 12, 0, 0)
    async with async_session_factory() as session, session.begin():
        # Preserve FK provenance while making the newer UUID lexically smaller.
        await session.execute(
            update(Run).where(Run.id == second.run.id).values(created_at=same_time)
        )
        await session.execute(
            update(Run).where(Run.id == first.run.id).values(created_at=same_time)
        )
    detail = await RunSessionService(async_session_factory).get_session_detail(
        revision_command.tenant_id,
        first.run.session_id,
        revision_command.actor_id,
        limit=100,
    )
    assert detail.latest_run_id == second.run.id
    assert [item.run.revision_seq for item in detail.revisions] == [1, 2]
    assert second.run.id < first.run.id


@pytest.mark.asyncio
async def test_revision_projection_is_bounded_and_cursor_paginates_without_full_old_prompts(
    async_session_factory: async_sessionmaker[AsyncSession],
    revision_command: CreateRunCommand,
) -> None:
    service = RunService(async_session_factory)
    created = []
    command = revision_command
    for index in range(4):
        item = await service.create_run(command)
        created.append(item)
        await _complete(async_session_factory, item.run, f"answer {index}")
        command = replace(
            revision_command,
            session_id=item.run.session_id,
            prompt=("X" * 10_000) + str(index + 1),
            idempotency_key=f"revision-{uuid.uuid4().hex}",
        )

    sessions = RunSessionService(async_session_factory)
    newest = await sessions.get_session_detail(
        revision_command.tenant_id,
        created[0].run.session_id,
        revision_command.actor_id,
        limit=100,
        revision_limit=2,
    )
    assert [item.run.id for item in newest.revisions] == [created[2].run.id, created[3].run.id]
    assert newest.revisions_has_more is True
    assert newest.revisions_next_cursor is not None
    assert newest.revisions[-1].prompt_is_full is True
    assert len(newest.revisions[0].prompt) <= 240

    older = await sessions.get_session_detail(
        revision_command.tenant_id,
        created[0].run.session_id,
        revision_command.actor_id,
        limit=100,
        revision_limit=2,
        revision_cursor=newest.revisions_next_cursor,
    )
    assert [item.run.id for item in older.revisions] == [created[0].run.id, created[1].run.id]
    assert older.revisions_has_more is False
    assert all(not item.prompt_is_full for item in older.revisions)

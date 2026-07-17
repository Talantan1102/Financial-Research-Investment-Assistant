"""Transactional creation and read operations for durable Runs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.run import Run, RunAttempt, RunEvent, RunMessage, RunPause, RunSession
from app.models.run_scheduling import RunOutbox
from app.models.tenant import Tenant, TenantMembership
from app.run_control.mutations import RunMutationStore
from app.run_control.types import (
    ACTIVE_RUN_STATUSES,
    TERMINAL_RUN_STATUSES,
    IdempotencyConflict,
    OutboxType,
    PauseType,
    ResourceNotFound,
    ResumeNotAllowed,
    RunStatus,
    SessionBusy,
    TenantQueueFull,
    TenantRole,
    assert_transition,
)
from app.services.trace_models import TraceSpanRow


@dataclass(frozen=True)
class CreateRunCommand:
    tenant_id: UUID
    actor_id: UUID
    session_id: UUID | None
    prompt: str
    idempotency_key: str
    replaces_run_id: UUID | None


@dataclass(frozen=True)
class CreatedRun:
    run: Run
    message: RunMessage
    events: tuple[RunEvent, ...]
    replayed: bool = False


class RunService:
    """Own all transaction boundaries for Run commands and queries."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_run(self, command: CreateRunCommand) -> CreatedRun:
        request_hash = _canonical_request_hash(command)
        async with self._session_factory() as session, session.begin():
            existing = await self._find_idempotent_run(session, command)
            if existing is not None:
                await self._require_membership(session, command.tenant_id, command.actor_id)
                return await self._replay_or_conflict(session, existing, request_hash)

            tenant = await session.scalar(
                select(Tenant).where(Tenant.id == command.tenant_id).with_for_update()
            )
            if tenant is None:
                raise ResourceNotFound("tenant not found")
            await self._require_membership(session, command.tenant_id, command.actor_id)

            # The tenant row lock serializes queued quota allocation and makes a
            # second idempotency lookup observe a concurrent creator's commit.
            existing = await self._find_idempotent_run(session, command)
            if existing is not None:
                return await self._replay_or_conflict(session, existing, request_hash)

            queued_count = await session.scalar(
                select(func.count(Run.id)).where(
                    Run.tenant_id == command.tenant_id,
                    Run.status == RunStatus.QUEUED.value,
                )
            )
            if int(queued_count or 0) >= int(tenant.max_queued_runs):
                raise TenantQueueFull("tenant queued run quota is full")

            run_session = await self._get_or_create_session(session, command)
            await session.execute(
                text(
                    "SELECT pg_advisory_xact_lock("
                    "hashtextextended('run-session:' || :session_id, 0))"
                ),
                {"session_id": str(run_session.id)},
            )

            active = await session.scalar(
                select(Run.id).where(
                    Run.session_id == run_session.id,
                    Run.status.in_(tuple(status.value for status in ACTIVE_RUN_STATUSES)),
                )
            )
            if active is not None:
                raise SessionBusy("session already has an active run")

            if command.replaces_run_id is not None:
                await self._validate_replacement(session, command, cast(UUID, run_session.id))

            message = RunMessage(
                tenant_id=command.tenant_id,
                session_id=run_session.id,
                role="user",
                content=command.prompt,
                status="complete",
            )
            session.add(message)
            await session.flush()

            run = Run(
                tenant_id=command.tenant_id,
                session_id=run_session.id,
                created_by_user_id=command.actor_id,
                run_type="chat",
                status=RunStatus.QUEUED.value,
                idempotency_key=command.idempotency_key,
                request_hash=request_hash,
                input_message_id=message.id,
                replaces_run_id=command.replaces_run_id,
                retry_count=0,
            )
            session.add(run)
            await session.flush()

            mutation_store = RunMutationStore(session)
            event = await mutation_store.append_event(
                run,
                "run.created",
                {
                    "run_id": str(run.id),
                    "session_id": str(run.session_id),
                    "status": RunStatus.QUEUED.value,
                },
            )
            self._add_outbox(
                session,
                event_type=OutboxType.SCHEDULE_WAKE,
                run=run,
                payload={"run_id": str(run.id), "reason": "created"},
                dedupe_key=f"schedule.wake:{run.id}:created",
            )
            return CreatedRun(run=run, message=message, events=(event,))

    async def get_run(self, tenant_id: UUID, run_id: UUID, actor_id: UUID) -> Run:
        async with self._session_factory() as session, session.begin():
            return await self._get_visible_run(session, tenant_id, run_id, actor_id)

    async def list_events(
        self,
        tenant_id: UUID,
        run_id: UUID,
        actor_id: UUID,
        *,
        after_seq: int = 0,
    ) -> tuple[RunEvent, ...]:
        async with self._session_factory() as session, session.begin():
            await self._get_visible_run(session, tenant_id, run_id, actor_id)
            rows = await session.scalars(
                select(RunEvent)
                .where(
                    RunEvent.tenant_id == tenant_id,
                    RunEvent.run_id == run_id,
                    RunEvent.seq > after_seq,
                )
                .order_by(RunEvent.seq.asc())
            )
            return tuple(rows.all())

    async def get_trace(
        self, tenant_id: UUID, run_id: UUID, actor_id: UUID
    ) -> tuple[TraceSpanRow, ...]:
        async with self._session_factory() as session, session.begin():
            await self._get_visible_run(session, tenant_id, run_id, actor_id)
            rows = await session.scalars(
                select(TraceSpanRow)
                .where(TraceSpanRow.request_id == str(run_id))
                .order_by(TraceSpanRow.started_at.asc(), TraceSpanRow.span_id.asc())
            )
            return tuple(rows.all())

    async def transition_run(
        self,
        tenant_id: UUID,
        run_id: UUID,
        actor_id: UUID,
        target_status: RunStatus,
        *,
        event_type: str,
        payload: dict[str, Any] | None = None,
        attempt_id: UUID | None = None,
    ) -> Run:
        async with self._session_factory() as session, session.begin():
            mutation_store = RunMutationStore(session)
            run = await self._lock_visible_run(session, mutation_store, tenant_id, run_id, actor_id)
            await mutation_store.transition(
                run,
                target_status,
                event_type,
                payload or {},
                attempt_id=attempt_id,
            )
            return run

    async def cancel_run(self, tenant_id: UUID, run_id: UUID, actor_id: UUID) -> Run:
        async with self._session_factory() as session, session.begin():
            mutation_store = RunMutationStore(session)
            run = await self._lock_visible_run(session, mutation_store, tenant_id, run_id, actor_id)
            current_status = RunStatus(cast(str, run.status))
            if (
                current_status in TERMINAL_RUN_STATUSES
                or current_status == RunStatus.CANCEL_REQUESTED
            ):
                return run

            if current_status in {
                RunStatus.QUEUED,
                RunStatus.WAITING_APPROVAL,
                RunStatus.WAITING_INPUT,
            }:
                target_status = RunStatus.CANCELLED
                event_type = "run.cancelled"
            else:
                target_status = RunStatus.CANCEL_REQUESTED
                event_type = "run.cancel_requested"

            await mutation_store.transition(
                run,
                target_status,
                event_type,
                {},
            )
            if current_status in {RunStatus.ASSIGNED, RunStatus.RUNNING}:
                attempt = await session.scalar(
                    select(RunAttempt)
                    .where(
                        RunAttempt.run_id == run.id,
                        RunAttempt.status.in_(("assigned", "running")),
                    )
                    .order_by(RunAttempt.attempt_no.desc())
                    .limit(1)
                )
                self._add_outbox(
                    session,
                    event_type=OutboxType.ATTEMPT_CANCEL,
                    run=run,
                    attempt=attempt,
                    payload={"run_id": str(run.id)},
                    dedupe_key=f"attempt.cancel:{run.id}",
                )
            return run

    async def record_pause(
        self,
        tenant_id: UUID,
        run_id: UUID,
        actor_id: UUID,
        pause_type: PauseType,
        *,
        request_payload: dict[str, Any],
        continuation_payload: dict[str, Any],
        attempt_id: UUID | None = None,
    ) -> RunPause:
        async with self._session_factory() as session, session.begin():
            mutation_store = RunMutationStore(session)
            run = await self._lock_visible_run(session, mutation_store, tenant_id, run_id, actor_id)
            target_status = {
                PauseType.APPROVAL: RunStatus.WAITING_APPROVAL,
                PauseType.INPUT: RunStatus.WAITING_INPUT,
            }[pause_type]
            assert_transition(RunStatus(cast(str, run.status)), target_status)
            last_pause_no = await session.scalar(
                select(func.coalesce(func.max(RunPause.pause_no), 0)).where(
                    RunPause.run_id == run.id
                )
            )
            pause = RunPause(
                run_id=run.id,
                pause_no=int(last_pause_no or 0) + 1,
                pause_type=pause_type.value,
                request_payload=request_payload,
                continuation_payload=continuation_payload,
            )
            session.add(pause)
            await session.flush()
            cast(Any, run).status = target_status.value
            await mutation_store.append_event(
                run,
                "run.paused",
                {
                    "pause_id": str(pause.id),
                    "pause_no": pause.pause_no,
                    "pause_type": pause.pause_type,
                    "status": target_status.value,
                },
                attempt_id=attempt_id,
            )
            return pause

    async def resume_run(
        self,
        tenant_id: UUID,
        run_id: UUID,
        actor_id: UUID,
        *,
        response: dict[str, Any],
    ) -> Run:
        async with self._session_factory() as session, session.begin():
            mutation_store = RunMutationStore(session)
            run = await self._lock_visible_run(session, mutation_store, tenant_id, run_id, actor_id)
            latest_pause = await session.scalar(
                select(RunPause)
                .where(RunPause.run_id == run.id)
                .order_by(RunPause.pause_no.desc())
                .limit(1)
                .with_for_update()
            )
            current_status = RunStatus(cast(str, run.status))
            if (
                current_status == RunStatus.QUEUED
                and latest_pause is not None
                and latest_pause.resolved_at is not None
            ):
                return run
            if current_status not in {
                RunStatus.WAITING_APPROVAL,
                RunStatus.WAITING_INPUT,
            }:
                raise ResumeNotAllowed("run is not waiting")
            if latest_pause is None or latest_pause.resolved_at is not None:
                raise ResumeNotAllowed("run has no unresolved pause")
            expected_pause_type = {
                RunStatus.WAITING_APPROVAL: PauseType.APPROVAL.value,
                RunStatus.WAITING_INPUT: PauseType.INPUT.value,
            }[current_status]
            if latest_pause.pause_type != expected_pause_type:
                raise ResumeNotAllowed("pause type does not match run status")

            assert_transition(current_status, RunStatus.QUEUED)
            now = _utcnow()
            latest_pause.response_payload = response
            latest_pause.resolved_at = now
            cast(Any, run).status = RunStatus.QUEUED.value
            cast(Any, run).queue_reason = "resume"
            cast(Any, run).queued_at = now
            await mutation_store.append_event(
                run,
                "run.resumed",
                {
                    "from_status": current_status.value,
                    "status": RunStatus.QUEUED.value,
                    "pause_id": str(latest_pause.id),
                    "pause_no": latest_pause.pause_no,
                },
            )
            self._add_outbox(
                session,
                event_type=OutboxType.SCHEDULE_WAKE,
                run=run,
                payload={"run_id": str(run.id), "reason": "resume"},
                dedupe_key=f"schedule.wake:{run.id}:resume:{latest_pause.id}",
            )
            return run

    async def get_pause(
        self,
        tenant_id: UUID,
        run_id: UUID,
        actor_id: UUID,
        pause_id: UUID,
    ) -> RunPause:
        async with self._session_factory() as session, session.begin():
            await self._get_visible_run(session, tenant_id, run_id, actor_id)
            pause = await session.scalar(
                select(RunPause).where(
                    RunPause.id == pause_id,
                    RunPause.run_id == run_id,
                )
            )
            if pause is None:
                raise ResourceNotFound("run pause not found")
            return pause

    async def _find_idempotent_run(
        self, session: AsyncSession, command: CreateRunCommand
    ) -> Run | None:
        return await session.scalar(
            select(Run).where(
                Run.tenant_id == command.tenant_id,
                Run.created_by_user_id == command.actor_id,
                Run.idempotency_key == command.idempotency_key,
            )
        )

    async def _replay_or_conflict(
        self, session: AsyncSession, existing: Run, request_hash: str
    ) -> CreatedRun:
        if existing.request_hash != request_hash:
            raise IdempotencyConflict("idempotency key was reused with different input")
        message = await session.scalar(
            select(RunMessage).where(
                RunMessage.tenant_id == existing.tenant_id,
                RunMessage.session_id == existing.session_id,
                RunMessage.id == existing.input_message_id,
            )
        )
        if message is None:
            raise ResourceNotFound("run input message not found")
        events = await session.scalars(
            select(RunEvent)
            .where(
                RunEvent.tenant_id == existing.tenant_id,
                RunEvent.run_id == existing.id,
            )
            .order_by(RunEvent.seq.asc())
        )
        return CreatedRun(
            run=existing,
            message=message,
            events=tuple(events.all()),
            replayed=True,
        )

    async def _get_or_create_session(
        self, session: AsyncSession, command: CreateRunCommand
    ) -> RunSession:
        if command.session_id is None:
            run_session = RunSession(
                tenant_id=command.tenant_id,
                created_by_user_id=command.actor_id,
            )
            session.add(run_session)
            await session.flush()
            return run_session

        existing_session = await session.scalar(
            select(RunSession).where(
                RunSession.id == command.session_id,
                RunSession.tenant_id == command.tenant_id,
                RunSession.created_by_user_id == command.actor_id,
            )
        )
        if existing_session is None:
            raise ResourceNotFound("session not found")
        return existing_session

    async def _validate_replacement(
        self, session: AsyncSession, command: CreateRunCommand, session_id: UUID
    ) -> None:
        replacement = await session.scalar(
            select(Run.id).where(
                Run.id == command.replaces_run_id,
                Run.tenant_id == command.tenant_id,
                Run.created_by_user_id == command.actor_id,
                Run.session_id == session_id,
                Run.status.in_(tuple(status.value for status in TERMINAL_RUN_STATUSES)),
            )
        )
        if replacement is None:
            raise ResourceNotFound("replaced run not found")
        existing_child = await session.scalar(
            select(Run.id).where(Run.replaces_run_id == command.replaces_run_id)
        )
        if existing_child is not None:
            raise ResourceNotFound("replaced run is not the latest revision")

    async def _get_visible_run(
        self, session: AsyncSession, tenant_id: UUID, run_id: UUID, actor_id: UUID
    ) -> Run:
        membership = await self._require_membership(session, tenant_id, actor_id)
        conditions = [Run.id == run_id, Run.tenant_id == tenant_id]
        if membership.role == TenantRole.MEMBER.value:
            conditions.append(Run.created_by_user_id == actor_id)
        run = await session.scalar(select(Run).where(*conditions))
        if run is None:
            raise ResourceNotFound("run not found")
        return run

    async def _lock_visible_run(
        self,
        session: AsyncSession,
        mutation_store: RunMutationStore,
        tenant_id: UUID,
        run_id: UUID,
        actor_id: UUID,
    ) -> Run:
        membership = await self._require_membership(session, tenant_id, actor_id)
        return await mutation_store.lock_run(
            tenant_id,
            run_id,
            created_by_user_id=(actor_id if membership.role == TenantRole.MEMBER.value else None),
        )

    @staticmethod
    def _add_outbox(
        session: AsyncSession,
        *,
        event_type: OutboxType,
        run: Run,
        payload: dict[str, Any],
        dedupe_key: str,
        attempt: RunAttempt | None = None,
    ) -> None:
        session.add(
            RunOutbox(
                event_type=event_type.value,
                tenant_id=run.tenant_id,
                run_id=run.id,
                attempt_id=attempt.id if attempt is not None else None,
                worker_id=attempt.worker_id if attempt is not None else None,
                payload=payload,
                dedupe_key=dedupe_key,
            )
        )

    @staticmethod
    async def _require_membership(
        session: AsyncSession, tenant_id: UUID, actor_id: UUID
    ) -> TenantMembership:
        membership = await session.scalar(
            select(TenantMembership).where(
                TenantMembership.tenant_id == tenant_id,
                TenantMembership.user_id == actor_id,
            )
        )
        if membership is None:
            raise ResourceNotFound("tenant not found")
        return membership


def _canonical_request_hash(command: CreateRunCommand) -> str:
    canonical = json.dumps(
        {
            "session_id": str(command.session_id) if command.session_id is not None else None,
            "prompt": command.prompt,
            "replaces_run_id": (
                str(command.replaces_run_id) if command.replaces_run_id is not None else None
            ),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)

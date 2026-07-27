"""Transactional RBAC operations for the v1 Session read model."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from app.models.run import Run, RunMessage, RunPause, RunSession
from app.models.tenant import TenantMembership
from app.run_control.types import ACTIVE_RUN_STATUSES, ResourceNotFound, TenantRole


@dataclass(frozen=True)
class RunRevision:
    run: Run
    prompt: str
    final_message_summary: str | None
    prompt_is_full: bool


@dataclass(frozen=True)
class RunSessionDetail:
    run_session: RunSession
    messages: tuple[RunMessage, ...]
    has_more: bool
    active_run: Run | None
    active_pause: RunPause | None
    revisions: tuple[RunRevision, ...]
    revisions_has_more: bool
    revisions_next_cursor: str | None
    latest_run_id: UUID | None
    latest_run_status: str | None


class RunSessionService:
    """Own Session query/mutation transactions and visibility checks."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_sessions(self, tenant_id: UUID, actor_id: UUID) -> tuple[RunSession, ...]:
        async with self._session_factory() as session, session.begin():
            membership = await self._require_membership(session, tenant_id, actor_id)
            conditions = [
                RunSession.tenant_id == tenant_id,
                RunSession.archived_at.is_(None),
            ]
            if membership.role == TenantRole.MEMBER.value:
                conditions.append(RunSession.created_by_user_id == actor_id)
            rows = await session.scalars(
                select(RunSession)
                .where(*conditions)
                .order_by(RunSession.updated_at.desc(), RunSession.id.desc())
            )
            return tuple(rows.all())

    async def get_session(self, tenant_id: UUID, session_id: UUID, actor_id: UUID) -> RunSession:
        async with self._session_factory() as session, session.begin():
            return await self._get_visible_session(session, tenant_id, session_id, actor_id)

    async def get_session_detail(
        self,
        tenant_id: UUID,
        session_id: UUID,
        actor_id: UUID,
        *,
        limit: int,
        revision_limit: int = 20,
        revision_cursor: str | None = None,
    ) -> RunSessionDetail:
        async with self._session_factory() as session, session.begin():
            # This service owns a fresh Session for the detail request. Set the
            # isolation level before its first read so authorization, messages,
            # Run control state, and revisions share one PostgreSQL snapshot.
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
            run_session = await self._get_visible_session(session, tenant_id, session_id, actor_id)
            parent = aliased(Run)
            child = aliased(Run)
            superseded_inputs = (
                select(parent.input_message_id)
                .join(child, child.replaces_run_id == parent.id)
                .where(
                    parent.tenant_id == tenant_id,
                    parent.session_id == session_id,
                    child.tenant_id == tenant_id,
                    child.session_id == session_id,
                )
            )
            superseded_finals = (
                select(parent.final_message_id)
                .join(child, child.replaces_run_id == parent.id)
                .where(
                    parent.tenant_id == tenant_id,
                    parent.session_id == session_id,
                    child.tenant_id == tenant_id,
                    child.session_id == session_id,
                    parent.final_message_id.is_not(None),
                )
            )
            superseded_messages = superseded_inputs.union_all(superseded_finals)
            rows = await session.scalars(
                select(RunMessage)
                .where(
                    RunMessage.tenant_id == tenant_id,
                    RunMessage.session_id == session_id,
                    RunMessage.id.not_in(superseded_messages),
                )
                .order_by(RunMessage.created_at.desc(), RunMessage.id.desc())
                .limit(limit + 1)
            )
            messages = tuple(rows.all())
            # Recovery consumers must never combine a Run from one committed
            # state with a pause from another. Fetch the latest Run, active Run,
            # and its unresolved pause in one PostgreSQL statement snapshot.
            latest = aliased(Run)
            latest_run_id = (
                select(latest.id)
                .where(latest.tenant_id == tenant_id, latest.session_id == session_id)
                .order_by(latest.revision_seq.desc())
                .limit(1)
                .scalar_subquery()
            )
            recovery_rows = (
                await session.execute(
                    select(Run, RunPause)
                    .outerjoin(
                        RunPause,
                        and_(
                            RunPause.run_id == Run.id,
                            RunPause.resolved_at.is_(None),
                        ),
                    )
                    .where(
                        Run.tenant_id == tenant_id,
                        Run.session_id == session_id,
                        or_(
                            Run.status.in_([status.value for status in ACTIVE_RUN_STATUSES]),
                            Run.id == latest_run_id,
                        ),
                    )
                    .order_by(Run.revision_seq.desc(), RunPause.pause_no.desc())
                )
            ).all()
            latest_run = recovery_rows[0][0] if recovery_rows else None
            active_run = next(
                (
                    run
                    for run, _pause in recovery_rows
                    if run.status in {status.value for status in ACTIVE_RUN_STATUSES}
                ),
                None,
            )
            active_pause = next(
                (
                    pause
                    for run, pause in recovery_rows
                    if active_run is not None and run.id == active_run.id and pause is not None
                ),
                None,
            )
            revision_statement = select(Run).where(
                Run.tenant_id == tenant_id, Run.session_id == session_id
            )
            if revision_cursor is not None:
                cursor_id = _decode_revision_cursor(revision_cursor)
                cursor_run = await session.scalar(
                    select(Run).where(
                        Run.id == cursor_id,
                        Run.tenant_id == tenant_id,
                        Run.session_id == session_id,
                    )
                )
                if cursor_run is None:
                    raise ResourceNotFound("revision cursor not found")
                revision_statement = revision_statement.where(
                    Run.revision_seq < cursor_run.revision_seq
                )
            newest_first = tuple(
                (
                    await session.scalars(
                        revision_statement.order_by(Run.revision_seq.desc()).limit(
                            revision_limit + 1
                        )
                    )
                ).all()
            )
            revisions_has_more = len(newest_first) > revision_limit
            page_newest_first = newest_first[:revision_limit]
            runs = tuple(reversed(page_newest_first))
            revisions_next_cursor = (
                _encode_revision_cursor(cast(UUID, page_newest_first[-1].id))
                if revisions_has_more and page_newest_first
                else None
            )
            message_ids = {
                message_id
                for run in runs
                for message_id in (run.input_message_id, run.final_message_id)
                if message_id is not None
            }
            revision_messages = {}
            if message_ids:
                revision_messages = {
                    message.id: message
                    for message in (
                        await session.scalars(
                            select(RunMessage).where(
                                RunMessage.tenant_id == tenant_id,
                                RunMessage.session_id == session_id,
                                RunMessage.id.in_(message_ids),
                            )
                        )
                    ).all()
                }
            revisions = tuple(
                RunRevision(
                    run=run,
                    prompt=(
                        cast(str, revision_messages[run.input_message_id].content)
                        if latest_run is not None and run.id == latest_run.id
                        else _summary(cast(str, revision_messages[run.input_message_id].content))
                    ),
                    final_message_summary=(
                        None
                        if run.final_message_id is None
                        else _summary(cast(str, revision_messages[run.final_message_id].content))
                    ),
                    prompt_is_full=(
                        latest_run is not None and cast(UUID, run.id) == cast(UUID, latest_run.id)
                    ),
                )
                for run in runs
            )
            return RunSessionDetail(
                run_session=run_session,
                messages=tuple(reversed(messages[:limit])),
                has_more=len(messages) > limit,
                active_run=active_run,
                active_pause=active_pause,
                revisions=revisions,
                revisions_has_more=revisions_has_more,
                revisions_next_cursor=revisions_next_cursor,
                latest_run_id=None if latest_run is None else cast(UUID, latest_run.id),
                latest_run_status=None if latest_run is None else cast(str, latest_run.status),
            )

    async def update_title(
        self,
        tenant_id: UUID,
        session_id: UUID,
        actor_id: UUID,
        title: str,
    ) -> RunSession:
        async with self._session_factory() as session, session.begin():
            run_session = await self._get_visible_session(
                session,
                tenant_id,
                session_id,
                actor_id,
                for_update=True,
            )
            run_session.title = title  # type: ignore[assignment]
            await session.flush()
            return run_session

    async def archive_session(self, tenant_id: UUID, session_id: UUID, actor_id: UUID) -> None:
        async with self._session_factory() as session, session.begin():
            run_session = await self._get_visible_session(
                session,
                tenant_id,
                session_id,
                actor_id,
                for_update=True,
            )
            if run_session.archived_at is None:
                run_session.archived_at = datetime.now(UTC).replace(tzinfo=None)
                await session.flush()

    @staticmethod
    async def _require_membership(
        session: AsyncSession,
        tenant_id: UUID,
        actor_id: UUID,
        *,
        for_update: bool = False,
    ) -> TenantMembership:
        statement = select(TenantMembership).where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.user_id == actor_id,
        )
        if for_update:
            statement = statement.with_for_update()
        membership = await session.scalar(statement)
        if membership is None:
            raise ResourceNotFound("tenant not found")
        return membership

    async def _get_visible_session(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        session_id: UUID,
        actor_id: UUID,
        *,
        for_update: bool = False,
    ) -> RunSession:
        # Mutation lock order is membership then Session. The membership lock
        # linearizes this authorization decision with a concurrent revocation.
        membership = await self._require_membership(
            session,
            tenant_id,
            actor_id,
            for_update=for_update,
        )
        conditions = [RunSession.id == session_id, RunSession.tenant_id == tenant_id]
        if membership.role == TenantRole.MEMBER.value:
            conditions.append(RunSession.created_by_user_id == actor_id)
        statement = select(RunSession).where(*conditions)
        if for_update:
            statement = statement.with_for_update()
        run_session = await session.scalar(statement)
        if run_session is None:
            raise ResourceNotFound("session not found")
        return run_session


def _encode_revision_cursor(run_id: UUID) -> str:
    return base64.urlsafe_b64encode(run_id.bytes).decode("ascii").rstrip("=")


def _decode_revision_cursor(cursor: str) -> UUID:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        return UUID(bytes=raw)
    except (ValueError, TypeError) as exc:
        raise ResourceNotFound("revision cursor not found") from exc


def _summary(content: str, *, limit: int = 240) -> str:
    compact = " ".join(content.split())
    return compact if len(compact) <= limit else f"{compact[: limit - 1]}…"

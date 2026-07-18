"""Transactional RBAC operations for the v1 Session read model."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.run import RunSession
from app.models.tenant import TenantMembership
from app.run_control.types import ResourceNotFound, TenantRole


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

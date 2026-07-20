"""Run-native provenance repository for research escalation handoff."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.run import Run, RunMessage, RunSession
from app.models.tenant import TenantMembership


class RunEscalationRepo:
    """Small adapter used by escalation; it never touches chat_* tables."""

    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self._sf = session_factory

    async def get_session(self, session_id: UUID) -> RunSession | None:
        async with self._sf() as session:
            return await session.scalar(select(RunSession).where(RunSession.id == session_id))

    async def session_belongs_to_tenant(self, session_id: UUID, tenant_id: UUID, user_id: UUID) -> bool:
        async with self._sf() as session:
            row = await session.scalar(
                select(RunSession)
                .join(TenantMembership, TenantMembership.tenant_id == RunSession.tenant_id)
                .where(
                    RunSession.id == session_id,
                    RunSession.tenant_id == tenant_id,
                    TenantMembership.user_id == user_id,
                )
            )
            return row is not None

    async def get_run(self, run_id: UUID) -> Run | None:
        async with self._sf() as session:
            return await session.scalar(select(Run).where(Run.id == run_id))

    async def append_message(self, *, session_id: UUID, role: str, content: str, **_: Any) -> RunMessage:
        async with self._sf() as session, session.begin():
            run_session = await session.scalar(select(RunSession).where(RunSession.id == session_id))
            if run_session is None:
                raise ValueError("run session not found")
            row = RunMessage(
                tenant_id=run_session.tenant_id,
                session_id=run_session.id,
                role=role,
                content=content,
                status="done",
            )
            session.add(row)
            await session.flush()
            return row

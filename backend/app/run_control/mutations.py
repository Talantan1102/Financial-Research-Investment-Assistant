"""Transaction-bound PostgreSQL mutation primitives for persistent runs."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.run import Run, RunEvent
from app.run_control.types import (
    TERMINAL_RUN_STATUSES,
    ResourceNotFound,
    RunStatus,
    assert_transition,
)


class RunMutationStore:
    """Mutate a locked Run without owning the caller's transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lock_run(
        self,
        tenant_id: UUID,
        run_id: UUID,
        *,
        created_by_user_id: UUID | None = None,
    ) -> Run:
        conditions = [Run.id == run_id, Run.tenant_id == tenant_id]
        if created_by_user_id is not None:
            conditions.append(Run.created_by_user_id == created_by_user_id)
        run = await self._session.scalar(select(Run).where(*conditions).with_for_update())
        if run is None:
            raise ResourceNotFound("run not found")
        return run

    async def transition(
        self,
        run: Run,
        target: RunStatus,
        event_type: str,
        payload: Mapping[str, Any],
        attempt_id: UUID | None = None,
    ) -> RunEvent:
        current = RunStatus(cast(str, run.status))
        assert_transition(current, target)
        self.apply_transition_timestamps(run, target)
        cast(Any, run).status = target.value
        return await self.append_event(
            run,
            event_type,
            {
                **payload,
                "from_status": current.value,
                "status": target.value,
            },
            attempt_id=attempt_id,
        )

    async def append_event(
        self,
        run: Run,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        attempt_id: UUID | None = None,
    ) -> RunEvent:
        last_seq = await self._session.scalar(
            select(func.coalesce(func.max(RunEvent.seq), 0)).where(RunEvent.run_id == run.id)
        )
        event = RunEvent(
            tenant_id=run.tenant_id,
            run_id=run.id,
            attempt_id=attempt_id,
            seq=int(last_seq or 0) + 1,
            event_type=event_type,
            payload=dict(payload),
        )
        self._session.add(event)
        await self._session.flush()
        return event

    @staticmethod
    def apply_transition_timestamps(run: Run, target: RunStatus) -> None:
        now = datetime.now(UTC).replace(tzinfo=None)
        if target == RunStatus.QUEUED:
            cast(Any, run).queued_at = now
        elif target == RunStatus.ASSIGNED:
            cast(Any, run).assigned_at = now
        elif target == RunStatus.RUNNING:
            cast(Any, run).started_at = now
        elif target == RunStatus.CANCEL_REQUESTED:
            cast(Any, run).cancel_requested_at = now
        elif target in TERMINAL_RUN_STATUSES:
            cast(Any, run).finished_at = now

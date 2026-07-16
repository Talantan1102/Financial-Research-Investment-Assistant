from __future__ import annotations

from typing import Any
from uuid import UUID

from app.models.run import Run, RunPause
from app.run_control.types import PauseType, RunStatus
from app.services.run_service import RunService


class FakeRunExecutor:
    """Drive lifecycle tests exclusively through RunService commands."""

    def __init__(self, service: RunService, tenant_id: UUID, actor_id: UUID) -> None:
        self._service = service
        self._tenant_id = tenant_id
        self._actor_id = actor_id

    async def start(self, run_id: UUID) -> Run:
        await self._service.transition_run(
            self._tenant_id,
            run_id,
            self._actor_id,
            RunStatus.ASSIGNED,
            event_type="run.assigned",
        )
        return await self._service.transition_run(
            self._tenant_id,
            run_id,
            self._actor_id,
            RunStatus.RUNNING,
            event_type="run.started",
        )

    async def pause_for_input(
        self,
        run_id: UUID,
        request_payload: dict[str, Any],
        continuation_payload: dict[str, Any] | None = None,
    ) -> RunPause:
        return await self._service.record_pause(
            self._tenant_id,
            run_id,
            self._actor_id,
            PauseType.INPUT,
            request_payload=request_payload,
            continuation_payload=continuation_payload or {"checkpoint": "fake-input"},
        )

    async def pause_for_approval(
        self,
        run_id: UUID,
        request_payload: dict[str, Any],
        continuation_payload: dict[str, Any] | None = None,
    ) -> RunPause:
        return await self._service.record_pause(
            self._tenant_id,
            run_id,
            self._actor_id,
            PauseType.APPROVAL,
            request_payload=request_payload,
            continuation_payload=continuation_payload or {"checkpoint": "fake-approval"},
        )

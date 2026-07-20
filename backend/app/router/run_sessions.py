"""Four fixed v1 Session read-model endpoints."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.user import User
from app.router.auth_router import get_current_user_required
from app.run_control.types import ResourceNotFound
from app.schemas.run_session import (
    RunMessageResponse,
    RunRevisionResponse,
    RunSessionDetailResponse,
    RunSessionResponse,
    RunSessionUpdateRequest,
)
from app.services.run_session_service import RunSessionService

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}/sessions", tags=["sessions-v1"])


def get_run_session_service(request: Request) -> RunSessionService:
    factory = cast(
        async_sessionmaker[AsyncSession],
        request.app.state.async_session_factory,
    )
    return RunSessionService(factory)


def _not_found(exc: ResourceNotFound) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("", response_model=list[RunSessionResponse])
async def list_sessions(
    tenant_id: UUID,
    current_user: User = Depends(get_current_user_required),
    service: RunSessionService = Depends(get_run_session_service),
) -> list[RunSessionResponse]:
    try:
        sessions = await service.list_sessions(tenant_id, cast(UUID, current_user.id))
    except ResourceNotFound as exc:
        raise _not_found(exc) from exc
    return [RunSessionResponse.model_validate(item) for item in sessions]


@router.get("/{session_id}", response_model=RunSessionDetailResponse)
async def get_session(
    tenant_id: UUID,
    session_id: UUID,
    limit: int = Query(default=1000, ge=1, le=1000),
    revision_limit: int = Query(default=20, ge=1, le=100),
    revision_cursor: str | None = Query(default=None, max_length=64),
    current_user: User = Depends(get_current_user_required),
    service: RunSessionService = Depends(get_run_session_service),
) -> RunSessionDetailResponse:
    try:
        detail = await service.get_session_detail(
            tenant_id,
            session_id,
            cast(UUID, current_user.id),
            limit=limit,
            revision_limit=revision_limit,
            revision_cursor=revision_cursor,
        )
    except ResourceNotFound as exc:
        raise _not_found(exc) from exc
    run_session = RunSessionResponse.model_validate(detail.run_session)
    return RunSessionDetailResponse(
        **run_session.model_dump(),
        messages=[RunMessageResponse.model_validate(item) for item in detail.messages],
        has_more=detail.has_more,
        active_run_id=None if detail.active_run is None else detail.active_run.id,
        active_run_status=None if detail.active_run is None else detail.active_run.status,
        active_pause_type=None if detail.active_pause is None else detail.active_pause.pause_type,
        active_pause_request=(
            None if detail.active_pause is None else detail.active_pause.request_payload
        ),
        revisions=[
            RunRevisionResponse(
                id=item.run.id,
                replaces_run_id=item.run.replaces_run_id,
                status=item.run.status,
                prompt=item.prompt,
                prompt_is_full=item.prompt_is_full,
                final_message_summary=item.final_message_summary,
                created_at=item.run.created_at,
                finished_at=item.run.finished_at,
            )
            for item in detail.revisions
        ],
        revisions_has_more=detail.revisions_has_more,
        revisions_next_cursor=detail.revisions_next_cursor,
        latest_run_id=detail.latest_run_id,
    )


@router.patch("/{session_id}", response_model=RunSessionResponse)
async def update_session(
    tenant_id: UUID,
    session_id: UUID,
    body: RunSessionUpdateRequest,
    current_user: User = Depends(get_current_user_required),
    service: RunSessionService = Depends(get_run_session_service),
) -> RunSessionResponse:
    try:
        run_session = await service.update_title(
            tenant_id,
            session_id,
            cast(UUID, current_user.id),
            body.title,
        )
    except ResourceNotFound as exc:
        raise _not_found(exc) from exc
    return RunSessionResponse.model_validate(run_session)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_session(
    tenant_id: UUID,
    session_id: UUID,
    current_user: User = Depends(get_current_user_required),
    service: RunSessionService = Depends(get_run_session_service),
) -> Response:
    try:
        await service.archive_session(tenant_id, session_id, cast(UUID, current_user.id))
    except ResourceNotFound as exc:
        raise _not_found(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)

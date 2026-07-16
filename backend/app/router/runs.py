"""Six fixed v1 Run endpoints backed only by the durable RunService."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated, NoReturn, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.run import RunEvent
from app.models.user import User
from app.router.auth_router import get_current_user_required
from app.run_control.types import (
    TERMINAL_RUN_STATUSES,
    IdempotencyConflict,
    InvalidRunTransition,
    ResourceNotFound,
    ResumeNotAllowed,
    RunControlError,
    SessionBusy,
    TenantQueueFull,
)
from app.schemas.run import (
    RunCreateRequest,
    RunResponse,
    RunResumeRequest,
    RunTraceResponse,
    TraceItem,
)
from app.services.run_service import CreateRunCommand, RunService

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}/runs", tags=["runs-v1"])

_TERMINAL_STATUS_VALUES = frozenset(item.value for item in TERMINAL_RUN_STATUSES)


def get_run_service(request: Request) -> RunService:
    factory = cast(
        async_sessionmaker[AsyncSession],
        request.app.state.async_session_factory,
    )
    return RunService(factory)


def _raise_http_error(exc: RunControlError) -> NoReturn:
    if isinstance(exc, ResourceNotFound):
        code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, TenantQueueFull):
        code = status.HTTP_429_TOO_MANY_REQUESTS
    elif isinstance(
        exc,
        (SessionBusy, IdempotencyConflict, ResumeNotAllowed, InvalidRunTransition),
    ):
        code = status.HTTP_409_CONFLICT
    else:  # pragma: no cover - protects future domain errors from becoming 500s
        code = status.HTTP_409_CONFLICT
    raise HTTPException(status_code=code, detail=str(exc)) from exc


def _validate_idempotency_key(
    value: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
) -> str:
    if not value.strip() or len(value.encode("utf-8")) > 128:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Idempotency-Key must contain 1 to 128 bytes",
        )
    return value


IdempotencyKey = Annotated[str, Depends(_validate_idempotency_key)]


@router.post("", response_model=RunResponse, status_code=status.HTTP_201_CREATED)
async def create_run(
    tenant_id: UUID,
    body: RunCreateRequest,
    response: Response,
    idempotency_key: IdempotencyKey,
    current_user: User = Depends(get_current_user_required),
    service: RunService = Depends(get_run_service),
) -> RunResponse:
    try:
        created = await service.create_run(
            CreateRunCommand(
                tenant_id=tenant_id,
                actor_id=cast(UUID, current_user.id),
                session_id=body.session_id,
                prompt=body.prompt,
                idempotency_key=idempotency_key,
                replaces_run_id=body.replaces_run_id,
            )
        )
    except RunControlError as exc:
        _raise_http_error(exc)
    response.status_code = status.HTTP_200_OK if created.replayed else status.HTTP_201_CREATED
    return RunResponse.model_validate(created.run)


@router.get("/{run_id}", response_model=RunResponse)
async def get_run(
    tenant_id: UUID,
    run_id: UUID,
    current_user: User = Depends(get_current_user_required),
    service: RunService = Depends(get_run_service),
) -> RunResponse:
    try:
        run = await service.get_run(tenant_id, run_id, cast(UUID, current_user.id))
    except RunControlError as exc:
        _raise_http_error(exc)
    return RunResponse.model_validate(run)


def _format_sse(event: RunEvent) -> str:
    data = json.dumps(event.payload, ensure_ascii=False, default=str)
    return f"id: {event.seq}\nevent: {event.event_type}\ndata: {data}\n\n"


async def _event_stream(
    request: Request,
    service: RunService,
    tenant_id: UUID,
    run_id: UUID,
    actor_id: UUID,
    initial_events: tuple[RunEvent, ...],
    initial_status: str,
    after_seq: int,
) -> AsyncIterator[str]:
    cursor = after_seq
    for event in initial_events:
        cursor = max(cursor, int(event.seq))
        yield _format_sse(event)
    if initial_status in _TERMINAL_STATUS_VALUES:
        return

    interval = float(getattr(request.app.state, "run_sse_poll_interval", 0.1))
    max_polls = int(getattr(request.app.state, "run_sse_max_polls", 300))
    for _ in range(max_polls):
        if await request.is_disconnected():
            return
        await asyncio.sleep(interval)
        events = await service.list_events(
            tenant_id,
            run_id,
            actor_id,
            after_seq=cursor,
        )
        for event in events:
            cursor = max(cursor, int(event.seq))
            yield _format_sse(event)
        run = await service.get_run(tenant_id, run_id, actor_id)
        if cast(str, run.status) in _TERMINAL_STATUS_VALUES:
            return


@router.get("/{run_id}/events")
async def get_run_events(
    tenant_id: UUID,
    run_id: UUID,
    request: Request,
    after_seq: Annotated[int | None, Query(ge=0)] = None,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    current_user: User = Depends(get_current_user_required),
    service: RunService = Depends(get_run_service),
) -> StreamingResponse:
    if after_seq is None:
        if last_event_id is None:
            after = 0
        else:
            try:
                after = int(last_event_id)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="Last-Event-ID must be a non-negative integer",
                ) from exc
            if after < 0:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="Last-Event-ID must be a non-negative integer",
                )
    else:
        after = after_seq

    actor_id = cast(UUID, current_user.id)
    try:
        initial_events = await service.list_events(
            tenant_id,
            run_id,
            actor_id,
            after_seq=after,
        )
        run = await service.get_run(tenant_id, run_id, actor_id)
    except RunControlError as exc:
        _raise_http_error(exc)
    return StreamingResponse(
        _event_stream(
            request,
            service,
            tenant_id,
            run_id,
            actor_id,
            initial_events,
            cast(str, run.status),
            after,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{run_id}/trace", response_model=RunTraceResponse)
async def get_run_trace(
    tenant_id: UUID,
    run_id: UUID,
    current_user: User = Depends(get_current_user_required),
    service: RunService = Depends(get_run_service),
) -> RunTraceResponse:
    try:
        rows = await service.get_trace(tenant_id, run_id, cast(UUID, current_user.id))
    except RunControlError as exc:
        _raise_http_error(exc)
    return RunTraceResponse(
        items=[
            TraceItem(
                span_id=row.span_id,
                request_id=row.request_id,
                parent_id=row.parent_id,
                name=row.name,
                inputs=row.inputs,
                outputs=row.outputs,
                metadata=row.attrs_json,
                started_at=row.started_at,
                ended_at=row.ended_at,
                error=row.error,
            )
            for row in rows
        ]
    )


@router.post("/{run_id}/cancel", response_model=RunResponse)
async def cancel_run(
    tenant_id: UUID,
    run_id: UUID,
    current_user: User = Depends(get_current_user_required),
    service: RunService = Depends(get_run_service),
) -> RunResponse:
    try:
        run = await service.cancel_run(tenant_id, run_id, cast(UUID, current_user.id))
    except RunControlError as exc:
        _raise_http_error(exc)
    return RunResponse.model_validate(run)


@router.post("/{run_id}/resume", response_model=RunResponse)
async def resume_run(
    tenant_id: UUID,
    run_id: UUID,
    body: RunResumeRequest,
    current_user: User = Depends(get_current_user_required),
    service: RunService = Depends(get_run_service),
) -> RunResponse:
    try:
        run = await service.resume_run(
            tenant_id,
            run_id,
            cast(UUID, current_user.id),
            response=body.response,
        )
    except RunControlError as exc:
        _raise_http_error(exc)
    return RunResponse.model_validate(run)

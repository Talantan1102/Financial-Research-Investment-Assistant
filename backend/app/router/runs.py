"""Six fixed v1 Run endpoints backed only by the durable RunService."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated, NoReturn, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.chatloop.approval_edits import SchemaEditableApprovalValidator
from app.chatloop.paper_trade_schemas import (
    CancelPaperOrderArgs,
    PlacePaperOrderArgs,
    ResetPaperAccountArgs,
)
from app.models.run import RunEvent
from app.models.user import User
from app.router.auth_router import get_current_user_required
from app.run_control.types import (
    TERMINAL_RUN_STATUSES,
    ResourceNotFound,
    RunControlError,
)
from app.schemas.run import (
    RunCreateRequest,
    RunEventCursor,
    RunResponse,
    RunResumeRequest,
    RunTraceResponse,
    TraceItem,
    parse_action_required_outcome,
)
from app.services.run_service import CreateRunCommand, RunService
from app.services.run_stream_bus import RunStreamBus, RunStreamEntry

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}/runs", tags=["runs-v1"])

_TERMINAL_STATUS_VALUES = frozenset(item.value for item in TERMINAL_RUN_STATUSES)
_RUN_STREAM_BLOCK_MS = 1_000
logger = logging.getLogger(__name__)


def get_run_service(request: Request) -> RunService:
    factory = cast(
        async_sessionmaker[AsyncSession],
        request.app.state.async_session_factory,
    )
    return RunService(
        factory,
        editable_approval_validator=SchemaEditableApprovalValidator(
            {
                "place_paper_order": PlacePaperOrderArgs,
                "cancel_paper_order": CancelPaperOrderArgs,
                "reset_paper_account": ResetPaperAccountArgs,
            }
        ),
    )


def get_run_stream_bus(request: Request) -> RunStreamBus | None:
    redis = getattr(request.app.state, "redis_async", None)
    return None if redis is None else RunStreamBus(redis)


def _raise_http_error(exc: RunControlError) -> NoReturn:
    code = (
        status.HTTP_404_NOT_FOUND if isinstance(exc, ResourceNotFound) else status.HTTP_409_CONFLICT
    )
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
    return _run_response(created.run)


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
    return _run_response(run)


def _run_response(run: object) -> RunResponse:
    response = RunResponse.model_validate(run)
    return response.model_copy(
        update={
            "outcome": parse_action_required_outcome(
                getattr(run, "outcome_payload", None),
                outcome_code=getattr(run, "outcome_code", None),
            )
        }
    )


def _format_sse(
    event: RunEvent,
    event_id: str | int,
    *,
    final_content: str | None = None,
) -> str:
    payload = dict(event.payload)
    if event.event_type == "run.completed" and final_content is not None:
        payload["content"] = final_content
    _sanitize_completed_outcome(payload, event.event_type)
    data = json.dumps(payload, ensure_ascii=False, default=str)
    return f"id: {event_id}\nevent: {event.event_type}\ndata: {data}\n\n"


def _format_stream_sse(entry: RunStreamEntry, event_id: str) -> str:
    payload = dict(entry.envelope.payload)
    _sanitize_completed_outcome(payload, entry.envelope.kind)
    data = json.dumps(payload, ensure_ascii=False, default=str)
    return f"id: {event_id}\nevent: {entry.envelope.kind}\ndata: {data}\n\n"


def _sanitize_completed_outcome(payload: dict[str, object], event_type: str) -> None:
    if event_type != "run.completed" or "outcome" not in payload:
        return
    outcome = parse_action_required_outcome(payload["outcome"])
    if outcome is None:
        payload.pop("outcome")
    else:
        payload["outcome"] = outcome.model_dump(mode="json")


async def _read_durable_snapshot(
    service: RunService,
    tenant_id: UUID,
    run_id: UUID,
    actor_id: UUID,
    *,
    after_seq: int,
) -> tuple[tuple[RunEvent, ...], str]:
    events = list(
        await service.list_events(
            tenant_id,
            run_id,
            actor_id,
            after_seq=after_seq,
        )
    )
    cursor = max((int(event.seq) for event in events), default=after_seq)
    run = await service.get_run(tenant_id, run_id, actor_id)
    run_status = cast(str, run.status)
    if run_status in _TERMINAL_STATUS_VALUES:
        # Status and its durable event commit atomically, but the two reads above
        # use separate transactions. Drain once after observing terminal state so
        # an event committed between those reads cannot be skipped.
        tail = await service.list_events(
            tenant_id,
            run_id,
            actor_id,
            after_seq=cursor,
        )
        events.extend(tail)
    return tuple(events), run_status


async def _terminal_final_content(
    service: RunService,
    tenant_id: UUID,
    run_id: UUID,
    actor_id: UUID,
    *,
    run_status: str,
) -> str | None:
    if run_status not in _TERMINAL_STATUS_VALUES:
        return None
    final_message = await service.get_final_message(tenant_id, run_id, actor_id)
    return None if final_message is None else cast(str, final_message.content)


async def _event_stream(
    initial_events: tuple[RunEvent, ...],
    *,
    initial_status: str,
    service: RunService,
    tenant_id: UUID,
    run_id: UUID,
    actor_id: UUID,
    cursor: RunEventCursor,
    bus: RunStreamBus | None,
) -> AsyncIterator[str]:
    durable_seq = cursor.durable_seq
    redis_id = cursor.redis_id
    final_content = await _terminal_final_content(
        service,
        tenant_id,
        run_id,
        actor_id,
        run_status=initial_status,
    )
    for event in initial_events:
        durable_seq = max(durable_seq, int(event.seq))
        event_id: str | int = (
            RunEventCursor(durable_seq, redis_id).encode() if bus is not None else durable_seq
        )
        yield _format_sse(event, event_id, final_content=final_content)

    if bus is None or initial_status in _TERMINAL_STATUS_VALUES:
        return

    while True:
        redis_read_failed = False
        read_batch = None
        try:
            read_batch = await bus.read(
                run_id,
                after_id=redis_id,
                block_ms=_RUN_STREAM_BLOCK_MS,
            )
            entries = read_batch.entries
        except Exception as exc:  # noqa: BLE001 - Redis loss must not hide durable facts
            logger.warning("Run stream read degraded for %s: %s", run_id, exc)
            entries = []
            redis_read_failed = True

        if entries:
            durable_events, run_status = await _read_durable_snapshot(
                service,
                tenant_id,
                run_id,
                actor_id,
                after_seq=durable_seq,
            )
            final_content = await _terminal_final_content(
                service,
                tenant_id,
                run_id,
                actor_id,
                run_status=run_status,
            )
            for event in durable_events:
                durable_seq = max(durable_seq, int(event.seq))
                yield _format_sse(
                    event,
                    RunEventCursor(durable_seq, redis_id).encode(),
                    final_content=final_content,
                )
            if run_status in _TERMINAL_STATUS_VALUES:
                return

        deferred_for_durable_watermark = False
        for entry in entries:
            if entry.envelope.durable_seq > durable_seq:
                durable_events, run_status = await _read_durable_snapshot(
                    service,
                    tenant_id,
                    run_id,
                    actor_id,
                    after_seq=durable_seq,
                )
                final_content = await _terminal_final_content(
                    service,
                    tenant_id,
                    run_id,
                    actor_id,
                    run_status=run_status,
                )
                for event in durable_events:
                    durable_seq = max(durable_seq, int(event.seq))
                    yield _format_sse(
                        event,
                        RunEventCursor(durable_seq, redis_id).encode(),
                        final_content=final_content,
                    )
                if run_status in _TERMINAL_STATUS_VALUES:
                    return
                if durable_seq < entry.envelope.durable_seq:
                    deferred_for_durable_watermark = True
                    break
            redis_id = entry.entry_id
            yield _format_stream_sse(
                entry,
                RunEventCursor(durable_seq, redis_id).encode(),
            )

        if read_batch is not None and not deferred_for_durable_watermark:
            redis_id = read_batch.last_seen_id

        durable_events, run_status = await _read_durable_snapshot(
            service,
            tenant_id,
            run_id,
            actor_id,
            after_seq=durable_seq,
        )
        final_content = await _terminal_final_content(
            service,
            tenant_id,
            run_id,
            actor_id,
            run_status=run_status,
        )
        for event in durable_events:
            durable_seq = max(durable_seq, int(event.seq))
            yield _format_sse(
                event,
                RunEventCursor(durable_seq, redis_id).encode(),
                final_content=final_content,
            )
        if run_status in _TERMINAL_STATUS_VALUES:
            return
        if deferred_for_durable_watermark or redis_read_failed:
            await asyncio.sleep(_RUN_STREAM_BLOCK_MS / 1_000)


@router.get("/{run_id}/events")
async def get_run_events(
    tenant_id: UUID,
    run_id: UUID,
    after_seq: Annotated[int | None, Query(ge=0)] = None,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    current_user: User = Depends(get_current_user_required),
    service: RunService = Depends(get_run_service),
    stream_bus: RunStreamBus | None = Depends(get_run_stream_bus),
) -> StreamingResponse:
    if after_seq is None:
        try:
            cursor = RunEventCursor.parse(last_event_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Last-Event-ID must be a valid Run event cursor",
            ) from exc
    else:
        cursor = RunEventCursor(durable_seq=after_seq)

    actor_id = cast(UUID, current_user.id)
    try:
        initial_events, run_status = await _read_durable_snapshot(
            service,
            tenant_id,
            run_id,
            actor_id,
            after_seq=cursor.durable_seq,
        )
    except RunControlError as exc:
        _raise_http_error(exc)
    return StreamingResponse(
        _event_stream(
            initial_events,
            initial_status=run_status,
            service=service,
            tenant_id=tenant_id,
            run_id=run_id,
            actor_id=actor_id,
            cursor=cursor,
            bus=stream_bus,
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
    return _run_response(run)


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
            pause_id=body.pause_id,
            response=body.response,
        )
    except RunControlError as exc:
        _raise_http_error(exc)
    return _run_response(run)

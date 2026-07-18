"""Lease-fenced Attempt commands backed by PostgreSQL row locks."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.chatloop.run_executor import CompletedResult, FailedResult, PauseResult, RunUsage
from app.models.run import Run, RunAttempt, RunMessage, RunPause
from app.models.run_execution import RunToolExecution, RunUsageRecord
from app.models.run_scheduling import RunOutbox
from app.run_control.mutations import RunMutationStore
from app.run_control.types import (
    AttemptStatus,
    OutboxType,
    PauseType,
    RunControlError,
    RunStatus,
)
from app.services.trace_models import TraceSpanRow

MAX_RESULT_BYTES = 64 * 1024
MAX_ERROR_CODE_LENGTH = 64
MAX_ERROR_MESSAGE_LENGTH = 2000


class AttemptCommandRejected(RunControlError):  # noqa: N818 - public domain error
    """Raised when a fenced Attempt command is no longer authoritative."""


@dataclass(frozen=True)
class ClaimedAssignment:
    tenant_id: UUID
    run_id: UUID
    attempt_id: UUID
    worker_id: UUID
    claim_token: UUID
    lease_expires_at: datetime


@dataclass(frozen=True)
class ClaimResult:
    claimed: bool
    assignment: ClaimedAssignment | None


@dataclass(frozen=True)
class LoadedChatExecution:
    session_id: UUID
    user_id: UUID
    prompt: str
    original_prompt: str
    history: tuple[dict[str, Any], ...]
    continuation: dict[str, Any] | None
    approved_semantic_keys: frozenset[str] = frozenset()
    approved_tool_executions: tuple[tuple[str, UUID], ...] = ()
    rejected_tool_execution_id: UUID | None = None


@dataclass(frozen=True)
class ToolExecutionReservation:
    idempotency_key: str
    execute: bool
    status: str
    result: dict[str, Any] | None
    reservation_token: UUID | None = None
    execution_epoch: int = 0
    ambiguous: bool = False


def _database_utc_now() -> Any:
    return func.timezone("UTC", func.statement_timestamp())


class AttemptService:
    """Own complete transactions for Worker claim, lease, and terminal commands."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        lease_duration: timedelta = timedelta(seconds=45),
        tool_reservation_duration: timedelta = timedelta(seconds=30),
        history_limit: int = 100,
    ) -> None:
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        if tool_reservation_duration <= timedelta(0):
            raise ValueError("tool_reservation_duration must be positive")
        if history_limit <= 0:
            raise ValueError("history_limit must be positive")
        self._session_factory = session_factory
        self._lease_duration = lease_duration
        self._tool_reservation_duration = tool_reservation_duration
        self._history_limit = history_limit

    async def claim(self, attempt_id: UUID, worker_id: UUID) -> ClaimResult:
        async with self._session_factory() as session, session.begin():
            attempt = await self._lock_attempt(session, attempt_id)
            if attempt is None:
                return ClaimResult(claimed=False, assignment=None)
            run = await self._lock_run(session, cast(UUID, attempt.run_id))
            if run is None:
                return ClaimResult(claimed=False, assignment=None)
            clock = (
                await session.execute(
                    select(
                        _database_utc_now().label("claimed_at"),
                        (_database_utc_now() + self._lease_duration).label("lease_expires_at"),
                    )
                )
            ).one()
            claimed_at = cast(datetime, clock.claimed_at)
            lease_expires_at = cast(datetime, clock.lease_expires_at)
            if not self._claimable(attempt, run, worker_id, claimed_at):
                return ClaimResult(claimed=False, assignment=None)

            claim_token = uuid4()
            cast(Any, attempt).status = AttemptStatus.RUNNING.value
            cast(Any, attempt).claim_token = claim_token
            cast(Any, attempt).claimed_at = claimed_at
            cast(Any, attempt).last_heartbeat_at = claimed_at
            cast(Any, attempt).lease_expires_at = lease_expires_at
            cast(Any, attempt).started_at = claimed_at
            await RunMutationStore(session).transition(
                run,
                RunStatus.RUNNING,
                "run.running",
                {"worker_id": str(worker_id)},
                attempt_id=cast(UUID, attempt.id),
            )
            cast(Any, run).started_at = claimed_at
            await self._acknowledge_outbox(
                session,
                attempt_id=cast(UUID, attempt.id),
                event_type=OutboxType.ATTEMPT_ASSIGNED,
                acknowledged_at=claimed_at,
            )
            return ClaimResult(
                claimed=True,
                assignment=ClaimedAssignment(
                    tenant_id=cast(UUID, run.tenant_id),
                    run_id=cast(UUID, run.id),
                    attempt_id=cast(UUID, attempt.id),
                    worker_id=worker_id,
                    claim_token=claim_token,
                    lease_expires_at=lease_expires_at,
                ),
            )

    async def renew(
        self,
        attempt_id: UUID,
        worker_id: UUID,
        token: UUID,
    ) -> datetime:
        async with self._session_factory() as session, session.begin():
            attempt, run = await self._lock_command_context(session, attempt_id)
            clock = (
                await session.execute(
                    select(
                        _database_utc_now().label("heartbeat_at"),
                        (_database_utc_now() + self._lease_duration).label("lease_expires_at"),
                    )
                )
            ).one()
            heartbeat_at = cast(datetime, clock.heartbeat_at)
            lease_expires_at = cast(datetime, clock.lease_expires_at)
            self._require_authoritative(
                attempt,
                run,
                worker_id,
                token,
                heartbeat_at,
                required_run_status=RunStatus.RUNNING,
            )
            cast(Any, attempt).last_heartbeat_at = heartbeat_at
            cast(Any, attempt).lease_expires_at = lease_expires_at
            return lease_expires_at

    async def complete_simulated(
        self,
        attempt_id: UUID,
        worker_id: UUID,
        token: UUID,
        result: Mapping[str, Any],
    ) -> None:
        safe_result = self._bounded_result(result)
        async with self._session_factory() as session, session.begin():
            attempt, run = await self._lock_command_context(session, attempt_id)
            now = cast(datetime, await session.scalar(select(_database_utc_now())))
            self._require_authoritative(
                attempt,
                run,
                worker_id,
                token,
                now,
                required_run_status=RunStatus.RUNNING,
            )
            await self._after_authority_check()
            self._finish_attempt(attempt, AttemptStatus.COMPLETED, now)
            await RunMutationStore(session).transition(
                run,
                RunStatus.COMPLETED,
                "run.completed",
                {"result": safe_result},
                attempt_id=cast(UUID, attempt.id),
            )
            cast(Any, run).finished_at = now

    async def load_chat_execution(self, assignment: ClaimedAssignment) -> LoadedChatExecution:
        """Load authoritative Run input and persisted continuation after claim."""
        async with self._session_factory() as session, session.begin():
            attempt, run = await self._lock_command_context(session, assignment.attempt_id)
            now = cast(datetime, await session.scalar(select(_database_utc_now())))
            self._require_assignment_authoritative(attempt, run, assignment, now)
            input_message = await session.scalar(
                select(RunMessage).where(
                    RunMessage.id == run.input_message_id,
                    RunMessage.tenant_id == run.tenant_id,
                    RunMessage.session_id == run.session_id,
                )
            )
            if input_message is None:
                raise AttemptCommandRejected("run input is unavailable")
            history_rows = tuple(
                (
                    await session.scalars(
                        select(RunMessage)
                        .where(
                            RunMessage.tenant_id == run.tenant_id,
                            RunMessage.session_id == run.session_id,
                            RunMessage.id != run.input_message_id,
                        )
                        .order_by(RunMessage.created_at.desc(), RunMessage.id.desc())
                        .limit(self._history_limit)
                    )
                ).all()
            )
            history = tuple(
                {"role": cast(str, message.role), "content": cast(str, message.content)}
                for message in reversed(history_rows)
            )
            continuation: dict[str, Any] | None = None
            approved_tool_executions: tuple[tuple[str, UUID], ...] = ()
            rejected_tool_execution_id: UUID | None = None
            prompt = cast(str, input_message.content)
            if cast(str | None, run.queue_reason) == "resume":
                pause = await session.scalar(
                    select(RunPause)
                    .where(RunPause.run_id == run.id)
                    .order_by(RunPause.pause_no.desc())
                    .limit(1)
                )
                if pause is None or pause.resolved_at is None or pause.response_payload is None:
                    raise AttemptCommandRejected("resolved run pause is unavailable")
                continuation = self._bounded_json_object(
                    cast(Mapping[str, Any], pause.continuation_payload),
                    limit=MAX_RESULT_BYTES,
                    label="continuation",
                )
                response = self._bounded_json_object(
                    cast(Mapping[str, Any], pause.response_payload),
                    limit=MAX_RESULT_BYTES,
                    label="pause response",
                )
                request = self._bounded_json_object(
                    cast(Mapping[str, Any], pause.request_payload),
                    limit=MAX_RESULT_BYTES,
                    label="pause request",
                )
                execution_id_raw = request.get("execution_id")
                tool_call = request.get("tool_call")
                if execution_id_raw is not None:
                    try:
                        execution_id = UUID(str(execution_id_raw))
                    except ValueError as exc:
                        raise AttemptCommandRejected(
                            "resolved run pause execution provenance is invalid"
                        ) from exc
                    if not isinstance(tool_call, Mapping) or not isinstance(
                        tool_call.get("id"), str
                    ):
                        raise AttemptCommandRejected(
                            "resolved run pause tool provenance is invalid"
                        )
                    if response.get("approved") is True:
                        approved_tool_executions = ((cast(str, tool_call["id"]), execution_id),)
                    elif response.get("approved") is False:
                        rejected_tool_execution_id = execution_id
                prompt = json.dumps(
                    response,
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            return LoadedChatExecution(
                session_id=cast(UUID, run.session_id),
                user_id=cast(UUID, run.created_by_user_id),
                prompt=prompt,
                original_prompt=cast(str, input_message.content),
                history=history,
                continuation=continuation,
                approved_tool_executions=approved_tool_executions,
                rejected_tool_execution_id=rejected_tool_execution_id,
            )

    async def complete_chat(
        self,
        assignment: ClaimedAssignment,
        result: CompletedResult,
    ) -> None:
        self._validate_result_identity(assignment, result)
        if not result.final_text:
            raise ValueError("completed chat result must contain final text")
        async with self._session_factory() as session, session.begin():
            attempt, run = await self._lock_command_context(session, assignment.attempt_id)
            now = cast(datetime, await session.scalar(select(_database_utc_now())))
            self._require_assignment_authoritative(attempt, run, assignment, now)
            message = RunMessage(
                tenant_id=run.tenant_id,
                session_id=run.session_id,
                role="assistant",
                content=result.final_text,
                status="complete",
            )
            session.add(message)
            await session.flush()
            cast(Any, run).final_message_id = message.id
            await self._persist_usage_and_trace(
                session,
                assignment,
                result.usage,
                now,
                status="completed",
                outputs={"final_message_id": str(message.id)},
            )
            self._finish_attempt(attempt, AttemptStatus.COMPLETED, now)
            await RunMutationStore(session).transition(
                run,
                RunStatus.COMPLETED,
                "run.completed",
                {"final_message_id": str(message.id)},
                attempt_id=assignment.attempt_id,
            )
            cast(Any, run).finished_at = now
            await self._before_chat_terminal_commit()

    async def pause_chat(
        self,
        assignment: ClaimedAssignment,
        result: PauseResult,
    ) -> None:
        self._validate_result_identity(assignment, result)
        request = self._bounded_json_object(result.request, limit=16 * 1024, label="pause request")
        continuation = self._bounded_json_object(
            result.continuation, limit=MAX_RESULT_BYTES, label="continuation"
        )
        async with self._session_factory() as session, session.begin():
            attempt, run = await self._lock_command_context(session, assignment.attempt_id)
            now = cast(datetime, await session.scalar(select(_database_utc_now())))
            self._require_assignment_authoritative(attempt, run, assignment, now)
            last_pause_no = await session.scalar(
                select(func.coalesce(func.max(RunPause.pause_no), 0)).where(
                    RunPause.run_id == run.id
                )
            )
            pause = RunPause(
                run_id=run.id,
                pause_no=int(last_pause_no or 0) + 1,
                pause_type=result.pause_type,
                request_payload=request,
                continuation_payload=continuation,
            )
            session.add(pause)
            await session.flush()
            await self._persist_usage_and_trace(
                session,
                assignment,
                result.usage,
                now,
                status="paused",
                outputs={"pause_id": str(pause.id), "pause_type": result.pause_type},
            )
            self._finish_attempt(attempt, AttemptStatus.PAUSED, now)
            target = {
                PauseType.INPUT.value: RunStatus.WAITING_INPUT,
                PauseType.APPROVAL.value: RunStatus.WAITING_APPROVAL,
            }[result.pause_type]
            await RunMutationStore(session).transition(
                run,
                target,
                "run.paused",
                {
                    "pause_id": str(pause.id),
                    "pause_no": pause.pause_no,
                    "pause_type": pause.pause_type,
                },
                attempt_id=assignment.attempt_id,
            )
            await self._before_chat_terminal_commit()

    async def fail_chat(
        self,
        assignment: ClaimedAssignment,
        result: FailedResult,
    ) -> None:
        self._validate_result_identity(assignment, result)
        error_code = result.error_code[:MAX_ERROR_CODE_LENGTH]
        error_message = result.message[:MAX_ERROR_MESSAGE_LENGTH]
        async with self._session_factory() as session, session.begin():
            attempt, run = await self._lock_command_context(session, assignment.attempt_id)
            now = cast(datetime, await session.scalar(select(_database_utc_now())))
            self._require_assignment_authoritative(attempt, run, assignment, now)
            await self._persist_usage_and_trace(
                session,
                assignment,
                result.usage,
                now,
                status="failed",
                outputs={"error_code": error_code},
                error=error_message,
            )
            self._finish_attempt(attempt, AttemptStatus.FAILED, now)
            cast(Any, attempt).error_code = error_code
            cast(Any, attempt).error_message = error_message
            cast(Any, run).error_code = error_code
            cast(Any, run).error_message = error_message
            await RunMutationStore(session).transition(
                run,
                RunStatus.FAILED,
                "run.failed",
                {"error_code": error_code, "error_message": error_message},
                attempt_id=assignment.attempt_id,
            )
            cast(Any, run).finished_at = now
            await self._before_chat_terminal_commit()

    async def cancel_chat(
        self,
        assignment: ClaimedAssignment,
        result: FailedResult,
    ) -> None:
        self._validate_result_identity(assignment, result)
        if result.error_code != "cancelled":
            raise ValueError("cancel chat requires a cancelled executor result")
        async with self._session_factory() as session, session.begin():
            attempt, run = await self._lock_command_context(session, assignment.attempt_id)
            now = cast(datetime, await session.scalar(select(_database_utc_now())))
            if (
                cast(UUID, run.id) != assignment.run_id
                or cast(UUID, run.tenant_id) != assignment.tenant_id
            ):
                raise AttemptCommandRejected("attempt command is no longer authoritative")
            self._require_authoritative(
                attempt,
                run,
                assignment.worker_id,
                assignment.claim_token,
                now,
                required_run_status=RunStatus.CANCEL_REQUESTED,
            )
            await self._persist_usage_and_trace(
                session,
                assignment,
                result.usage,
                now,
                status="cancelled",
                outputs={"partial_text_present": bool(result.partial_text)},
            )
            self._finish_attempt(attempt, AttemptStatus.CANCELLED, now)
            await RunMutationStore(session).transition(
                run,
                RunStatus.CANCELLED,
                "run.cancelled",
                {},
                attempt_id=assignment.attempt_id,
            )
            cast(Any, run).finished_at = now
            await self._acknowledge_outbox(
                session,
                attempt_id=assignment.attempt_id,
                event_type=OutboxType.ATTEMPT_CANCEL,
                acknowledged_at=now,
            )
            await self._before_chat_terminal_commit()

    async def reserve_tool_execution(
        self,
        assignment: ClaimedAssignment,
        *,
        tool_call_id: str,
        tool_name: str,
        request: Mapping[str, Any],
        safe_to_retry: bool,
        approved: bool,
        approved_execution_id: UUID | None = None,
    ) -> ToolExecutionReservation:
        if not tool_call_id or len(tool_call_id) > 255:
            raise ValueError("tool_call_id must be 1..255 characters")
        if not tool_name or len(tool_name) > 255:
            raise ValueError("tool_name must be 1..255 characters")
        safe_request = self._bounded_json_object(request, limit=16 * 1024, label="tool request")
        key = self.tool_idempotency_key(assignment.run_id, tool_call_id, tool_name, safe_request)
        semantic_key = self.tool_semantic_key(tool_name, safe_request)
        summary = {"args": safe_request}
        async with self._session_factory() as session, session.begin():
            attempt, run = await self._lock_command_context(session, assignment.attempt_id)
            now = cast(datetime, await session.scalar(select(_database_utc_now())))
            self._require_assignment_authoritative(attempt, run, assignment, now)
            existing = await session.scalar(
                select(RunToolExecution)
                .where(
                    RunToolExecution.run_id == assignment.run_id,
                    RunToolExecution.tool_call_id == tool_call_id,
                )
                .with_for_update()
            )
            if existing is not None:
                if (
                    existing.idempotency_key != key
                    or existing.tool_name != tool_name
                    or existing.request_summary != summary
                ):
                    raise ValueError("tool_call_id was reused with different tool input")
                status = cast(str, existing.status)
                if status == "completed":
                    result = self._bounded_json_object(
                        cast(Mapping[str, Any], existing.result_summary),
                        limit=MAX_RESULT_BYTES,
                        label="tool result",
                    )
                    return ToolExecutionReservation(key, False, status, result)
                if status == "started" and cast(datetime, existing.reservation_expires_at) > now:
                    return ToolExecutionReservation(key, False, status, None)
                if status == "started" and not cast(bool, existing.safe_to_retry):
                    cast(Any, existing).status = "approval_required"
                    cast(Any, existing).reservation_token = None
                    cast(Any, existing).reservation_expires_at = None
                    return ToolExecutionReservation(
                        key, False, "approval_required", None, ambiguous=True
                    )
                if (
                    status in {"approval_required", "failed"}
                    and not cast(bool, existing.safe_to_retry)
                    and not approved
                ):
                    if status == "failed":
                        return ToolExecutionReservation(key, False, "failed", None)
                    return ToolExecutionReservation(key, False, status, None)
                if approved and (
                    approved_execution_id is None
                    or cast(UUID, existing.id) != approved_execution_id
                    or status != "approval_required"
                ):
                    raise AttemptCommandRejected("tool approval provenance does not match")
                token = uuid4()
                cast(Any, existing).status = "started"
                cast(Any, existing).attempt_id = assignment.attempt_id
                cast(Any, existing).safe_to_retry = safe_to_retry
                cast(Any, existing).reservation_token = token
                cast(Any, existing).reservation_expires_at = now + self._tool_reservation_duration
                cast(Any, existing).execution_epoch = cast(int, existing.execution_epoch) + 1
                cast(Any, existing).finished_at = None
                cast(Any, existing).result_summary = None
                cast(Any, existing).error_code = None
                cast(Any, existing).error_message = None
                return ToolExecutionReservation(
                    key,
                    True,
                    "started",
                    None,
                    token,
                    cast(int, existing.execution_epoch),
                )

            if approved_execution_id is not None:
                raise AttemptCommandRejected("tool approval provenance does not match")

            ambiguous = (
                await session.scalar(
                    select(RunToolExecution.id).where(
                        RunToolExecution.run_id == assignment.run_id,
                        RunToolExecution.semantic_key == semantic_key,
                        RunToolExecution.tool_call_id != tool_call_id,
                        RunToolExecution.safe_to_retry.is_(False),
                        RunToolExecution.status.in_(("started", "approval_required")),
                    )
                )
                is not None
            )
            status = (
                "started"
                if (safe_to_retry or approved) and (not ambiguous or approved)
                else "approval_required"
            )
            fresh_token: UUID | None = uuid4() if status == "started" else None
            session.add(
                RunToolExecution(
                    run_id=assignment.run_id,
                    attempt_id=assignment.attempt_id,
                    tool_call_id=tool_call_id,
                    idempotency_key=key,
                    semantic_key=semantic_key,
                    tool_name=tool_name,
                    request_summary=summary,
                    safe_to_retry=safe_to_retry,
                    status=status,
                    reservation_token=fresh_token,
                    reservation_expires_at=(
                        now + self._tool_reservation_duration if fresh_token is not None else None
                    ),
                    execution_epoch=1 if fresh_token is not None else 0,
                    started_at=now,
                )
            )
            return ToolExecutionReservation(
                key,
                status == "started",
                status,
                None,
                fresh_token,
                1 if fresh_token is not None else 0,
                ambiguous,
            )

    async def reject_tool_execution(
        self, assignment: ClaimedAssignment, execution_id: UUID
    ) -> None:
        """Atomically converge one server-bound approval row to manual rejection."""
        async with self._session_factory() as session, session.begin():
            attempt, run = await self._lock_command_context(session, assignment.attempt_id)
            now = cast(datetime, await session.scalar(select(_database_utc_now())))
            self._require_assignment_authoritative(attempt, run, assignment, now)
            row = await session.scalar(
                select(RunToolExecution)
                .where(
                    RunToolExecution.id == execution_id,
                    RunToolExecution.run_id == assignment.run_id,
                )
                .with_for_update()
            )
            if row is None or cast(str, row.status) != "approval_required":
                raise AttemptCommandRejected("tool rejection provenance does not match")
            cast(Any, row).status = "failed"
            cast(Any, row).reservation_token = None
            cast(Any, row).reservation_expires_at = None
            cast(Any, row).finished_at = now
            cast(Any, row).error_code = "manual_rejected"
            cast(Any, row).error_message = "Tool execution was rejected by the user."

    async def find_unsafe_recovery(self, assignment: ClaimedAssignment) -> dict[str, Any] | None:
        """Return the oldest unresolved unsafe execution before any model rerun."""
        async with self._session_factory() as session, session.begin():
            attempt, run = await self._lock_command_context(session, assignment.attempt_id)
            now = cast(datetime, await session.scalar(select(_database_utc_now())))
            self._require_assignment_authoritative(attempt, run, assignment, now)
            row = await session.scalar(
                select(RunToolExecution)
                .where(
                    RunToolExecution.run_id == assignment.run_id,
                    RunToolExecution.safe_to_retry.is_(False),
                    RunToolExecution.status.in_(("started", "approval_required")),
                    RunToolExecution.attempt_id != assignment.attempt_id,
                )
                .order_by(RunToolExecution.started_at.asc(), RunToolExecution.id.asc())
                .limit(1)
            )
            if row is None:
                return None
            if cast(str, row.status) == "started":
                cast(Any, row).status = "approval_required"
                cast(Any, row).reservation_token = None
                cast(Any, row).reservation_expires_at = None
            summary = self._bounded_json_object(
                cast(Mapping[str, Any], row.request_summary),
                limit=16 * 1024,
                label="tool request",
            )
            request = summary.get("args")
            if not isinstance(request, dict):
                raise AttemptCommandRejected("unsafe tool recovery request is invalid")
            return {
                "execution_id": str(row.id),
                "tool_call_id": cast(str, row.tool_call_id),
                "tool_name": cast(str, row.tool_name),
                "request": request,
                "semantic_key": cast(str, row.semantic_key),
            }

    async def complete_tool_execution(
        self,
        assignment: ClaimedAssignment,
        idempotency_key: str,
        result: Mapping[str, Any],
        *,
        reservation_token: UUID | None = None,
        execution_epoch: int = 0,
    ) -> None:
        safe_result = self._bounded_json_object(result, limit=MAX_RESULT_BYTES, label="tool result")
        async with self._session_factory() as session, session.begin():
            attempt, run = await self._lock_command_context(session, assignment.attempt_id)
            now = cast(datetime, await session.scalar(select(_database_utc_now())))
            self._require_assignment_authoritative(attempt, run, assignment, now)
            row = await session.scalar(
                select(RunToolExecution)
                .where(
                    RunToolExecution.run_id == assignment.run_id,
                    RunToolExecution.idempotency_key == idempotency_key,
                )
                .with_for_update()
            )
            if (
                row is None
                or cast(str, row.status) != "started"
                or cast(UUID | None, row.reservation_token) != reservation_token
                or cast(int, row.execution_epoch) != execution_epoch
                or cast(UUID, row.attempt_id) != assignment.attempt_id
                or row.reservation_expires_at is None
                or cast(datetime, row.reservation_expires_at) <= now
            ):
                raise AttemptCommandRejected("tool reservation owner is no longer writable")
            cast(Any, row).status = "completed"
            cast(Any, row).result_summary = safe_result
            cast(Any, row).finished_at = now

    async def fail_tool_execution(
        self,
        assignment: ClaimedAssignment,
        idempotency_key: str,
        *,
        error_code: str,
        error_message: str,
        reservation_token: UUID | None,
        execution_epoch: int,
    ) -> None:
        async with self._session_factory() as session, session.begin():
            attempt, run = await self._lock_command_context(session, assignment.attempt_id)
            now = cast(datetime, await session.scalar(select(_database_utc_now())))
            self._require_assignment_authoritative(attempt, run, assignment, now)
            row = await session.scalar(
                select(RunToolExecution)
                .where(
                    RunToolExecution.run_id == assignment.run_id,
                    RunToolExecution.idempotency_key == idempotency_key,
                )
                .with_for_update()
            )
            if (
                row is None
                or cast(str, row.status) != "started"
                or cast(UUID | None, row.reservation_token) != reservation_token
                or cast(int, row.execution_epoch) != execution_epoch
                or cast(UUID, row.attempt_id) != assignment.attempt_id
                or row.reservation_expires_at is None
                or cast(datetime, row.reservation_expires_at) <= now
            ):
                raise AttemptCommandRejected("tool reservation owner is no longer writable")
            cast(Any, row).status = "failed"
            cast(Any, row).error_code = error_code[:MAX_ERROR_CODE_LENGTH] or "tool_error"
            cast(Any, row).error_message = error_message[:MAX_ERROR_MESSAGE_LENGTH]
            cast(Any, row).finished_at = now

    async def fail(
        self,
        attempt_id: UUID,
        worker_id: UUID,
        token: UUID,
        error_code: str,
        error_message: str,
    ) -> None:
        if not error_code or len(error_code) > MAX_ERROR_CODE_LENGTH:
            raise ValueError(f"error_code must be 1..{MAX_ERROR_CODE_LENGTH} characters")
        safe_message = error_message[:MAX_ERROR_MESSAGE_LENGTH]
        async with self._session_factory() as session, session.begin():
            attempt, run = await self._lock_command_context(session, attempt_id)
            now = cast(datetime, await session.scalar(select(_database_utc_now())))
            self._require_authoritative(
                attempt,
                run,
                worker_id,
                token,
                now,
                required_run_status=RunStatus.RUNNING,
            )
            self._finish_attempt(attempt, AttemptStatus.FAILED, now)
            cast(Any, attempt).error_code = error_code
            cast(Any, attempt).error_message = safe_message
            cast(Any, run).error_code = error_code
            cast(Any, run).error_message = safe_message
            await RunMutationStore(session).transition(
                run,
                RunStatus.FAILED,
                "run.failed",
                {"error_code": error_code, "error_message": safe_message},
                attempt_id=cast(UUID, attempt.id),
            )
            cast(Any, run).finished_at = now

    async def acknowledge_cancel(
        self,
        attempt_id: UUID,
        worker_id: UUID,
        token: UUID,
    ) -> None:
        async with self._session_factory() as session, session.begin():
            attempt, run = await self._lock_command_context(session, attempt_id)
            now = cast(datetime, await session.scalar(select(_database_utc_now())))
            self._require_authoritative(
                attempt,
                run,
                worker_id,
                token,
                now,
                required_run_status=RunStatus.CANCEL_REQUESTED,
            )
            self._finish_attempt(attempt, AttemptStatus.CANCELLED, now)
            await RunMutationStore(session).transition(
                run,
                RunStatus.CANCELLED,
                "run.cancelled",
                {},
                attempt_id=cast(UUID, attempt.id),
            )
            cast(Any, run).finished_at = now
            await self._acknowledge_outbox(
                session,
                attempt_id=cast(UUID, attempt.id),
                event_type=OutboxType.ATTEMPT_CANCEL,
                acknowledged_at=now,
            )

    async def _before_attempt_lock(self) -> None:
        """Deterministic concurrency seam; production performs no work here."""

    async def _lock_attempt(self, session: AsyncSession, attempt_id: UUID) -> RunAttempt | None:
        await self._before_attempt_lock()
        attempt = await session.scalar(
            select(RunAttempt).where(RunAttempt.id == attempt_id).with_for_update()
        )
        if attempt is not None:
            await self._after_attempt_lock(attempt)
        return attempt

    async def _after_attempt_lock(self, attempt: RunAttempt) -> None:
        """Deterministic concurrency seam; production performs no work here."""

    async def _after_authority_check(self) -> None:
        """Deterministic terminal-race seam; production performs no work here."""

    async def _before_chat_terminal_commit(self) -> None:
        """Deterministic atomicity seam; production performs no work here."""

    @staticmethod
    async def _lock_run(session: AsyncSession, run_id: UUID) -> Run | None:
        return await session.scalar(select(Run).where(Run.id == run_id).with_for_update())

    async def _lock_command_context(
        self,
        session: AsyncSession,
        attempt_id: UUID,
    ) -> tuple[RunAttempt, Run]:
        attempt = await self._lock_attempt(session, attempt_id)
        if attempt is None:
            raise AttemptCommandRejected("attempt command is no longer authoritative")
        run = await self._lock_run(session, cast(UUID, attempt.run_id))
        if run is None:
            raise AttemptCommandRejected("attempt command is no longer authoritative")
        return attempt, run

    @staticmethod
    def _claimable(
        attempt: RunAttempt,
        run: Run,
        worker_id: UUID,
        now: datetime,
    ) -> bool:
        return bool(
            cast(str, attempt.status) == AttemptStatus.ASSIGNED.value
            and attempt.worker_id == worker_id
            and attempt.claim_token is None
            and attempt.lease_expires_at is not None
            and cast(datetime, attempt.lease_expires_at) > now
            and cast(str, run.status) == RunStatus.ASSIGNED.value
            and run.cancel_requested_at is None
        )

    @staticmethod
    def _require_authoritative(
        attempt: RunAttempt,
        run: Run,
        worker_id: UUID,
        token: UUID,
        now: datetime,
        *,
        required_run_status: RunStatus,
    ) -> None:
        if not (
            cast(str, attempt.status) == AttemptStatus.RUNNING.value
            and attempt.worker_id == worker_id
            and attempt.claim_token == token
            and attempt.lease_expires_at is not None
            and cast(datetime, attempt.lease_expires_at) > now
            and cast(str, run.status) == required_run_status.value
        ):
            raise AttemptCommandRejected("attempt command is no longer authoritative")

    @classmethod
    def _require_assignment_authoritative(
        cls,
        attempt: RunAttempt,
        run: Run,
        assignment: ClaimedAssignment,
        now: datetime,
    ) -> None:
        if (
            cast(UUID, run.id) != assignment.run_id
            or cast(UUID, run.tenant_id) != assignment.tenant_id
        ):
            raise AttemptCommandRejected("attempt command is no longer authoritative")
        cls._require_authoritative(
            attempt,
            run,
            assignment.worker_id,
            assignment.claim_token,
            now,
            required_run_status=RunStatus.RUNNING,
        )

    @staticmethod
    def _finish_attempt(
        attempt: RunAttempt,
        status: AttemptStatus,
        finished_at: datetime,
    ) -> None:
        cast(Any, attempt).status = status.value
        cast(Any, attempt).finished_at = finished_at
        cast(Any, attempt).claim_token = None

    @staticmethod
    async def _acknowledge_outbox(
        session: AsyncSession,
        *,
        attempt_id: UUID,
        event_type: OutboxType,
        acknowledged_at: datetime,
    ) -> None:
        await session.execute(
            update(RunOutbox)
            .where(
                RunOutbox.attempt_id == attempt_id,
                RunOutbox.event_type == event_type.value,
                RunOutbox.acknowledged_at.is_(None),
            )
            .values(acknowledged_at=acknowledged_at)
        )

    @staticmethod
    def _bounded_result(result: Mapping[str, Any]) -> dict[str, Any]:
        safe_result = deepcopy(dict(result))
        try:
            encoded = json.dumps(
                safe_result,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("result must be a JSON object") from exc
        if len(encoded) > MAX_RESULT_BYTES:
            raise ValueError(f"result exceeds {MAX_RESULT_BYTES} UTF-8 bytes")
        return safe_result

    @staticmethod
    def _bounded_json_object(value: Mapping[str, Any], *, limit: int, label: str) -> dict[str, Any]:
        try:
            encoded = json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} must be a JSON object") from exc
        if len(encoded) > limit:
            raise ValueError(f"{label} exceeds {limit} UTF-8 bytes")
        decoded = json.loads(encoded)
        if not isinstance(decoded, dict):
            raise ValueError(f"{label} must be a JSON object")
        return decoded

    @classmethod
    def tool_idempotency_key(
        cls,
        run_id: UUID,
        tool_call_id: str,
        tool_name: str,
        request: Mapping[str, Any],
    ) -> str:
        canonical = cls._bounded_json_object(request, limit=16 * 1024, label="tool request")
        material = json.dumps(
            [str(run_id), tool_call_id, tool_name, canonical],
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(material).hexdigest()

    @classmethod
    def tool_semantic_key(cls, tool_name: str, request: Mapping[str, Any]) -> str:
        canonical = cls._bounded_json_object(request, limit=16 * 1024, label="tool request")
        material = json.dumps(
            [tool_name, canonical],
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(material).hexdigest()

    @staticmethod
    def _validate_result_identity(
        assignment: ClaimedAssignment,
        result: CompletedResult | PauseResult | FailedResult,
    ) -> None:
        if result.run_id != assignment.run_id or result.attempt_id != assignment.attempt_id:
            raise ValueError("executor result identity does not match claimed assignment")

    @staticmethod
    async def _persist_usage_and_trace(
        session: AsyncSession,
        assignment: ClaimedAssignment,
        usage: RunUsage,
        now: datetime,
        *,
        status: str,
        outputs: Mapping[str, Any],
        error: str | None = None,
    ) -> None:
        if (
            min(usage.input_tokens, usage.output_tokens, usage.cached_tokens, usage.total_tokens)
            < 0
            or usage.total_tokens != usage.input_tokens + usage.output_tokens
            or usage.cached_tokens > usage.input_tokens
            or usage.cost_cny < 0
        ):
            raise ValueError("executor usage violates persistence constraints")
        session.add(
            RunUsageRecord(
                run_id=assignment.run_id,
                attempt_id=assignment.attempt_id,
                provider=usage.provider[:64],
                model=usage.model[:255],
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cached_tokens=usage.cached_tokens,
                total_tokens=usage.total_tokens,
                cost_cny=Decimal(str(usage.cost_cny)),
            )
        )
        aware_now = now.replace(tzinfo=UTC)
        session.add(
            TraceSpanRow(
                span_id=f"run-{assignment.attempt_id.hex}",
                request_id=str(assignment.run_id),
                parent_id=None,
                name="run.chat.execute",
                inputs={},
                outputs=dict(outputs),
                attrs_json={
                    "kind": "run",
                    "status": status,
                    "tenant_id": str(assignment.tenant_id),
                    "attempt_id": str(assignment.attempt_id),
                    "worker_id": str(assignment.worker_id),
                },
                started_at=aware_now,
                ended_at=aware_now,
                error=error,
            )
        )
        await session.flush()

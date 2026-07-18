"""Durable adapter between claimed Run Attempts and the transport-free chat executor."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Protocol, cast

from app.chatloop.contracts import ToolResult
from app.chatloop.inprocess import InProcessTool
from app.chatloop.loop import PauseDirective
from app.chatloop.run_executor import (
    ChatRunExecutor,
    CompletedResult,
    ExecuteChatRun,
    FailedResult,
    PauseResult,
    RunEvent,
    RunUsage,
)
from app.chatloop.state import ChatLoopState
from app.services.attempt_service import (
    AttemptCommandRejected,
    AttemptService,
    ClaimedAssignment,
    LoadedChatExecution,
)
from app.services.llm_step import StepToolCall


@dataclass(frozen=True)
class ContinuationKey:
    key_id: str
    secret: bytes


@dataclass(frozen=True)
class ContinuationKeyring:
    """Server-owned HMAC keys; transports never contribute key material."""

    active_key_id: str
    keys: Mapping[str, bytes]

    def __post_init__(self) -> None:
        if self.active_key_id not in self.keys:
            raise ValueError("active continuation key is unavailable")
        if any(not key_id or len(secret) < 32 for key_id, secret in self.keys.items()):
            raise ValueError("continuation keys require nonempty ids and 32-byte secrets")

    def select(self, continuation: Mapping[str, Any] | None) -> ContinuationKey:
        key_id = self.active_key_id
        if continuation is not None:
            candidate = continuation.get("key_id")
            if not isinstance(candidate, str) or candidate not in self.keys:
                raise ValueError("continuation key id is not trusted")
            key_id = candidate
        return ContinuationKey(key_id, self.keys[key_id])


class ChatAttemptExecutor(Protocol):
    async def execute(
        self, command: ExecuteChatRun
    ) -> CompletedResult | PauseResult | FailedResult: ...


EventSink = Callable[[RunEvent], Awaitable[None]]
ExecutorBuilder = Callable[
    [LoadedChatExecution, EventSink, asyncio.Event, "PersistentToolLedger", ContinuationKey],
    ChatAttemptExecutor,
]


class PersistentToolLedger:
    """Assignment-fenced facade over PostgreSQL tool execution facts."""

    def __init__(self, attempts: AttemptService, assignment: ClaimedAssignment) -> None:
        self._attempts = attempts
        self._assignment = assignment

    async def reserve(
        self,
        call: StepToolCall,
        *,
        safe_to_retry: bool,
        approved: bool,
    ) -> Any:
        try:
            request = call.parsed_args
        except ValueError:
            request = {}
        return await self._attempts.reserve_tool_execution(
            self._assignment,
            tool_call_id=call.id,
            tool_name=call.name,
            request=request,
            safe_to_retry=safe_to_retry,
            approved=approved,
        )

    async def complete(self, key: str, result: ToolResult) -> None:
        await self._attempts.complete_tool_execution(
            self._assignment,
            key,
            result.model_dump(mode="json"),
        )

    async def fail(self, key: str, result: ToolResult) -> None:
        await self._attempts.fail_tool_execution(
            self._assignment,
            key,
            error_code="tool_error",
            error_message=result.error or "Tool execution failed.",
        )


class ToolRiskPolicy:
    """Conservative risk classification: mutable in-process tools require approval."""

    SAFE_INPROCESS = frozenset(
        {
            "memory_search",
            "load_skill",
            "read_cached_result",
            "get_portfolio_positions",
            "search_tools",
        }
    )

    @classmethod
    def safe_to_retry(cls, hub: Any, tool_name: str) -> bool:
        tool = getattr(hub, "_tools", {}).get(tool_name)
        return not isinstance(tool, InProcessTool) or tool_name in cls.SAFE_INPROCESS


class DurableApprovalController:
    def __init__(
        self,
        hub: Any,
        approved_tool_call_ids: frozenset[str],
        risk_policy: type[ToolRiskPolicy] = ToolRiskPolicy,
    ) -> None:
        self._hub = hub
        self._approved = approved_tool_call_ids
        self._risk_policy = risk_policy

    async def check(
        self,
        *,
        phase: str,
        state: ChatLoopState,
        tool_calls: tuple[StepToolCall, ...] = (),
    ) -> PauseDirective | None:
        del state
        if phase != "before_tools":
            return None
        risky = [
            call
            for call in tool_calls
            if not self._risk_policy.safe_to_retry(self._hub, call.name)
            and call.id not in self._approved
        ]
        if not risky:
            return None
        return PauseDirective(
            "approval",
            {
                "tool_calls": [
                    {"id": call.id, "name": call.name, "arguments": call.arguments}
                    for call in risky
                ]
            },
        )


class DurableToolHub:
    """ToolHub proxy that commits a ledger reservation before every side effect."""

    def __init__(
        self,
        delegate: Any,
        ledger: PersistentToolLedger,
        approved_tool_call_ids: frozenset[str],
        risk_policy: type[ToolRiskPolicy] = ToolRiskPolicy,
    ) -> None:
        self._delegate = delegate
        self._ledger = ledger
        self._approved = approved_tool_call_ids
        self._risk_policy = risk_policy

    def schemas_for_llm(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], self._delegate.schemas_for_llm())

    async def dispatch(self, calls: list[StepToolCall], state: ChatLoopState) -> list[ToolResult]:
        results: list[ToolResult | None] = [None] * len(calls)
        executable: list[StepToolCall] = []
        executable_slots: list[tuple[int, str]] = []
        for index, call in enumerate(calls):
            safe = self._risk_policy.safe_to_retry(self._delegate, call.name)
            reservation = await self._ledger.reserve(
                call,
                safe_to_retry=safe,
                approved=call.id in self._approved,
            )
            if reservation.status == "completed" and reservation.result is not None:
                results[index] = ToolResult.model_validate(reservation.result)
                continue
            if not reservation.execute:
                results[index] = ToolResult(
                    tool_name=call.name,
                    args=self._safe_args(call),
                    success=False,
                    error=(
                        "Tool execution outcome is unknown after a worker crash; "
                        "manual approval is required and it was not re-executed."
                    ),
                    latency_ms=0,
                )
                continue
            executable.append(call)
            executable_slots.append((index, reservation.idempotency_key))

        try:
            executed_results = await self._delegate.dispatch(executable, state)
        except BaseException:
            # Committed `started` rows intentionally remain unknown.  A
            # non-idempotent retry will fail closed rather than claim exactly-once.
            raise
        if len(executed_results) != len(executable_slots):
            raise RuntimeError("durable tool dispatch returned an invalid result count")
        for result, (index, idempotency_key) in zip(
            executed_results, executable_slots, strict=True
        ):
            if result.success:
                await self._ledger.complete(idempotency_key, result)
            else:
                await self._ledger.fail(idempotency_key, result)
            results[index] = result
        if any(result is None for result in results):
            raise RuntimeError("durable tool dispatch left an unresolved result")
        return cast(list[ToolResult], results)

    @staticmethod
    def _safe_args(call: StepToolCall) -> dict[str, Any]:
        try:
            return call.parsed_args
        except ValueError:
            return {}


@dataclass
class _ComponentsProxy:
    llm: Any
    tool_hub: DurableToolHub
    gate_cfg: Any
    skill_listing: str
    system_prompt: str


def _approved_tool_call_ids(loaded: LoadedChatExecution) -> frozenset[str]:
    continuation = loaded.continuation
    if continuation is None:
        return frozenset()
    body = continuation.get("body")
    if not isinstance(body, Mapping) or body.get("pause_type") != "approval":
        return frozenset()
    try:
        response = json.loads(loaded.prompt)
    except json.JSONDecodeError:
        return frozenset()
    if not isinstance(response, dict) or response.get("approved") is not True:
        return frozenset()
    calls = body.get("pending_tool_calls")
    if not isinstance(calls, list):
        return frozenset()
    ids = {
        str(call.get("id"))
        for call in calls
        if isinstance(call, Mapping) and isinstance(call.get("id"), str)
    }
    return frozenset(ids)


def build_chat_executor_builder(
    singletons: Any,
    *,
    provider: str,
    model: str,
) -> ExecutorBuilder:
    """Create the production builder while retaining per-Attempt event/ledger state."""
    from app.chatloop.events import SeqCounter
    from app.chatloop.worker_wiring import build_turn_components

    def build(
        loaded: LoadedChatExecution,
        event_sink: EventSink,
        cancel_event: asyncio.Event,
        ledger: PersistentToolLedger,
        key: ContinuationKey,
    ) -> ChatRunExecutor:
        approved = _approved_tool_call_ids(loaded)
        controller_box: list[DurableApprovalController] = []

        def components_factory(emit: Any, seq_counter: SeqCounter) -> _ComponentsProxy:
            components = build_turn_components(singletons, emit=emit, seq_counter=seq_counter)
            durable_hub = DurableToolHub(components.tool_hub, ledger, approved)
            controller_box.append(DurableApprovalController(components.tool_hub, approved))
            return _ComponentsProxy(
                components.llm,
                durable_hub,
                components.gate_cfg,
                components.skill_listing,
                components.system_prompt,
            )

        class _LazyController:
            async def check(self, **kwargs: Any) -> PauseDirective | None:
                if not controller_box:
                    return None
                return await controller_box[-1].check(**kwargs)

        return ChatRunExecutor(
            components_factory=components_factory,
            event_sink=event_sink,
            cancel_event=cancel_event,
            user_id=loaded.user_id,
            continuation_secret=key.secret,
            continuation_key_id=key.key_id,
            pause_controller=_LazyController(),
            provider=provider,
            model=model,
        )

    return build


class RunChatWorker:
    """Execute one already-claimed assignment and durably close its Attempt."""

    def __init__(
        self,
        *,
        attempts: AttemptService,
        executor_builder: ExecutorBuilder,
        continuation_keys: ContinuationKeyring,
        renew_interval: float = 10.0,
        event_sink: EventSink | None = None,
    ) -> None:
        if renew_interval <= 0:
            raise ValueError("renew_interval must be positive")
        self._attempts = attempts
        self._executor_builder = executor_builder
        self._continuation_keys = continuation_keys
        self._renew_interval = renew_interval
        self._event_sink = event_sink or self._discard_event
        self._cancellations: dict[Any, asyncio.Event] = {}

    async def execute(self, assignment: ClaimedAssignment) -> None:
        """Compatibility entry point for the Phase 2 RunWorker protocol."""
        await self.execute_assignment(assignment)

    async def execute_assignment(self, assignment: ClaimedAssignment) -> None:
        loaded = await self._attempts.load_chat_execution(assignment)
        try:
            key = self._continuation_keys.select(loaded.continuation)
        except ValueError:
            await self._attempts.fail(
                assignment.attempt_id,
                assignment.worker_id,
                assignment.claim_token,
                "invalid_continuation_key",
                "Continuation authentication key is unavailable.",
            )
            return

        cancel_event = asyncio.Event()
        self._cancellations[assignment.attempt_id] = cancel_event
        ledger = PersistentToolLedger(self._attempts, assignment)
        executor = self._executor_builder(loaded, self._event_sink, cancel_event, ledger, key)
        stop_renew = asyncio.Event()
        renew_task = asyncio.create_task(self._renew_loop(assignment, stop_renew))
        terminal_phase = False
        try:
            # Give the renewal task a scheduling turn so very short executions are
            # still covered by a live lease check.
            await asyncio.sleep(0)
            command = ExecuteChatRun(
                run_id=assignment.run_id,
                attempt_id=assignment.attempt_id,
                session_id=loaded.session_id,
                prompt=loaded.prompt,
                history=loaded.history,
                continuation=loaded.continuation,
            )
            result = await executor.execute(command)
            await self._stop_renewal(stop_renew, renew_task)
            terminal_phase = True
            if isinstance(result, CompletedResult):
                await self._attempts.complete_chat(assignment, result)
            elif isinstance(result, PauseResult):
                await self._attempts.pause_chat(assignment, result)
            elif result.error_code == "cancelled":
                await self._attempts.cancel_chat(assignment, result)
            else:
                await self._attempts.fail_chat(assignment, result)
        except asyncio.CancelledError:
            cancel_event.set()
            raise
        except AttemptCommandRejected:
            # A stale lease/token is an expected fence, never a reason to attempt
            # a second fact write from this worker.
            return
        except Exception:
            if terminal_phase:
                raise
            await self._stop_renewal(stop_renew, renew_task)
            failed = FailedResult(
                assignment.run_id,
                assignment.attempt_id,
                loaded.session_id,
                "executor_error",
                "Chat execution failed.",
                False,
                "",
                RunUsage("unknown", "unknown", 0, 0, 0, 0, 0.0),
                (),
                (),
            )
            with suppress(AttemptCommandRejected):
                await self._attempts.fail_chat(assignment, failed)
        finally:
            await self._stop_renewal(stop_renew, renew_task)
            self._cancellations.pop(assignment.attempt_id, None)
            close = getattr(executor, "aclose", None)
            if close is not None:
                with suppress(Exception):
                    await close()

    def request_cancel(self, attempt_id: Any) -> bool:
        event = self._cancellations.get(attempt_id)
        if event is None:
            return False
        event.set()
        return True

    async def _renew_loop(self, assignment: ClaimedAssignment, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await self._attempts.renew(
                assignment.attempt_id,
                assignment.worker_id,
                assignment.claim_token,
            )
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._renew_interval)
            except TimeoutError:
                continue

    @staticmethod
    async def _stop_renewal(stop: asyncio.Event, task: asyncio.Task[None]) -> None:
        stop.set()
        if not task.done():
            task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await task

    @staticmethod
    async def _discard_event(_event: RunEvent) -> None:
        return None


__all__ = [
    "ContinuationKey",
    "ContinuationKeyring",
    "DurableToolHub",
    "PersistentToolLedger",
    "RunChatWorker",
    "ToolRiskPolicy",
    "build_chat_executor_builder",
]

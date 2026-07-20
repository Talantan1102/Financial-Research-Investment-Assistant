"""Durable adapter between claimed Run Attempts and the transport-free chat executor."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Protocol, cast

from app.chatloop.contracts import ToolResult
from app.chatloop.loop import PauseDirective
from app.chatloop.run_executor import (
    ChatRunExecutor,
    CompletedResult,
    ExecuteChatRun,
    FailedResult,
    PauseResult,
    RunEvent,
    RunUsage,
    ToolExecution,
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


def load_continuation_keyring(environment: Mapping[str, str]) -> ContinuationKeyring:
    """Load only trusted server configuration; no transport value is consulted."""
    encoded = environment.get("RUN_CONTINUATION_HMAC_KEYS_JSON")
    if encoded is not None:
        try:
            raw = json.loads(encoded)
        except json.JSONDecodeError as exc:
            raise ValueError("invalid continuation key configuration") from exc
        if not isinstance(raw, dict) or any(
            not isinstance(key_id, str) or not isinstance(secret, str)
            for key_id, secret in raw.items()
        ):
            raise ValueError("invalid continuation key configuration")
        active = environment.get("RUN_CONTINUATION_HMAC_ACTIVE_KEY_ID", "")
        try:
            return ContinuationKeyring(
                active_key_id=active,
                keys={key_id: secret.encode("utf-8") for key_id, secret in raw.items()},
            )
        except ValueError as exc:
            raise ValueError("invalid continuation key configuration") from exc
    legacy_secret = environment.get("RUN_CONTINUATION_HMAC_SECRET")
    legacy_id = environment.get("RUN_CONTINUATION_HMAC_KEY_ID", "default")
    if legacy_secret is None:
        raise ValueError("invalid continuation key configuration")
    try:
        return ContinuationKeyring(
            active_key_id=legacy_id,
            keys={legacy_id: legacy_secret.encode("utf-8")},
        )
    except ValueError as exc:
        raise ValueError("invalid continuation key configuration") from exc


def resolve_llm_identity(llm: Any) -> tuple[str, str]:
    provider = getattr(llm, "provider", None)
    model = getattr(llm, "default_model", None)
    if model is None:
        router = getattr(llm, "_tier_router", None)
        resolve = getattr(router, "resolve", None)
        if resolve is not None:
            model = resolve("fast")
    if not isinstance(provider, str) or not provider or not isinstance(model, str) or not model:
        raise ValueError("LLM execution identity is unavailable")
    return provider, model


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
        approved_execution_id: Any = None,
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
            approved_execution_id=approved_execution_id,
        )

    async def complete(self, reservation: Any, result: ToolResult) -> None:
        await self._attempts.complete_tool_execution(
            self._assignment,
            reservation.idempotency_key,
            result.model_dump(mode="json"),
            reservation_token=reservation.reservation_token,
            execution_epoch=reservation.execution_epoch,
        )

    async def fail(self, reservation: Any, result: ToolResult) -> None:
        await self._attempts.fail_tool_execution(
            self._assignment,
            reservation.idempotency_key,
            error_code="tool_error",
            error_message=result.error or "Tool execution failed.",
            reservation_token=reservation.reservation_token,
            execution_epoch=reservation.execution_epoch,
        )


@dataclass(frozen=True)
class ToolRiskPolicy:
    """Server-owned capability registry. Unknown tools always fail closed."""

    safe_idempotent_tools: frozenset[str]

    @classmethod
    def from_trusted_names(cls, names: set[str] | frozenset[str]) -> ToolRiskPolicy:
        if any(not name or len(name) > 255 for name in names):
            raise ValueError("trusted tool names must be 1..255 characters")
        return cls(frozenset(names))

    def safe_to_retry(self, tool_name: str) -> bool:
        return tool_name in self.safe_idempotent_tools


SAFE_IDEMPOTENT_TOOL_CATALOG_V1 = frozenset(
    {"search_tools", "memory_search", "read_cached_result", "get_portfolio_positions"}
)


def load_tool_risk_policy(environ: Mapping[str, str]) -> ToolRiskPolicy:
    """Load a versioned, fail-closed production retry catalog."""
    version = environ.get("RUN_TOOL_RISK_CATALOG", "v1")
    if version != "v1":
        raise ValueError(f"unknown RUN_TOOL_RISK_CATALOG: {version}")
    configured = environ.get("RUN_SAFE_IDEMPOTENT_TOOLS")
    names = (
        SAFE_IDEMPOTENT_TOOL_CATALOG_V1
        if configured is None or not configured.strip()
        else frozenset(name.strip() for name in configured.split(",") if name.strip())
    )
    unknown = names - SAFE_IDEMPOTENT_TOOL_CATALOG_V1
    if unknown:
        raise ValueError(f"untrusted safe tool names: {', '.join(sorted(unknown))}")
    return ToolRiskPolicy.from_trusted_names(names)


class DurableApprovalController:
    def __init__(
        self,
        risk_policy: ToolRiskPolicy,
        approved_tool_call_ids: frozenset[str],
        approved_semantic_keys: frozenset[str] = frozenset(),
    ) -> None:
        self._approved = approved_tool_call_ids
        self._approved_semantics = approved_semantic_keys
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
            if not self._risk_policy.safe_to_retry(call.name)
            and call.id not in self._approved
            and AttemptService.tool_semantic_key(call.name, self._safe_args(call))
            not in self._approved_semantics
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

    @staticmethod
    def _safe_args(call: StepToolCall) -> dict[str, Any]:
        try:
            return call.parsed_args
        except ValueError:
            return {}


class DurableToolHub:
    """ToolHub proxy that commits a ledger reservation before every side effect."""

    def __init__(
        self,
        delegate: Any,
        ledger: PersistentToolLedger,
        approved_tool_call_ids: frozenset[str],
        risk_policy: ToolRiskPolicy,
        approved_semantic_keys: frozenset[str] = frozenset(),
        approved_tool_executions: Mapping[str, Any] | None = None,
    ) -> None:
        self._delegate = delegate
        self._ledger = ledger
        self._approved = approved_tool_call_ids
        self._risk_policy = risk_policy
        self._approved_semantics = approved_semantic_keys
        self._approved_executions = dict(approved_tool_executions or {})

    def schemas_for_llm(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], self._delegate.schemas_for_llm())

    async def dispatch(self, calls: list[StepToolCall], state: ChatLoopState) -> list[ToolResult]:
        results: list[ToolResult | None] = [None] * len(calls)
        executable: list[StepToolCall] = []
        executable_slots: list[tuple[int, Any]] = []
        for index, call in enumerate(calls):
            safe = self._risk_policy.safe_to_retry(call.name)
            semantic_approved = (
                AttemptService.tool_semantic_key(call.name, self._safe_args(call))
                in self._approved_semantics
            )
            reservation = await self._ledger.reserve(
                call,
                safe_to_retry=safe,
                approved=call.id in self._approved or semantic_approved,
                approved_execution_id=self._approved_executions.get(call.id),
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
            executable_slots.append((index, reservation))

        try:
            executed_results = await self._delegate.dispatch(executable, state)
        except BaseException:
            # Committed `started` rows intentionally remain unknown.  A
            # non-idempotent retry will fail closed rather than claim exactly-once.
            raise
        if len(executed_results) != len(executable_slots):
            raise RuntimeError("durable tool dispatch returned an invalid result count")
        for result, (index, reservation) in zip(executed_results, executable_slots, strict=True):
            if result.success:
                await self._ledger.complete(reservation, result)
            else:
                await self._ledger.fail(reservation, result)
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
    action = body.get("pending_action") if isinstance(body, Mapping) else None
    if not isinstance(action, Mapping) or action.get("pause_type") != "approval":
        return frozenset()
    try:
        response = json.loads(loaded.prompt)
    except json.JSONDecodeError:
        return frozenset()
    if not isinstance(response, dict):
        return frozenset()
    calls = action.get("pending_tool_calls")
    if not isinstance(calls, list):
        return frozenset()
    if response.get("approved") is True:
        ids = {
            str(call.get("id"))
            for call in calls
            if isinstance(call, Mapping) and isinstance(call.get("id"), str)
        }
    elif isinstance(response.get("decisions"), Mapping):
        decisions = cast(Mapping[str, Any], response["decisions"])
        ids = {
            str(call.get("id"))
            for call in calls
            if isinstance(call, Mapping)
            and isinstance(call.get("id"), str)
            and decisions.get(cast(str, call["id"])) is True
        }
    else:
        ids = set()
    return frozenset(ids)


def build_chat_executor_builder(
    singletons: Any,
    *,
    provider: str,
    model: str,
    risk_policy: ToolRiskPolicy,
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
        approved_executions = dict(getattr(loaded, "approved_tool_executions", ()))
        controller_box: list[DurableApprovalController] = []

        def components_factory(emit: Any, seq_counter: SeqCounter) -> _ComponentsProxy:
            components = build_turn_components(singletons, emit=emit, seq_counter=seq_counter)
            durable_hub = DurableToolHub(
                components.tool_hub,
                ledger,
                approved,
                risk_policy,
                loaded.approved_semantic_keys,
                approved_executions,
            )
            controller_box.append(
                DurableApprovalController(risk_policy, approved, loaded.approved_semantic_keys)
            )
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
        try:
            loaded = await self._attempts.load_chat_execution(assignment)
        except (AttemptCommandRejected, ValueError):
            with suppress(AttemptCommandRejected):
                await self._attempts.fail(
                    assignment.attempt_id,
                    assignment.worker_id,
                    assignment.claim_token,
                    "invalid_approval_decision",
                    "The approval decision is invalid.",
                )
            return
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
        # Prove the claim is still live before building any model/tool graph,
        # then fail closed on unresolved unsafe side effects from prior Attempts.
        await self._attempts.renew(
            assignment.attempt_id, assignment.worker_id, assignment.claim_token
        )
        try:
            find_many = getattr(self._attempts, "find_unsafe_recoveries", None)
            if find_many is None:
                recovery = await self._attempts.find_unsafe_recovery(assignment)
                recoveries = () if recovery is None else (recovery,)
            else:
                recoveries = await find_many(assignment)
        except (AttemptCommandRejected, ValueError):
            await self._converge_invalid_approval(assignment, loaded)
            return
        approved_bindings = dict(getattr(loaded, "approved_tool_executions", ()))
        approved_execution_ids = {str(value) for value in approved_bindings.values()}
        rejected_execution_ids = tuple(getattr(loaded, "rejected_tool_execution_ids", ()))
        decided_execution_ids = approved_execution_ids | {
            str(value) for value in rejected_execution_ids
        }
        recovery_execution_ids = {str(row["execution_id"]) for row in recoveries}
        if recoveries and decided_execution_ids != recovery_execution_ids:
            await self._attempts.pause_chat(
                assignment,
                self._unsafe_recovery_pause(assignment, loaded, key, recoveries),
            )
            return
        if rejected_execution_ids:
            try:
                reject_many = getattr(self._attempts, "reject_tool_executions", None)
                if reject_many is None:
                    for execution_id in rejected_execution_ids:
                        await self._attempts.reject_tool_execution(assignment, execution_id)
                else:
                    await reject_many(assignment, rejected_execution_ids)
            except (AttemptCommandRejected, ValueError):
                await self._converge_invalid_approval(assignment, loaded)
                return

        cancel_event = asyncio.Event()
        self._cancellations[assignment.attempt_id] = cancel_event
        ledger = PersistentToolLedger(self._attempts, assignment)
        stop_renew = asyncio.Event()
        renew_task: asyncio.Task[None] | None = None
        executor: ChatAttemptExecutor | None = None
        terminal_phase = False
        lease_lost = False
        execute_task: asyncio.Task[CompletedResult | PauseResult | FailedResult] | None = None
        try:
            built_executor = self._executor_builder(
                loaded, self._event_sink, cancel_event, ledger, key
            )
            executor = built_executor
            renew_task = asyncio.create_task(self._renew_loop(assignment, stop_renew))
            command = ExecuteChatRun(
                run_id=assignment.run_id,
                attempt_id=assignment.attempt_id,
                session_id=loaded.session_id,
                prompt=loaded.prompt,
                history=loaded.history,
                continuation=loaded.continuation,
            )
            execute_task = asyncio.create_task(built_executor.execute(command))
            done, _pending = await asyncio.wait(
                {execute_task, renew_task}, return_when=asyncio.FIRST_COMPLETED
            )
            # A simultaneously completed execution wins: it has a legitimate
            # terminal result and the terminal transaction performs the final fence.
            if execute_task in done:
                result = await execute_task
                await self._stop_renewal(stop_renew, renew_task, ignore_done_error=True)
            else:
                lease_lost = True
                cancel_event.set()
                with suppress(asyncio.CancelledError):
                    await execute_task
                await renew_task
                raise RuntimeError("renew task ended without an error")
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
            if lease_lost:
                raise
            # A stale lease/token is an expected fence, never a reason to attempt
            # a second fact write from this worker.
            return
        except Exception:
            if terminal_phase or lease_lost:
                raise
            if renew_task is not None:
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
            if execute_task is not None and not execute_task.done():
                cancel_event.set()
                execute_task.cancel()
                with suppress(asyncio.CancelledError):
                    await execute_task
            if renew_task is not None:
                await self._stop_renewal(
                    stop_renew,
                    renew_task,
                    ignore_done_error=lease_lost or terminal_phase,
                )
            self._cancellations.pop(assignment.attempt_id, None)
            close = getattr(executor, "aclose", None) if executor is not None else None
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
    async def _stop_renewal(
        stop: asyncio.Event,
        task: asyncio.Task[None],
        *,
        ignore_done_error: bool = False,
    ) -> None:
        stop.set()
        if not task.done():
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            return
        except Exception:
            if not ignore_done_error:
                raise

    @staticmethod
    async def _discard_event(_event: RunEvent) -> None:
        return None

    @staticmethod
    def _unsafe_recovery_pause(
        assignment: ClaimedAssignment,
        loaded: LoadedChatExecution,
        key: ContinuationKey,
        recoveries: tuple[Mapping[str, Any], ...],
    ) -> PauseResult:
        calls = tuple(
            StepToolCall(
                id=str(recovery["tool_call_id"]),
                name=str(recovery["tool_name"]),
                arguments=json.dumps(
                    recovery["request"],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
            for recovery in recoveries
        )
        command = ExecuteChatRun(
            run_id=assignment.run_id,
            attempt_id=assignment.attempt_id,
            session_id=loaded.session_id,
            prompt=getattr(loaded, "original_prompt", loaded.prompt),
            history=loaded.history,
            continuation=None,
        )
        continuation = ChatRunExecutor.approval_snapshot(
            command,
            user_id=str(loaded.user_id),
            pending_tool_calls=calls,
            continuation_secret=key.secret,
            continuation_key_id=key.key_id,
        )
        request: Mapping[str, Any] = {
            "reason": "unsafe_tool_outcome_unknown",
            "action": "execute_anyway_or_reject",
            "execution_bindings": [
                {
                    "execution_id": recovery["execution_id"],
                    "semantic_key": recovery["semantic_key"],
                    "tool_call": {
                        "id": recovery["tool_call_id"],
                        "name": recovery["tool_name"],
                        "arguments": recovery["request"],
                    },
                }
                for recovery in recoveries
            ],
        }
        tools = tuple(
            ToolExecution(
                str(recovery["tool_call_id"]),
                str(recovery["tool_name"]),
                cast(Mapping[str, Any], recovery["request"]),
                "approval_required",
                "Unsafe tool outcome is unknown; manual decision required.",
                None,
                None,
                None,
                0,
            )
            for recovery in recoveries
        )
        return PauseResult(
            assignment.run_id,
            assignment.attempt_id,
            loaded.session_id,
            "approval",
            request,
            continuation,
            RunUsage("control", "unsafe-recovery", 0, 0, 0, 0, 0.0),
            tools,
            (),
        )

    async def _converge_invalid_approval(
        self, assignment: ClaimedAssignment, loaded: LoadedChatExecution
    ) -> None:
        failed = FailedResult(
            assignment.run_id,
            assignment.attempt_id,
            loaded.session_id,
            "invalid_continuation",
            "The approval decision could not be matched to its pending tool execution.",
            False,
            "",
            RunUsage("control", "approval-recovery", 0, 0, 0, 0, 0.0),
            (),
            (),
        )
        with suppress(AttemptCommandRejected):
            await self._attempts.fail_chat(assignment, failed)


__all__ = [
    "ContinuationKey",
    "ContinuationKeyring",
    "DurableToolHub",
    "PersistentToolLedger",
    "RunChatWorker",
    "ToolRiskPolicy",
    "load_tool_risk_policy",
    "build_chat_executor_builder",
    "load_continuation_keyring",
    "resolve_llm_identity",
]

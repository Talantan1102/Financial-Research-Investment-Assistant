"""Transport-free, Run-oriented adapter around the shared chat ToolLoop core."""

from __future__ import annotations

import asyncio
import copy
import json
import math
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Any, Literal, Protocol, TypeAlias
from uuid import UUID

from app.chatloop.context import ContextDeps
from app.chatloop.events import LoopEvent, SeqCounter
from app.chatloop.loop import (
    CancelledByUser,
    LoopPaused,
    ModelExecutionError,
    PauseControllerProtocol,
    PauseDirective,
    ToolExecutionError,
    execute_tool_loop,
)
from app.chatloop.state import ChatLoopState, args_hash_of
from app.services.llm_step import StepToolCall

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | Mapping[str, "JsonValue"] | tuple["JsonValue", ...]


class ChatLoopComponentsProtocol(Protocol):
    llm: Any
    tool_hub: Any
    gate_cfg: Any
    skill_listing: str
    system_prompt: str


EventSink = Callable[["RunEvent"], Awaitable[None]]
ComponentsFactory = Callable[
    [Callable[[LoopEvent], Awaitable[None]], SeqCounter], ChatLoopComponentsProtocol
]


@dataclass(frozen=True)
class ExecuteChatRun:
    run_id: UUID
    attempt_id: UUID
    session_id: UUID
    prompt: str
    history: tuple[dict[str, Any], ...]
    continuation: dict[str, Any] | None


@dataclass(frozen=True)
class RunUsage:
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    total_tokens: int
    cost_cny: float


@dataclass(frozen=True)
class RunEvent:
    run_id: UUID
    attempt_id: UUID
    kind: str
    seq: int
    step: int
    payload: Mapping[str, JsonValue]


@dataclass(frozen=True)
class ToolExecution:
    tool_call_id: str
    tool_name: str
    request: Mapping[str, JsonValue]
    status: Literal["completed", "failed", "approval_required"]
    digest: str
    cache_key: str | None
    error_code: str | None
    error_message: str | None
    step: int

    @property
    def success(self) -> bool:
        return self.status == "completed"


@dataclass(frozen=True)
class CompletedResult:
    run_id: UUID
    attempt_id: UUID
    session_id: UUID
    final_text: str
    usage: RunUsage
    tools: tuple[ToolExecution, ...]
    events: tuple[RunEvent, ...]


@dataclass(frozen=True)
class PauseResult:
    run_id: UUID
    attempt_id: UUID
    session_id: UUID
    pause_type: Literal["input", "approval"]
    request: Mapping[str, JsonValue]
    continuation: Mapping[str, JsonValue]
    usage: RunUsage
    tools: tuple[ToolExecution, ...]
    events: tuple[RunEvent, ...]

    def thaw_continuation(self) -> dict[str, Any]:
        thawed = thaw_json(self.continuation)
        assert isinstance(thawed, dict)
        return thawed

    def continuation_json(self) -> str:
        return json.dumps(
            self.thaw_continuation(),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )


@dataclass(frozen=True)
class FailedResult:
    run_id: UUID
    attempt_id: UUID
    session_id: UUID
    error_code: Literal[
        "model_error",
        "tool_error",
        "cancelled",
        "executor_error",
        "invalid_continuation",
        "continuation_too_large",
    ]
    message: str
    retryable: bool
    partial_text: str
    usage: RunUsage
    tools: tuple[ToolExecution, ...]
    events: tuple[RunEvent, ...]


ExecutionResult: TypeAlias = CompletedResult | PauseResult | FailedResult


class _ContinuationTooLargeError(ValueError):
    pass


@dataclass(frozen=True)
class _UsageBaseline:
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    cost_cny: float
    ledger_count: int
    message_count: int


def _freeze_json(value: Any) -> JsonValue:
    """Deep-copy JSON data into immutable mappings/tuples before crossing the boundary."""

    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, JsonValue]:
    frozen = _freeze_json(value)
    assert isinstance(frozen, Mapping)
    return frozen


def thaw_json(value: JsonValue) -> Any:
    if isinstance(value, Mapping):
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


def _canonical_portable_json(value: Any, *, max_bytes: int) -> Any:
    """Validate hostile input iteratively before allocating a defensive JSON copy."""

    max_depth = 64
    max_nodes = 10_000
    max_int = 2**63 - 1
    stack: list[tuple[Any, int]] = [(value, 0)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > max_nodes or depth > max_depth:
            raise _ContinuationTooLargeError("continuation structure exceeds limits")
        if current is None or isinstance(current, (str, bool)):
            if isinstance(current, str) and (
                len(current) > max_bytes or len(current.encode("utf-8")) > max_bytes
            ):
                raise _ContinuationTooLargeError("continuation string exceeds limit")
            continue
        if isinstance(current, int):
            if abs(current) > max_int:
                raise ValueError("integer outside portable range")
            continue
        if isinstance(current, float):
            if not math.isfinite(current):
                raise ValueError("non-finite float")
            continue
        if isinstance(current, Mapping):
            if len(current) > max_nodes:
                raise _ContinuationTooLargeError("continuation mapping exceeds limit")
            for key, item in current.items():
                if not isinstance(key, str):
                    raise ValueError("JSON object keys must be strings")
                if len(key) > max_bytes or len(key.encode("utf-8")) > max_bytes:
                    raise _ContinuationTooLargeError("continuation key exceeds limit")
                stack.append((item, depth + 1))
            continue
        if isinstance(current, (list, tuple)):
            if len(current) > max_nodes:
                raise _ContinuationTooLargeError("continuation sequence exceeds limit")
            stack.extend((item, depth + 1) for item in current)
            continue
        raise ValueError("non-portable continuation value")

    encoder = json.JSONEncoder(
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    encoded = bytearray()
    for chunk in encoder.iterencode(value):
        chunk_bytes = chunk.encode("utf-8")
        if len(encoded) + len(chunk_bytes) > max_bytes:
            raise _ContinuationTooLargeError("continuation exceeds byte limit")
        encoded.extend(chunk_bytes)
    return json.loads(encoded.decode("utf-8"))


def _final_text(state: ChatLoopState) -> str:
    if state.final_response:
        return state.final_response
    for message in reversed(state.messages):
        if message.get("role") == "assistant" and isinstance(message.get("content"), str):
            return message["content"]
    return ""


class ChatRunExecutor:
    """Execute one Run attempt without persistence, web, queue, or bus dependencies."""

    MAX_CONTINUATION_BYTES = 64 * 1024

    def __init__(
        self,
        *,
        components: ChatLoopComponentsProtocol | None = None,
        components_factory: ComponentsFactory | None = None,
        event_sink: EventSink,
        cancel_event: asyncio.Event,
        user_id: UUID | str,
        pause_controller: PauseControllerProtocol | None = None,
        provider: str = "unknown",
        model: str = "unknown",
        reference_date: date | None = None,
        persona_block: str = "",
        max_context_tokens: int = 100_000,
        oversize_result_char_threshold: int = 24_000,
    ) -> None:
        if (components is None) == (components_factory is None):
            raise ValueError("provide exactly one of components or components_factory")
        self._components = components
        self._components_factory = components_factory
        self._event_sink = event_sink
        self._cancel_event = cancel_event
        self._user_id = str(user_id)
        self._pause_controller = pause_controller
        self._provider = provider
        self._model = model
        self._reference_date = reference_date or date.today()
        self._persona_block = persona_block
        self._max_context_tokens = max_context_tokens
        self._oversize_result_char_threshold = oversize_result_char_threshold

    async def execute(self, command: ExecuteChatRun) -> ExecutionResult:
        history = copy.deepcopy(command.history)
        events: list[RunEvent] = []
        emitted_tokens: list[str] = []
        seq_counter = SeqCounter()

        try:
            continuation = (
                None
                if command.continuation is None
                else _canonical_portable_json(
                    command.continuation, max_bytes=self.MAX_CONTINUATION_BYTES
                )
            )
            state, pending_tool_calls, resume_prompt, approval_decision = self._initial_state(
                command, continuation
            )
        except _ContinuationTooLargeError:
            return self._failed(
                command,
                "continuation_too_large",
                "Continuation exceeds the portable size limit.",
                False,
                ChatLoopState(
                    user_id="",
                    session_id=str(command.session_id),
                    request_id=str(command.run_id),
                    messages=[],
                ),
                events,
                emitted_tokens,
                _UsageBaseline(0, 0, 0, 0.0, 0, 0),
            )
        except (TypeError, ValueError):
            return self._failed(
                command,
                "invalid_continuation",
                "Continuation is invalid.",
                False,
                ChatLoopState(
                    user_id="",
                    session_id=str(command.session_id),
                    request_id=str(command.run_id),
                    messages=[],
                ),
                events,
                emitted_tokens,
                _UsageBaseline(0, 0, 0, 0.0, 0, 0),
            )

        baseline = self._baseline(state)

        async def publish(event: RunEvent) -> None:
            events.append(event)
            # Event delivery is best-effort at this pure execution boundary.
            with suppress(Exception):
                await self._event_sink(event)

        async def emit(loop_event: LoopEvent) -> None:
            payload = copy.deepcopy(loop_event.data)
            if loop_event.type == "tool_error":
                payload = {
                    "tool": str(payload.get("tool", "")),
                    "code": "tool_error",
                    "message": "Tool execution failed.",
                }
            elif loop_event.type == "error":
                payload = {"code": str(payload.get("code", "executor_error"))}
            event = RunEvent(
                run_id=command.run_id,
                attempt_id=command.attempt_id,
                kind=loop_event.type,
                seq=loop_event.seq,
                step=loop_event.step,
                payload=_freeze_mapping(payload),
            )
            if event.kind == "token":
                text = event.payload.get("text")
                if isinstance(text, str):
                    emitted_tokens.append(text)
            await publish(event)

        try:
            components = (
                self._components_factory(emit, seq_counter)
                if self._components_factory is not None
                else self._components
            )
            assert components is not None
            deps = ContextDeps(
                system_prompt=components.system_prompt,
                persona_block=self._persona_block,
                skill_listing=components.skill_listing,
                history_block=history,
                max_steps=components.gate_cfg.max_steps,
                max_cny=components.gate_cfg.max_cny,
                max_context_tokens=self._max_context_tokens,
                oversize_result_char_threshold=self._oversize_result_char_threshold,
                reference_date=self._reference_date,
            )
        except Exception:
            await self._emit_control_event(
                command,
                events,
                seq_counter,
                "error",
                state.step,
                {"code": "executor_error"},
                publish,
            )
            return self._failed(
                command,
                "executor_error",
                "Chat execution failed.",
                False,
                state,
                events,
                emitted_tokens,
                baseline,
                pending_tool_calls=pending_tool_calls,
                approval_rejected=approval_decision == "reject",
            )

        try:
            state = await execute_tool_loop(
                state=state,
                llm=components.llm,
                tool_hub=components.tool_hub,
                context_deps=deps,
                gate_cfg=components.gate_cfg,
                emit=emit,
                cancel_event=self._cancel_event,
                seq_counter=seq_counter,
                model=None if self._model == "unknown" else self._model,
                pause_controller=self._pause_controller,
                pending_tool_calls=pending_tool_calls,
                resume_prompt=resume_prompt,
                approval_decision=approval_decision,
            )
        except LoopPaused as paused:
            state = paused.state
            try:
                continuation_payload = self._snapshot(
                    state, paused.pending_tool_calls, paused.directive.pause_type
                )
                request_payload = _canonical_portable_json(
                    paused.directive.request, max_bytes=self.MAX_CONTINUATION_BYTES
                )
                if not isinstance(request_payload, dict):
                    raise ValueError("pause request must be an object")
            except _ContinuationTooLargeError:
                return self._failed(
                    command,
                    "continuation_too_large",
                    "Continuation exceeds the portable size limit.",
                    False,
                    state,
                    events,
                    emitted_tokens,
                    baseline,
                    pending_tool_calls=paused.pending_tool_calls,
                )
            except (TypeError, ValueError):
                return self._failed(
                    command,
                    "executor_error",
                    "Chat execution failed.",
                    False,
                    state,
                    events,
                    emitted_tokens,
                    baseline,
                    pending_tool_calls=paused.pending_tool_calls,
                )
            await self._emit_control_event(
                command,
                events,
                seq_counter,
                "approval_request"
                if paused.directive.pause_type == "approval"
                else "input_request",
                state.step,
                request_payload,
                publish,
            )
            return PauseResult(
                command.run_id,
                command.attempt_id,
                command.session_id,
                paused.directive.pause_type,
                _freeze_mapping(request_payload),
                _freeze_mapping(continuation_payload),
                self._usage(state, baseline),
                self._tools(
                    state,
                    baseline=baseline,
                    pending_approval=paused.directive.pause_type == "approval",
                ),
                tuple(events),
            )
        except CancelledByUser:
            await self._emit_control_event(
                command,
                events,
                seq_counter,
                "cancelled",
                state.step,
                {"reason": "user_cancel"},
                publish,
            )
            return self._failed(
                command,
                "cancelled",
                "Run was cancelled.",
                False,
                state,
                events,
                emitted_tokens,
                baseline,
                pending_tool_calls=pending_tool_calls,
                approval_rejected=approval_decision == "reject",
            )
        except ModelExecutionError:
            await self._emit_control_event(
                command, events, seq_counter, "error", state.step, {"code": "model_error"}, publish
            )
            return self._failed(
                command,
                "model_error",
                "Model execution failed.",
                True,
                state,
                events,
                emitted_tokens,
                baseline,
                pending_tool_calls=pending_tool_calls,
                approval_rejected=approval_decision == "reject",
            )
        except ToolExecutionError:
            await self._emit_control_event(
                command, events, seq_counter, "error", state.step, {"code": "tool_error"}, publish
            )
            return self._failed(
                command,
                "tool_error",
                "Tool execution failed.",
                True,
                state,
                events,
                emitted_tokens,
                baseline,
                pending_tool_calls=pending_tool_calls,
                approval_rejected=approval_decision == "reject",
            )
        except Exception:
            await self._emit_control_event(
                command,
                events,
                seq_counter,
                "error",
                state.step,
                {"code": "executor_error"},
                publish,
            )
            return self._failed(
                command,
                "executor_error",
                "Chat execution failed.",
                False,
                state,
                events,
                emitted_tokens,
                baseline,
                pending_tool_calls=pending_tool_calls,
                approval_rejected=approval_decision == "reject",
            )

        return CompletedResult(
            command.run_id,
            command.attempt_id,
            command.session_id,
            _final_text(state),
            self._usage(state, baseline),
            self._tools(
                state,
                baseline=baseline,
                pending_tool_calls=pending_tool_calls,
                approval_rejected=approval_decision == "reject",
            ),
            tuple(events),
        )

    def _initial_state(
        self, command: ExecuteChatRun, continuation: dict[str, Any] | None
    ) -> tuple[
        ChatLoopState,
        tuple[StepToolCall, ...],
        str | None,
        Literal["approve", "reject"] | None,
    ]:
        if continuation is None:
            return (
                ChatLoopState(
                    user_id=self._user_id,
                    session_id=str(command.session_id),
                    request_id=str(command.run_id),
                    messages=[{"role": "user", "content": command.prompt}],
                ),
                (),
                None,
                None,
            )
        if (
            set(continuation) != {"pause_type", "state", "pending_tool_calls"}
            or not isinstance(continuation["state"], dict)
            or not isinstance(continuation["pending_tool_calls"], list)
        ):
            raise ValueError("unknown continuation shape")
        pause_type = continuation["pause_type"]
        if pause_type not in {"input", "approval"}:
            raise ValueError("unknown pause type")
        state = ChatLoopState.model_validate(continuation["state"])
        pending_tool_calls = tuple(
            StepToolCall.model_validate(call) for call in continuation["pending_tool_calls"]
        )
        self._validate_pause_snapshot(state, pending_tool_calls, pause_type)
        state.user_id = self._user_id
        state.request_id = str(command.run_id)
        state.session_id = str(command.session_id)
        if not pending_tool_calls:
            state.messages.append({"role": "user", "content": command.prompt})
            return state, pending_tool_calls, None, None
        try:
            response = json.loads(command.prompt)
        except json.JSONDecodeError as exc:
            raise ValueError("approval response must be JSON") from exc
        if (
            not isinstance(response, dict)
            or type(response.get("approved")) is not bool
            or ("text" in response and not isinstance(response["text"], str))
        ):
            raise ValueError("approval response must contain boolean approved")
        resume_prompt = response.get("text") or json.dumps(
            response, ensure_ascii=False, sort_keys=True
        )
        return (
            state,
            pending_tool_calls,
            resume_prompt,
            "approve" if response["approved"] else "reject",
        )

    @staticmethod
    def _snapshot(
        state: ChatLoopState,
        pending_tool_calls: tuple[StepToolCall, ...],
        pause_type: Literal["input", "approval"],
    ) -> dict[str, Any]:
        payload = {
            "pause_type": pause_type,
            "state": state.model_dump(mode="json"),
            "pending_tool_calls": [call.model_dump(mode="json") for call in pending_tool_calls],
        }
        ChatRunExecutor._validate_pause_snapshot(state, pending_tool_calls, pause_type)
        canonical = _canonical_portable_json(
            payload, max_bytes=ChatRunExecutor.MAX_CONTINUATION_BYTES
        )
        assert isinstance(canonical, dict)
        return canonical

    @staticmethod
    def _canonical_arguments(raw: Any) -> str:
        if not isinstance(raw, str):
            raise ValueError("tool arguments must be a string")
        parsed = json.loads(raw or "{}")
        if not isinstance(parsed, dict):
            raise ValueError("tool arguments must be an object")
        return json.dumps(
            parsed, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        )

    @classmethod
    def _validate_pause_snapshot(
        cls,
        state: ChatLoopState,
        pending_tool_calls: tuple[StepToolCall, ...],
        pause_type: str,
    ) -> None:
        if pause_type == "input":
            if pending_tool_calls:
                raise ValueError("input pause cannot contain pending tools")
            if state.messages:
                tail = state.messages[-1]
                if tail.get("role") == "assistant" and tail.get("tool_calls"):
                    raise ValueError("input pause cannot leave unresolved tool calls")
            return
        if not pending_tool_calls or not state.messages:
            raise ValueError("approval pause requires pending tools")
        assistant = state.messages[-1]
        if assistant.get("role") != "assistant":
            raise ValueError("approval pause must end at assistant tool calls")
        message_calls = assistant.get("tool_calls")
        if not isinstance(message_calls, list) or len(message_calls) != len(pending_tool_calls):
            raise ValueError("pending tools do not match assistant message")
        pending_ids = [call.id for call in pending_tool_calls]
        if len(set(pending_ids)) != len(pending_ids):
            raise ValueError("pending tool ids must be unique")
        if any(
            message.get("role") == "tool" and str(message.get("tool_call_id", "")) in pending_ids
            for message in state.messages[:-1]
        ):
            raise ValueError("pending tool already has a response")
        if any(entry.tool_call_id in pending_ids for entry in state.ledger.entries):
            raise ValueError("pending tool already has a ledger result")
        for message_call, pending in zip(message_calls, pending_tool_calls, strict=True):
            if not isinstance(message_call, dict):
                raise ValueError("invalid assistant tool call")
            function = message_call.get("function")
            if (
                not isinstance(function, dict)
                or str(message_call.get("id", "")) != pending.id
                or str(function.get("name", "")) != pending.name
                or cls._canonical_arguments(function.get("arguments"))
                != cls._canonical_arguments(pending.arguments)
            ):
                raise ValueError("pending tools do not match assistant message")

    @staticmethod
    def _baseline(state: ChatLoopState) -> _UsageBaseline:
        return _UsageBaseline(
            state.prompt_tokens_total,
            state.completion_tokens_total,
            state.cached_tokens_total,
            state.budget_spent_cny,
            len(state.ledger.entries),
            len(state.messages),
        )

    def _usage(self, state: ChatLoopState, baseline: _UsageBaseline) -> RunUsage:
        input_tokens = max(0, state.prompt_tokens_total - baseline.input_tokens)
        output_tokens = max(0, state.completion_tokens_total - baseline.output_tokens)
        return RunUsage(
            provider=self._provider,
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=max(0, state.cached_tokens_total - baseline.cached_tokens),
            total_tokens=input_tokens + output_tokens,
            cost_cny=max(0.0, state.budget_spent_cny - baseline.cost_cny),
        )

    @staticmethod
    def _tools(
        state: ChatLoopState,
        *,
        baseline: _UsageBaseline,
        pending_approval: bool = False,
        pending_tool_calls: tuple[StepToolCall, ...] = (),
        approval_rejected: bool = False,
    ) -> tuple[ToolExecution, ...]:
        calls: list[tuple[int, str, str, dict[str, Any]]] = []
        step = 0
        for index, message in enumerate(state.messages):
            if message.get("role") != "assistant":
                continue
            step += 1
            if index < baseline.message_count:
                continue
            for call in message.get("tool_calls", []):
                function = call.get("function", {})
                try:
                    request = json.loads(function.get("arguments") or "{}")
                except (TypeError, json.JSONDecodeError):
                    request = {}
                if not isinstance(request, dict):
                    request = {}
                calls.append(
                    (step, str(call.get("id", "")), str(function.get("name", "")), request)
                )
        projected_call_ids = {call_id for _, call_id, _, _ in calls}
        for call in pending_tool_calls:
            if call.id in projected_call_ids:
                continue
            try:
                request = call.parsed_args
            except ValueError:
                request = {}
            calls.append((state.step, call.id, call.name, request))

        tools: list[ToolExecution] = []
        ledger_by_call_id = {
            entry.tool_call_id: entry
            for entry in state.ledger.entries[baseline.ledger_count :]
            if entry.tool_call_id is not None
        }
        for call_step, call_id, call_name, request in calls:
            ledger = ledger_by_call_id.get(call_id)
            if ledger is not None and (
                ledger.tool_name != call_name or ledger.args_hash != args_hash_of(request)
            ):
                ledger = None
            success = bool(ledger is not None and ledger.success)
            status: Literal["completed", "failed", "approval_required"] = (
                "completed"
                if success
                else "approval_required"
                if pending_approval and ledger is None
                else "failed"
            )
            tools.append(
                ToolExecution(
                    tool_call_id=call_id,
                    tool_name=call_name,
                    request=_freeze_mapping(request),
                    status=status,
                    digest=(
                        ledger.digest
                        if ledger is not None
                        else "Approval required."
                        if status == "approval_required"
                        else "Tool execution failed."
                    ),
                    cache_key=ledger.cache_key if ledger is not None else None,
                    error_code=(
                        None
                        if status != "failed"
                        else "approval_rejected"
                        if approval_rejected
                        else "tool_error"
                    ),
                    error_message=None if status != "failed" else "Tool execution failed.",
                    step=ledger.step if ledger is not None else call_step,
                )
            )
        return tuple(tools)

    async def _emit_control_event(
        self,
        command: ExecuteChatRun,
        events: list[RunEvent],
        seq_counter: SeqCounter,
        kind: str,
        step: int,
        payload: Mapping[str, Any],
        publish: Callable[[RunEvent], Awaitable[None]],
    ) -> None:
        event = RunEvent(
            command.run_id,
            command.attempt_id,
            kind,
            seq_counter.next(),
            step,
            _freeze_mapping(copy.deepcopy(payload)),
        )
        await publish(event)

    def _failed(
        self,
        command: ExecuteChatRun,
        error_code: Any,
        message: str,
        retryable: bool,
        state: ChatLoopState,
        events: list[RunEvent],
        emitted_tokens: list[str],
        baseline: _UsageBaseline,
        pending_tool_calls: tuple[StepToolCall, ...] = (),
        approval_rejected: bool = False,
    ) -> FailedResult:
        state_text = _final_text(state)
        streamed = "".join(emitted_tokens)
        partial = state_text if len(state_text) >= len(streamed) else streamed
        return FailedResult(
            command.run_id,
            command.attempt_id,
            command.session_id,
            error_code,
            message,
            retryable,
            partial,
            self._usage(state, baseline),
            self._tools(
                state,
                baseline=baseline,
                pending_tool_calls=pending_tool_calls,
                approval_rejected=approval_rejected,
            ),
            tuple(events),
        )


__all__ = [
    "ChatRunExecutor",
    "CompletedResult",
    "EventSink",
    "ExecuteChatRun",
    "ExecutionResult",
    "FailedResult",
    "PauseDirective",
    "PauseResult",
    "RunEvent",
    "RunUsage",
    "ToolExecution",
]

from __future__ import annotations

import ast
import asyncio
import hashlib
import hmac
import json
from dataclasses import FrozenInstanceError
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from app.chatloop.continuation import ContinuationV1, PendingActionV1
from app.chatloop.contracts import ToolResult
from app.chatloop.gates import GateConfig
from app.chatloop.run_executor import (
    ChatRunExecutor,
    CompletedResult,
    ExecuteChatRun,
    FailedResult,
    PauseDirective,
    PauseResult,
)
from app.chatloop.state import ChatLoopState
from app.services.llm_step import StepDelta, StepResult, StepToolCall

TEST_CONTINUATION_SECRET = b"s" * 32


def _signed_test_continuation(
    command: ExecuteChatRun,
    *,
    user_id: str,
    pause_type: str,
    state: dict[str, Any],
    pending_tool_calls: list[dict[str, Any]] | None = None,
    key_id: str = "default",
) -> dict[str, Any]:
    restored = ChatLoopState.model_validate(state)
    restored.user_id = user_id
    restored.session_id = str(command.session_id)
    restored.request_id = str(command.run_id)
    action = PendingActionV1(
        pause_type=pause_type,
        tool_name="ask_user" if pause_type == "input" else "approve_tools",
        request={"question": "resume"},
        pending_tool_calls=tuple(
            StepToolCall.model_validate(call) for call in (pending_tool_calls or [])
        ),
    )
    draft = ContinuationV1.from_state(restored, action, key_id=key_id, signature="0" * 64)
    body = draft.body.model_dump(mode="json")
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return {
        **draft.model_dump(mode="json"),
        "signature": hmac.new(TEST_CONTINUATION_SECRET, encoded, hashlib.sha256).hexdigest(),
    }


class _ScriptedLLM:
    def __init__(
        self,
        steps: list[StepResult],
        *,
        error: BaseException | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> None:
        self.steps = list(steps)
        self.error = error
        self.cancel_event = cancel_event
        self.messages: list[list[dict[str, Any]]] = []

    async def stream_step(self, *, messages: Any, on_delta: Any, **_: Any) -> StepResult:
        self.messages.append(messages)
        if self.error is not None:
            raise self.error
        step = self.steps.pop(0)
        if step.content:
            midpoint = max(1, len(step.content) // 2)
            await on_delta(StepDelta(kind="content", text=step.content[:midpoint]))
            if self.cancel_event is not None:
                self.cancel_event.set()
            await on_delta(StepDelta(kind="content", text=step.content[midpoint:]))
        return step


class _Hub:
    def schemas_for_llm(self) -> list[dict[str, Any]]:
        return []

    async def dispatch(self, calls: Any, state: Any) -> list[Any]:
        raise AssertionError("no tool call expected")


class _RecordingHub:
    def __init__(self) -> None:
        self.calls: list[StepToolCall] = []
        self.user_ids: list[str] = []

    def schemas_for_llm(self) -> list[dict[str, Any]]:
        return []

    async def dispatch(self, calls: list[StepToolCall], state: Any) -> list[ToolResult]:
        self.calls.extend(calls)
        self.user_ids.append(state.user_id)
        results = []
        for call in calls:
            args = call.parsed_args
            state.ledger.record(
                step=state.step,
                tool_call_id=call.id,
                tool_name=call.name,
                args=args,
                digest="approved",
                success=True,
            )
            results.append(
                ToolResult(
                    tool_name=call.name,
                    args=args,
                    success=True,
                    output={"approved": True},
                    latency_ms=1,
                )
            )
        return results


class _PauseAt:
    def __init__(self, phase: str, pause_type: str) -> None:
        self.phase = phase
        self.pause_type = pause_type

    async def check(self, *, phase: str, state: Any, tool_calls: Any = ()) -> Any:
        if phase == self.phase:
            return PauseDirective(
                pause_type=self.pause_type,
                request={"question": "continue?", "nested": {"choices": ["yes", "no"]}},
            )
        return None


def _step(text: str, *, input_tokens: int = 11, output_tokens: int = 7) -> StepResult:
    return StepResult(
        content=text,
        tool_calls=[],
        finish_reason="stop",
        prompt_tokens=input_tokens,
        completion_tokens=output_tokens,
        cached_tokens=3,
        cost_cny=0.0123,
    )


def _command(
    *, prompt: str = "鍒嗘瀽鑼呭彴", history: tuple[dict[str, Any], ...] = ()
) -> ExecuteChatRun:
    return ExecuteChatRun(
        run_id=uuid4(),
        attempt_id=uuid4(),
        session_id=uuid4(),
        prompt=prompt,
        history=history,
        continuation=None,
    )


def _components(llm: Any) -> Any:
    return SimpleNamespace(
        llm=llm,
        tool_hub=_Hub(),
        gate_cfg=GateConfig(),
        skill_listing="",
        system_prompt="financial assistant",
    )


def test_public_approval_snapshot_round_trips_through_standard_continuation() -> None:
    command = _command(prompt="place it")
    call = StepToolCall(id="call-1", name="place_order", arguments='{"quantity":1}')

    continuation = ChatRunExecutor.approval_snapshot(
        command,
        user_id="user-1",
        pending_tool_calls=(call,),
        continuation_secret=TEST_CONTINUATION_SECRET,
        continuation_key_id="default",
    )
    executor = ChatRunExecutor(
        user_id="user-1",
        continuation_secret=TEST_CONTINUATION_SECRET,
        components=_components(_ScriptedLLM([_step("done")])),
        event_sink=None,
        cancel_event=asyncio.Event(),
        provider="scripted",
        model="scripted-v1",
    )
    resumed = ExecuteChatRun(
        command.run_id,
        uuid4(),
        command.session_id,
        '{"approved":true}',
        (),
        continuation,
    )

    state, pending, _prompt, decision = executor._initial_state(resumed, continuation)

    assert decision == "approve"
    assert pending == (call,)
    assert state.messages[-1]["tool_calls"][0]["id"] == "call-1"


async def test_completed_contract_usage_event_order_and_immutable_inputs() -> None:
    history_dict = {"role": "assistant", "content": {"nested": ["old"]}}
    history = (history_dict,)
    command = _command(history=history)
    events = []

    async def collect(event: Any) -> None:
        events.append(event)

    llm = _ScriptedLLM([_step("answer")])
    executor = ChatRunExecutor(
        user_id=uuid4(),
        continuation_secret=TEST_CONTINUATION_SECRET,
        components=_components(llm),
        event_sink=collect,
        cancel_event=asyncio.Event(),
        provider="scripted",
        model="scripted-v1",
    )

    result = await executor.execute(command)

    assert isinstance(result, CompletedResult)
    assert result.final_text == "answer"
    assert result.usage.input_tokens == 11
    assert result.usage.output_tokens == 7
    assert result.usage.cached_tokens == 3
    assert result.usage.total_tokens == 18
    assert result.usage.cost_cny == pytest.approx(0.0123)
    assert [event.kind for event in events] == [
        "step_start",
        "token",
        "token",
        "cost_update",
        "done",
    ]
    assert [event.seq for event in events] == [1, 2, 3, 4, 5]
    assert result.events == tuple(events)
    assert command.history == history
    assert history_dict == {"role": "assistant", "content": {"nested": ["old"]}}
    with pytest.raises(TypeError):
        events[0].payload["nested"] = "mutate"
    with pytest.raises(FrozenInstanceError):
        result.final_text = "mutate"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("phase", "pause_type"),
    [("before_model", "input"), ("before_tools", "approval")],
)
async def test_pause_contract_is_serializable_bounded_and_resumable(
    phase: str, pause_type: str
) -> None:
    call = StepToolCall(id="call-1", name="dangerous_tool", arguments='{"x": 1}')
    first_step = StepResult(
        content="",
        tool_calls=[call],
        finish_reason="tool_calls",
        prompt_tokens=5,
        completion_tokens=2,
        cached_tokens=1,
        cost_cny=0.001,
    )
    llm = _ScriptedLLM([first_step])
    controller = _PauseAt(phase, pause_type)
    trusted_user = uuid4()
    executor = ChatRunExecutor(
        user_id=trusted_user,
        continuation_secret=TEST_CONTINUATION_SECRET,
        components=_components(llm),
        event_sink=lambda _event: asyncio.sleep(0),
        cancel_event=asyncio.Event(),
        pause_controller=controller,
    )

    paused = await executor.execute(_command())

    assert isinstance(paused, PauseResult)
    assert paused.pause_type == pause_type
    if pause_type == "approval":
        assert paused.tools[0].status == "approval_required"
        assert paused.tools[0].success is False
        assert paused.tools[0].digest == "Approval required."
    encoded = paused.continuation_json()
    assert len(encoded.encode("utf-8")) <= ChatRunExecutor.MAX_CONTINUATION_BYTES
    assert "connection" not in encoded and "client" not in encoded

    resume = ExecuteChatRun(
        run_id=paused.run_id,
        attempt_id=uuid4(),
        session_id=paused.session_id,
        prompt=(
            json.dumps({"approved": True, "text": "yes"}) if pause_type == "approval" else "yes"
        ),
        history=(),
        continuation=paused.thaw_continuation(),
    )
    resumed_llm = _ScriptedLLM([_step("resumed", input_tokens=13, output_tokens=3)])
    resumed_hub = _RecordingHub() if pause_type == "approval" else _Hub()
    resumed_executor = ChatRunExecutor(
        user_id=trusted_user,
        continuation_secret=TEST_CONTINUATION_SECRET,
        components=SimpleNamespace(
            **{
                **vars(_components(resumed_llm)),
                "tool_hub": resumed_hub,
            }
        ),
        event_sink=lambda _event: asyncio.sleep(0),
        cancel_event=asyncio.Event(),
    )
    result = await resumed_executor.execute(resume)
    assert isinstance(result, CompletedResult)
    assert result.final_text == "resumed"
    assert any(message.get("content") == "yes" for message in resumed_llm.messages[0])
    assert result.usage.input_tokens == 13
    assert result.usage.output_tokens == 3
    if pause_type == "approval":
        assert [call.id for call in resumed_hub.calls] == ["call-1"]
        roles = [message.get("role") for message in resumed_llm.messages[0]]
        assistant_index = roles.index("assistant")
        assert roles[assistant_index + 1] == "tool"


async def test_rejected_approval_closes_protocol_without_dispatch() -> None:
    call = StepToolCall(id="call-reject", name="dangerous_tool", arguments="{}")
    first_step = StepResult(
        content="",
        tool_calls=[call],
        finish_reason="tool_calls",
        prompt_tokens=5,
        completion_tokens=2,
        cached_tokens=0,
        cost_cny=0.0,
    )
    trusted_user = uuid4()
    paused = await ChatRunExecutor(
        user_id=trusted_user,
        continuation_secret=TEST_CONTINUATION_SECRET,
        components=_components(_ScriptedLLM([first_step])),
        event_sink=lambda _event: asyncio.sleep(0),
        cancel_event=asyncio.Event(),
        pause_controller=_PauseAt("before_tools", "approval"),
    ).execute(_command())
    assert isinstance(paused, PauseResult)

    hub = _RecordingHub()
    llm = _ScriptedLLM([_step("not executed")])
    result = await ChatRunExecutor(
        user_id=trusted_user,
        continuation_secret=TEST_CONTINUATION_SECRET,
        components=SimpleNamespace(**{**vars(_components(llm)), "tool_hub": hub}),
        event_sink=lambda _event: asyncio.sleep(0),
        cancel_event=asyncio.Event(),
    ).execute(
        ExecuteChatRun(
            paused.run_id,
            uuid4(),
            paused.session_id,
            json.dumps({"approved": False, "text": "no"}),
            (),
            paused.thaw_continuation(),
        )
    )

    assert isinstance(result, CompletedResult)
    assert hub.calls == []
    roles = [message.get("role") for message in llm.messages[0]]
    assistant_index = roles.index("assistant")
    assert roles[assistant_index + 1] == "tool"
    assert result.tools[0].status == "failed"
    assert result.tools[0].error_code == "approval_rejected"


async def test_per_call_approval_decisions_preserve_assistant_tool_result_order() -> None:
    calls = (
        StepToolCall(id="call-a", name="dangerous_tool", arguments='{"n":1}'),
        StepToolCall(id="call-b", name="dangerous_tool", arguments='{"n":2}'),
    )
    command = _command(prompt="batch")
    user_id = str(uuid4())
    continuation = ChatRunExecutor.approval_snapshot(
        command,
        user_id=user_id,
        pending_tool_calls=calls,
        continuation_secret=TEST_CONTINUATION_SECRET,
        continuation_key_id="default",
    )
    hub = _RecordingHub()
    llm = _ScriptedLLM([_step("mixed done")])

    result = await ChatRunExecutor(
        user_id=user_id,
        continuation_secret=TEST_CONTINUATION_SECRET,
        components=SimpleNamespace(**{**vars(_components(llm)), "tool_hub": hub}),
        event_sink=lambda _event: asyncio.sleep(0),
        cancel_event=asyncio.Event(),
    ).execute(
        ExecuteChatRun(
            command.run_id,
            uuid4(),
            command.session_id,
            json.dumps({"decisions": {"call-a": True, "call-b": False}}),
            (),
            continuation,
        )
    )

    assert isinstance(result, CompletedResult)
    assert [call.id for call in hub.calls] == ["call-a"]
    tool_messages = [message for message in llm.messages[0] if message.get("role") == "tool"]
    assert [message["tool_call_id"] for message in tool_messages] == ["call-a", "call-b"]
    assert [tool.status for tool in result.tools] == ["completed", "failed"]


async def test_conflicting_batch_and_legacy_approval_decisions_fail_closed() -> None:
    call = StepToolCall(id="call-a", name="dangerous_tool", arguments="{}")
    command = _command(prompt="batch")
    user_id = str(uuid4())
    continuation = ChatRunExecutor.approval_snapshot(
        command,
        user_id=user_id,
        pending_tool_calls=(call,),
        continuation_secret=TEST_CONTINUATION_SECRET,
        continuation_key_id="default",
    )

    result = await ChatRunExecutor(
        user_id=user_id,
        continuation_secret=TEST_CONTINUATION_SECRET,
        components=_components(_ScriptedLLM([_step("must not run")])),
        event_sink=lambda _event: asyncio.sleep(0),
        cancel_event=asyncio.Event(),
    ).execute(
        ExecuteChatRun(
            command.run_id,
            uuid4(),
            command.session_id,
            json.dumps({"approved": True, "decisions": {"call-a": False}}),
            (),
            continuation,
        )
    )

    assert isinstance(result, FailedResult)
    assert result.error_code == "invalid_continuation"


async def test_mixed_approval_rejects_wrong_approved_hub_result_count() -> None:
    calls = (
        StepToolCall(id="call-a", name="dangerous_tool", arguments="{}"),
        StepToolCall(id="call-b", name="dangerous_tool", arguments="{}"),
    )
    command = _command(prompt="batch")
    user_id = str(uuid4())
    continuation = ChatRunExecutor.approval_snapshot(
        command,
        user_id=user_id,
        pending_tool_calls=calls,
        continuation_secret=TEST_CONTINUATION_SECRET,
        continuation_key_id="default",
    )

    class _WrongCountHub(_RecordingHub):
        async def dispatch(self, calls: list[StepToolCall], state: Any) -> list[ToolResult]:
            await super().dispatch(calls, state)
            return []

    result = await ChatRunExecutor(
        user_id=user_id,
        continuation_secret=TEST_CONTINUATION_SECRET,
        components=SimpleNamespace(
            **{
                **vars(_components(_ScriptedLLM([_step("must not run")]))),
                "tool_hub": _WrongCountHub(),
            }
        ),
        event_sink=lambda _event: asyncio.sleep(0),
        cancel_event=asyncio.Event(),
    ).execute(
        ExecuteChatRun(
            command.run_id,
            uuid4(),
            command.session_id,
            json.dumps({"decisions": {"call-a": True, "call-b": False}}),
            (),
            continuation,
        )
    )

    assert isinstance(result, FailedResult)
    assert result.error_code == "tool_error"


async def test_input_resume_does_not_project_historical_tools_as_attempt_failures() -> None:
    command = _command()
    trusted_user = str(uuid4())
    state = {
        "user_id": str(uuid4()),
        "session_id": str(command.session_id),
        "request_id": str(command.run_id),
        "step": 1,
        "messages": [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "old-call",
                        "type": "function",
                        "function": {"name": "old_tool", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "old-call", "content": "old"},
        ],
        "ledger": {
            "entries": [
                {
                    "step": 1,
                    "tool_call_id": "old-call",
                    "tool_name": "old_tool",
                    "args_hash": "44136fa355b3678a",
                    "digest": "old",
                    "success": True,
                }
            ]
        },
    }
    continuation = _signed_test_continuation(
        command, user_id=trusted_user, pause_type="input", state=state
    )
    result = await ChatRunExecutor(
        user_id=trusted_user,
        continuation_secret=TEST_CONTINUATION_SECRET,
        components=_components(_ScriptedLLM([_step("new answer")])),
        event_sink=lambda _event: asyncio.sleep(0),
        cancel_event=asyncio.Event(),
    ).execute(
        ExecuteChatRun(
            command.run_id,
            command.attempt_id,
            command.session_id,
            "new input",
            (),
            continuation,
        )
    )
    assert isinstance(result, CompletedResult)
    assert result.tools == ()


def test_tool_result_has_one_canonical_runtime_identity() -> None:
    from app.agents.schemas import ToolResult as LegacyToolResult

    assert LegacyToolResult is ToolResult


async def test_malformed_pending_arguments_fail_pause_as_strict_result() -> None:
    call = StepToolCall(id="malformed", name="dangerous_tool", arguments="{")
    result = await ChatRunExecutor(
        user_id="test-user",
        continuation_secret=TEST_CONTINUATION_SECRET,
        components=_components(
            _ScriptedLLM(
                [
                    StepResult(
                        content="",
                        tool_calls=[call],
                        finish_reason="tool_calls",
                        prompt_tokens=1,
                        completion_tokens=1,
                        cached_tokens=0,
                        cost_cny=0,
                    )
                ]
            )
        ),
        event_sink=lambda _event: asyncio.sleep(0),
        cancel_event=asyncio.Event(),
        pause_controller=_PauseAt("before_tools", "approval"),
    ).execute(_command())
    assert isinstance(result, FailedResult)
    assert result.error_code == "executor_error"


async def test_server_identity_overwrites_continuation_identity() -> None:
    user_id = uuid4()
    command = _command()
    state = {
        "user_id": str(uuid4()),
        "session_id": str(command.session_id),
        "request_id": str(command.run_id),
        "messages": [],
    }
    executor = ChatRunExecutor(
        components=_components(_ScriptedLLM([_step("ok")])),
        event_sink=lambda _event: asyncio.sleep(0),
        cancel_event=asyncio.Event(),
        pause_controller=_PauseAt("before_model", "input"),
        user_id=user_id,
        continuation_secret=TEST_CONTINUATION_SECRET,
    )
    continuation = _signed_test_continuation(
        command, user_id=str(user_id), pause_type="input", state=state
    )
    result = await executor.execute(
        ExecuteChatRun(
            command.run_id,
            command.attempt_id,
            command.session_id,
            "resume",
            (),
            continuation,
        )
    )
    assert isinstance(result, PauseResult)
    assert result.continuation["body"]["user_id"] == str(user_id)


async def test_model_error_and_cancel_are_structured_without_secret_leakage() -> None:
    secret = "sk-secret at C:\\private\\worker.py"
    failed = await ChatRunExecutor(
        user_id=uuid4(),
        continuation_secret=TEST_CONTINUATION_SECRET,
        components=_components(_ScriptedLLM([], error=RuntimeError(secret))),
        event_sink=lambda _event: asyncio.sleep(0),
        cancel_event=asyncio.Event(),
    ).execute(_command())
    assert isinstance(failed, FailedResult)
    assert failed.error_code == "model_error"
    assert secret not in failed.message
    assert "private" not in failed.message

    cancel = asyncio.Event()
    cancelled = await ChatRunExecutor(
        user_id=uuid4(),
        continuation_secret=TEST_CONTINUATION_SECRET,
        components=_components(_ScriptedLLM([_step("partial answer")], cancel_event=cancel)),
        event_sink=lambda _event: asyncio.sleep(0),
        cancel_event=cancel,
    ).execute(_command())
    assert isinstance(cancelled, FailedResult)
    assert cancelled.error_code == "cancelled"
    assert cancelled.partial_text


async def test_cancel_closes_stream_and_oversized_continuation_is_classified() -> None:
    cancel = asyncio.Event()
    closed = asyncio.Event()

    class _GeneratorLLM:
        async def stream_step(self, *, on_delta: Any, **_: Any) -> StepResult:
            async def chunks() -> Any:
                try:
                    yield "first"
                    cancel.set()
                    yield "second"
                finally:
                    closed.set()

            stream = chunks()
            try:
                async for chunk in stream:
                    await on_delta(StepDelta(kind="content", text=chunk))
            finally:
                await stream.aclose()
            raise AssertionError("cancel should interrupt the stream")

    cancelled = await ChatRunExecutor(
        user_id=uuid4(),
        continuation_secret=TEST_CONTINUATION_SECRET,
        components=_components(_GeneratorLLM()),
        event_sink=lambda _event: asyncio.sleep(0),
        cancel_event=cancel,
    ).execute(_command())
    assert isinstance(cancelled, FailedResult)
    assert cancelled.error_code == "cancelled"
    assert closed.is_set()

    command = _command()
    oversized = ExecuteChatRun(
        command.run_id,
        command.attempt_id,
        command.session_id,
        command.prompt,
        (),
        {"state": {"blob": "x" * (ChatRunExecutor.MAX_CONTINUATION_BYTES + 1)}},
    )
    failed = await ChatRunExecutor(
        user_id=uuid4(),
        continuation_secret=TEST_CONTINUATION_SECRET,
        components=_components(_ScriptedLLM([_step("unused")])),
        event_sink=lambda _event: asyncio.sleep(0),
        cancel_event=asyncio.Event(),
    ).execute(oversized)
    assert isinstance(failed, FailedResult)
    assert failed.error_code == "continuation_too_large"


async def test_dependency_and_sink_failures_still_return_strict_result_union() -> None:
    async def broken_sink(_event: Any) -> None:
        raise RuntimeError("redis secret")

    completed = await ChatRunExecutor(
        user_id=uuid4(),
        continuation_secret=TEST_CONTINUATION_SECRET,
        components=_components(_ScriptedLLM([_step("answer")])),
        event_sink=broken_sink,
        cancel_event=asyncio.Event(),
    ).execute(_command())
    assert isinstance(completed, CompletedResult)
    assert completed.final_text == "answer"

    def broken_factory(_emit: Any, _counter: Any) -> Any:
        raise RuntimeError("factory secret")

    failed = await ChatRunExecutor(
        user_id=uuid4(),
        continuation_secret=TEST_CONTINUATION_SECRET,
        components_factory=broken_factory,
        event_sink=lambda _event: asyncio.sleep(0),
        cancel_event=asyncio.Event(),
    ).execute(_command())
    assert isinstance(failed, FailedResult)
    assert failed.error_code == "executor_error"
    assert "secret" not in failed.message


async def test_force_conclude_model_failure_is_model_error() -> None:
    components = _components(_ScriptedLLM([], error=RuntimeError("force secret")))
    components.gate_cfg = GateConfig(max_steps=0)
    failed = await ChatRunExecutor(
        user_id=uuid4(),
        continuation_secret=TEST_CONTINUATION_SECRET,
        components=components,
        event_sink=lambda _event: asyncio.sleep(0),
        cancel_event=asyncio.Event(),
    ).execute(_command())
    assert isinstance(failed, FailedResult)
    assert failed.error_code == "model_error"
    assert "secret" not in failed.message


def test_executor_import_graph_is_transport_free() -> None:
    app_root = Path(__file__).parents[3] / "app"
    pending = ["app.chatloop.run_executor"]
    visited: set[str] = set()
    imported: set[str] = set()
    while pending:
        module = pending.pop()
        if module in visited:
            continue
        visited.add(module)
        path = app_root.parent / Path(*module.split(".")).with_suffix(".py")
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        direct = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        direct.update(
            node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        )
        imported.update(direct)
        pending.extend(name for name in direct if name.startswith("app."))
    forbidden = ("sqlalchemy", "celery", "fastapi", "chat_task", "redis", "event_bus")
    assert not any(any(part in module.lower() for part in forbidden) for module in imported)


def test_worker_wiring_exposes_run_executor_transport_boundary() -> None:
    path = Path(__file__).parents[3] / "app" / "chatloop" / "worker_wiring.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    builder = functions["build_run_executor"]
    defaults = dict(
        zip(
            (argument.arg for argument in builder.args.kwonlyargs),
            builder.args.kw_defaults,
            strict=True,
        )
    )
    assert defaults["continuation_secret"] is None
    assert defaults["provider"] is None


async def _approval_pause_with_calls(calls: list[StepToolCall]) -> PauseResult:
    paused = await ChatRunExecutor(
        user_id="test-user",
        continuation_secret=TEST_CONTINUATION_SECRET,
        components=_components(
            _ScriptedLLM(
                [
                    StepResult(
                        content="",
                        tool_calls=calls,
                        finish_reason="tool_calls",
                        prompt_tokens=1,
                        completion_tokens=1,
                        cached_tokens=0,
                        cost_cny=0,
                    )
                ]
            )
        ),
        event_sink=lambda _event: asyncio.sleep(0),
        cancel_event=asyncio.Event(),
        pause_controller=_PauseAt("before_tools", "approval"),
    ).execute(_command())
    assert isinstance(paused, PauseResult)
    return paused


@pytest.mark.parametrize(
    "mutation",
    [
        "empty_messages",
        "id",
        "name",
        "args",
        "pause_type",
        "input_with_pending",
        "existing_response",
        "existing_ledger",
        "duplicate_id",
    ],
)
async def test_forged_approval_continuation_is_rejected_without_dispatch(
    mutation: str,
) -> None:
    paused = await _approval_pause_with_calls(
        [StepToolCall(id="safe-id", name="dangerous_tool", arguments='{"x":1}')]
    )
    continuation = paused.thaw_continuation()
    body = continuation["body"]
    action = body["pending_action"]
    if mutation == "empty_messages":
        body["messages"] = []
    elif mutation == "id":
        action["pending_tool_calls"][0]["id"] = "forged"
    elif mutation == "name":
        action["pending_tool_calls"][0]["name"] = "other_tool"
    elif mutation == "args":
        action["pending_tool_calls"][0]["arguments"] = '{"x":2}'
    elif mutation == "pause_type":
        action["pause_type"] = "other"
    elif mutation == "input_with_pending":
        action["pause_type"] = "input"
    elif mutation == "existing_response":
        body["messages"].insert(-1, {"role": "tool", "tool_call_id": "safe-id", "content": "done"})
    elif mutation == "existing_ledger":
        body["tool_ledger"].append(
            {
                "step": 1,
                "tool_call_id": "safe-id",
                "tool_name": "dangerous_tool",
                "args_hash": "hash",
                "digest": "done",
                "success": True,
            }
        )
    else:
        action["pending_tool_calls"].append(dict(action["pending_tool_calls"][0]))
        body["messages"][-1]["tool_calls"].append(dict(body["messages"][-1]["tool_calls"][0]))
    hub = _RecordingHub()
    result = await ChatRunExecutor(
        user_id=uuid4(),
        continuation_secret=TEST_CONTINUATION_SECRET,
        components=SimpleNamespace(
            **{**vars(_components(_ScriptedLLM([_step("unused")]))), "tool_hub": hub}
        ),
        event_sink=lambda _event: asyncio.sleep(0),
        cancel_event=asyncio.Event(),
    ).execute(
        ExecuteChatRun(
            paused.run_id,
            uuid4(),
            paused.session_id,
            json.dumps({"approved": True}),
            (),
            continuation,
        )
    )
    assert isinstance(result, FailedResult)
    assert result.error_code == "invalid_continuation"
    assert hub.calls == []


@pytest.mark.parametrize(
    ("bad_value", "expected_code"),
    [
        (float("nan"), "invalid_continuation"),
        (float("inf"), "invalid_continuation"),
        (2**80, "invalid_continuation"),
        (b"bytes", "invalid_continuation"),
        ("x" * (ChatRunExecutor.MAX_CONTINUATION_BYTES + 1), "continuation_too_large"),
        ([None] * 10_001, "continuation_too_large"),
        (["1234567890"] * 6_000, "continuation_too_large"),
    ],
    ids=[
        "nan",
        "inf",
        "huge-int",
        "bytes",
        "huge-string",
        "huge-list",
        "aggregate-bytes",
    ],
)
async def test_hostile_continuation_preflight_is_bounded(
    bad_value: Any, expected_code: str
) -> None:
    command = _command()
    result = await ChatRunExecutor(
        user_id=uuid4(),
        continuation_secret=TEST_CONTINUATION_SECRET,
        components=_components(_ScriptedLLM([_step("unused")])),
        event_sink=lambda _event: asyncio.sleep(0),
        cancel_event=asyncio.Event(),
    ).execute(
        ExecuteChatRun(
            command.run_id,
            command.attempt_id,
            command.session_id,
            "resume",
            (),
            {"pause_type": "input", "state": bad_value, "pending_tool_calls": []},
        )
    )
    assert isinstance(result, FailedResult)
    assert result.error_code == expected_code


async def test_non_string_key_and_excessive_depth_are_rejected() -> None:
    command = _command()
    nested: Any = {}
    for _ in range(70):
        nested = {"x": nested}
    cases = [
        ({1: "bad"}, "invalid_continuation"),
        (
            {"pause_type": "input", "state": nested, "pending_tool_calls": []},
            "continuation_too_large",
        ),
    ]
    for continuation, expected in cases:
        result = await ChatRunExecutor(
            user_id=uuid4(),
            continuation_secret=TEST_CONTINUATION_SECRET,
            components=_components(_ScriptedLLM([_step("unused")])),
            event_sink=lambda _event: asyncio.sleep(0),
            cancel_event=asyncio.Event(),
        ).execute(
            ExecuteChatRun(
                command.run_id,
                command.attempt_id,
                command.session_id,
                "resume",
                (),
                continuation,  # type: ignore[arg-type]
            )
        )
        assert isinstance(result, FailedResult)
        assert result.error_code == expected


async def test_valid_continuation_is_canonicalized_without_deepcopy() -> None:
    class _NoDeepcopyDict(dict[str, Any]):
        def __deepcopy__(self, _memo: Any) -> Any:
            raise AssertionError("continuation must be preflighted, not deep-copied")

    command = _command()
    trusted_user = str(uuid4())
    continuation = _NoDeepcopyDict(
        _signed_test_continuation(
            command,
            user_id=trusted_user,
            pause_type="input",
            state={
                "user_id": "forged",
                "session_id": str(command.session_id),
                "request_id": str(command.run_id),
                "messages": [],
            },
        )
    )
    result = await ChatRunExecutor(
        user_id=trusted_user,
        continuation_secret=TEST_CONTINUATION_SECRET,
        components=_components(_ScriptedLLM([_step("ok")])),
        event_sink=lambda _event: asyncio.sleep(0),
        cancel_event=asyncio.Event(),
    ).execute(
        ExecuteChatRun(
            command.run_id,
            command.attempt_id,
            command.session_id,
            "resume",
            (),
            continuation,
        )
    )
    assert isinstance(result, CompletedResult)


async def test_pause_result_nested_data_is_immutable_and_has_controlled_json() -> None:
    paused = await _approval_pause_with_calls(
        [StepToolCall(id="immutable", name="dangerous_tool", arguments="{}")]
    )
    with pytest.raises(TypeError):
        paused.continuation["body"]["messages"] = []  # type: ignore[index]
    with pytest.raises(TypeError):
        dict.__setitem__(paused.continuation, "pause_type", "forged")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        paused.request["nested"]["choices"][0] = "mutate"  # type: ignore[index]
    thawed = paused.thaw_continuation()
    thawed["body"]["messages"].clear()
    assert paused.continuation["body"]["messages"]
    assert (
        json.loads(paused.continuation_json())["body"]["pending_action"]["pause_type"] == "approval"
    )


async def test_reference_date_and_provider_are_injected() -> None:
    llm = _ScriptedLLM([_step("ok")])
    result = await ChatRunExecutor(
        user_id=uuid4(),
        continuation_secret=TEST_CONTINUATION_SECRET,
        components=_components(llm),
        event_sink=lambda _event: asyncio.sleep(0),
        cancel_event=asyncio.Event(),
        reference_date=date(2025, 1, 2),
        provider="scripted-provider",
    ).execute(_command())
    assert isinstance(result, CompletedResult)
    assert result.usage.provider == "scripted-provider"
    assert "2025-01-02" in str(llm.messages[0])


async def test_tool_projection_matches_call_id_under_reverse_mixed_completion() -> None:
    calls = [
        StepToolCall(id="a", name="same_tool", arguments='{"x":1}'),
        StepToolCall(id="b", name="same_tool", arguments='{"x":2}'),
        StepToolCall(id="c", name="same_tool", arguments='{"x":3}'),
    ]

    class _ReverseHub(_RecordingHub):
        async def dispatch(self, incoming: list[StepToolCall], state: Any) -> list[ToolResult]:
            outcomes = {"a": True, "b": False, "c": True}
            for call in reversed(incoming):
                state.ledger.record(
                    step=state.step,
                    tool_call_id=call.id,
                    tool_name=call.name,
                    args=call.parsed_args,
                    digest=f"digest-{call.id}",
                    success=outcomes[call.id],
                )
            return [
                ToolResult(
                    tool_name=call.name,
                    args=call.parsed_args,
                    success=outcomes[call.id],
                    output={} if outcomes[call.id] else None,
                    error=None if outcomes[call.id] else "failed",
                    latency_ms=1,
                )
                for call in incoming
            ]

    first = StepResult(
        content="",
        tool_calls=calls,
        finish_reason="tool_calls",
        prompt_tokens=1,
        completion_tokens=1,
        cached_tokens=0,
        cost_cny=0,
    )
    result = await ChatRunExecutor(
        user_id=uuid4(),
        continuation_secret=TEST_CONTINUATION_SECRET,
        components=SimpleNamespace(
            **{
                **vars(_components(_ScriptedLLM([first, _step("done")]))),
                "tool_hub": _ReverseHub(),
            }
        ),
        event_sink=lambda _event: asyncio.sleep(0),
        cancel_event=asyncio.Event(),
    ).execute(_command())
    assert isinstance(result, CompletedResult)
    assert [
        (tool.tool_call_id, tool.status, tool.digest, dict(tool.request)) for tool in result.tools
    ] == [
        ("a", "completed", "digest-a", {"x": 1}),
        ("b", "failed", "digest-b", {"x": 2}),
        ("c", "completed", "digest-c", {"x": 3}),
    ]


async def test_fresh_duplicate_tool_call_ids_fail_before_dispatch() -> None:
    calls = [
        StepToolCall(id="dup", name="same_tool", arguments='{"x":1}'),
        StepToolCall(id="dup", name="same_tool", arguments='{"x":2}'),
    ]
    first = StepResult(
        content="",
        tool_calls=calls,
        finish_reason="tool_calls",
        prompt_tokens=1,
        completion_tokens=1,
        cached_tokens=0,
        cost_cny=0,
    )
    hub = _RecordingHub()
    result = await ChatRunExecutor(
        user_id=uuid4(),
        continuation_secret=TEST_CONTINUATION_SECRET,
        components=SimpleNamespace(**{**vars(_components(_ScriptedLLM([first]))), "tool_hub": hub}),
        event_sink=lambda _event: asyncio.sleep(0),
        cancel_event=asyncio.Event(),
    ).execute(_command())
    assert isinstance(result, FailedResult)
    assert result.error_code == "tool_error"
    assert hub.calls == []


@pytest.mark.parametrize("cancel_before_dispatch", [False, True])
async def test_approval_hard_failure_keeps_all_pending_tool_audit(
    cancel_before_dispatch: bool,
) -> None:
    calls = [
        StepToolCall(id="p1", name="same_tool", arguments='{"x":1}'),
        StepToolCall(id="p2", name="same_tool", arguments='{"x":2}'),
    ]
    paused = await _approval_pause_with_calls(calls)

    class _PartialHardFailureHub(_RecordingHub):
        async def dispatch(self, incoming: list[StepToolCall], state: Any) -> list[ToolResult]:
            state.ledger.record(
                step=state.step,
                tool_call_id="p2",
                tool_name="same_tool",
                args={"x": 2},
                digest="second-complete",
                success=True,
            )
            raise RuntimeError("hard dispatch failure")

    cancel = asyncio.Event()
    if cancel_before_dispatch:
        cancel.set()
    result = await ChatRunExecutor(
        user_id="test-user",
        continuation_secret=TEST_CONTINUATION_SECRET,
        components=SimpleNamespace(
            **{
                **vars(_components(_ScriptedLLM([_step("unused")]))),
                "tool_hub": _PartialHardFailureHub(),
            }
        ),
        event_sink=lambda _event: asyncio.sleep(0),
        cancel_event=cancel,
    ).execute(
        ExecuteChatRun(
            paused.run_id,
            uuid4(),
            paused.session_id,
            json.dumps({"approved": True}),
            (),
            paused.thaw_continuation(),
        )
    )
    assert isinstance(result, FailedResult)
    assert [tool.tool_call_id for tool in result.tools] == ["p1", "p2"]
    if cancel_before_dispatch:
        assert result.error_code == "cancelled"
        assert [tool.status for tool in result.tools] == ["failed", "failed"]
    else:
        assert result.error_code == "tool_error"
        assert [tool.status for tool in result.tools] == ["failed", "completed"]
        assert result.tools[1].digest == "second-complete"


async def test_tool_call_id_reuse_across_model_rounds_fails_before_second_dispatch() -> None:
    first = StepResult(
        content="",
        tool_calls=[StepToolCall(id="reused", name="same_tool", arguments='{"x":1}')],
        finish_reason="tool_calls",
        prompt_tokens=1,
        completion_tokens=1,
        cached_tokens=0,
        cost_cny=0,
    )
    second = StepResult(
        content="",
        tool_calls=[StepToolCall(id="reused", name="same_tool", arguments='{"x":2}')],
        finish_reason="tool_calls",
        prompt_tokens=1,
        completion_tokens=1,
        cached_tokens=0,
        cost_cny=0,
    )
    hub = _RecordingHub()
    result = await ChatRunExecutor(
        user_id=uuid4(),
        continuation_secret=TEST_CONTINUATION_SECRET,
        components=SimpleNamespace(
            **{**vars(_components(_ScriptedLLM([first, second]))), "tool_hub": hub}
        ),
        event_sink=lambda _event: asyncio.sleep(0),
        cancel_event=asyncio.Event(),
    ).execute(_command())
    assert isinstance(result, FailedResult)
    assert result.error_code == "tool_error"
    assert [call.id for call in hub.calls] == ["reused"]
    assert [(tool.tool_call_id, tool.status) for tool in result.tools] == [
        ("reused", "completed"),
        ("reused", "failed"),
    ]


async def test_tool_call_id_reuse_from_continuation_history_fails_before_dispatch() -> None:
    command = _command()
    state = {
        "user_id": "untrusted-snapshot-user",
        "session_id": str(command.session_id),
        "request_id": str(command.run_id),
        "step": 1,
        "messages": [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "historical-id",
                        "type": "function",
                        "function": {"name": "same_tool", "arguments": '{"x":1}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "historical-id", "content": "old"},
        ],
        "ledger": {
            "entries": [
                {
                    "step": 1,
                    "tool_call_id": "historical-id",
                    "tool_name": "same_tool",
                    "args_hash": "5041bf1f713df204",
                    "digest": "old-digest",
                    "success": True,
                }
            ]
        },
    }
    continuation = _signed_test_continuation(
        command,
        user_id="trusted-user",
        pause_type="input",
        state=state,
    )
    reused = StepResult(
        content="",
        tool_calls=[StepToolCall(id="historical-id", name="same_tool", arguments='{"x":2}')],
        finish_reason="tool_calls",
        prompt_tokens=1,
        completion_tokens=1,
        cached_tokens=0,
        cost_cny=0,
    )
    hub = _RecordingHub()
    result = await ChatRunExecutor(
        user_id="trusted-user",
        continuation_secret=TEST_CONTINUATION_SECRET,
        components=SimpleNamespace(
            **{**vars(_components(_ScriptedLLM([reused]))), "tool_hub": hub}
        ),
        event_sink=lambda _event: asyncio.sleep(0),
        cancel_event=asyncio.Event(),
    ).execute(
        ExecuteChatRun(
            command.run_id,
            uuid4(),
            command.session_id,
            "resume",
            (),
            continuation,
        )
    )
    assert isinstance(result, FailedResult)
    assert result.error_code == "tool_error"
    assert hub.calls == []
    assert [(tool.tool_call_id, tool.status) for tool in result.tools] == [
        ("historical-id", "failed")
    ]


async def test_empty_tool_call_id_is_tool_error_without_dispatch() -> None:
    first = StepResult(
        content="",
        tool_calls=[StepToolCall(id="", name="same_tool", arguments="{}")],
        finish_reason="tool_calls",
        prompt_tokens=1,
        completion_tokens=1,
        cached_tokens=0,
        cost_cny=0,
    )
    hub = _RecordingHub()
    result = await ChatRunExecutor(
        user_id=uuid4(),
        continuation_secret=TEST_CONTINUATION_SECRET,
        components=SimpleNamespace(**{**vars(_components(_ScriptedLLM([first]))), "tool_hub": hub}),
        event_sink=lambda _event: asyncio.sleep(0),
        cancel_event=asyncio.Event(),
    ).execute(_command())
    assert isinstance(result, FailedResult)
    assert result.error_code == "tool_error"
    assert hub.calls == []


async def test_continuation_envelope_is_signed_and_context_bound() -> None:
    paused = await ChatRunExecutor(
        user_id="trusted-user",
        continuation_secret=TEST_CONTINUATION_SECRET,
        continuation_key_id="test-key",
        components=_components(_ScriptedLLM([_step("unused")])),
        event_sink=lambda _event: asyncio.sleep(0),
        cancel_event=asyncio.Event(),
        pause_controller=_PauseAt("before_model", "input"),
    ).execute(_command())
    assert isinstance(paused, PauseResult)
    envelope = paused.thaw_continuation()
    assert set(envelope) == {"version", "key_id", "body", "signature"}
    assert envelope["version"] == 1
    assert envelope["key_id"] == "test-key"
    assert envelope["body"]["user_id"] == "trusted-user"
    assert len(envelope["signature"]) == 64
    assert len(paused.continuation_json().encode("utf-8")) <= 64 * 1024


@pytest.mark.parametrize(
    "tamper",
    [
        "body",
        "signature",
        "key_id",
        "run",
        "session",
        "user",
        "missing_signature",
        "wrong_secret",
    ],
)
async def test_tampered_or_replayed_continuation_is_rejected_without_dispatch(
    tamper: str,
) -> None:
    command = _command()
    paused = await ChatRunExecutor(
        user_id="trusted-user",
        continuation_secret=TEST_CONTINUATION_SECRET,
        continuation_key_id="test-key",
        components=_components(_ScriptedLLM([_step("unused")])),
        event_sink=lambda _event: asyncio.sleep(0),
        cancel_event=asyncio.Event(),
        pause_controller=_PauseAt("before_model", "input"),
    ).execute(command)
    assert isinstance(paused, PauseResult)
    envelope = paused.thaw_continuation()
    resume_run_id = paused.run_id
    resume_session_id = paused.session_id
    resume_user = "trusted-user"
    secret = TEST_CONTINUATION_SECRET
    if tamper == "body":
        envelope["body"]["messages"].append({"role": "user", "content": "forged"})
    elif tamper == "signature":
        envelope["signature"] = "0" * 64
    elif tamper == "key_id":
        envelope["key_id"] = "other-key"
    elif tamper == "run":
        resume_run_id = uuid4()
    elif tamper == "session":
        resume_session_id = uuid4()
    elif tamper == "user":
        resume_user = "other-user"
    elif tamper == "missing_signature":
        del envelope["signature"]
    else:
        secret = b"w" * 32
    hub = _RecordingHub()
    result = await ChatRunExecutor(
        user_id=resume_user,
        continuation_secret=secret,
        continuation_key_id="test-key",
        components=SimpleNamespace(
            **{**vars(_components(_ScriptedLLM([_step("unused")]))), "tool_hub": hub}
        ),
        event_sink=lambda _event: asyncio.sleep(0),
        cancel_event=asyncio.Event(),
    ).execute(
        ExecuteChatRun(
            resume_run_id,
            uuid4(),
            resume_session_id,
            "resume",
            (),
            envelope,
        )
    )
    assert isinstance(result, FailedResult)
    assert result.error_code == "invalid_continuation"
    assert hub.calls == []


async def test_pause_without_server_secret_fails_closed_but_fresh_completion_works() -> None:
    fresh = await ChatRunExecutor(
        user_id=uuid4(),
        components=_components(_ScriptedLLM([_step("fresh")])),
        event_sink=lambda _event: asyncio.sleep(0),
        cancel_event=asyncio.Event(),
    ).execute(_command())
    assert isinstance(fresh, CompletedResult)
    paused = await ChatRunExecutor(
        user_id=uuid4(),
        components=_components(_ScriptedLLM([_step("unused")])),
        event_sink=lambda _event: asyncio.sleep(0),
        cancel_event=asyncio.Event(),
        pause_controller=_PauseAt("before_model", "input"),
    ).execute(_command())
    assert isinstance(paused, FailedResult)
    assert paused.error_code == "executor_error"

    command = _command()
    continuation = _signed_test_continuation(
        command,
        user_id="trusted-user",
        pause_type="input",
        state={
            "user_id": "snapshot-user",
            "session_id": str(command.session_id),
            "request_id": str(command.run_id),
            "messages": [],
        },
    )
    hub = _RecordingHub()
    resumed = await ChatRunExecutor(
        user_id="trusted-user",
        components=SimpleNamespace(
            **{**vars(_components(_ScriptedLLM([_step("unused")]))), "tool_hub": hub}
        ),
        event_sink=lambda _event: asyncio.sleep(0),
        cancel_event=asyncio.Event(),
    ).execute(
        ExecuteChatRun(
            command.run_id,
            uuid4(),
            command.session_id,
            "resume",
            (),
            continuation,
        )
    )
    assert isinstance(resumed, FailedResult)
    assert resumed.error_code == "invalid_continuation"
    assert hub.calls == []


def test_continuation_secret_must_have_256_bits() -> None:
    with pytest.raises(ValueError, match="at least 32 bytes"):
        ChatRunExecutor(
            user_id="trusted-user",
            continuation_secret=b"too-short",
            components=_components(_ScriptedLLM([_step("unused")])),
            event_sink=lambda _event: asyncio.sleep(0),
            cancel_event=asyncio.Event(),
        )

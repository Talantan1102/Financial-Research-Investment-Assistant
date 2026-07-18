from __future__ import annotations

import ast
import asyncio
import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
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
from app.services.llm_step import StepDelta, StepResult, StepToolCall


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
    *, prompt: str = "分析茅台", history: tuple[dict[str, Any], ...] = ()
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
    executor = ChatRunExecutor(
        user_id=uuid4(),
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
    encoded = json.dumps(paused.continuation, ensure_ascii=False)
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
        continuation=dict(paused.continuation),
    )
    resumed_llm = _ScriptedLLM([_step("resumed", input_tokens=13, output_tokens=3)])
    resumed_hub = _RecordingHub() if pause_type == "approval" else _Hub()
    resumed_executor = ChatRunExecutor(
        user_id=uuid4(),
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
    paused = await ChatRunExecutor(
        user_id=uuid4(),
        components=_components(_ScriptedLLM([first_step])),
        event_sink=lambda _event: asyncio.sleep(0),
        cancel_event=asyncio.Event(),
        pause_controller=_PauseAt("before_tools", "approval"),
    ).execute(_command())
    assert isinstance(paused, PauseResult)

    hub = _RecordingHub()
    llm = _ScriptedLLM([_step("not executed")])
    result = await ChatRunExecutor(
        user_id=uuid4(),
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
            dict(paused.continuation),
        )
    )

    assert isinstance(result, CompletedResult)
    assert hub.calls == []
    roles = [message.get("role") for message in llm.messages[0]]
    assistant_index = roles.index("assistant")
    assert roles[assistant_index + 1] == "tool"
    assert result.tools[0].status == "failed"
    assert result.tools[0].error_code == "approval_rejected"


async def test_input_resume_does_not_project_historical_tools_as_attempt_failures() -> None:
    command = _command()
    continuation = {
        "state": {
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
                        "tool_name": "old_tool",
                        "args_hash": "44136fa355b3678a",
                        "digest": "old",
                        "success": True,
                    }
                ]
            },
        },
        "pending_tool_calls": [],
    }
    result = await ChatRunExecutor(
        user_id=uuid4(),
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


@pytest.mark.parametrize("approved", [True, False])
async def test_malformed_pending_arguments_still_return_strict_result(
    approved: bool,
) -> None:
    class _MalformedSafeHub(_RecordingHub):
        async def dispatch(self, calls: list[StepToolCall], state: Any) -> list[ToolResult]:
            self.calls.extend(calls)
            state.ledger.record(
                step=state.step,
                tool_name=calls[0].name,
                args={},
                digest="handled",
                success=True,
            )
            return [
                ToolResult(
                    tool_name=calls[0].name,
                    args={},
                    success=True,
                    output={"ok": True},
                    latency_ms=1,
                )
            ]

    call = StepToolCall(id="malformed", name="dangerous_tool", arguments="{")
    paused = await ChatRunExecutor(
        user_id=uuid4(),
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
    assert isinstance(paused, PauseResult)

    result = await ChatRunExecutor(
        user_id=uuid4(),
        components=SimpleNamespace(
            **{
                **vars(_components(_ScriptedLLM([_step("done")]))),
                "tool_hub": _MalformedSafeHub(),
            }
        ),
        event_sink=lambda _event: asyncio.sleep(0),
        cancel_event=asyncio.Event(),
    ).execute(
        ExecuteChatRun(
            paused.run_id,
            uuid4(),
            paused.session_id,
            json.dumps({"approved": approved}),
            (),
            dict(paused.continuation),
        )
    )
    assert isinstance(result, CompletedResult)
    assert result.tools[0].request == {}


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
    )
    result = await executor.execute(
        ExecuteChatRun(
            command.run_id,
            command.attempt_id,
            command.session_id,
            "resume",
            (),
            {"state": state, "pending_tool_calls": []},
        )
    )
    assert isinstance(result, PauseResult)
    assert result.continuation["state"]["user_id"] == str(user_id)


async def test_model_error_and_cancel_are_structured_without_secret_leakage() -> None:
    secret = "sk-secret at C:\\private\\worker.py"
    failed = await ChatRunExecutor(
        user_id=uuid4(),
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
    functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert "build_run_executor" in functions

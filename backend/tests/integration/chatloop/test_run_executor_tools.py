from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from app.chatloop.gates import GateConfig
from app.chatloop.run_executor import ChatRunExecutor, CompletedResult, ExecuteChatRun, FailedResult
from app.chatloop.tool_hub import ToolHub
from app.services.llm_step import StepDelta, StepResult, StepToolCall
from app.tools.base import Tool, ToolError
from pydantic import BaseModel


class _Args(BaseModel):
    query: str


class _Tool(Tool):
    name = "scripted_tool"
    description = "scripted"
    args_schema = _Args

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    async def run(self, args: _Args) -> dict[str, Any]:
        if self.fail:
            raise ToolError("upstream secret detail")
        return {"answer": args.query}


class _FakeMCPRegistry:
    def __init__(self, tool: Tool) -> None:
        self.tool = tool

    def list_for_llm(self) -> list[dict[str, Any]]:
        return [self.tool.schema_for_llm()]

    def get(self, name: str) -> Tool:
        assert name == self.tool.name
        return self.tool


class _LLM:
    def __init__(self, steps: list[StepResult]) -> None:
        self.steps = list(steps)

    async def stream_step(self, *, on_delta: Any, **_: Any) -> StepResult:
        step = self.steps.pop(0)
        for call in step.tool_calls:
            await on_delta(StepDelta(kind="tool_call", tool_name=call.name))
        if step.content:
            await on_delta(StepDelta(kind="content", text=step.content))
        return step


class _ExplodingHub(ToolHub):
    async def dispatch(self, calls: Any, state: Any) -> list[Any]:
        raise RuntimeError("tool transport leaked C:\\secret")


def _step(content: str = "", calls: list[StepToolCall] | None = None) -> StepResult:
    calls = calls or []
    return StepResult(
        content=content,
        tool_calls=calls,
        finish_reason="tool_calls" if calls else "stop",
        prompt_tokens=4,
        completion_tokens=2,
        cached_tokens=1,
        cost_cny=0.001,
    )


def _command() -> ExecuteChatRun:
    return ExecuteChatRun(uuid4(), uuid4(), uuid4(), "lookup", (), None, uuid4())


def _components(llm: Any, hub: Any) -> Any:
    return SimpleNamespace(
        llm=llm,
        tool_hub=hub,
        gate_cfg=GateConfig(),
        skill_listing="",
        system_prompt="assistant",
    )


async def test_real_tool_hub_records_exact_tool_contract_and_soft_error_recovers() -> None:
    call = StepToolCall(id="call-7", name="scripted_tool", arguments='{"query":"price"}')
    hub = ToolHub()
    hub.register_registry(_FakeMCPRegistry(_Tool(fail=True)))
    events = []

    async def collect(event: Any) -> None:
        events.append(event)

    result = await ChatRunExecutor(
        user_id=uuid4(),
        components=_components(_LLM([_step(calls=[call]), _step("fallback")]), hub),
        event_sink=collect,
        cancel_event=asyncio.Event(),
    ).execute(_command())

    assert isinstance(result, CompletedResult)
    assert result.final_text == "fallback"
    assert len(result.tools) == 1
    tool = result.tools[0]
    assert tool.tool_call_id == "call-7"
    assert tool.tool_name == "scripted_tool"
    assert tool.request == {"query": "price"}
    assert tool.success is False
    assert "upstream secret detail" not in (tool.error_message or "")
    assert "upstream secret detail" not in repr(tool)
    assert "upstream secret detail" not in repr(events)
    assert "upstream secret detail" not in repr(result.events)


async def test_hard_tool_dispatch_error_is_classified_and_sanitized() -> None:
    call = StepToolCall(id="call-8", name="scripted_tool", arguments='{"query":"price"}')
    result = await ChatRunExecutor(
        user_id=uuid4(),
        components=_components(_LLM([_step(calls=[call])]), _ExplodingHub()),
        event_sink=lambda _event: asyncio.sleep(0),
        cancel_event=asyncio.Event(),
    ).execute(_command())

    assert isinstance(result, FailedResult)
    assert result.error_code == "tool_error"
    assert "secret" not in result.message.lower()

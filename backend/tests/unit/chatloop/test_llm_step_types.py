"""StepResult/StepDelta 纯数据类型测试 + ScriptedStepClient 测试(L0,无 I/O)。"""
from __future__ import annotations

import pytest
from app.services.llm_step import StepDelta, StepResult, StepToolCall

# ---------------------------------------------------------------------------
# StepResult / StepToolCall — Step 1 tests
# ---------------------------------------------------------------------------

def test_step_result_natural_stop():
    r = StepResult(content="茅台现价 1700 元", tool_calls=[], finish_reason="stop",
                   prompt_tokens=100, completion_tokens=20, cached_tokens=80, cost_cny=0.001)
    assert not r.tool_calls and r.finish_reason == "stop"


def test_step_result_with_calls_parses_args():
    r = StepResult(content="我查一下", finish_reason="tool_calls", prompt_tokens=1, completion_tokens=1,
                   cached_tokens=0, cost_cny=0.0,
                   tool_calls=[StepToolCall(id="c1", name="get_stock_quote",
                                            arguments='{"ts_code": "600519.SH"}')])
    assert r.tool_calls[0].parsed_args == {"ts_code": "600519.SH"}


def test_step_tool_call_bad_json_raises_value_error():
    with pytest.raises(ValueError):
        StepToolCall(id="c1", name="x", arguments="{not json").parsed_args  # noqa: B018


# ---------------------------------------------------------------------------
# ScriptedStepClient — Step 6 tests
# ---------------------------------------------------------------------------

from app.services.llm_scripted_client import ScriptedStepClient  # noqa: E402


def _make_step(content: str = "ok", finish_reason: str = "stop") -> StepResult:
    return StepResult(
        content=content,
        tool_calls=[],
        finish_reason=finish_reason,
        prompt_tokens=10,
        completion_tokens=5,
        cached_tokens=0,
        cost_cny=0.0,
    )


async def test_scripted_client_returns_steps_in_order():
    """剧本按序弹出。"""
    s1 = _make_step("第一圈")
    s2 = _make_step("第二圈")
    client = ScriptedStepClient([s1, s2])
    r1 = await client.stream_chat(
        messages=[{"role": "user", "content": "hi"}],
        model="qwen-plus",
        tools=None,
        tool_choice="auto",
    )
    r2 = await client.stream_chat(
        messages=[{"role": "user", "content": "hi2"}],
        model="qwen-plus",
        tools=None,
        tool_choice="auto",
    )
    assert r1.content == "第一圈"
    assert r2.content == "第二圈"


async def test_scripted_client_records_messages_and_tool_choice():
    """messages 与 tool_choice 被记录到 received_messages / received_tool_choice。"""
    client = ScriptedStepClient([_make_step(), _make_step()])
    msgs1 = [{"role": "user", "content": "问题一"}]
    msgs2 = [{"role": "user", "content": "问题二"}, {"role": "assistant", "content": "回答"}]
    await client.stream_chat(messages=msgs1, model="m", tools=None, tool_choice="auto")
    await client.stream_chat(messages=msgs2, model="m", tools=None, tool_choice="none")
    assert client.received_messages == [msgs1, msgs2]
    assert client.received_tool_choice == ["auto", "none"]


async def test_scripted_client_exhausted_raises_assertion_error():
    """剧本耗尽后再调用应抛 AssertionError。"""
    client = ScriptedStepClient([_make_step()])
    await client.stream_chat(messages=[], model="m", tools=None, tool_choice="auto")
    with pytest.raises(AssertionError, match="剧本已耗尽"):
        await client.stream_chat(messages=[], model="m", tools=None, tool_choice="auto")


async def test_scripted_client_on_delta_receives_content():
    """on_delta 回调在 step.content 非空时被调用一次,携带 kind='content'。"""
    received: list[StepDelta] = []

    async def capture(delta: StepDelta) -> None:
        received.append(delta)

    client = ScriptedStepClient([_make_step("茅台")])
    await client.stream_chat(
        messages=[],
        model="m",
        tools=None,
        tool_choice="auto",
        on_delta=capture,
    )
    assert len(received) == 1
    assert received[0].kind == "content"
    assert received[0].text == "茅台"


async def test_scripted_client_on_delta_not_called_for_empty_content():
    """content 为空时 on_delta 不触发。"""
    received: list[StepDelta] = []

    async def capture(delta: StepDelta) -> None:
        received.append(delta)

    client = ScriptedStepClient([_make_step(content="")])
    await client.stream_chat(
        messages=[],
        model="m",
        tools=None,
        tool_choice="auto",
        on_delta=capture,
    )
    assert received == []

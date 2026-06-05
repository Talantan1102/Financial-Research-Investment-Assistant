"""LLMService.stream_step — L1 unit tests (ScriptedStepClient 注入,无网络)。

LLM_MODE 处理: conftest autouse 把 LLM_MODE=none;
构造 LLMService 时 monkeypatch.setenv("LLM_MODE", "mock") 覆盖,
与既有 test_analyst.py / test_agent_base.py 同款模式。
"""

from __future__ import annotations

import pytest
from app.services.cost_budget import BudgetExceeded, CostBudget
from app.services.llm_scripted_client import ScriptedStepClient
from app.services.llm_service import LLMService
from app.services.llm_step import StepDelta, StepResult, StepToolCall
from app.services.pricing import compute_cost
from app.services.trace_models import Span

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_step(
    content: str = "ok",
    finish_reason: str = "stop",
    cost_cny: float = 0.001,
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
    cached_tokens: int = 0,
    tool_calls: list[StepToolCall] | None = None,
) -> StepResult:
    return StepResult(
        content=content,
        tool_calls=tool_calls or [],
        finish_reason=finish_reason,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cached_tokens=cached_tokens,
        cost_cny=cost_cny,
    )


def _make_service(
    client: object,
    monkeypatch: pytest.MonkeyPatch,
    budget: CostBudget | None = None,
) -> LLMService:
    monkeypatch.setenv("LLM_MODE", "mock")
    return LLMService(client=client, cost_budget=budget)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# basic round-trip
# ---------------------------------------------------------------------------


async def test_stream_step_returns_scripted_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """stream_step 返回剧本里的 StepResult。"""
    step = _make_step("茅台回答")
    client = ScriptedStepClient([step])
    svc = _make_service(client, monkeypatch)

    result = await svc.stream_step(
        messages=[{"role": "user", "content": "茅台现价?"}],
    )
    assert result.content == "茅台回答"
    assert result.finish_reason == "stop"


async def test_stream_step_budget_track_called(monkeypatch: pytest.MonkeyPatch) -> None:
    """stream_step 调用后 budget.spent_cny 应增加 cost_cny。"""
    step = _make_step(cost_cny=0.005)
    client = ScriptedStepClient([step])
    budget = CostBudget(limit_cny=10.0)
    svc = _make_service(client, monkeypatch, budget=budget)

    await svc.stream_step(messages=[{"role": "user", "content": "hi"}])
    assert budget.spent_cny == pytest.approx(0.005)


async def test_stream_step_tool_choice_propagated(monkeypatch: pytest.MonkeyPatch) -> None:
    """tool_choice='none' 透传给 client.received_tool_choice。"""
    step = _make_step()
    client = ScriptedStepClient([step])
    svc = _make_service(client, monkeypatch)

    await svc.stream_step(
        messages=[{"role": "user", "content": "hi"}],
        tool_choice="none",
    )
    assert client.received_tool_choice == ["none"]


async def test_stream_step_no_stream_chat_raises_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """注入的 client 无 stream_chat 时立即 RuntimeError(fail loud)。"""
    monkeypatch.setenv("LLM_MODE", "mock")

    class _NoStreamChat:
        """Stub client 不带 stream_chat 方法。"""

    svc = LLMService(client=_NoStreamChat())  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="stream_chat"):
        await svc.stream_step(messages=[])


async def test_stream_step_cost_backfill(monkeypatch: pytest.MonkeyPatch) -> None:
    """剧本给 cost_cny=0 + 有 tokens → 返回值 cost_cny == compute_cost(...)。"""
    model_name = "deepseek-v4-flash"
    prompt_tokens = 100
    completion_tokens = 50
    expected = compute_cost(model_name, prompt_tokens, completion_tokens)
    assert expected > 0

    step = StepResult(
        content="回答",
        tool_calls=[],
        finish_reason="stop",
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cached_tokens=0,
        cost_cny=0.0,  # 让 stream_step 回填
    )
    client = ScriptedStepClient([step])

    # 用能在 pricing table 找到的 tier/model — 直接把 tier_router 换掉更简单
    from app.services.tier_router import TierConfig, TierRouter

    monkeypatch.setenv("LLM_MODE", "mock")
    # 构造一个 router,让 "balanced" 解析为 deepseek-v4-flash
    router = TierRouter(TierConfig(fast=model_name, balanced=model_name, deep=model_name))
    svc = LLMService(client=client, tier_router=router)  # type: ignore[arg-type]

    result = await svc.stream_step(
        messages=[{"role": "user", "content": "hi"}],
        tier="balanced",
    )
    assert result.cost_cny == pytest.approx(expected)


async def test_stream_step_on_delta_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    """on_delta 回调被调用,收到 content delta。"""
    step = _make_step("回答内容")
    client = ScriptedStepClient([step])
    svc = _make_service(client, monkeypatch)

    received: list[StepDelta] = []

    async def capture(delta: StepDelta) -> None:
        received.append(delta)

    await svc.stream_step(
        messages=[{"role": "user", "content": "hi"}],
        on_delta=capture,
    )
    assert len(received) >= 1
    assert received[0].kind == "content"
    assert received[0].text == "回答内容"


async def test_stream_step_parent_span_id_propagated(monkeypatch: pytest.MonkeyPatch) -> None:
    """传入 parent_span_id 后,写入 TraceService 的 span.parent_id 与之一致。"""
    step = _make_step("回答")
    client = ScriptedStepClient([step])

    # 构造 spy trace_service
    written_spans: list[Span] = []

    class _SpyTrace:
        def write_span(self, span: Span) -> None:
            written_spans.append(span)

    monkeypatch.setenv("LLM_MODE", "mock")
    svc = LLMService(
        client=client,  # type: ignore[arg-type]
        trace_service=_SpyTrace(),  # type: ignore[arg-type]
    )

    parent_id = "req-abc123-parent"
    await svc.stream_step(
        messages=[{"role": "user", "content": "hi"}],
        parent_span_id=parent_id,
    )

    assert len(written_spans) == 1
    assert written_spans[0].parent_id == parent_id


async def test_stream_step_budget_exceeded_before_client_called(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """已超限的 CostBudget → stream_step 在调 client 前即抛 BudgetExceeded。

    构造:limit=1.0,先 track 2.0 使 spent > limit,再调 stream_step。
    断言:BudgetExceeded 被抛,client.received_messages 仍为空(client 未被调用)。
    """
    step = _make_step()
    client = ScriptedStepClient([step])

    budget = CostBudget(limit_cny=1.0)
    budget.track(2.0)  # spent(2.0) > limit(1.0) → assert_under_limit 将抛出

    monkeypatch.setenv("LLM_MODE", "mock")
    svc = LLMService(client=client, cost_budget=budget)  # type: ignore[arg-type]

    with pytest.raises(BudgetExceeded):
        await svc.stream_step(messages=[{"role": "user", "content": "hi"}])

    # client 未被调用
    assert client.received_messages == []

"""ToolHub 基座 — L0 单测(假 Tool 实例,不碰真 MCP/DB,spec § 3.1)。

覆盖:双后端注册顺序、dispatch 成功/未知工具/坏 JSON/异常/超时的指导性错误、
等长按序、台账去重、并行性、事件序列、cache 注入、hub 不抛硬契约。
"""
from __future__ import annotations

import asyncio
import json

import pytest
from app.chatloop.events import LoopEvent, SeqCounter
from app.chatloop.state import ChatLoopState, args_hash_of
from app.chatloop.tool_hub import ToolHub
from app.services.llm_step import StepToolCall
from app.services.tool_result_cache import CacheHit
from app.tools.base import Tool, ToolError
from pydantic import BaseModel

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _QuoteArgs(BaseModel):
    ts_code: str


class FakeTool(Tool):
    """记调用次数的假工具;可配 sleep / 抛异常 / 返回固定 output。"""

    def __init__(
        self,
        name: str,
        *,
        output: dict | None = None,
        raises: BaseException | None = None,
        sleep: float = 0.0,
        description: str = "fake tool",
    ) -> None:
        self.name = name
        self.description = description
        self.args_schema = _QuoteArgs
        self._output = output if output is not None else {"ok": True}
        self._raises = raises
        self._sleep = sleep
        self.call_count = 0

    async def run(self, args: BaseModel) -> dict:
        self.call_count += 1
        if self._sleep:
            await asyncio.sleep(self._sleep)
        if self._raises is not None:
            raise self._raises
        return dict(self._output)


class FakeRegistry:
    """最小 ToolRegistry 替身:持 dict[str, Tool],list_for_llm + get。"""

    def __init__(self, tools: list[Tool]) -> None:
        self._tools = {t.name: t for t in tools}

    def list_for_llm(self) -> list[dict]:
        return [t.schema_for_llm() for t in self._tools.values()]

    def get(self, name: str) -> Tool:
        return self._tools[name]


class _Collector:
    def __init__(self) -> None:
        self.events: list[LoopEvent] = []

    async def __call__(self, ev: LoopEvent) -> None:
        self.events.append(ev)

    def types(self) -> list[str]:
        return [e.type for e in self.events]

    def of(self, type_: str) -> list[LoopEvent]:
        return [e for e in self.events if e.type == type_]


class FakeCache:
    """get_or_compute 返回固定 (dict, HIT/MISS);记 cache_key 调用。"""

    def __init__(self, hit: CacheHit = CacheHit.HIT) -> None:
        self._hit = hit
        self.computed = False

    @staticmethod
    def cache_key(user_id: str, tool_name: str, args: dict) -> str:
        from app.services.tool_result_cache import ToolResultCache

        return ToolResultCache.cache_key(user_id, tool_name, args)

    async def get_or_compute(self, *, user_id, tool_name, args, compute_fn, ttl_seconds=None):
        if self._hit == CacheHit.HIT:
            return {"cached": True}, CacheHit.HIT
        self.computed = True
        out = await compute_fn()
        return out, self._hit


def _call(name: str, args: dict, *, id_: str | None = None, raw: str | None = None) -> StepToolCall:
    return StepToolCall(
        id=id_ or f"{name}-{args_hash_of(args)[:6]}",
        name=name,
        arguments=raw if raw is not None else json.dumps(args, ensure_ascii=False),
    )


def _state() -> ChatLoopState:
    s = ChatLoopState(
        user_id="u1",
        session_id="s1",
        request_id="r1",
        messages=[{"role": "user", "content": "茅台"}],
    )
    # 记账契约:post-apply_step 的 state.step。模拟 loop 已折叠完本圈 LLM 输出。
    s.step = 1
    return s


# ---------------------------------------------------------------------------
# schemas_for_llm + 注册
# ---------------------------------------------------------------------------


async def test_schemas_order_is_registration_order():
    hub = ToolHub()
    hub.register_inprocess([FakeTool("a"), FakeTool("b")])
    hub.register_inprocess([FakeTool("c")])
    names = [s["function"]["name"] for s in hub.schemas_for_llm()]
    assert names == ["a", "b", "c"]


async def test_register_duplicate_fails_loud():
    hub = ToolHub()
    hub.register_inprocess([FakeTool("dup")])
    with pytest.raises(ValueError, match="dup"):
        hub.register_inprocess([FakeTool("dup")])


async def test_register_registry_merges_tools():
    hub = ToolHub()
    hub.register_inprocess([FakeTool("memory_search")])
    hub.register_registry(FakeRegistry([FakeTool("get_stock_quote"), FakeTool("get_news")]))
    names = [s["function"]["name"] for s in hub.schemas_for_llm()]
    assert names == ["memory_search", "get_stock_quote", "get_news"]


# ---------------------------------------------------------------------------
# dispatch 成功
# ---------------------------------------------------------------------------


async def test_dispatch_success_records_ledger_with_post_step():
    hub = ToolHub()
    hub.register_inprocess([FakeTool("get_stock_quote", output={"price": 1600})])
    state = _state()  # step = 1
    results = await hub.dispatch([_call("get_stock_quote", {"ts_code": "600519.SH"})], state)

    assert len(results) == 1
    r = results[0]
    assert r.success is True
    assert r.output == {"price": 1600}
    # 台账记 post-apply_step 的 step
    assert len(state.ledger.entries) == 1
    entry = state.ledger.entries[0]
    assert entry.step == 1
    assert entry.tool_name == "get_stock_quote"
    assert entry.success is True
    assert len(entry.digest) <= 200


async def test_dispatch_digest_truncated_to_200():
    big = {"blob": "x" * 5000}
    hub = ToolHub()
    hub.register_inprocess([FakeTool("big", output=big)])
    state = _state()
    await hub.dispatch([_call("big", {"ts_code": "X"})], state)
    assert len(state.ledger.entries[0].digest) <= 200


# ---------------------------------------------------------------------------
# 指导性错误
# ---------------------------------------------------------------------------


async def test_unknown_tool_guidance_error():
    hub = ToolHub()
    hub.register_inprocess([FakeTool("known")])
    state = _state()
    results = await hub.dispatch([_call("ghost", {"ts_code": "X"})], state)
    r = results[0]
    assert r.success is False
    assert "[未知工具]" in r.error
    assert "ghost" in r.error
    assert "search_tools" in r.error
    # 仍按工具名记账
    assert state.ledger.entries[0].tool_name == "ghost"
    assert state.ledger.entries[0].success is False


async def test_bad_json_args_guidance_error():
    hub = ToolHub()
    hub.register_inprocess([FakeTool("get_stock_quote")])
    state = _state()
    bad = StepToolCall(id="c1", name="get_stock_quote", arguments="{not json")
    results = await hub.dispatch([bad], state)
    r = results[0]
    assert r.success is False
    assert "[参数格式错误]" in r.error
    # 工具名仍记账
    assert state.ledger.entries[0].tool_name == "get_stock_quote"
    assert state.ledger.entries[0].success is False


async def test_tool_exception_wrapped_with_guidance():
    hub = ToolHub()
    hub.register_inprocess(
        [FakeTool("boom", raises=ToolError("backend 503"))]
    )
    state = _state()
    results = await hub.dispatch([_call("boom", {"ts_code": "X"})], state)
    r = results[0]
    assert r.success is False
    assert "[执行失败]" in r.error
    assert "backend 503" in r.error


async def test_timeout_guidance_error():
    hub = ToolHub()
    hub.register_inprocess(
        [FakeTool("slow", raises=TimeoutError())]
    )
    state = _state()
    results = await hub.dispatch([_call("slow", {"ts_code": "X"})], state)
    r = results[0]
    assert r.success is False
    assert "[超时]" in r.error


async def test_validation_error_lists_field_names():
    hub = ToolHub()
    # ts_code 必填,缺它 → model_validate 抛 ValidationError
    hub.register_inprocess([FakeTool("get_stock_quote")])
    state = _state()
    results = await hub.dispatch([_call("get_stock_quote", {"wrong": "x"})], state)
    r = results[0]
    assert r.success is False
    assert "[参数校验失败]" in r.error
    assert "ts_code" in r.error  # 字段名列表


# ---------------------------------------------------------------------------
# 等长按序
# ---------------------------------------------------------------------------


async def test_equal_length_in_order_with_middle_failure():
    hub = ToolHub()
    hub.register_inprocess(
        [
            FakeTool("t1", output={"n": 1}),
            FakeTool("t3", output={"n": 3}),
        ]
    )
    state = _state()
    calls = [
        _call("t1", {"ts_code": "A"}, id_="c1"),
        _call("ghost", {"ts_code": "B"}, id_="c2"),  # 中间失败(未知工具)
        _call("t3", {"ts_code": "C"}, id_="c3"),
    ]
    results = await hub.dispatch(calls, state)
    assert len(results) == 3
    assert results[0].success is True
    assert results[1].success is False
    assert results[2].success is True
    # 原顺序对齐
    assert results[0].tool_name == "t1"
    assert results[1].tool_name == "ghost"
    assert results[2].tool_name == "t3"


# ---------------------------------------------------------------------------
# 台账去重
# ---------------------------------------------------------------------------


async def test_ledger_dedup_does_not_rerun():
    tool = FakeTool("get_stock_quote", output={"price": 1600})
    hub = ToolHub()
    hub.register_inprocess([tool])
    state = _state()
    args = {"ts_code": "600519.SH"}

    first = await hub.dispatch([_call("get_stock_quote", args)], state)
    assert first[0].success is True
    assert tool.call_count == 1

    emit = _Collector()
    hub2 = ToolHub(emit=emit)
    hub2.register_inprocess([tool])  # 同一 tool 实例
    second = await hub2.dispatch([_call("get_stock_quote", args)], state)
    # 第二次命中台账 → 不重跑
    assert tool.call_count == 1
    r = second[0]
    assert r.success is True
    assert "cached_digest" in r.output
    assert "ref" in r.output
    # tool_end 事件带 cached=True
    end_events = emit.of("tool_end")
    assert end_events
    assert end_events[-1].data.get("cached") is True


# ---------------------------------------------------------------------------
# 并行性
# ---------------------------------------------------------------------------


async def test_parallel_dispatch_faster_than_serial():
    hub = ToolHub()
    hub.register_inprocess(
        [
            FakeTool("s1", sleep=0.1, output={"n": 1}),
            FakeTool("s2", sleep=0.1, output={"n": 2}),
        ]
    )
    state = _state()
    started = asyncio.get_event_loop().time()
    results = await hub.dispatch(
        [_call("s1", {"ts_code": "A"}), _call("s2", {"ts_code": "B"})], state
    )
    elapsed = asyncio.get_event_loop().time() - started
    assert len(results) == 2
    assert all(r.success for r in results)
    assert elapsed < 0.18  # 并行 ~0.1s,串行会 ~0.2s


# ---------------------------------------------------------------------------
# 事件序列
# ---------------------------------------------------------------------------


async def test_event_sequence_success():
    emit = _Collector()
    hub = ToolHub(emit=emit)
    hub.register_inprocess([FakeTool("get_stock_quote", output={"price": 1})])
    state = _state()
    await hub.dispatch([_call("get_stock_quote", {"ts_code": "X"})], state)
    types = emit.types()
    assert types == ["tool_call", "tool_start", "tool_end"]


async def test_event_sequence_failure_uses_tool_error():
    emit = _Collector()
    hub = ToolHub(emit=emit)
    hub.register_inprocess([FakeTool("boom", raises=ToolError("x"))])
    state = _state()
    await hub.dispatch([_call("boom", {"ts_code": "X"})], state)
    types = emit.types()
    assert "tool_error" in types
    assert "tool_end" not in types
    err_ev = emit.of("tool_error")[0]
    assert "error" in err_ev.data


# ---------------------------------------------------------------------------
# cache 注入
# ---------------------------------------------------------------------------


async def test_cache_injection_records_cache_key():
    emit = _Collector()
    cache = FakeCache(hit=CacheHit.HIT)
    hub = ToolHub(emit=emit, cache=cache)
    hub.register_inprocess([FakeTool("get_stock_quote", output={"price": 1})])
    state = _state()
    args = {"ts_code": "600519.SH"}
    results = await hub.dispatch([_call("get_stock_quote", args)], state)
    assert results[0].success is True
    # cache HIT 传播到 ToolResult.cached
    assert results[0].cached is True
    # cache HIT 传播到 tool_end 事件
    end_events = emit.of("tool_end")
    assert end_events, "应有 tool_end 事件"
    assert end_events[0].data["cached"] is True
    entry = state.ledger.entries[0]
    expected_key = cache.cache_key("u1", "get_stock_quote", args)
    assert entry.cache_key == expected_key


async def test_no_cache_records_none_cache_key():
    hub = ToolHub()
    hub.register_inprocess([FakeTool("get_stock_quote", output={"price": 1})])
    state = _state()
    await hub.dispatch([_call("get_stock_quote", {"ts_code": "X"})], state)
    assert state.ledger.entries[0].cache_key is None


# ---------------------------------------------------------------------------
# hub 不抛硬契约
# ---------------------------------------------------------------------------


async def test_hub_never_raises_on_tool_exception():
    hub = ToolHub()
    hub.register_inprocess([FakeTool("boom", raises=RuntimeError("kaboom"))])
    state = _state()
    # 不应抛
    results = await hub.dispatch([_call("boom", {"ts_code": "X"})], state)
    assert len(results) == 1
    assert results[0].success is False


async def test_dispatch_empty_calls_returns_empty():
    hub = ToolHub()
    hub.register_inprocess([FakeTool("a")])
    state = _state()
    results = await hub.dispatch([], state)
    assert results == []


# ---------------------------------------------------------------------------
# 共享 SeqCounter — loop 与 hub 注入同一实例,全局 seq 严格递增无重号
# ---------------------------------------------------------------------------


async def test_shared_seq_counter_no_duplicate_seq():
    """同一 SeqCounter 注入 loop 与 hub,单 call 剧本收集两边全部事件,
    断言 seq 全局严格递增无重号。"""
    from app.chatloop.context import ContextDeps
    from app.chatloop.loop import ToolLoop
    from app.chatloop.state import ChatLoopState
    from app.services.llm_step import StepDelta, StepResult, StepToolCall

    # ---- 极简 Fake LLM(单圈:call → done) ----
    class _SimpleLLM:
        async def stream_step(self, *, messages, tools=None, tool_choice="auto",
                              tier="balanced", request_id=None, on_delta=None):
            if on_delta:
                tc = StepToolCall(id="tc1", name="get_stock_quote",
                                  arguments='{"ts_code":"600519.SH"}')
                await on_delta(StepDelta(kind="tool_call", text="", tool_name=tc.name))
                # 第二次调用返回收尾
            if not hasattr(self, "_called"):
                self._called = True
                return StepResult(
                    content="",
                    tool_calls=[StepToolCall(id="tc1", name="get_stock_quote",
                                            arguments='{"ts_code":"600519.SH"}')],
                    finish_reason="tool_calls",
                    prompt_tokens=10, completion_tokens=5,
                    cached_tokens=0, cost_cny=0.001,
                )
            return StepResult(
                content="茅台 1600 元",
                tool_calls=[],
                finish_reason="stop",
                prompt_tokens=10, completion_tokens=5,
                cached_tokens=0, cost_cny=0.001,
            )

    # ---- 极简 Fake ToolHub(Protocol 实现,注入共享 counter) ----
    class _SimpleHub:
        def __init__(self, emit_fn, seq_counter):
            self._hub = ToolHub(emit=emit_fn, seq_counter=seq_counter)
            self._hub.register_inprocess([FakeTool("get_stock_quote", output={"price": 1600})])

        def schemas_for_llm(self):
            return self._hub.schemas_for_llm()

        async def dispatch(self, calls, state):
            return await self._hub.dispatch(calls, state)

    shared_counter = SeqCounter()
    collector = _Collector()

    hub = _SimpleHub(collector, shared_counter)
    loop = ToolLoop(
        llm=_SimpleLLM(),
        tool_hub=hub,
        context_deps=ContextDeps(system_prompt="助手", max_steps=12, max_cny=1.0),
        emit=collector,
        seq_counter=shared_counter,
    )
    state = ChatLoopState(
        user_id="u1", session_id="s1", request_id="r1",
        messages=[{"role": "user", "content": "茅台"}],
    )
    await loop.run(state)

    seqs = [e.seq for e in collector.events]
    assert seqs, "应有事件"
    # 严格递增 — 无重号、无乱序
    for i in range(1, len(seqs)):
        assert seqs[i] == seqs[i - 1] + 1, (
            f"seq 不连续: 位置 {i-1}={seqs[i-1]}, 位置 {i}={seqs[i]}"
        )

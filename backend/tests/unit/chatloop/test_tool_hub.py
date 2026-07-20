"""ToolHub 基座 — L0 单测(假 Tool 实例,不碰真 MCP/DB,spec § 3.1)。

覆盖:双后端注册顺序、dispatch 成功/未知工具/坏 JSON/异常/超时的指导性错误、
等长按序、台账去重、并行性、事件序列、cache 注入、hub 不抛硬契约。
"""

from __future__ import annotations

import asyncio
import json

import pytest
from app.chatloop.events import LoopEvent, SeqCounter
from app.chatloop.inprocess import InProcessTool
from app.chatloop.state import ChatLoopState, args_hash_of
from app.chatloop.tool_hub import ToolHub
from app.chatloop.tool_runtime_policy import TOOL_RISK_METADATA, ToolRiskPolicy
from app.runtime.hooks import HookDecision, HookPipeline
from app.runtime.models import RiskLevel
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


class FakeInProcessTool(InProcessTool):
    """记 run_with_state 调用次数的假 InProcessTool;可配固定 output。"""

    def __init__(
        self,
        name: str,
        *,
        output: dict | None = None,
        sleep: float = 0.0,
        raises: BaseException | None = None,
        description: str = "fake inprocess tool",
    ) -> None:
        self.name = name
        self.description = description
        self.args_schema = _QuoteArgs
        self._output = output if output is not None else {"ok": True}
        self._sleep = sleep
        self._raises = raises
        self.call_count = 0

    async def run_with_state(self, args: BaseModel, state: ChatLoopState) -> dict:
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
    """get_or_compute 返回固定 (dict, HIT/MISS);记 cache_key 调用次数。"""

    def __init__(self, hit: CacheHit = CacheHit.HIT) -> None:
        self._hit = hit
        self.computed = False
        self.call_count = 0  # get_or_compute 被调次数

    @staticmethod
    def cache_key(user_id: str, tool_name: str, args: dict) -> str:
        from app.services.tool_result_cache import ToolResultCache

        return ToolResultCache.cache_key(user_id, tool_name, args)

    async def get_or_compute(self, *, user_id, tool_name, args, compute_fn, ttl_seconds=None):
        self.call_count += 1
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


async def test_schemas_unknown_tools_fail_safe_then_search_tools_last():
    """Task 3.2 后:schemas_for_llm 按渐进披露分组。
    未在 TOOL_DOCS 的工具(a/b/c)走 fail-safe 完整 schema,保持注册序,
    search_tools 殿后(分组细节见 test_progressive_disclosure)。"""
    hub = ToolHub()
    hub.register_inprocess([FakeTool("a"), FakeTool("b")])
    hub.register_inprocess([FakeTool("c")])
    names = [s["function"]["name"] for s in hub.schemas_for_llm()]
    assert names == ["a", "b", "c", "search_tools"]


async def test_register_duplicate_fails_loud():
    hub = ToolHub()
    hub.register_inprocess([FakeTool("dup")])
    with pytest.raises(ValueError, match="dup"):
        hub.register_inprocess([FakeTool("dup")])


async def test_register_registry_merges_tools():
    """注册并入仍生效;schemas_for_llm 按分组重排:core(memory_search/
    get_stock_quote)在前、deferred(get_news)其次、search_tools 殿后。"""
    hub = ToolHub()
    hub.register_inprocess([FakeTool("memory_search")])
    hub.register_registry(FakeRegistry([FakeTool("get_stock_quote"), FakeTool("get_news")]))
    names = [s["function"]["name"] for s in hub.schemas_for_llm()]
    # 三个工具都已并入(注册成功),CORE_TOOLS 序:get_stock_quote 在 memory_search 前
    assert names == ["get_stock_quote", "memory_search", "get_news", "search_tools"]


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
    hub.register_inprocess([FakeTool("boom", raises=ToolError("backend 503"))])
    state = _state()
    results = await hub.dispatch([_call("boom", {"ts_code": "X"})], state)
    r = results[0]
    assert r.success is False
    assert "[执行失败]" in r.error
    assert "backend 503" in r.error


async def test_timeout_guidance_error():
    hub = ToolHub()
    hub.register_inprocess([FakeTool("slow", raises=TimeoutError())])
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
        async def stream_step(
            self,
            *,
            messages,
            tools=None,
            tool_choice="auto",
            tier="balanced",
            model=None,
            request_id=None,
            on_delta=None,
        ):
            if on_delta:
                tc = StepToolCall(
                    id="tc1", name="get_stock_quote", arguments='{"ts_code":"600519.SH"}'
                )
                await on_delta(StepDelta(kind="tool_call", text="", tool_name=tc.name))
                # 第二次调用返回收尾
            if not hasattr(self, "_called"):
                self._called = True
                return StepResult(
                    content="",
                    tool_calls=[
                        StepToolCall(
                            id="tc1", name="get_stock_quote", arguments='{"ts_code":"600519.SH"}'
                        )
                    ],
                    finish_reason="tool_calls",
                    prompt_tokens=10,
                    completion_tokens=5,
                    cached_tokens=0,
                    cost_cny=0.001,
                )
            return StepResult(
                content="茅台 1600 元",
                tool_calls=[],
                finish_reason="stop",
                prompt_tokens=10,
                completion_tokens=5,
                cached_tokens=0,
                cost_cny=0.001,
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
        user_id="u1",
        session_id="s1",
        request_id="r1",
        messages=[{"role": "user", "content": "茅台"}],
    )
    await loop.run(state)

    seqs = [e.seq for e in collector.events]
    assert seqs, "应有事件"
    # 严格递增 — 无重号、无乱序
    for i in range(1, len(seqs)):
        assert seqs[i] == seqs[i - 1] + 1, (
            f"seq 不连续: 位置 {i - 1}={seqs[i - 1]}, 位置 {i}={seqs[i]}"
        )


# ---------------------------------------------------------------------------
# InProcessTool 绕过 cache 与台账去重(状态变更工具不可缓存)
# ---------------------------------------------------------------------------


async def test_inprocess_tool_bypasses_cache_always_runs():
    """InProcessTool 同参两次 dispatch → run_with_state 被调 2 次;cache(注入 Fake)零调用。

    状态变更类工具(memory_write / offer_deep_research / load_skill)不可缓存:
    同参缓存命中会导致 run_with_state 被跳过,状态更新静默丢失。
    """
    tool = FakeInProcessTool("memory_write", output={"written": True})
    cache = FakeCache(hit=CacheHit.HIT)  # 若 InProcessTool 误走 cache 则 HIT 直返
    hub = ToolHub(cache=cache)
    hub.register_inprocess([tool])
    state = _state()
    args = {"ts_code": "600519.SH"}

    # 第一次
    r1 = await hub.dispatch([_call("memory_write", args)], state)
    assert r1[0].success is True
    assert tool.call_count == 1

    # 第二次(同参)
    r2 = await hub.dispatch([_call("memory_write", args)], state)
    assert r2[0].success is True
    # run_with_state 仍被调(共 2 次),cache 的 get_or_compute 从未被调
    assert tool.call_count == 2
    assert cache.call_count == 0  # InProcessTool 完全绕过 cache,get_or_compute 零调用


async def test_registry_tool_still_uses_cache():
    """回归:registry 后端只读工具(非 InProcessTool)仍走 cache。"""
    reg_tool = FakeTool("get_stock_quote", output={"price": 1600})
    cache = FakeCache(hit=CacheHit.HIT)
    hub = ToolHub(cache=cache)
    hub.register_registry(FakeRegistry([reg_tool]))
    state = _state()
    args = {"ts_code": "600519.SH"}

    results = await hub.dispatch([_call("get_stock_quote", args)], state)
    assert results[0].success is True
    # cache HIT → tool.run 未被调(compute_fn 未执行)
    assert reg_tool.call_count == 0
    # cache_key 已写入台账
    entry = state.ledger.entries[0]
    assert entry.cache_key is not None


async def test_inprocess_tool_not_deduped_by_ledger():
    """InProcessTool 不被台账去重短路:同参第二次仍真执行,台账记两行。

    memory_write 同参二次调用不应被 ledger find_success 短路——写入是业务意图。
    台账仍两行(spinning 检测依赖完整轨迹)。
    """
    tool = FakeInProcessTool("memory_write", output={"written": True})
    hub = ToolHub()
    hub.register_inprocess([tool])
    state = _state()
    args = {"ts_code": "600519.SH"}

    await hub.dispatch([_call("memory_write", args)], state)
    assert tool.call_count == 1
    assert len(state.ledger.entries) == 1

    # 第二次同参
    r2 = await hub.dispatch([_call("memory_write", args)], state)
    assert r2[0].success is True
    # 仍真执行(未被 ledger find_success 短路)
    assert tool.call_count == 2
    # 台账两行(轨迹完整,spinning 检测可用)
    assert len(state.ledger.entries) == 2


# ---------------------------------------------------------------------------
# ③ 工具超时(数据工具单次超时,in-process 豁免)
# ---------------------------------------------------------------------------


async def test_data_tool_timeout_returns_guidance_error():
    """数据工具单次执行超时 → success=False + [超时] 指导性错误(落进现有映射)。"""
    hub = ToolHub(tool_timeout_s=0.05)
    hub.register_registry(FakeRegistry([FakeTool("slow_quote", sleep=0.3)]))
    state = _state()
    [res] = await hub.dispatch([_call("slow_quote", {"ts_code": "x"})], state)
    assert res.success is False
    assert res.error is not None and res.error.startswith("[超时]")


async def test_inprocess_tool_uses_uniform_timeout():
    """in-process 也必须经过统一安全执行器的超时边界。"""
    hub = ToolHub(tool_timeout_s=0.05)
    hub.register_inprocess([FakeInProcessTool("memory_write", sleep=0.3, output={"ok": True})])
    state = _state()
    [res] = await hub.dispatch([_call("memory_write", {"ts_code": "x"})], state)
    assert res.success is False
    assert res.error is not None and res.error.startswith("[超时]")


async def test_data_tool_under_timeout_succeeds_and_isolates():
    """同圈一快一慢(均不超时)→ 各自独立返回,互不影响(per-call 隔离)。"""
    hub = ToolHub(tool_timeout_s=0.5)
    hub.register_registry(
        FakeRegistry(
            [
                FakeTool("fast", sleep=0.0, output={"v": 1}),
                FakeTool("slowish", sleep=0.05, output={"v": 2}),
            ]
        )
    )
    state = _state()
    r1, r2 = await hub.dispatch(
        [_call("fast", {"ts_code": "a"}), _call("slowish", {"ts_code": "b"})], state
    )
    assert (r1.success, r1.output) == (True, {"v": 1})
    assert (r2.success, r2.output) == (True, {"v": 2})


# ---------------------------------------------------------------------------
# Unified runtime safety boundary
# ---------------------------------------------------------------------------


async def test_request_visibility_is_enforced_at_execution_boundary():
    tool = FakeTool("get_stock_quote")
    emit = _Collector()
    hub = ToolHub(emit=emit, visibility_resolver=lambda _state: frozenset())
    hub.register_registry(FakeRegistry([tool]))

    [result] = await hub.dispatch([_call(tool.name, {"ts_code": "X"})], _state())

    assert result.success is False
    assert "[不可见工具]" in (result.error or "")
    assert tool.call_count == 0


async def test_pre_and_post_hooks_wrap_real_tool_execution():
    events: list[str] = []
    tool = FakeTool("get_stock_quote", output={"price": 1})

    async def pre(invocation):
        events.append(f"pre:{invocation.input['ts_code']}")
        return HookDecision(updated_input={"ts_code": "B"})

    async def post(invocation):
        events.append(f"post:{invocation.input['ts_code']}:{invocation.output['price']}")
        return HookDecision()

    hub = ToolHub(hooks=HookPipeline(pre_hooks=[pre], post_hooks=[post]))
    hub.register_registry(FakeRegistry([tool]))

    [result] = await hub.dispatch([_call(tool.name, {"ts_code": "A"})], _state())

    assert result.success is True
    assert result.args == {"ts_code": "B"}
    assert events == ["pre:A", "post:B:1"]


async def test_uncontrolled_inprocess_tool_fails_closed_and_requests_permission():
    emit = _Collector()
    tool = FakeInProcessTool("unclassified_state_mutation")
    hub = ToolHub(emit=emit)
    hub.register_inprocess([tool])

    [result] = await hub.dispatch([_call(tool.name, {"ts_code": "X"})], _state())

    assert result.success is False
    assert "[需要授权]" in (result.error or "")
    assert tool.call_count == 0
    assert emit.of("permission_required")[0].data["tool"] == tool.name


async def test_controlled_business_and_sandbox_tools_are_system_allowed():
    for name in ("memory_write", "run_skill_script", "run_python"):
        tool = FakeInProcessTool(name)
        hub = ToolHub()
        hub.register_inprocess([tool])
        [result] = await hub.dispatch([_call(name, {"ts_code": "X"})], _state())
        assert result.success is True, name
        assert tool.call_count == 1, name


async def test_inprocess_tool_uses_same_timeout_as_registry_tools():
    tool = FakeInProcessTool("memory_write", sleep=0.2)
    hub = ToolHub(tool_timeout_s=0.01)
    hub.register_inprocess([tool])

    [result] = await hub.dispatch([_call(tool.name, {"ts_code": "X"})], _state())

    assert result.success is False
    assert result.error is not None and result.error.startswith("[超时]")


async def test_runtime_bounds_and_redacts_inprocess_output():
    secret = FakeInProcessTool(
        "memory_write",
        output={"access_token": "visible-token", "message": "Bearer visible-token"},
    )
    redacting_hub = ToolHub()
    redacting_hub.register_inprocess([secret])
    [redacted] = await redacting_hub.dispatch([_call(secret.name, {"ts_code": "X"})], _state())
    assert redacted.output == {"access_token": "[REDACTED]", "message": "[REDACTED]"}

    large = FakeInProcessTool("memory_write", output={"blob": "x" * 100})
    bounded_hub = ToolHub(max_output_bytes=10)
    bounded_hub.register_inprocess([large])
    [bounded] = await bounded_hub.dispatch([_call(large.name, {"ts_code": "X"})], _state())
    assert bounded.success is False
    assert "[输出超限]" in (bounded.error or "")


async def test_cancelled_tool_propagates_cancellation_without_ledger_entry():
    tool = FakeInProcessTool("memory_write", raises=asyncio.CancelledError())
    hub = ToolHub()
    hub.register_inprocess([tool])
    state = _state()

    with pytest.raises(asyncio.CancelledError):
        await hub.dispatch([_call(tool.name, {"ts_code": "X"})], state)

    assert state.ledger.entries == []


async def test_tool_risk_metadata_is_explicit_and_fail_closed_for_unknown_inprocess():
    assert TOOL_RISK_METADATA["get_stock_quote"].risk is RiskLevel.LOW
    assert TOOL_RISK_METADATA["memory_write"].risk is RiskLevel.HIGH
    assert TOOL_RISK_METADATA["run_python"].system_allow_reason == "sandboxed_execution"
    unknown = FakeInProcessTool("unknown_mutator")
    metadata = ToolRiskPolicy().metadata_for(unknown)
    assert metadata.risk is RiskLevel.MEDIUM
    assert metadata.system_allow_reason is None


async def test_dispatch_builds_dependency_graph_and_resolves_task_output():
    class ProduceArgs(BaseModel):
        ts_code: str

    class ConsumeArgs(BaseModel):
        quote: dict

    class Produce(FakeTool):
        args_schema = ProduceArgs

    class Consume(FakeTool):
        args_schema = ConsumeArgs

    producer = Produce("producer", output={"price": 10}, sleep=0.02)
    consumer = Consume("consumer", output={"used": True})
    producer.args_schema = ProduceArgs
    consumer.args_schema = ConsumeArgs
    hub = ToolHub()
    hub.register_registry(FakeRegistry([producer, consumer]))
    state = _state()

    results = await hub.dispatch(
        [
            _call(
                "producer",
                {"__task_id": "quote", "ts_code": "X"},
                id_="provider-a",
            ),
            _call(
                "consumer",
                {
                    "__task_id": "analysis",
                    "__depends_on": ["quote"],
                    "quote": "$task.quote.output",
                },
                id_="provider-b",
            ),
        ],
        state,
    )

    assert [result.success for result in results] == [True, True], [
        result.error for result in results
    ]
    assert results[0].args == {"ts_code": "X"}
    assert results[1].args == {"quote": {"price": 10}}


async def test_dependency_failure_skips_downstream_tool_and_preserves_result_order():
    failing = FakeTool("upstream", raises=ToolError("unavailable"))
    downstream = FakeTool("downstream", output={"should": "not run"})
    hub = ToolHub()
    hub.register_registry(FakeRegistry([failing, downstream]))

    first, second = await hub.dispatch(
        [
            _call("upstream", {"__task_id": "a", "ts_code": "X"}, id_="one"),
            _call(
                "downstream",
                {"__task_id": "b", "__depends_on": ["a"], "ts_code": "X"},
                id_="two",
            ),
        ],
        _state(),
    )

    assert first.tool_name == "upstream" and first.success is False
    assert second.tool_name == "downstream" and second.success is False
    assert "[依赖失败]" in (second.error or "")
    assert downstream.call_count == 0


async def test_state_mutation_concurrency_group_serializes_calls():
    active = 0
    maximum = 0

    class Stateful(FakeInProcessTool):
        async def run_with_state(self, args: BaseModel, state: ChatLoopState) -> dict:
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0.02)
            active -= 1
            return {"ok": True}

    tool = Stateful("memory_write")
    hub = ToolHub()
    hub.register_inprocess([tool])
    results = await hub.dispatch(
        [
            _call("memory_write", {"ts_code": "A"}, id_="a"),
            _call("memory_write", {"ts_code": "B"}, id_="b"),
        ],
        _state(),
    )

    assert all(result.success for result in results)
    assert maximum == 1

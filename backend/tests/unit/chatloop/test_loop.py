"""ToolLoop while 本体 — L0 编排测试(十剧本,无 I/O,无真 LLM)。

依赖注入的 llm/tool_hub/steer_source/cancel_event 全部用 Fake 替身,
loop 本身只编排副作用,判定逻辑在 gates/context/state 纯函数(单独测过)。

剧本(spec § 1.2 节拍 / § 1.3 闸 / § 3.5 升级熔断 / § 4.3 取消插话):
  1. 多跳:圈1 一 call → 圈2 直答 stop;
  2. 直答:圈1 无 calls;
  3. 报错自纠:圈1 失败 → 圈2 改参成功 → 圈3 直答;
  4. 撞 max_steps:max_steps=2,三圈都发 call → 第 2 圈后 force_conclude;
  5. 升级熔断:offer_deep_research 置 escalate_offered + tool_choice=none → 收尾圈;
  6. 插话:第 2 圈边界并入 user 消息;
  7. 取消:预先 set / 流式中途 set;
  8. spinning:两圈同签名 → 第 3 圈前 check_gates 命中 → force_conclude;
  9. burned:同签名失败 3 次后第 4 圈被 filter_burned 拒;
 10. 协议异常:tool_choice=none 仍给 tool_calls → RuntimeError。
"""

from __future__ import annotations

import asyncio
import json

import pytest
from app.agents.schemas import ToolResult
from app.chatloop.context import ContextDeps
from app.chatloop.events import LoopEvent
from app.chatloop.gates import GateConfig
from app.chatloop.loop import CancelledByUser, ToolLoop
from app.chatloop.state import ChatLoopState, args_hash_of
from app.services.llm_step import StepDelta, StepResult, StepToolCall

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


def _call(name: str, args: dict, *, id_: str | None = None) -> StepToolCall:
    return StepToolCall(
        id=id_ or f"{name}-{args_hash_of(args)[:6]}",
        name=name,
        arguments=json.dumps(args, ensure_ascii=False),
    )


def _step(
    content: str = "",
    tool_calls: list[StepToolCall] | None = None,
    finish_reason: str | None = None,
    cost_cny: float = 0.001,
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
    cached_tokens: int = 0,
) -> StepResult:
    tcs = tool_calls or []
    fr = finish_reason or ("tool_calls" if tcs else "stop")
    return StepResult(
        content=content,
        tool_calls=tcs,
        finish_reason=fr,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cached_tokens=cached_tokens,
        cost_cny=cost_cny,
    )


class FakeLLM:
    """持剧本 list[StepResult],stream_step 逐圈弹出并触发 on_delta。

    记录每圈收到的 tool_choice 与 messages 供断言。
    cancel_at_delta:第几圈(0-based)在第一个 content delta 前置 cancel_event。
    """

    def __init__(
        self,
        steps: list[StepResult],
        *,
        cancel_event: asyncio.Event | None = None,
        cancel_at_round: int | None = None,
    ) -> None:
        self._steps = list(steps)
        self.received_tool_choice: list[str] = []
        self.received_messages: list[list[dict]] = []
        self.received_tools: list[object] = []
        self._round = 0
        self._cancel_event = cancel_event
        self._cancel_at_round = cancel_at_round

    async def stream_step(
        self,
        *,
        messages,
        tools=None,
        tool_choice="auto",
        tier="balanced",
        request_id=None,
        on_delta=None,
    ) -> StepResult:
        if not self._steps:
            raise AssertionError("FakeLLM 剧本已耗尽 — 剧本步数与循环圈数不符")
        self.received_tool_choice.append(tool_choice)
        self.received_messages.append([dict(m) for m in messages])
        self.received_tools.append(tools)
        cur_round = self._round
        self._round += 1
        step = self._steps.pop(0)

        # emit 增量:先发 tool_call(name 级),再发 content(模拟流式形态)
        if on_delta is not None:
            for tc in step.tool_calls:
                await on_delta(StepDelta(kind="tool_call", text="", tool_name=tc.name))
            if step.content:
                # 流式中途取消注入点:本圈是 cancel_at_round → 发 content 前 set
                if self._cancel_event is not None and self._cancel_at_round == cur_round:
                    self._cancel_event.set()
                await on_delta(StepDelta(kind="content", text=step.content))
        return step


class FakeToolHub:
    """预排 dispatch 返回表(按 call.name 顺序消费),记录收到的 calls。

    契约:dispatch 时按 post-apply_step 的 state.step 往 ledger 记账
    (模拟真实 ToolHub Phase 3 行为)。
    side_effect:可选,dispatch 时对 state 施加副作用(如置 escalate)。
    """

    def __init__(
        self,
        *,
        results_per_round: list[list[ToolResult]],
        schemas: list[dict] | None = None,
        side_effects: list | None = None,
    ) -> None:
        self._results_per_round = list(results_per_round)
        self._schemas = schemas or [{"type": "function", "function": {"name": "x"}}]
        self._side_effects = side_effects or []
        self.dispatched_calls: list[list[StepToolCall]] = []
        self._round = 0

    def schemas_for_llm(self) -> list[dict]:
        return self._schemas

    async def dispatch(self, calls: list[StepToolCall], state: ChatLoopState) -> list[ToolResult]:
        cur = self._round
        self.dispatched_calls.append(list(calls))
        if cur < len(self._side_effects) and self._side_effects[cur] is not None:
            self._side_effects[cur](state)
        results = self._results_per_round[cur]
        # 契约:按 post-apply_step 的 state.step 记账
        for call, res in zip(calls, results):
            try:
                args = call.parsed_args
            except ValueError:
                args = {}
            state.ledger.record(
                step=state.step,
                tool_name=call.name,
                args=args,
                digest=(res.error or "ok")[:200],
                success=res.success,
            )
        self._round += 1
        # 只返回与 allowed calls 等长的结果(loop 负责对齐 rejected)
        assert len(results) == len(calls), (
            f"FakeToolHub round {cur}: results({len(results)}) != calls({len(calls)})"
        )
        return list(results)


class FakeSteerSource:
    """预排每圈边界返回的插话列表(按调用顺序消费)。"""

    def __init__(self, per_round: list[list[str]]) -> None:
        self._per_round = list(per_round)
        self._round = 0

    async def pop_all(self) -> list[str]:
        out = self._per_round[self._round] if self._round < len(self._per_round) else []
        self._round += 1
        return out


def _ok_result(name: str, args: dict, output: dict | None = None) -> ToolResult:
    return ToolResult(
        tool_name=name,
        args=args,
        success=True,
        output=output or {"data": "ok"},
        error=None,
        latency_ms=1,
    )


def _err_result(name: str, args: dict, error: str = "ts_code 格式错误") -> ToolResult:
    return ToolResult(
        tool_name=name,
        args=args,
        success=False,
        output=None,
        error=error,
        latency_ms=1,
    )


def _make_state(tool_choice: str = "auto") -> ChatLoopState:
    return ChatLoopState(
        user_id="u1",
        session_id="s1",
        request_id="r1",
        messages=[{"role": "user", "content": "茅台值得买吗"}],
        tool_choice=tool_choice,
    )


def _deps() -> ContextDeps:
    return ContextDeps(system_prompt="你是金融助手", max_steps=12, max_cny=0.10)


class _Collector:
    """emit 收集器。"""

    def __init__(self) -> None:
        self.events: list[LoopEvent] = []

    async def __call__(self, ev: LoopEvent) -> None:
        self.events.append(ev)

    def types(self) -> list[str]:
        return [e.type for e in self.events]

    def of(self, type_: str) -> list[LoopEvent]:
        return [e for e in self.events if e.type == type_]


# ---------------------------------------------------------------------------
# 剧本 1:多跳(圈1 call → 圈2 直答)
# ---------------------------------------------------------------------------


async def test_scenario_1_multihop():
    args = {"ts_code": "600519.SH"}
    llm = FakeLLM(
        [
            _step(content="", tool_calls=[_call("get_stock_quote", args)]),
            _step(content="茅台目前 1600 元,估值偏高。", finish_reason="stop"),
        ]
    )
    hub = FakeToolHub(results_per_round=[[_ok_result("get_stock_quote", args)]])
    emit = _Collector()
    loop = ToolLoop(llm=llm, tool_hub=hub, context_deps=_deps(), emit=emit)
    state = await loop.run(_make_state())

    assert state.step == 2
    assert state.halt_reason == "natural"
    assert state.final_response == "茅台目前 1600 元,估值偏高。"
    # 事件序列断言
    types = emit.types()
    assert types.count("step_start") == 2
    assert types.count("cost_update") == 2
    assert "token" in types
    assert "tool_call" in types
    assert types[-1] == "done"
    assert emit.of("done")[0].data["stop_reason"] == "natural"
    # hub 收到一圈调用
    assert len(hub.dispatched_calls) == 1
    assert hub.dispatched_calls[0][0].name == "get_stock_quote"


# ---------------------------------------------------------------------------
# 剧本 2:直答(圈1 无 calls)
# ---------------------------------------------------------------------------


async def test_scenario_2_direct_answer():
    llm = FakeLLM([_step(content="你好,我能帮你分析股票。", finish_reason="stop")])
    hub = FakeToolHub(results_per_round=[])
    emit = _Collector()
    loop = ToolLoop(llm=llm, tool_hub=hub, context_deps=_deps(), emit=emit)
    state = await loop.run(_make_state())

    assert state.step == 1
    assert state.halt_reason == "natural"
    assert state.final_response == "你好,我能帮你分析股票。"
    assert len(hub.dispatched_calls) == 0
    assert emit.types().count("step_start") == 1
    assert emit.types()[-1] == "done"


# ---------------------------------------------------------------------------
# 剧本 3:报错自纠(失败 → 改参成功 → 直答)
# ---------------------------------------------------------------------------


async def test_scenario_3_error_self_correction():
    bad_args = {"ts_code": "茅台"}
    good_args = {"ts_code": "600519.SH"}
    llm = FakeLLM(
        [
            _step(tool_calls=[_call("get_stock_quote", bad_args)]),
            _step(tool_calls=[_call("get_stock_quote", good_args)]),
            _step(content="修正后查到了,茅台 1600 元。", finish_reason="stop"),
        ]
    )
    hub = FakeToolHub(
        results_per_round=[
            [_err_result("get_stock_quote", bad_args)],
            [_ok_result("get_stock_quote", good_args)],
        ]
    )
    emit = _Collector()
    loop = ToolLoop(llm=llm, tool_hub=hub, context_deps=_deps(), emit=emit)
    state = await loop.run(_make_state())

    assert state.step == 3
    assert state.halt_reason == "natural"
    # 第 1 圈的 tool 消息应是 [ERROR] 开头
    tool_msgs = [m for m in state.messages if m.get("role") == "tool"]
    assert any(m["content"].startswith("[ERROR]") for m in tool_msgs)
    assert len(hub.dispatched_calls) == 2


# ---------------------------------------------------------------------------
# 剧本 4:撞 max_steps → force_conclude
# ---------------------------------------------------------------------------


async def test_scenario_4_max_steps_force_conclude():
    # max_steps=2;三圈都发不同 args 的 call(防 spinning),第 2 圈后 step=2 达上限
    llm = FakeLLM(
        [
            _step(tool_calls=[_call("get_stock_quote", {"ts_code": "600519.SH"})]),
            _step(tool_calls=[_call("get_stock_quote", {"ts_code": "000001.SZ"})]),
            # force_conclude 圈(tool_choice=none)→ 模型收尾
            _step(content="已达上限,基于已查信息:茅台估值偏高。", finish_reason="stop"),
        ]
    )
    hub = FakeToolHub(
        results_per_round=[
            [_ok_result("get_stock_quote", {"ts_code": "600519.SH"})],
            [_ok_result("get_stock_quote", {"ts_code": "000001.SZ"})],
        ]
    )
    emit = _Collector()
    loop = ToolLoop(
        llm=llm,
        tool_hub=hub,
        context_deps=_deps(),
        gate_cfg=GateConfig(max_steps=2),
        emit=emit,
    )
    state = await loop.run(_make_state())

    assert state.halt_reason == "max_steps"
    # loop_halt{max_steps} 事件
    halts = emit.of("loop_halt")
    assert len(halts) == 1
    assert halts[0].data["reason"] == "max_steps"
    # 终圈(force_conclude)收到的 tool_choice == none
    assert llm.received_tool_choice[-1] == "none"
    # final 消息含系统收尾指令(在 force_conclude 里 append 的 user 消息)
    user_contents = [m["content"] for m in state.messages if m.get("role") == "user"]
    assert any("已达执行上限" in c and "max_steps" in c for c in user_contents)
    # done{stop_reason: max_steps}
    assert emit.of("done")[0].data["stop_reason"] == "max_steps"
    # 只分发了 2 圈(force_conclude 圈不分发工具)
    assert len(hub.dispatched_calls) == 2


# ---------------------------------------------------------------------------
# 剧本 5:升级熔断(offer_deep_research → 收尾圈)
# ---------------------------------------------------------------------------


async def test_scenario_5_escalation_circuit_breaker():
    def _set_escalate(state: ChatLoopState) -> None:
        state.escalate_offered = True
        state.tool_choice = "none"

    args = {"reason": "需要深度尽调"}
    llm = FakeLLM(
        [
            _step(tool_calls=[_call("offer_deep_research", args)]),
            _step(content="已为你准备深度研究入口,请确认。", finish_reason="stop"),
        ]
    )
    hub = FakeToolHub(
        results_per_round=[
            [_ok_result("offer_deep_research", args, {"escalation_proposed": True})]
        ],
        side_effects=[_set_escalate],
    )
    emit = _Collector()
    loop = ToolLoop(llm=llm, tool_hub=hub, context_deps=_deps(), emit=emit)
    state = await loop.run(_make_state())

    # 圈2 的 tool_choice == none(escalate 副作用在圈1 dispatch 时置)
    assert llm.received_tool_choice == ["auto", "none"]
    assert state.escalate_offered is True
    # 收尾自然停 → halt_reason natural(escalate 标志单独在 state.escalate_offered)
    assert state.halt_reason == "natural"
    assert state.step == 2
    # 修法 A(spec § 4.3):escalate_offered 时 loop **不发 done**,由 runner 在
    # escalate_request + escalate_packet_draft 之后补发唯一终止 done。
    assert emit.of("done") == []
    # 但收尾 token / cost_update 等仍正常发(只是 done 让位给 runner)
    assert "token" in emit.types()


# ---------------------------------------------------------------------------
# 剧本 6:插话(第 2 圈边界并入 user 消息)
# ---------------------------------------------------------------------------


async def test_scenario_6_steering():
    args = {"ts_code": "600519.SH"}
    llm = FakeLLM(
        [
            _step(tool_calls=[_call("get_stock_quote", args)]),
            _step(content="结合负债率看,茅台财务稳健。", finish_reason="stop"),
        ]
    )
    hub = FakeToolHub(results_per_round=[[_ok_result("get_stock_quote", args)]])
    # 第 1 圈边界无插话,第 2 圈边界返回 ["先看负债率"]
    steer = FakeSteerSource(per_round=[[], ["先看负债率"]])
    emit = _Collector()
    loop = ToolLoop(llm=llm, tool_hub=hub, context_deps=_deps(), emit=emit, steer_source=steer)
    state = await loop.run(_make_state())

    # state.messages 含该 user 消息
    steer_msgs = [
        i
        for i, m in enumerate(state.messages)
        if m.get("role") == "user" and m.get("content") == "先看负债率"
    ]
    assert len(steer_msgs) == 1
    steer_idx = steer_msgs[0]
    # 位置在第 2 圈 assistant 之前:steer_idx 之后必有一条 assistant
    later_assistant = [
        i for i, m in enumerate(state.messages) if i > steer_idx and m.get("role") == "assistant"
    ]
    assert later_assistant, "插话消息后应有第 2 圈 assistant 收尾"
    # steer_merged 事件
    merged = emit.of("steer_merged")
    assert len(merged) == 1
    assert merged[0].data["preview"] == "先看负债率"


# ---------------------------------------------------------------------------
# 剧本 7a:取消(cancel_event 预先 set → 圈边界抛)
# ---------------------------------------------------------------------------


async def test_scenario_7a_cancel_preset_at_boundary():
    cancel = asyncio.Event()
    cancel.set()
    llm = FakeLLM([_step(content="不应被调用", finish_reason="stop")])
    hub = FakeToolHub(results_per_round=[])
    loop = ToolLoop(llm=llm, tool_hub=hub, context_deps=_deps(), cancel_event=cancel)
    with pytest.raises(CancelledByUser):
        await loop.run(_make_state())
    # 圈边界即抛,LLM 未被调用
    assert llm.received_tool_choice == []


# ---------------------------------------------------------------------------
# 剧本 7b:取消(流式 delta 中途 set → 第 2 圈流中抛)
# ---------------------------------------------------------------------------


async def test_scenario_7b_cancel_mid_stream():
    cancel = asyncio.Event()
    args = {"ts_code": "600519.SH"}
    # 第 1 圈 call(无 content delta,不触发取消),第 2 圈发 content delta 前 set
    llm = FakeLLM(
        [
            _step(tool_calls=[_call("get_stock_quote", args)]),
            _step(content="第二圈收尾文字", finish_reason="stop"),
        ],
        cancel_event=cancel,
        cancel_at_round=1,  # 第 2 圈(0-based round=1)
    )
    hub = FakeToolHub(results_per_round=[[_ok_result("get_stock_quote", args)]])
    loop = ToolLoop(llm=llm, tool_hub=hub, context_deps=_deps(), cancel_event=cancel)
    with pytest.raises(CancelledByUser):
        await loop.run(_make_state())
    # 第 1 圈正常跑完,第 2 圈流中抛
    assert len(llm.received_tool_choice) == 2


# ---------------------------------------------------------------------------
# 剧本 8:spinning(两圈同签名 → 第 3 圈前命中 → force_conclude)
# ---------------------------------------------------------------------------


async def test_scenario_8_spinning_force_conclude():
    args = {"ts_code": "600519.SH"}
    llm = FakeLLM(
        [
            _step(tool_calls=[_call("get_stock_quote", args)]),
            _step(tool_calls=[_call("get_stock_quote", args)]),  # 完全相同
            _step(content="检测到打转,基于已有信息作答。", finish_reason="stop"),
        ]
    )
    hub = FakeToolHub(
        results_per_round=[
            [_ok_result("get_stock_quote", args)],
            [_ok_result("get_stock_quote", args)],
        ]
    )
    emit = _Collector()
    loop = ToolLoop(llm=llm, tool_hub=hub, context_deps=_deps(), emit=emit)
    state = await loop.run(_make_state())

    assert state.halt_reason == "spinning"
    halts = emit.of("loop_halt")
    assert len(halts) == 1
    assert halts[0].data["reason"] == "spinning"
    # force_conclude 圈 tool_choice == none
    assert llm.received_tool_choice[-1] == "none"
    assert emit.of("done")[0].data["stop_reason"] == "spinning"


# ---------------------------------------------------------------------------
# 剧本 9:burned(同签名失败 3 次后第 4 圈被 filter_burned 拒)
# ---------------------------------------------------------------------------


async def test_scenario_9_burned_signature_rejected():
    """同签名失败 3 次烧掉,第 4 圈被 filter_burned 拒。

    每圈把"始终失败的目标 call"与"逐圈变化的陪跑 call"并发,使每圈签名集互不相同
    (避开 spinning 闸),让目标签名独立累计到 3 次失败触发烧签名。
    """
    bad_args = {"ts_code": "茅台"}  # 始终坏参数 → 失败
    sig = f"get_stock_quote:{args_hash_of(bad_args)}"

    def _bad(id_: str) -> StepToolCall:
        return _call("get_stock_quote", bad_args, id_=id_)

    def _vary(n: int, id_: str) -> StepToolCall:
        return _call("get_news", {"ts_code": f"{n:06d}.SH"}, id_=id_)

    llm = FakeLLM(
        [
            _step(tool_calls=[_bad("b1"), _vary(1, "v1")]),
            _step(tool_calls=[_bad("b2"), _vary(2, "v2")]),
            _step(tool_calls=[_bad("b3"), _vary(3, "v3")]),
            # 圈4:目标已烧 → filter_burned 拒目标,放行陪跑
            _step(tool_calls=[_bad("b4"), _vary(4, "v4")]),
            _step(content="该方法连续失败,改用已有信息作答。", finish_reason="stop"),
        ]
    )
    hub = FakeToolHub(
        results_per_round=[
            [
                _err_result("get_stock_quote", bad_args),
                _ok_result("get_news", {"ts_code": "000001.SH"}),
            ],
            [
                _err_result("get_stock_quote", bad_args),
                _ok_result("get_news", {"ts_code": "000002.SH"}),
            ],
            [
                _err_result("get_stock_quote", bad_args),
                _ok_result("get_news", {"ts_code": "000003.SH"}),
            ],
            # 圈4:hub 只收到放行的陪跑 call(目标被 filter_burned 拒)
            [_ok_result("get_news", {"ts_code": "000004.SH"})],
        ]
    )
    emit = _Collector()
    loop = ToolLoop(llm=llm, tool_hub=hub, context_deps=_deps(), emit=emit)
    state = await loop.run(_make_state())

    assert sig in state.burned_signatures
    # 圈4 hub 只收到陪跑 call(目标 b4 被 filter_burned 拒,未进 dispatch)
    assert len(hub.dispatched_calls[3]) == 1
    assert hub.dispatched_calls[3][0].id == "v4"
    # 圈4 目标 call 的 tool 消息是熔断文案
    tool_msgs = [m for m in state.messages if m.get("role") == "tool"]
    assert any("连续失败 3 次被熔断" in m["content"] for m in tool_msgs)
    # b4 的 tool_call_id 必有对应 tool 消息(协议红线)
    assert any(m["tool_call_id"] == "b4" for m in tool_msgs)


# ---------------------------------------------------------------------------
# 剧本 10:协议异常(tool_choice=none 仍给 tool_calls → RuntimeError)
# ---------------------------------------------------------------------------


async def test_scenario_10_protocol_violation_tool_choice_none():
    args = {"ts_code": "600519.SH"}
    llm = FakeLLM([_step(tool_calls=[_call("get_stock_quote", args)])])
    hub = FakeToolHub(results_per_round=[[_ok_result("get_stock_quote", args)]])
    # 预置 tool_choice=none(模拟熔断收尾态),模型却仍产 tool_calls
    state = _make_state(tool_choice="none")
    loop = ToolLoop(llm=llm, tool_hub=hub, context_deps=_deps())
    with pytest.raises(RuntimeError, match="协议违例"):
        await loop.run(state)


# ---------------------------------------------------------------------------
# 补充:burned 部分拒(放行的 result 与 rejected 的错误按原顺序对齐)
# ---------------------------------------------------------------------------


async def test_partial_burned_merge_order():
    """同圈两 call,一个被烧一个放行 → tool 消息顺序与 tool_calls 一致。"""
    burned_args = {"ts_code": "茅台"}
    ok_args = {"ts_code": "600519.SH"}
    sig = f"get_stock_quote:{args_hash_of(burned_args)}"
    state = _make_state()
    state.burned_signatures.add(sig)

    burned = _call("get_stock_quote", burned_args, id_="burned")
    good = _call("get_news", ok_args, id_="good")
    llm = FakeLLM(
        [
            _step(tool_calls=[burned, good]),
            _step(content="完成", finish_reason="stop"),
        ]
    )
    # 只有放行的 good 会被分发
    hub = FakeToolHub(results_per_round=[[_ok_result("get_news", ok_args)]])
    loop = ToolLoop(llm=llm, tool_hub=hub, context_deps=_deps())
    state = await loop.run(state)

    tool_msgs = [m for m in state.messages if m.get("role") == "tool"]
    # 两条 tool 消息,顺序 = tool_calls 顺序(burned 先,good 后)
    assert len(tool_msgs) == 2
    assert tool_msgs[0]["tool_call_id"] == "burned"
    assert tool_msgs[0]["content"].startswith("[ERROR]")
    assert "连续失败 3 次被熔断" in tool_msgs[0]["content"]
    assert tool_msgs[1]["tool_call_id"] == "good"
    assert not tool_msgs[1]["content"].startswith("[ERROR]")
    # hub 只收到 good
    assert hub.dispatched_calls[0] == [good]

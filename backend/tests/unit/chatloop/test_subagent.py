"""L0 — dispatch_subagents 子 agent 派发原语(契约/factory/tool/护栏)。"""

from __future__ import annotations

import json
from typing import Any

import pytest
from app.chatloop.events import LoopEvent, SeqCounter
from app.chatloop.gates import GateConfig
from app.chatloop.state import ChatLoopState
from app.chatloop.subagent import (
    MAX_SUBAGENTS,
    DispatchSubagentsArgs,
    DispatchSubagentsTool,
    SubagentFactory,
    SubagentResult,
    SubtaskRequest,
)
from app.services.llm_step import StepResult, StepToolCall
from app.tools.base import ToolError


def test_subtask_request_minimal() -> None:
    # LLM 只需填 goal;target/output_hint/boundary 可选
    req = SubtaskRequest(goal="查贵州茅台现价与近一年营收增速")
    assert req.goal == "查贵州茅台现价与近一年营收增速"
    assert req.target is None
    assert req.output_hint == ""
    assert req.boundary is None


def test_subtask_request_full() -> None:
    req = SubtaskRequest(
        goal="查五粮液财报要点",
        target="000858.SZ",
        output_hint="现价+营收增速+一句话风险",
        boundary="只看近一年",
    )
    assert req.target == "000858.SZ"
    assert req.boundary == "只看近一年"


def test_subagent_result_fields() -> None:
    r = SubagentResult(
        subtask_id="sub-0",
        target="600519.SH",
        summary="茅台现价 1700,营收增速 18%。",
        evidence_refs=["u1::cache:abc"],
        status="ok",
        gap_note=None,
        tokens_spent=1200,
        cost_cny=0.003,
        steps_used=2,
        tier="fast",
    )
    assert r.status == "ok"
    assert r.summary.startswith("茅台")
    assert r.tokens_spent == 1200


def test_subagent_result_status_literal() -> None:
    # 非法 status 被 Pydantic 拒
    with pytest.raises(ValueError):
        SubagentResult(
            subtask_id="x",
            target=None,
            summary="",
            evidence_refs=[],
            status="bogus",  # type: ignore[arg-type]
            gap_note=None,
            tokens_spent=0,
            cost_cny=0.0,
            steps_used=0,
            tier="fast",
        )


# ── Task 3/4/5: factory / tool 测试基建 ────────────────────────────────────


def _step(content: str = "", tool_calls=None, finish_reason: str = "tool_calls") -> StepResult:
    return StepResult(
        content=content,
        tool_calls=tool_calls or [],
        finish_reason=finish_reason,
        prompt_tokens=10,
        completion_tokens=5,
        cached_tokens=0,
        cost_cny=0.001,
    )


def _call(name: str, args: dict[str, Any]) -> StepToolCall:
    return StepToolCall(id=f"c-{name}", name=name, arguments=json.dumps(args))


class _FakeLLM:
    """逐圈吐预排 StepResult。"""

    def __init__(self, script: list[StepResult]) -> None:
        self._script = list(script)

    async def stream_step(self, **kwargs: Any) -> StepResult:
        on_delta = kwargs.get("on_delta")
        if on_delta is not None:
            pass  # 子循环测试不验流式增量
        return self._script.pop(0)


class _FakeRegistry:
    """子 hub 用:暴露一个 get_stock_quote 只读工具。"""

    def __init__(self) -> None:
        from app.tools.base import Tool
        from pydantic import BaseModel

        class _A(BaseModel):
            ts_code: str

        class _T(Tool):
            def __init__(self) -> None:
                self.name = "get_stock_quote"
                self.description = "查行情"
                self.args_schema = _A

            async def run(self, args: BaseModel) -> dict[str, Any]:
                return {"price": 1700}

        self._t = _T()

    def list_for_llm(self) -> list[dict[str, Any]]:
        return [{"function": {"name": "get_stock_quote"}}]

    def get(self, name: str) -> Any:
        return self._t if name == "get_stock_quote" else None


def _parent_state() -> ChatLoopState:
    return ChatLoopState(
        user_id="u1",
        session_id="s1",
        request_id="r1",
        messages=[{"role": "user", "content": "比一比"}],
        budget_spent_cny=0.0,
        budget_spent_tokens=0,
    )


@pytest.mark.asyncio
async def test_spawn_one_returns_ok_result() -> None:
    # 子循环:第1圈调 get_stock_quote,第2圈自然停作答
    llm = _FakeLLM(
        [
            _step(tool_calls=[_call("get_stock_quote", {"ts_code": "600519.SH"})]),
            _step(content="茅台现价 1700,估值偏高。", finish_reason="stop"),
        ]
    )
    events: list[LoopEvent] = []

    async def _emit(ev: LoopEvent) -> None:
        events.append(ev)

    factory = SubagentFactory(
        llm=llm,
        registry=_FakeRegistry(),
        cache=None,
        emit=_emit,
        seq_counter=SeqCounter(),
        gate_cfg=GateConfig(),
        audit_repo=None,
    )
    req = SubtaskRequest(goal="查茅台", target="600519.SH")
    result = await factory.spawn_one(req, _parent_state(), subtask_id="sub-0")

    assert result.status == "ok"
    assert "茅台" in result.summary
    assert result.target == "600519.SH"
    assert result.steps_used == 2
    # 子循环事件带 lane=subtask_id
    assert all(ev.data.get("lane") == "sub-0" for ev in events if ev.type != "done")


class _PerChildFakeLLM:
    """按 request_id 给每个子循环独立脚本 —— 并发 gather 下脚本不串(子 request_id 唯一)。

    单一共享 list 在 asyncio.gather 下 pop(0) 会被并发交错(子循环间偷步 →
    同签名连调触发 spinning),非确定性。子循环 request_id = parent::sub::sub-{i},
    天然唯一,按它路由即隔离。
    """

    def __init__(self, per_child: list[list[StepResult]]) -> None:
        # request_id 形如 r1::sub::sub-0,取末尾 index 路由到对应脚本
        self._scripts = {f"sub-{i}": list(s) for i, s in enumerate(per_child)}

    async def stream_step(self, **kwargs: Any) -> StepResult:
        rid = str(kwargs.get("request_id", ""))
        key = rid.rsplit("::", 1)[-1]
        return self._scripts[key].pop(0)


@pytest.mark.asyncio
async def test_dispatch_three_parallel_rolls_budget_and_emits() -> None:
    # 三个子任务各跑两圈(查→答),各自独立脚本(并发隔离)
    per_child = [
        [
            _step(tool_calls=[_call("get_stock_quote", {"ts_code": f"x{i}"})]),
            _step(content="结论 1700。", finish_reason="stop"),
        ]
        for i in range(3)
    ]
    llm = _PerChildFakeLLM(per_child)
    events: list[LoopEvent] = []

    async def _emit(ev: LoopEvent) -> None:
        events.append(ev)

    factory = SubagentFactory(
        llm=llm,
        registry=_FakeRegistry(),
        cache=None,
        emit=_emit,
        seq_counter=SeqCounter(),
        gate_cfg=GateConfig(),
        audit_repo=None,
    )
    parent = _parent_state()
    reqs = [SubtaskRequest(goal=f"查{i}", target=f"t{i}") for i in range(3)]
    results = await factory.dispatch(reqs, parent)

    assert len(results) == 3
    assert all(r.status == "ok" for r in results)
    # 预算回滚进父 state(3 个子循环各烧了 token/钱)
    assert parent.budget_spent_tokens > 0
    assert parent.budget_spent_cny > 0
    # dispatch_start / dispatch_end 各一次
    assert sum(1 for e in events if e.type == "dispatch_start") == 1
    assert sum(1 for e in events if e.type == "dispatch_end") == 1


@pytest.mark.asyncio
async def test_dispatch_one_child_fails_others_survive() -> None:
    # sub-2 脚本为空 → 首圈 pop 抛 IndexError → 子循环异常包成 failed;sub-0/1 正常作答。
    # (并发隔离:用 per-child 脚本,故 failed 落在确定的那个子任务上,断言不抖)
    ok_pair = [
        _step(tool_calls=[_call("get_stock_quote", {"ts_code": "x"})]),
        _step(content="ok", finish_reason="stop"),
    ]
    llm = _PerChildFakeLLM([list(ok_pair), list(ok_pair), []])  # sub-2 空脚本 → failed

    async def _emit(ev: LoopEvent) -> None:
        pass

    factory = SubagentFactory(
        llm=llm,
        registry=_FakeRegistry(),
        cache=None,
        emit=_emit,
        seq_counter=SeqCounter(),
        gate_cfg=GateConfig(),
        audit_repo=None,
    )
    results = await factory.dispatch(
        [SubtaskRequest(goal="a"), SubtaskRequest(goal="b"), SubtaskRequest(goal="c")],
        _parent_state(),
    )
    assert len(results) == 3  # 永远回 N 份,不抛
    assert any(r.status == "failed" for r in results)
    assert any(r.status == "ok" for r in results)


# ── Task 5: DispatchSubagentsTool 护栏 ─────────────────────────────────────


class _StubFactory:
    def __init__(self) -> None:
        self.called_with = None

    async def dispatch(self, subtasks, parent):
        self.called_with = (subtasks, parent)
        return [
            SubagentResult(
                subtask_id=f"sub-{i}",
                target=s.target,
                summary=f"摘要{i}",
                evidence_refs=[],
                status="ok",
                gap_note=None,
                tokens_spent=100,
                cost_cny=0.001,
                steps_used=2,
                tier="fast",
            )
            for i, s in enumerate(subtasks)
        ]


@pytest.mark.asyncio
async def test_dispatch_tool_returns_synthesizable_dict() -> None:
    factory = _StubFactory()
    tool = DispatchSubagentsTool(factory=factory)
    args = DispatchSubagentsArgs(
        reason="比三只票",
        subtasks=[
            SubtaskRequest(goal="查茅台", target="600519.SH"),
            SubtaskRequest(goal="查五粮液", target="000858.SZ"),
        ],
    )
    out = await tool.run_with_state(args, _parent_state())
    assert out["dispatched"] == 2
    assert out["results"][0]["summary"] == "摘要0"
    assert out["results"][0]["status"] == "ok"


@pytest.mark.asyncio
async def test_dispatch_tool_rejects_empty() -> None:
    tool = DispatchSubagentsTool(factory=_StubFactory())
    with pytest.raises(ToolError):
        await tool.run_with_state(DispatchSubagentsArgs(reason="x", subtasks=[]), _parent_state())


@pytest.mark.asyncio
async def test_dispatch_tool_rejects_over_cap() -> None:
    tool = DispatchSubagentsTool(factory=_StubFactory())
    too_many = [SubtaskRequest(goal=f"g{i}") for i in range(MAX_SUBAGENTS + 1)]
    with pytest.raises(ToolError):
        await tool.run_with_state(
            DispatchSubagentsArgs(reason="x", subtasks=too_many), _parent_state()
        )

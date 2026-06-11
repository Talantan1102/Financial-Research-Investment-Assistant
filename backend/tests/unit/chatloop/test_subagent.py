"""L0 — dispatch_subagents 子 agent 派发原语(契约/factory/tool/护栏)。"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.chatloop.events import LoopEvent, SeqCounter
from app.chatloop.gates import GateConfig
from app.chatloop.state import ChatLoopState
from app.chatloop.subagent import SubagentFactory, SubagentResult, SubtaskRequest
from app.services.llm_step import StepResult, StepToolCall


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
            subtask_id="x", target=None, summary="", evidence_refs=[],
            status="bogus", gap_note=None, tokens_spent=0, cost_cny=0.0,
            steps_used=0, tier="fast",
        )


# ── Task 3/4/5: factory / tool 测试基建 ────────────────────────────────────


def _step(content: str = "", tool_calls=None, finish_reason: str = "tool_calls") -> StepResult:
    return StepResult(
        content=content, tool_calls=tool_calls or [], finish_reason=finish_reason,
        prompt_tokens=10, completion_tokens=5, cached_tokens=0, cost_cny=0.001,
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
        from pydantic import BaseModel

        from app.tools.base import Tool

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
        user_id="u1", session_id="s1", request_id="r1",
        messages=[{"role": "user", "content": "比一比"}],
        budget_spent_cny=0.0, budget_spent_tokens=0,
    )


@pytest.mark.asyncio
async def test_spawn_one_returns_ok_result() -> None:
    # 子循环:第1圈调 get_stock_quote,第2圈自然停作答
    llm = _FakeLLM([
        _step(tool_calls=[_call("get_stock_quote", {"ts_code": "600519.SH"})]),
        _step(content="茅台现价 1700,估值偏高。", finish_reason="stop"),
    ])
    events: list[LoopEvent] = []

    async def _emit(ev: LoopEvent) -> None:
        events.append(ev)

    factory = SubagentFactory(
        llm=llm, registry=_FakeRegistry(), cache=None,
        emit=_emit, seq_counter=SeqCounter(), gate_cfg=GateConfig(),
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

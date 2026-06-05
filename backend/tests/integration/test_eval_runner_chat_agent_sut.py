"""L1 — EvalRunner SUT swap: backward-compat (bare LLMService) + ChatLoopAgent SUT.

Task 6.1(评测换靶,spec § 5.2):chat 模式从 LangGraph 单程图换成裸 while ToolLoop。
评测 SUT 随之从老 ChatAgent(从 plan.tool_calls 抽)换成 ChatLoopAgent(从 final
.messages 的 assistant tool_calls 抽,因 ledger 只有 args_hash 没有原始 args)。

断言:
1. 裸 LLMService SUT → tool_correctness is None(Plan C backward compat,回归不动);
2. ChatLoopAgent SUT → tool_calls 传给 Judge → tool_correctness is not None,且
   SUTOutput.tool_calls 含 get_stock_quote;
3. escalate 剧本 → SUTOutput.escalate_offered True;
4. search_tools 调用被排除出 tool_calls(spec § 3.2 渐进披露的机制工具非业务工具);
5. golden_set_v0.jsonl 的 v0-chat-001 用 ChatLoopAgent 跑 run_one 全链不炸。

ChatLoopAgent 用 ScriptedStepClient(裹进 LLMService 走 stream_step)+ FakeToolHub
驱动(参照 backend/tests/unit/chatloop/test_loop.py 的基建);run_one 全链沿用本
文件既有的真 PG db_session 模式。
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

from app.agents.schemas import ToolResult
from app.chatloop.context import ContextDeps
from app.chatloop.eval_agent import ChatLoopAgent
from app.chatloop.state import ChatLoopState, args_hash_of
from app.services.eval_models import GoldenCase, load_golden_jsonl
from app.services.eval_recorder import EvalRecorder
from app.services.eval_runner import EvalRunner
from app.services.judge import Judge
from app.services.llm_mock_client import MockLLMClient
from app.services.llm_scripted_client import ScriptedStepClient
from app.services.llm_service import LLMService
from app.services.llm_step import StepResult, StepToolCall
from app.services.trace_service import TraceService

# 评测 golden fixture 路径(本文件在 backend/tests/integration 下,parents[1] = backend/tests)
_GOLDEN_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "eval" / "golden_set_v0.jsonl"


# ---------------------------------------------------------------------------
# ScriptedStepClient / FakeToolHub helpers(参照 test_loop.py 基建)
# ---------------------------------------------------------------------------


def _call(name: str, args: dict[str, Any], *, id_: str | None = None) -> StepToolCall:
    return StepToolCall(
        id=id_ or f"{name}-{args_hash_of(args)[:6]}",
        name=name,
        arguments=json.dumps(args, ensure_ascii=False),
    )


def _step(
    content: str = "",
    tool_calls: list[StepToolCall] | None = None,
    finish_reason: str | None = None,
) -> StepResult:
    tcs = tool_calls or []
    return StepResult(
        content=content,
        tool_calls=tcs,
        finish_reason=finish_reason or ("tool_calls" if tcs else "stop"),
        prompt_tokens=10,
        completion_tokens=5,
        cached_tokens=0,
        cost_cny=0.001,
    )


def _ok_result(name: str, args: dict[str, Any], output: dict | None = None) -> ToolResult:
    return ToolResult(
        tool_name=name,
        args=args,
        success=True,
        output=output or {"data": "ok"},
        error=None,
        latency_ms=1,
    )


class FakeToolHub:
    """预排 dispatch 返回表(按圈消费),记录收到的 calls。side_effects 可改 state。

    精简自 test_loop.py 的 FakeToolHub —— 评测 SUT 不验台账细节,只验从 messages
    抽 tool_calls,故记账保持最小(loop._merge_results / apply_results 仍需结果等长)。
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
        self._round = 0

    def schemas_for_llm(self) -> list[dict]:
        return self._schemas

    async def dispatch(
        self, calls: list[StepToolCall], state: ChatLoopState
    ) -> list[ToolResult]:
        cur = self._round
        if cur < len(self._side_effects) and self._side_effects[cur] is not None:
            self._side_effects[cur](state)
        results = self._results_per_round[cur]
        # 契约:按 post-apply_step 的 state.step 记账(对齐 ToolHub Phase 3 行为)
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
        assert len(results) == len(calls), (
            f"FakeToolHub round {cur}: results({len(results)}) != calls({len(calls)})"
        )
        return list(results)


def _deps() -> ContextDeps:
    return ContextDeps(system_prompt="你是金融助手", max_steps=12, max_cny=0.10)


def _sut_llm(scripted: ScriptedStepClient) -> LLMService:
    """裹 ScriptedStepClient 进 LLMService(走 stream_step)。

    ScriptedStepClient 满足 stream_chat 协议但非 ChatClient(无同步 chat),沿用
    test_stream_step.py 既定约定 type: ignore[arg-type]。
    """
    return LLMService(client=scripted)  # type: ignore[arg-type]


def _make_case(case_id: str) -> GoldenCase:
    return GoldenCase(
        case_id=case_id,
        category="single_tool_call",
        user_input="查一下 600519.SH 的股价",
        expected_behavior={"response_must_contain": ["600519", "股价"]},
        metadata={"added_by": "test", "added_at": "2026-06-05", "tags": []},
    )


# ---------------------------------------------------------------------------
# 1. 裸 LLMService SUT → tool_correctness is None(Plan C backward compat,不动)
# ---------------------------------------------------------------------------


def test_llm_service_sut_tool_correctness_is_none(
    mock_llm_client: MockLLMClient,
    db_session,
) -> None:
    """Backward-compat: bare LLMService SUT → JudgeScores.tool_correctness is None."""
    trace = TraceService(session_factory=lambda: contextlib.nullcontext(db_session))
    recorder = EvalRecorder(session_factory=lambda: contextlib.nullcontext(db_session))

    sut_llm = LLMService(client=mock_llm_client, trace_service=trace)
    judge_llm = LLMService(client=mock_llm_client)
    judge = Judge(llm=judge_llm, judge_tier="balanced")

    runner = EvalRunner(sut=sut_llm, judge=judge, trace_service=trace, recorder=recorder)
    case = _make_case("llm-sut-compat")

    result = runner.run_one(case)

    assert result.scores.factuality is not None
    tc = result.scores.tool_correctness
    assert tc is None, f"Expected tool_correctness=None for bare LLMService SUT, got {tc}"


# ---------------------------------------------------------------------------
# 2. ChatLoopAgent SUT → tool_correctness is not None + tool_calls 含 get_stock_quote
# ---------------------------------------------------------------------------


def test_chat_loop_agent_sut_tool_correctness_is_not_none(
    mock_llm_client: MockLLMClient,
    db_session,
) -> None:
    """ChatLoopAgent SUT:两圈剧本(call get_stock_quote → 直答)→ run_one 全链 →
    tool_correctness 非 None 且 SUTOutput.tool_calls 含 get_stock_quote。"""
    trace = TraceService(session_factory=lambda: contextlib.nullcontext(db_session))
    recorder = EvalRecorder(session_factory=lambda: contextlib.nullcontext(db_session))

    args = {"ts_code": "600519.SH"}
    scripted = ScriptedStepClient(
        steps=[
            _step(tool_calls=[_call("get_stock_quote", args)]),
            _step(content="600519 当前股价 1820.5 元,估值偏高。", finish_reason="stop"),
        ]
    )
    sut_llm = _sut_llm(scripted)
    hub = FakeToolHub(results_per_round=[[_ok_result("get_stock_quote", args)]])
    agent = ChatLoopAgent(llm=sut_llm, tool_hub=hub, context_deps=_deps())

    judge_llm = LLMService(client=mock_llm_client)
    judge = Judge(llm=judge_llm, judge_tier="balanced")

    runner = EvalRunner(sut=agent, judge=judge, trace_service=trace, recorder=recorder)
    case = _make_case("chat-loop-agent-sut")

    result = runner.run_one(case)

    assert result.scores.factuality is not None
    tc = result.scores.tool_correctness
    assert tc is not None, "Expected tool_correctness to be scored for ChatLoopAgent SUT, got None"


def test_chat_loop_agent_extracts_tool_calls_from_messages() -> None:
    """SUTOutput.tool_calls 从 final.messages 的 assistant tool_calls 抽 —— 含原始 args。"""
    import asyncio

    args = {"ts_code": "600519.SH"}
    scripted = ScriptedStepClient(
        steps=[
            _step(tool_calls=[_call("get_stock_quote", args)]),
            _step(content="茅台 1820.5 元。", finish_reason="stop"),
        ]
    )
    agent = ChatLoopAgent(
        llm=_sut_llm(scripted),
        tool_hub=FakeToolHub(results_per_round=[[_ok_result("get_stock_quote", args)]]),
        context_deps=_deps(),
    )

    out = asyncio.run(agent.run(user_input="查一下 600519.SH 的股价", request_id="r-extract"))

    assert out.request_id == "r-extract"
    assert out.response_text == "茅台 1820.5 元。"
    names = [tc.tool_name for tc in out.tool_calls]
    assert names == ["get_stock_quote"]
    # 原始 args 从 messages 还原(非台账 hash)
    assert out.tool_calls[0].args == args
    assert out.escalate_offered is False


# ---------------------------------------------------------------------------
# 3. escalate 剧本 → SUTOutput.escalate_offered True
# ---------------------------------------------------------------------------


def test_chat_loop_agent_escalate_offered() -> None:
    """offer_deep_research 置 escalate_offered + tool_choice=none → 收尾圈 →
    SUTOutput.escalate_offered True。"""
    import asyncio

    def _set_escalate(state: ChatLoopState) -> None:
        state.escalate_offered = True
        state.tool_choice = "none"

    args = {"reason": "需要深度尽调"}
    scripted = ScriptedStepClient(
        steps=[
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
    agent = ChatLoopAgent(
        llm=_sut_llm(scripted), tool_hub=hub, context_deps=_deps()
    )

    out = asyncio.run(agent.run(user_input="帮我深度研究茅台", request_id="r-escalate"))

    assert out.escalate_offered is True
    # offer_deep_research 是控制类业务工具 → 进 tool_calls(非 search_tools 不排除)
    assert [tc.tool_name for tc in out.tool_calls] == ["offer_deep_research"]


# ---------------------------------------------------------------------------
# 4. search_tools 调用被排除出 tool_calls(spec § 3.2 机制工具非业务工具)
# ---------------------------------------------------------------------------


def test_chat_loop_agent_excludes_search_tools_from_tool_calls() -> None:
    """search_tools(渐进披露的文档检索)不算业务工具调用 → 排除出 SUTOutput.tool_calls。"""
    import asyncio

    quote_args = {"ts_code": "600519.SH"}
    search_args = {"query": "get_stock_quote"}
    # 圈1:先 search_tools 拿文档;圈2:正经调 get_stock_quote;圈3:直答。
    scripted = ScriptedStepClient(
        steps=[
            _step(tool_calls=[_call("search_tools", search_args)]),
            _step(tool_calls=[_call("get_stock_quote", quote_args)]),
            _step(content="茅台 1820.5 元。", finish_reason="stop"),
        ]
    )
    hub = FakeToolHub(
        results_per_round=[
            [_ok_result("search_tools", search_args, {"docs": []})],
            [_ok_result("get_stock_quote", quote_args)],
        ]
    )
    agent = ChatLoopAgent(
        llm=_sut_llm(scripted), tool_hub=hub, context_deps=_deps()
    )

    out = asyncio.run(agent.run(user_input="查一下 600519.SH 的股价", request_id="r-search"))

    names = [tc.tool_name for tc in out.tool_calls]
    assert "search_tools" not in names, "search_tools 应被排除出业务 tool_calls"
    assert names == ["get_stock_quote"]


def test_chat_loop_agent_bad_json_args_fallback_to_empty() -> None:
    """坏 JSON arguments 容错:json.loads 失败用 {}(不让整个评测炸)。"""
    import asyncio

    # 直接构造一个 arguments 为非法 JSON 的 StepToolCall(绕过 _call 的 json.dumps)
    bad_call = StepToolCall(id="bad-1", name="get_stock_quote", arguments="{not json")
    scripted = ScriptedStepClient(
        steps=[
            _step(tool_calls=[bad_call]),
            _step(content="参数有误,无法查询。", finish_reason="stop"),
        ]
    )
    hub = FakeToolHub(
        results_per_round=[
            [
                ToolResult(
                    tool_name="get_stock_quote",
                    args={},
                    success=False,
                    output=None,
                    error="[参数格式错误]",
                    latency_ms=0,
                )
            ]
        ]
    )
    agent = ChatLoopAgent(
        llm=_sut_llm(scripted), tool_hub=hub, context_deps=_deps()
    )

    out = asyncio.run(agent.run(user_input="查一下股价", request_id="r-badjson"))

    assert [tc.tool_name for tc in out.tool_calls] == ["get_stock_quote"]
    assert out.tool_calls[0].args == {}


# ---------------------------------------------------------------------------
# 5. golden 兼容:v0-chat-001 用 ChatLoopAgent 跑 run_one 全链不炸
# ---------------------------------------------------------------------------


def test_golden_v0_chat_001_runs_with_chat_loop_agent(
    mock_llm_client: MockLLMClient,
    db_session,
) -> None:
    """golden_set_v0.jsonl 的 v0-chat-001 用 ChatLoopAgent 跑 run_one 全链不炸 —— 确认
    eval_runner.run_one 对新 SUT 兼容(协议不变是设计点)。Scripted 剧本对齐 expected
    tool_calls(get_stock_quote ts_code=600519.SH)。"""
    cases = load_golden_jsonl(_GOLDEN_PATH)
    case = next(c for c in cases if c.case_id == "v0-chat-001")

    trace = TraceService(session_factory=lambda: contextlib.nullcontext(db_session))
    recorder = EvalRecorder(session_factory=lambda: contextlib.nullcontext(db_session))

    args = {"ts_code": "600519.SH"}
    scripted = ScriptedStepClient(
        steps=[
            _step(tool_calls=[_call("get_stock_quote", args)]),
            _step(content="600519.SH 当前股价 1820.5 元。", finish_reason="stop"),
        ]
    )
    agent = ChatLoopAgent(
        llm=_sut_llm(scripted),
        tool_hub=FakeToolHub(results_per_round=[[_ok_result("get_stock_quote", args)]]),
        context_deps=_deps(),
    )

    judge_llm = LLMService(client=mock_llm_client)
    judge = Judge(llm=judge_llm, judge_tier="balanced")
    runner = EvalRunner(sut=agent, judge=judge, trace_service=trace, recorder=recorder)

    result = runner.run_one(case)

    assert result.case_id == "v0-chat-001"
    assert result.scores.factuality is not None
    # ChatLoopAgent 产出了 tool_calls → tool_correctness 被评分(非 None)
    assert result.scores.tool_correctness is not None

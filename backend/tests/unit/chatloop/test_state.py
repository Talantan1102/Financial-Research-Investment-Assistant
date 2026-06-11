"""ChatLoopState / ToolLedger 纯数据层测试(L0,无 I/O)。

覆盖(≥12 条):
1. args_hash 稳定性(键序无关)
2. record + find_success
3. signature_set 按圈
4. fail_count
5. to_extractor_view 只含 success
6. apply_step — 含 tool_calls 形态
7. apply_step — 不含 tool_calls 形态
8. apply_step — reasoning 绝不出现
9. apply_step — final_response 在自然停时被设置
10. apply_step — final_response 在有 tool_calls 时不设置
11. apply_step — 预算累计
12. apply_results — 正常配对(每 call 一条 tool 消息,顺序)
13. apply_results — 长度不匹配抛 AssertionError
14. apply_results — 错误结果格式 [ERROR]
15. apply_results — success=False,error 字段进 content
16. to_extractor_view — cache_key 为 None 时仍包含条目且 cache_id=None
"""

from __future__ import annotations

import pytest
from app.agents.schemas import ToolResult
from app.chatloop.state import (
    ChatLoopState,
    LedgerEntry,
    ToolLedger,
    apply_results,
    apply_step,
    args_hash_of,
    turn_summary,
)
from app.services.llm_step import StepResult, StepToolCall

# ---------------------------------------------------------------------------
# 辅助构建函数
# ---------------------------------------------------------------------------


def _make_state(msgs: list[dict] | None = None) -> ChatLoopState:
    return ChatLoopState(
        user_id="u1",
        session_id="s1",
        request_id="r1",
        messages=msgs if msgs is not None else [{"role": "user", "content": "hi"}],
    )


def _make_step_result(
    content: str = "ok",
    finish_reason: str = "stop",
    tool_calls: list[StepToolCall] | None = None,
    prompt_tokens: int = 100,
    completion_tokens: int = 20,
    cached_tokens: int = 0,
    cost_cny: float = 0.001,
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


def _make_tool_call(
    call_id: str = "c1", name: str = "get_stock_quote", arguments: str = '{"ts_code":"600519.SH"}'
) -> StepToolCall:
    return StepToolCall(id=call_id, name=name, arguments=arguments)


def _make_tool_result(
    tool_name: str = "get_stock_quote",
    success: bool = True,
    output: dict | None = None,
    error: str | None = None,
) -> ToolResult:
    return ToolResult(
        tool_name=tool_name,
        args={"ts_code": "600519.SH"},
        success=success,
        output=output if output is not None else {"price": 1700},
        error=error,
        latency_ms=50,
    )


# ---------------------------------------------------------------------------
# 1. args_hash 稳定性(键序无关)
# ---------------------------------------------------------------------------


def test_args_hash_key_order_independent():
    """不同键序产生相同哈希。"""
    h1 = args_hash_of({"a": 1, "b": 2})
    h2 = args_hash_of({"b": 2, "a": 1})
    assert h1 == h2


def test_args_hash_different_values_differ():
    """值不同则哈希不同。"""
    h1 = args_hash_of({"ts_code": "600519.SH"})
    h2 = args_hash_of({"ts_code": "000001.SZ"})
    assert h1 != h2


def test_args_hash_length_16():
    """哈希固定 16 位。"""
    h = args_hash_of({"x": 1})
    assert len(h) == 16


# ---------------------------------------------------------------------------
# 2. record + find_success
# ---------------------------------------------------------------------------


def test_record_and_find_success():
    """record 后 find_success 能找到 success=True 的条目。"""
    ledger = ToolLedger()
    ledger.record(
        step=0,
        tool_name="get_stock_quote",
        args={"ts_code": "600519.SH"},
        digest="price=1700",
        success=True,
    )
    entry = ledger.find_success(tool_name="get_stock_quote", args={"ts_code": "600519.SH"})
    assert entry is not None
    assert entry.tool_name == "get_stock_quote"
    assert entry.success is True


def test_find_success_returns_none_for_failed_entry():
    """find_success 对 success=False 的条目返回 None。"""
    ledger = ToolLedger()
    ledger.record(
        step=0,
        tool_name="get_stock_quote",
        args={"ts_code": "600519.SH"},
        digest="err",
        success=False,
    )
    result = ledger.find_success(tool_name="get_stock_quote", args={"ts_code": "600519.SH"})
    assert result is None


def test_find_success_returns_latest_success():
    """多条同签名 success 时返回最新(最后一条)。"""
    ledger = ToolLedger()
    ledger.record(step=0, tool_name="t", args={"x": 1}, digest="old", success=True)
    ledger.record(step=1, tool_name="t", args={"x": 1}, digest="new", success=True)
    entry = ledger.find_success(tool_name="t", args={"x": 1})
    assert entry is not None
    assert entry.digest == "new"


# ---------------------------------------------------------------------------
# 3. signature_set 按圈
# ---------------------------------------------------------------------------


def test_signature_set_filters_by_step():
    """signature_set(step) 只返回该圈的签名。"""
    ledger = ToolLedger()
    ledger.record(step=0, tool_name="a", args={"k": 1}, digest="d", success=True)
    ledger.record(step=0, tool_name="b", args={"k": 2}, digest="d", success=True)
    ledger.record(step=1, tool_name="a", args={"k": 1}, digest="d", success=True)

    sigs_step0 = ledger.signature_set(0)
    sigs_step1 = ledger.signature_set(1)

    assert len(sigs_step0) == 2
    assert len(sigs_step1) == 1
    # step1 的签名与 step0 中同参数的 a 相同
    a_sig = LedgerEntry(
        step=0,
        tool_name="a",
        args_hash=args_hash_of({"k": 1}),
        digest="d",
        success=True,
    ).signature
    assert a_sig in sigs_step1


# ---------------------------------------------------------------------------
# 4. fail_count
# ---------------------------------------------------------------------------


def test_fail_count_counts_failures_only():
    """fail_count 只统计 success=False 的同签名条目。"""
    ledger = ToolLedger()
    args = {"ts_code": "600519.SH"}
    sig = f"get_stock_quote:{args_hash_of(args)}"

    ledger.record(step=0, tool_name="get_stock_quote", args=args, digest="e1", success=False)
    ledger.record(step=1, tool_name="get_stock_quote", args=args, digest="e2", success=False)
    ledger.record(step=2, tool_name="get_stock_quote", args=args, digest="ok", success=True)

    assert ledger.fail_count(sig) == 2


# ---------------------------------------------------------------------------
# 5. to_extractor_view 只含 success
# ---------------------------------------------------------------------------


def test_to_extractor_view_only_success():
    """to_extractor_view 只返回 success=True 的条目。"""
    ledger = ToolLedger()
    ledger.record(step=0, tool_name="a", args={"x": 1}, digest="ok", success=True, cache_key="ck1")
    ledger.record(step=0, tool_name="b", args={"x": 2}, digest="fail", success=False)

    view = ledger.to_extractor_view()
    assert len(view) == 1
    assert view[0]["tool_name"] == "a"
    assert view[0]["summary"] == "ok"
    assert view[0]["cache_id"] == "ck1"


def test_to_extractor_view_cache_key_none_included():
    """cache_key 为 None 时条目仍出现,cache_id=None。"""
    ledger = ToolLedger()
    ledger.record(step=0, tool_name="a", args={"x": 1}, digest="sum", success=True, cache_key=None)

    view = ledger.to_extractor_view()
    assert len(view) == 1
    assert view[0]["cache_id"] is None


# ---------------------------------------------------------------------------
# 6. apply_step — 含 tool_calls 形态
# ---------------------------------------------------------------------------


def test_apply_step_with_tool_calls_appends_correct_message():
    """有 tool_calls 时 assistant 消息含 tool_calls 键,格式符合 OpenAI。"""
    state = _make_state()
    tc = _make_tool_call("c1", "get_stock_quote", '{"ts_code":"600519.SH"}')
    step = _make_step_result(content="我查一下", finish_reason="tool_calls", tool_calls=[tc])
    state = apply_step(state, step)

    last = state.messages[-1]
    assert last["role"] == "assistant"
    assert "tool_calls" in last
    assert len(last["tool_calls"]) == 1
    assert last["tool_calls"][0]["id"] == "c1"
    assert last["tool_calls"][0]["type"] == "function"
    assert last["tool_calls"][0]["function"]["name"] == "get_stock_quote"


# ---------------------------------------------------------------------------
# 7. apply_step — 不含 tool_calls 形态
# ---------------------------------------------------------------------------


def test_apply_step_without_tool_calls_no_tool_calls_key():
    """无 tool_calls 时 assistant 消息不携带 tool_calls 键。"""
    state = _make_state()
    step = _make_step_result(content="茅台现价 1700", finish_reason="stop")
    state = apply_step(state, step)

    last = state.messages[-1]
    assert last["role"] == "assistant"
    assert "tool_calls" not in last


# ---------------------------------------------------------------------------
# 8. apply_step — reasoning 绝不出现
# ---------------------------------------------------------------------------


def test_apply_step_never_carries_reasoning():
    """assistant 消息中不存在 reasoning 或 reasoning_content 字段。"""
    state = _make_state()
    step = _make_step_result(content="分析结果", finish_reason="stop")
    state = apply_step(state, step)

    last = state.messages[-1]
    assert "reasoning" not in last
    assert "reasoning_content" not in last
    # 只有 role 和 content
    assert set(last.keys()) == {"role", "content"}


def test_apply_step_with_tool_calls_never_carries_reasoning():
    """含 tool_calls 的 assistant 消息也不含 reasoning 字段。"""
    state = _make_state()
    tc = _make_tool_call()
    step = _make_step_result(content="", finish_reason="tool_calls", tool_calls=[tc])
    state = apply_step(state, step)

    last = state.messages[-1]
    assert "reasoning" not in last
    assert "reasoning_content" not in last
    assert set(last.keys()) == {"role", "content", "tool_calls"}


# ---------------------------------------------------------------------------
# 9. apply_step — final_response 在自然停时被设置
# ---------------------------------------------------------------------------


def test_apply_step_sets_final_response_on_natural_stop():
    """finish_reason='stop' 且无 tool_calls → final_response=content。"""
    state = _make_state()
    step = _make_step_result(content="最终答案", finish_reason="stop")
    state = apply_step(state, step)
    assert state.final_response == "最终答案"


# ---------------------------------------------------------------------------
# 10. apply_step — final_response 在有 tool_calls 时不设置
# ---------------------------------------------------------------------------


def test_apply_step_no_final_response_when_tool_calls():
    """有 tool_calls 时 final_response 不被设置。"""
    state = _make_state()
    tc = _make_tool_call()
    step = _make_step_result(content="我查一下", finish_reason="tool_calls", tool_calls=[tc])
    state = apply_step(state, step)
    assert state.final_response is None


# ---------------------------------------------------------------------------
# 11. apply_step — 预算累计
# ---------------------------------------------------------------------------


def test_apply_step_accumulates_budget():
    """连续两圈预算正确累计。"""
    state = _make_state()
    s1 = _make_step_result(
        content="",
        finish_reason="tool_calls",
        tool_calls=[_make_tool_call()],
        prompt_tokens=100,
        completion_tokens=20,
        cost_cny=0.010,
    )
    s2 = _make_step_result(
        content="done",
        finish_reason="stop",
        prompt_tokens=200,
        completion_tokens=50,
        cost_cny=0.020,
    )
    state = apply_step(state, s1)
    # apply_results 用空列表模拟(不影响预算计算)
    state = apply_step(state, s2)

    assert state.budget_spent_tokens == 100 + 20 + 200 + 50
    assert abs(state.budget_spent_cny - 0.030) < 1e-9
    assert state.step == 2


# ---------------------------------------------------------------------------
# 12. apply_results — 正常配对
# ---------------------------------------------------------------------------


def test_apply_results_appends_tool_messages_in_order():
    """apply_results 按 calls 顺序追加 tool 消息,tool_call_id 对应正确。"""
    state = _make_state()
    # 先 apply_step 以符合协议(有 assistant 消息在先)
    tc1 = _make_tool_call("c1", "get_stock_quote", '{"ts_code":"600519.SH"}')
    tc2 = _make_tool_call("c2", "web_search", '{"query":"茅台"}')
    step = _make_step_result(content="", finish_reason="tool_calls", tool_calls=[tc1, tc2])
    state = apply_step(state, step)

    r1 = _make_tool_result("get_stock_quote", success=True, output={"price": 1700})
    r2 = _make_tool_result("web_search", success=True, output={"results": ["a"]})
    state = apply_results(state, [r1, r2], [tc1, tc2])

    tool_msgs = [m for m in state.messages if m["role"] == "tool"]
    assert len(tool_msgs) == 2
    assert tool_msgs[0]["tool_call_id"] == "c1"
    assert tool_msgs[1]["tool_call_id"] == "c2"


# ---------------------------------------------------------------------------
# 13. apply_results — 长度不匹配抛 AssertionError
# ---------------------------------------------------------------------------


def test_apply_results_length_mismatch_raises_assertion():
    """calls 与 results 长度不等时抛 AssertionError。"""
    state = _make_state()
    tc = _make_tool_call()
    with pytest.raises(AssertionError):
        apply_results(state, [], [tc])  # 1 call, 0 results


def test_apply_results_empty_ok():
    """calls=[] results=[] 时不报错。"""
    state = _make_state()
    state = apply_results(state, [], [])
    # messages 不变
    assert len(state.messages) == 1


# ---------------------------------------------------------------------------
# 14. apply_results — 错误结果格式 [ERROR]
# ---------------------------------------------------------------------------


def test_apply_results_error_result_content_format():
    """success=False 时 content 以 [ERROR] 开头。"""
    state = _make_state()
    tc = _make_tool_call("c1")
    step = _make_step_result(content="", finish_reason="tool_calls", tool_calls=[tc])
    state = apply_step(state, step)

    r = _make_tool_result(success=False, error="ts_code 格式错误", output=None)
    state = apply_results(state, [r], [tc])

    tool_msg = next(m for m in state.messages if m["role"] == "tool")
    assert tool_msg["content"].startswith("[ERROR]")
    assert "ts_code 格式错误" in tool_msg["content"]


# ---------------------------------------------------------------------------
# 15. apply_results — success=False, error 字段进 content
# ---------------------------------------------------------------------------


def test_apply_results_error_without_explicit_message():
    """error=None 的失败结果用 'unknown error' 兜底。"""
    state = _make_state()
    tc = _make_tool_call("c1")
    step = _make_step_result(content="", finish_reason="tool_calls", tool_calls=[tc])
    state = apply_step(state, step)

    r = ToolResult(
        tool_name="get_stock_quote",
        args={"ts_code": "600519.SH"},
        success=False,
        output=None,
        error=None,
        latency_ms=10,
    )
    state = apply_results(state, [r], [tc])

    tool_msg = next(m for m in state.messages if m["role"] == "tool")
    assert "[ERROR]" in tool_msg["content"]
    assert "unknown error" in tool_msg["content"]


# ---------------------------------------------------------------------------
# 17. args_hash 嵌套 dict 键序无关(评审遗留 Minor)
# ---------------------------------------------------------------------------


def test_args_hash_nested_dict_key_order_independent():
    """嵌套 dict 的键序不同不影响哈希结果。"""
    h1 = args_hash_of({"outer": {"z": 3, "a": 1}, "x": 0})
    h2 = args_hash_of({"x": 0, "outer": {"a": 1, "z": 3}})
    assert h1 == h2


# ---------------------------------------------------------------------------
# ⑦ token 拆分累计 + turn_summary 账单
# ---------------------------------------------------------------------------


def test_apply_step_accumulates_token_breakdown():
    """apply_step 累计 prompt/completion/cached;turn_summary 算出命中率。"""
    st = ChatLoopState(user_id="u", session_id="s", request_id="r", messages=[])
    apply_step(st, _make_step_result(finish_reason="tool_calls", tool_calls=[_make_tool_call()],
                                     prompt_tokens=1000, completion_tokens=100, cached_tokens=800))
    apply_step(st, _make_step_result(finish_reason="stop",
                                     prompt_tokens=2000, completion_tokens=50, cached_tokens=1900))
    assert st.prompt_tokens_total == 3000
    assert st.completion_tokens_total == 150
    assert st.cached_tokens_total == 2700
    s = turn_summary(st)
    assert s["llm_calls"] == 2
    assert s["prompt_tokens"] == 3000 and s["cached_tokens"] == 2700
    assert s["cache_hit_rate"] == round(2700 / 3000, 3)


def test_turn_summary_zero_prompt_no_div_zero():
    """无任何 LLM 调用时 cache_hit_rate=0,不除零。"""
    st = ChatLoopState(user_id="u", session_id="s", request_id="r", messages=[])
    assert turn_summary(st)["cache_hit_rate"] == 0.0
    assert turn_summary(st)["llm_calls"] == 0

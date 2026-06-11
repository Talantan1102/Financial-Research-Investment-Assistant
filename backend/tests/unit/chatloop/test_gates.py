"""四道闸 / 打转检测 / 烧签名纯谓词测试(L0,无 I/O)。

覆盖(≥12 条):
check_gates:
  1. 无任何超限 → None
  2. step 达 max_steps → "max_steps"
  3. 金额超预算 → "budget"
  4. token 超预算 → "budget"
  5. 同时超 steps 与 budget → "max_steps"(顺序优先)
spinning:
  6. 连续两圈签名集完全相同且非空 → "spinning"
  7. 两圈签名集不同(换 args)→ None
  8. 当前圈空集 → None(不误判)
  9. step < 2 时不检 spinning
  10. 三个工具的集合完全相同也命中
filter_burned:
  11. burned_signatures 为空 → 全部放行,被拒列表为空
  12. 调用命中 burned_signatures → 被剔除,返回被拒签名
  13. 部分命中(2 放行 1 被拒)
  新增. 坏 JSON arguments → 放行进 allowed,rejected 为空(不炸穿 ToolLoop)
update_burned:
  14. fail_count 达 burn_threshold → 签名进 burned_signatures
  15. fail_count 未达阈值(2 次)→ 不入 burned
  16. 幂等:重复调用 update_burned 不重复添加(set 天然)
"""

from __future__ import annotations

from typing import Any

from app.chatloop.gates import (
    GateConfig,
    budget_margin_exhausted,
    check_gates,
    filter_burned,
    update_burned,
)
from app.chatloop.state import ChatLoopState, args_hash_of
from app.services.llm_step import StepToolCall

# ---------------------------------------------------------------------------
# 辅助构建
# ---------------------------------------------------------------------------


def _make_state(
    step: int = 0,
    budget_cny: float = 0.0,
    budget_tokens: int = 0,
    burned: set[str] | None = None,
) -> ChatLoopState:
    return ChatLoopState(
        user_id="u1",
        session_id="s1",
        request_id="r1",
        messages=[{"role": "user", "content": "hi"}],
        step=step,
        budget_spent_cny=budget_cny,
        budget_spent_tokens=budget_tokens,
        burned_signatures=burned if burned is not None else set(),
    )


def _cfg(**kw: Any) -> GateConfig:
    defaults: dict[str, Any] = {
        "max_steps": 12,
        "max_cny": 0.10,
        "max_tokens": 120_000,
        "burn_threshold": 3,
    }
    defaults.update(kw)
    return GateConfig(**defaults)


def _make_call(name: str, args: dict) -> StepToolCall:
    import json

    return StepToolCall(id=f"{name}-id", name=name, arguments=json.dumps(args))


def _sig(name: str, args: dict) -> str:
    return f"{name}:{args_hash_of(args)}"


def _record_calls(state: ChatLoopState, step: int, calls: list[tuple[str, dict]]) -> None:
    """向 ledger 记账一组 (tool_name, args),均 success=True。"""
    for name, args in calls:
        state.ledger.record(
            step=step,
            tool_name=name,
            args=args,
            digest="ok",
            success=True,
        )


# ---------------------------------------------------------------------------
# 1. 无任何超限 → None
# ---------------------------------------------------------------------------


def test_check_gates_no_limit_returns_none():
    state = _make_state(step=0, budget_cny=0.0, budget_tokens=0)
    cfg = _cfg()
    assert check_gates(state, cfg) is None


# ---------------------------------------------------------------------------
# 2. step 达 max_steps → "max_steps"
# ---------------------------------------------------------------------------


def test_check_gates_max_steps_hit():
    state = _make_state(step=12)
    cfg = _cfg(max_steps=12)
    assert check_gates(state, cfg) == "max_steps"


def test_check_gates_step_below_max_ok():
    state = _make_state(step=11)
    cfg = _cfg(max_steps=12)
    assert check_gates(state, cfg) is None


# ---------------------------------------------------------------------------
# 3. 金额超预算 → "budget"
# ---------------------------------------------------------------------------


def test_check_gates_cny_over_budget():
    state = _make_state(step=0, budget_cny=0.11)
    cfg = _cfg(max_cny=0.10)
    assert check_gates(state, cfg) == "budget"


def test_check_gates_cny_exact_limit():
    """等于阈值也触发(>=)。"""
    state = _make_state(step=0, budget_cny=0.10)
    cfg = _cfg(max_cny=0.10)
    assert check_gates(state, cfg) == "budget"


# ---------------------------------------------------------------------------
# 4. token 超预算 → "budget"
# ---------------------------------------------------------------------------


def test_check_gates_tokens_over_budget():
    state = _make_state(step=0, budget_tokens=120_001)
    cfg = _cfg(max_tokens=120_000)
    assert check_gates(state, cfg) == "budget"


# ---------------------------------------------------------------------------
# 5. 同时超 steps 与 budget → "max_steps" 优先
# ---------------------------------------------------------------------------


def test_check_gates_steps_priority_over_budget():
    state = _make_state(step=12, budget_cny=0.50)
    cfg = _cfg(max_steps=12, max_cny=0.10)
    result = check_gates(state, cfg)
    assert result == "max_steps"


# ---------------------------------------------------------------------------
# 6. 连续两圈签名集完全相同且非空 → "spinning"
# ---------------------------------------------------------------------------


def test_check_gates_spinning_detected():
    state = _make_state(step=2)
    calls = [("get_stock_quote", {"ts_code": "600519.SH"})]
    _record_calls(state, step=1, calls=calls)  # prev round
    _record_calls(state, step=2, calls=calls)  # current round — identical
    cfg = _cfg()
    assert check_gates(state, cfg) == "spinning"


# ---------------------------------------------------------------------------
# 7. 两圈签名集不同(换 args)→ None
# ---------------------------------------------------------------------------


def test_check_gates_no_spinning_when_args_differ():
    state = _make_state(step=2)
    _record_calls(state, step=1, calls=[("get_stock_quote", {"ts_code": "600519.SH"})])
    _record_calls(state, step=2, calls=[("get_stock_quote", {"ts_code": "000001.SZ"})])
    cfg = _cfg()
    assert check_gates(state, cfg) is None


# ---------------------------------------------------------------------------
# 8. 当前圈空集 → None(不误判)
# ---------------------------------------------------------------------------


def test_check_gates_no_spinning_on_empty_current():
    state = _make_state(step=2)
    _record_calls(state, step=1, calls=[("get_stock_quote", {"ts_code": "600519.SH"})])
    # step=2 没有任何记录 → 空集
    cfg = _cfg()
    assert check_gates(state, cfg) is None


# ---------------------------------------------------------------------------
# 9. step < 2 时不检 spinning
# ---------------------------------------------------------------------------


def test_check_gates_no_spinning_when_step_lt_2():
    state = _make_state(step=1)
    _record_calls(state, step=0, calls=[("t", {"x": 1})])
    _record_calls(state, step=1, calls=[("t", {"x": 1})])
    cfg = _cfg()
    # step=1 < 2,不检 spinning
    assert check_gates(state, cfg) is None


# ---------------------------------------------------------------------------
# 10. 三个工具的集合完全相同也命中
# ---------------------------------------------------------------------------


def test_check_gates_spinning_with_multiple_tools():
    state = _make_state(step=3)
    three_calls = [
        ("tool_a", {"k": "v1"}),
        ("tool_b", {"k": "v2"}),
        ("tool_c", {"k": "v3"}),
    ]
    _record_calls(state, step=2, calls=three_calls)
    _record_calls(state, step=3, calls=three_calls)
    cfg = _cfg()
    assert check_gates(state, cfg) == "spinning"


# ---------------------------------------------------------------------------
# 11. burned 为空 → 全部放行
# ---------------------------------------------------------------------------


def test_filter_burned_empty_burned_passes_all():
    state = _make_state(burned=set())
    calls = [
        _make_call("get_stock_quote", {"ts_code": "600519.SH"}),
        _make_call("web_search", {"query": "茅台"}),
    ]
    allowed, rejected = filter_burned(calls, state)
    assert len(allowed) == 2
    assert rejected == []


# ---------------------------------------------------------------------------
# 12. 命中 burned_signatures → 被剔除,返回被拒签名
# ---------------------------------------------------------------------------


def test_filter_burned_rejects_burned_call():
    args = {"ts_code": "600519.SH"}
    sig = _sig("get_stock_quote", args)
    state = _make_state(burned={sig})
    calls = [_make_call("get_stock_quote", args)]
    allowed, rejected = filter_burned(calls, state)
    assert allowed == []
    assert sig in rejected


# ---------------------------------------------------------------------------
# 13. 部分命中(2 放 1 拒)
# ---------------------------------------------------------------------------


def test_filter_burned_partial_match():
    burned_args = {"ts_code": "600519.SH"}
    burned_sig = _sig("get_stock_quote", burned_args)
    state = _make_state(burned={burned_sig})

    call1 = _make_call("get_stock_quote", burned_args)  # 被拒
    call2 = _make_call("web_search", {"query": "茅台"})  # 放行
    call3 = _make_call("get_fin_data", {"ts_code": "600519.SH"})  # 放行

    allowed, rejected = filter_burned([call1, call2, call3], state)
    assert len(allowed) == 2
    assert len(rejected) == 1
    assert rejected[0] == burned_sig
    # call2, call3 放行
    allowed_names = {c.name for c in allowed}
    assert "web_search" in allowed_names
    assert "get_fin_data" in allowed_names


# ---------------------------------------------------------------------------
# 新增:坏 JSON arguments 的 call 放行进 allowed(不炸穿 ToolLoop)
# ---------------------------------------------------------------------------


def test_filter_burned_bad_json_call_passes_through():
    """call.parsed_args 对坏 JSON 抛 ValueError → 放行进 allowed,rejected 为空。

    模型流式可能产出残缺 JSON;filter_burned 不应炸穿 ToolLoop,
    应交 ToolHub schema 校验产指导性错误喂回,由自纠回路接住。
    """
    state = _make_state(burned=set())
    bad_call = StepToolCall(id="bad-id", name="get_stock_quote", arguments="{not json")
    allowed, rejected = filter_burned([bad_call], state)
    assert bad_call in allowed
    assert rejected == []


# ---------------------------------------------------------------------------
# 14. fail_count 达 burn_threshold → 签名入 burned_signatures
# ---------------------------------------------------------------------------


def test_update_burned_adds_when_threshold_reached():
    state = _make_state()
    cfg = _cfg(burn_threshold=3)
    args = {"ts_code": "600519.SH"}
    sig = _sig("get_stock_quote", args)
    # 记录 3 次失败
    for _ in range(3):
        state.ledger.record(
            step=0,
            tool_name="get_stock_quote",
            args=args,
            digest="err",
            success=False,
        )
    update_burned(state, cfg)
    assert sig in state.burned_signatures


# ---------------------------------------------------------------------------
# 15. fail_count 未达阈值(2 次)→ 不入 burned
# ---------------------------------------------------------------------------


def test_update_burned_does_not_add_below_threshold():
    state = _make_state()
    cfg = _cfg(burn_threshold=3)
    args = {"ts_code": "600519.SH"}
    sig = _sig("get_stock_quote", args)
    # 只记录 2 次失败
    for _ in range(2):
        state.ledger.record(
            step=0,
            tool_name="get_stock_quote",
            args=args,
            digest="err",
            success=False,
        )
    update_burned(state, cfg)
    assert sig not in state.burned_signatures


# ---------------------------------------------------------------------------
# 16. 幂等:重复调用 update_burned 不重复添加(set 天然)
# ---------------------------------------------------------------------------


def test_update_burned_idempotent():
    state = _make_state()
    cfg = _cfg(burn_threshold=3)
    args = {"ts_code": "600519.SH"}
    sig = _sig("get_stock_quote", args)
    for _ in range(5):
        state.ledger.record(
            step=0,
            tool_name="get_stock_quote",
            args=args,
            digest="err",
            success=False,
        )
    update_burned(state, cfg)
    update_burned(state, cfg)
    # set 天然去重,只存在一次
    count = sum(1 for s in state.burned_signatures if s == sig)
    assert count == 1


# ---------------------------------------------------------------------------
# ④(a) repeated_failures — 跨签名连续失败
# ---------------------------------------------------------------------------


def test_check_gates_repeated_failures_across_signatures():
    """换参数硬试:5 圈签名各不同(避开 spinning/burn),连续失败 → repeated_failures。"""
    state = _make_state(step=5)
    for i in range(5):
        state.ledger.record(
            step=i + 1, tool_name="query_kb", args={"symbol": f"x{i}"}, digest="err", success=False
        )
    cfg = _cfg(max_consecutive_failures=5)
    assert check_gates(state, cfg) == "repeated_failures"


def test_check_gates_repeated_failures_reset_on_success():
    state = _make_state(step=5)
    for i in range(4):
        state.ledger.record(
            step=i + 1, tool_name="query_kb", args={"symbol": f"x{i}"}, digest="err", success=False
        )
    state.ledger.record(
        step=5, tool_name="query_kb", args={"symbol": "ok"}, digest="ok", success=True
    )
    cfg = _cfg(max_consecutive_failures=5)
    assert check_gates(state, cfg) is None


def test_check_gates_repeated_failures_below_threshold():
    state = _make_state(step=4)
    for i in range(4):
        state.ledger.record(
            step=i + 1, tool_name="query_kb", args={"symbol": f"x{i}"}, digest="err", success=False
        )
    cfg = _cfg(max_consecutive_failures=5)
    assert check_gates(state, cfg) is None


# ---------------------------------------------------------------------------
# ④(b) budget_margin_exhausted — 分发前预算余量判定
# ---------------------------------------------------------------------------


def test_budget_margin_exhausted_by_cny():
    # 上限 0.10,余量阈值 = 0.10*0.2 = 0.02;已花 0.085 → 剩 0.015 < 0.02 → True
    state = _make_state(budget_cny=0.085)
    assert budget_margin_exhausted(state, _cfg(max_cny=0.10)) is True


def test_budget_margin_exhausted_by_tokens():
    # 上限 120000,阈值 24000;已花 119000 → 剩 1000 < 24000 → True
    state = _make_state(budget_tokens=119_000)
    assert budget_margin_exhausted(state, _cfg(max_tokens=120_000)) is True


def test_budget_margin_sufficient():
    state = _make_state(budget_cny=0.05, budget_tokens=50_000)
    assert budget_margin_exhausted(state, _cfg()) is False

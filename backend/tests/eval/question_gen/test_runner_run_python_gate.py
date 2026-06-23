"""判分第二门单测 — trace_has_run_python + judge_with_gate(纯函数,不启动 agent/MCP/PG)。

背景:难档自算题(requires_run_python=True,如 PE分位/TWR/归因)要求 agent 真写代码
(run_python)算,而非心算/蒙数恰好命中容差。第二道门:数字命中(ok)之外,还须执行轨迹里
真出现过 run_python 工具调用,否则该 case 判未过。requires_run_python=False 不受影响。

messages 结构(见 app/chatloop/state.py apply_step/apply_results):
- assistant 携工具调用:{"role":"assistant","tool_calls":[{"id":..,"type":"function",
  "function":{"name":"run_python","arguments":..}}]}(工具名唯一权威来源)
- tool 结果消息:{"role":"tool","tool_call_id":..,"content":..}(本仓不带 name 字段)
trace_has_run_python 同时兼容 tool-role 消息带 name 字段的 OpenAI 变体(robust)。
"""

from __future__ import annotations

from eval.question_gen.case import ComputationCase
from eval.question_gen.runner import judge_with_gate, trace_has_run_python

# ── helpers:用真实 messages 结构造正负例 ──────────────────────────────────────


def _assistant_run_python_msg() -> dict:
    """真实 assistant(tool_calls) 结构 —— 调用 run_python(apply_step 同款格式)。"""
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "run_python", "arguments": '{"code": "print(1)"}'},
            }
        ],
    }


def _assistant_other_tool_msg() -> dict:
    """assistant(tool_calls) 但调用的是别的工具(非 run_python)。"""
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "call_0",
                "type": "function",
                "function": {"name": "stock_history", "arguments": "{}"},
            }
        ],
    }


def _tool_result_msg(tool_call_id: str = "call_1") -> dict:
    """真实 tool 结果消息(apply_results 同款:role/tool_call_id/content,无 name)。"""
    return {"role": "tool", "tool_call_id": tool_call_id, "content": "{}"}


def _messages_with_run_python() -> list[dict]:
    return [
        {"role": "user", "content": "茅台当前 PE 在过去十年的分位?"},
        _assistant_other_tool_msg(),
        _tool_result_msg("call_0"),
        _assistant_run_python_msg(),
        _tool_result_msg("call_1"),
        {"role": "assistant", "content": "约 85% 分位"},
    ]


def _messages_without_run_python() -> list[dict]:
    return [
        {"role": "user", "content": "茅台当前 PE 在过去十年的分位?"},
        _assistant_other_tool_msg(),
        _tool_result_msg("call_0"),
        {"role": "assistant", "content": "约 85% 分位"},  # 没写代码,直接报数
    ]


def _rrp_case(requires: bool) -> ComputationCase:
    return ComputationCase(
        case_id="comp-gate",
        intent="PE分位",
        difficulty="复杂",
        question="茅台当前 PE 在过去十年的分位?",
        stocks=["600519.SH"],
        indicator="pe_percentile",
        window="2016-06-22~2026-06-22",
        gold=0.85,
        gold_shape="scalar",
        tolerance={"rel": 0.01},
        requires_run_python=requires,
    )


# ── trace_has_run_python ──────────────────────────────────────────────────────


def test_trace_has_run_python_positive_assistant_tool_calls():
    """assistant.tool_calls 里 function.name == run_python → True。"""
    assert trace_has_run_python(_messages_with_run_python()) is True


def test_trace_has_run_python_negative_no_run_python():
    """轨迹里只有别的工具调用 → False。"""
    assert trace_has_run_python(_messages_without_run_python()) is False


def test_trace_has_run_python_empty():
    """空轨迹 → False。"""
    assert trace_has_run_python([]) is False


def test_trace_has_run_python_tool_role_name_variant():
    """robust:兼容 tool-role 消息带 name 字段的 OpenAI 变体。"""
    messages = [
        {"role": "user", "content": "q"},
        {"role": "tool", "tool_call_id": "x", "name": "run_python", "content": "{}"},
    ]
    assert trace_has_run_python(messages) is True


def test_trace_has_run_python_robust_to_malformed():
    """脏数据(缺键/None/非 dict)不抛异常,判 False。"""
    messages = [
        None,
        "not a dict",
        {"role": "assistant"},  # 无 tool_calls
        {"role": "assistant", "tool_calls": None},
        {"role": "assistant", "tool_calls": [{"type": "function"}]},  # 无 function
        {"role": "assistant", "tool_calls": [{"function": None}]},
        {"role": "assistant", "tool_calls": [{"function": {}}]},  # 无 name
    ]
    assert trace_has_run_python(messages) is False


# ── judge_with_gate ───────────────────────────────────────────────────────────


def test_gate_requires_python_pass_when_trace_has_run_python():
    """requires_run_python=True + ok=True + 轨迹有 run_python → True。"""
    c = _rrp_case(requires=True)
    assert judge_with_gate(c, True, _messages_with_run_python()) is True


def test_gate_requires_python_blocked_when_trace_lacks_run_python():
    """requires_run_python=True + ok=True 但轨迹无 run_python → False(假阳被拦)。"""
    c = _rrp_case(requires=True)
    assert judge_with_gate(c, True, _messages_without_run_python()) is False


def test_gate_requires_python_still_fail_when_ok_false():
    """数字不对(ok=False)即便有 run_python 照样不过。"""
    c = _rrp_case(requires=True)
    assert judge_with_gate(c, False, _messages_with_run_python()) is False


def test_gate_not_required_unaffected():
    """requires_run_python=False:不受门影响,ok 直接透传(无 run_python 也过)。"""
    c = _rrp_case(requires=False)
    assert judge_with_gate(c, True, _messages_without_run_python()) is True


def test_gate_not_required_false_ok_stays_false():
    """requires_run_python=False + ok=False → False(门不会反转 ok)。"""
    c = _rrp_case(requires=False)
    assert judge_with_gate(c, False, _messages_with_run_python()) is False

"""窗口四区组装 / 降级保护名单 / CJK token 估算 — L0 纯函数测试。

覆盖(≥15 条):
四区顺序与内容:
  1. 首条 system 含三段(system_prompt / persona_block / skill_listing)全部拼入
  2. history_block 透传,位置在 system 之后、state.messages 之前
  3. 尾部动态区含 "第 N/M 步" 与 "预算剩"
  4. 尾部动态区剩余预算下界为 0

前缀稳定:
  5. 同一 deps、state 多走一圈后,重新 assemble 的前 K 条消息与上一圈逐条相等

降级:
  6. 老圈大 tool 消息(>阈值)content 被替换为含 "[全文已缓存 ref=" 与 digest
  7. role 与 tool_call_id 在降级后不变
  8. 连续两次 assemble,第二次不重复替换(幂等——digest 不会变成 digest 的 digest)

保护名单:
  9.  最近一圈大 tool 消息不降级
  10. "[ERROR]" 开头的消息不降级
  11. load_skill 的 tool 消息不降级

cache_key 反查:
  12. ledger 有对应 success 条目时 ref={cache_key}
  13. ledger 无对应条目时 ref=n/a

estimate_tokens:
  14. 全中文文本
  15. 全英文文本
  16. 混合文本

协议红线:
  17. 降级后 assistant(tool_calls) 与 tool 消息配对完整(数量相等、id 对应)
"""
from __future__ import annotations

import json
import math

from app.chatloop.context import ContextDeps, assemble_context, estimate_tokens
from app.chatloop.state import ChatLoopState, ToolLedger

# ---------------------------------------------------------------------------
# 辅助构建
# ---------------------------------------------------------------------------

_BIG = "茅" * 800  # 800 CJK 字符,远超默认阈值 1320 字符


def _make_state(
    messages: list[dict] | None = None,
    step: int = 0,
    budget_spent_cny: float = 0.0,
    ledger: ToolLedger | None = None,
) -> ChatLoopState:
    return ChatLoopState(
        user_id="u1",
        session_id="s1",
        request_id="r1",
        messages=messages if messages is not None else [{"role": "user", "content": "hi"}],
        step=step,
        budget_spent_cny=budget_spent_cny,
        ledger=ledger if ledger is not None else ToolLedger(),
    )


def _make_deps(
    system_prompt: str = "角色指令",
    persona_block: str = "用户画像",
    skill_listing: str = "技能清单",
    history_block: tuple = (),
    max_steps: int = 12,
    max_cny: float = 0.10,
    downgrade_char_threshold: int = 1320,
) -> ContextDeps:
    return ContextDeps(
        system_prompt=system_prompt,
        persona_block=persona_block,
        skill_listing=skill_listing,
        history_block=history_block,
        max_steps=max_steps,
        max_cny=max_cny,
        downgrade_char_threshold=downgrade_char_threshold,
    )


def _tool_call_msg(call_id: str, name: str, args: dict) -> dict:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
            }
        ],
    }


def _tool_result_msg(call_id: str, content: str) -> dict:
    return {"role": "tool", "tool_call_id": call_id, "content": content}


# ---------------------------------------------------------------------------
# 1. 首条 system 含三段拼接
# ---------------------------------------------------------------------------


def test_system_message_contains_all_three_parts():
    """首条消息是 system,content 含三段:system_prompt / persona_block / skill_listing。"""
    deps = _make_deps(
        system_prompt="角色指令",
        persona_block="用户画像",
        skill_listing="技能清单",
    )
    state = _make_state()
    msgs = assemble_context(state, deps)

    assert msgs[0]["role"] == "system"
    content = msgs[0]["content"]
    assert "角色指令" in content
    assert "用户画像" in content
    assert "技能清单" in content


def test_system_message_separator():
    """三段之间以 '---' 分隔符拼接。"""
    deps = _make_deps(system_prompt="A", persona_block="B", skill_listing="C")
    state = _make_state()
    msgs = assemble_context(state, deps)
    assert "---" in msgs[0]["content"]


def test_system_message_empty_parts_skipped():
    """空 persona_block 与 skill_listing 不插入多余分隔符。"""
    deps = _make_deps(system_prompt="只有这一段", persona_block="", skill_listing="")
    state = _make_state()
    msgs = assemble_context(state, deps)
    assert msgs[0]["content"] == "只有这一段"


# ---------------------------------------------------------------------------
# 2. history_block 透传,位置在 system 之后、state.messages 之前
# ---------------------------------------------------------------------------


def test_history_block_position():
    """history_block 在 system 之后、state.messages 之前。"""
    hist_msg = {"role": "user", "content": "历史 turn 摘要"}
    deps = _make_deps(history_block=(hist_msg,))
    state = _make_state(messages=[{"role": "user", "content": "当前问题"}])

    msgs = assemble_context(state, deps)

    # 索引 0 = system, 1 = history_block[0], 2 = state.messages[0]
    assert msgs[0]["role"] == "system"
    assert msgs[1] == hist_msg
    assert msgs[2] == state.messages[0]


def test_history_block_multiple_messages():
    """多条 history_block 按序透传。"""
    h1 = {"role": "user", "content": "老问题"}
    h2 = {"role": "assistant", "content": "老回答"}
    deps = _make_deps(history_block=(h1, h2))
    state = _make_state()
    msgs = assemble_context(state, deps)
    assert msgs[1] == h1
    assert msgs[2] == h2


# ---------------------------------------------------------------------------
# 3. 尾部动态区含 "第 N/M 步" 与 "预算剩"
# ---------------------------------------------------------------------------


def test_tail_message_contains_step_info():
    """尾部消息含 '第 1/12 步' 格式。"""
    deps = _make_deps(max_steps=12)
    state = _make_state(step=0)
    msgs = assemble_context(state, deps)
    tail = msgs[-1]
    assert tail["role"] == "user"
    assert "第 1/12 步" in tail["content"]


def test_tail_message_contains_budget_remaining():
    """尾部消息含 '预算剩 ¥x.xx'。"""
    deps = _make_deps(max_cny=0.10)
    state = _make_state(budget_spent_cny=0.03)
    msgs = assemble_context(state, deps)
    tail = msgs[-1]
    assert "预算剩" in tail["content"]
    assert "¥0.07" in tail["content"]


def test_tail_step_increments():
    """step=3 时尾部显示 '第 4/12 步'。"""
    deps = _make_deps(max_steps=12)
    state = _make_state(step=3)
    msgs = assemble_context(state, deps)
    assert "第 4/12 步" in msgs[-1]["content"]


# ---------------------------------------------------------------------------
# 4. 尾部剩余预算下界为 0
# ---------------------------------------------------------------------------


def test_tail_budget_remaining_floor_zero():
    """超支时剩余预算显示 ¥0.00,不显示负数。"""
    deps = _make_deps(max_cny=0.10)
    state = _make_state(budget_spent_cny=0.20)  # 超支
    msgs = assemble_context(state, deps)
    tail = msgs[-1]["content"]
    assert "¥0.00" in tail
    # 不含负号
    assert "¥-" not in tail


# ---------------------------------------------------------------------------
# 5. 前缀稳定:多走一圈后前 K 条不变
# ---------------------------------------------------------------------------


def test_prefix_stability_across_rounds():
    """同一 deps,state 追加新消息后 assemble,前 K 条与上一圈完全相同。"""
    deps = _make_deps()
    msgs_round1_input = [{"role": "user", "content": "问题"}]
    state = _make_state(messages=msgs_round1_input[:], step=0)

    round1 = assemble_context(state, deps)
    # 保存前 K 条(除尾部动态区外全部)
    K = len(round1) - 1

    # 模拟第二圈:追加 assistant + tool 消息,step+1
    state.messages.append({"role": "assistant", "content": "中间回答"})
    state.step = 1

    round2 = assemble_context(state, deps)

    # 前 K 条逐条相等(system + history + 旧 state.messages 部分)
    for i in range(K):
        assert round1[i] == round2[i], f"第 {i} 条消息在两圈之间发生变化"


# ---------------------------------------------------------------------------
# 6. 老圈大 tool 消息降级:content 含 "[全文已缓存 ref=" 与 digest
# ---------------------------------------------------------------------------


def test_downgrade_old_large_tool_message():
    """老圈大 tool 消息(>阈值)content 被降级为含 '[全文已缓存 ref=' 与 digest。"""
    big_content = "数" * 1400  # 1400 字符 > 默认阈值 1320
    call_id = "c1"

    messages = [
        {"role": "user", "content": "问"},
        _tool_call_msg(call_id, "get_stock_quote", {"ts_code": "600519.SH"}),
        _tool_result_msg(call_id, big_content),
        # 最近一圈:新的 assistant+tool
        _tool_call_msg("c2", "web_search", {"query": "茅台"}),
        _tool_result_msg("c2", "小结果"),  # 最近圈,不降级
    ]
    state = _make_state(messages=messages, step=2)
    deps = _make_deps(downgrade_char_threshold=1320)

    assemble_context(state, deps)

    # 降级改 state.messages 本体(Pydantic 构造时 deep-copy,从 state.messages 读取)
    downgraded_content = state.messages[2]["content"]
    assert "[全文已缓存 ref=" in downgraded_content
    # digest = 前 200 字符
    assert big_content[:200] in downgraded_content


# ---------------------------------------------------------------------------
# 7. 降级后 role / tool_call_id 不变
# ---------------------------------------------------------------------------


def test_downgrade_preserves_role_and_tool_call_id():
    """降级只改 content,role 与 tool_call_id 必须保持不变。"""
    call_id = "keep-me"
    big_content = "X" * 1400
    messages = [
        {"role": "user", "content": "q"},
        _tool_call_msg(call_id, "get_fin_data", {"ts_code": "600519.SH"}),
        _tool_result_msg(call_id, big_content),
        # 新圈,让 idx=2 成为老圈
        _tool_call_msg("c_new", "web_search", {"query": "x"}),
        _tool_result_msg("c_new", "small"),
    ]
    state = _make_state(messages=messages, step=2)
    deps = _make_deps()

    assemble_context(state, deps)

    # 从 state.messages 读取(Pydantic 深拷贝)
    msg = state.messages[2]
    assert msg["role"] == "tool"
    assert msg["tool_call_id"] == call_id


# ---------------------------------------------------------------------------
# 8. 幂等:连续两次 assemble,第二次不重复替换
# ---------------------------------------------------------------------------


def test_downgrade_idempotent():
    """连续两次 assemble 后,tool 消息的 content 不会变成 digest 的 digest。"""
    call_id = "idem"
    big_content = "字" * 1400
    messages = [
        {"role": "user", "content": "q"},
        _tool_call_msg(call_id, "get_stock_quote", {"ts_code": "600519.SH"}),
        _tool_result_msg(call_id, big_content),
        _tool_call_msg("c2", "web_search", {"query": "茅台"}),
        _tool_result_msg("c2", "small"),
    ]
    state = _make_state(messages=messages, step=2)
    deps = _make_deps()

    assemble_context(state, deps)
    # 从 state.messages 读取(Pydantic 深拷贝)
    content_after_first = state.messages[2]["content"]

    assemble_context(state, deps)
    content_after_second = state.messages[2]["content"]

    assert content_after_first == content_after_second


# ---------------------------------------------------------------------------
# 9. 保护:最近一圈大 tool 消息不降级
# ---------------------------------------------------------------------------


def test_latest_round_tool_message_not_downgraded():
    """最近一圈的大 tool 消息不被降级。"""
    big_content = "大" * 1400
    call_id = "latest"
    # 只有一圈:assistant + tool,属于最近一圈
    messages = [
        {"role": "user", "content": "q"},
        _tool_call_msg(call_id, "get_stock_quote", {"ts_code": "600519.SH"}),
        _tool_result_msg(call_id, big_content),
    ]
    state = _make_state(messages=messages, step=1)
    deps = _make_deps()

    assemble_context(state, deps)

    # 最近一圈,content 应原样保留(从 state.messages 读取)
    assert state.messages[2]["content"] == big_content


# ---------------------------------------------------------------------------
# 10. 保护:"[ERROR]" 开头的消息不降级
# ---------------------------------------------------------------------------


def test_error_message_not_downgraded():
    """content 以 '[ERROR]' 开头的 tool 消息永不降级,即使超过阈值。"""
    error_content = "[ERROR] " + "E" * 1400
    call_id = "err-call"
    messages = [
        {"role": "user", "content": "q"},
        _tool_call_msg(call_id, "get_stock_quote", {"ts_code": "600519.SH"}),
        _tool_result_msg(call_id, error_content),
        # 新圈,让 idx=2 成为老圈
        _tool_call_msg("c2", "web_search", {"query": "x"}),
        _tool_result_msg("c2", "small"),
    ]
    state = _make_state(messages=messages, step=2)
    deps = _make_deps()

    assemble_context(state, deps)

    assert state.messages[2]["content"] == error_content


# ---------------------------------------------------------------------------
# 11. 保护:load_skill 的 tool 消息不降级
# ---------------------------------------------------------------------------


def test_load_skill_tool_message_not_downgraded():
    """assistant tool_calls 中 name='load_skill' 的对应 tool 消息不降级。"""
    big_content = "技" * 1400
    call_id = "skill-call"
    messages = [
        {"role": "user", "content": "q"},
        _tool_call_msg(call_id, "load_skill", {"name": "portfolio_risk"}),
        _tool_result_msg(call_id, big_content),
        # 新圈
        _tool_call_msg("c2", "web_search", {"query": "x"}),
        _tool_result_msg("c2", "small"),
    ]
    state = _make_state(messages=messages, step=2)
    deps = _make_deps()

    assemble_context(state, deps)

    assert state.messages[2]["content"] == big_content


# ---------------------------------------------------------------------------
# 12. cache_key 反查:ledger 有条目时 ref={cache_key}
# ---------------------------------------------------------------------------


def test_downgrade_ref_from_ledger_cache_key():
    """ledger 有 success 条目且 cache_key 非空时,ref 写入 cache_key。"""
    call_id = "ck-call"
    big_content = "数" * 1400
    tool_name = "get_stock_quote"
    args = {"ts_code": "600519.SH"}

    ledger = ToolLedger()
    ledger.record(
        step=0,
        tool_name=tool_name,
        args=args,
        digest="价格摘要",
        success=True,
        cache_key="CACHE_XYZ",
    )

    messages = [
        {"role": "user", "content": "q"},
        _tool_call_msg(call_id, tool_name, args),
        _tool_result_msg(call_id, big_content),
        # 新圈
        _tool_call_msg("c2", "web_search", {"query": "x"}),
        _tool_result_msg("c2", "small"),
    ]
    state = _make_state(messages=messages, step=2, ledger=ledger)
    deps = _make_deps()

    assemble_context(state, deps)

    # 从 state.messages 读取(Pydantic 深拷贝)
    assert "ref=CACHE_XYZ" in state.messages[2]["content"]


# ---------------------------------------------------------------------------
# 13. cache_key 反查:ledger 无对应条目时 ref=n/a
# ---------------------------------------------------------------------------


def test_downgrade_ref_na_when_no_ledger_entry():
    """ledger 中无 success 条目时,ref 写 'n/a'。"""
    call_id = "no-entry"
    big_content = "大" * 1400
    messages = [
        {"role": "user", "content": "q"},
        _tool_call_msg(call_id, "get_fin_data", {"ts_code": "600519.SH"}),
        _tool_result_msg(call_id, big_content),
        # 新圈
        _tool_call_msg("c2", "web_search", {"query": "x"}),
        _tool_result_msg("c2", "small"),
    ]
    state = _make_state(messages=messages, step=2)
    deps = _make_deps()

    assemble_context(state, deps)

    # 从 state.messages 读取(Pydantic 深拷贝)
    assert "ref=n/a" in state.messages[2]["content"]


# ---------------------------------------------------------------------------
# 14. estimate_tokens:全中文
# ---------------------------------------------------------------------------


def test_estimate_tokens_all_cjk():
    """全 CJK 文本:N 字符 → ceil(N/1.65) tokens。"""
    text = "茅台股价"  # 4 CJK
    expected = math.ceil(4 / 1.65)
    assert estimate_tokens(text) == expected


# ---------------------------------------------------------------------------
# 15. estimate_tokens:全英文
# ---------------------------------------------------------------------------


def test_estimate_tokens_all_ascii():
    """全 ASCII 文本:N 字符 → ceil(N/4) tokens。"""
    text = "hello"  # 5 ASCII
    expected = math.ceil(5 / 4)
    assert estimate_tokens(text) == expected


# ---------------------------------------------------------------------------
# 16. estimate_tokens:混合文本
# ---------------------------------------------------------------------------


def test_estimate_tokens_mixed():
    """混合文本:CJK 按 1.65、其余按 4 分别计算。"""
    # "茅台" = 2 CJK, " 1700" = 5 ASCII
    text = "茅台 1700"
    cjk = 2
    other = len(text) - cjk  # "茅台 1700" = 7 字符,CJK=2,other=5
    expected = math.ceil(cjk / 1.65 + other / 4)
    assert estimate_tokens(text) == expected


# ---------------------------------------------------------------------------
# 17. 协议红线:降级后 assistant/tool 配对完整
# ---------------------------------------------------------------------------


def test_downgrade_pairing_intact():
    """降级后 assistant(tool_calls) 消息数量 == tool 消息数量,且 id 一一对应。"""
    big = "大" * 1400
    messages = [
        {"role": "user", "content": "q"},
        _tool_call_msg("c1", "get_stock_quote", {"ts_code": "600519.SH"}),
        _tool_result_msg("c1", big),
        _tool_call_msg("c2", "web_search", {"query": "茅台"}),
        _tool_result_msg("c2", "small"),
    ]
    state = _make_state(messages=messages, step=2)
    deps = _make_deps()

    result = assemble_context(state, deps)

    # 从结果中提取(不含 system 和 tail)
    assistant_calls = [m for m in result if m.get("role") == "assistant" and m.get("tool_calls")]
    tool_msgs = [m for m in result if m.get("role") == "tool"]

    assert len(assistant_calls) == len(tool_msgs)

    # 收集全部 assistant 发起的 tool_call ids
    expected_ids: set[str] = set()
    for am in assistant_calls:
        for tc in am["tool_calls"]:
            expected_ids.add(tc["id"])

    actual_ids = {m["tool_call_id"] for m in tool_msgs}
    assert expected_ids == actual_ids

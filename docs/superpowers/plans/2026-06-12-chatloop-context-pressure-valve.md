# Chat Loop 上下文压力安全阀 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 `assemble_context` 加一道"按总量收紧的降级安全阀"——拼完一圈的请求逼近模型窗口时,自动把降级阈值逐级调小、多榨老圈,最近一圈永远全文保护;榨到下限仍超则 best-effort 照发并发 `context_pressure` 告警事件。

**Architecture:** 纯本地改动,无新 LLM 调用。安全阀全在 `context.py:assemble_context` 内;压力信号经 `state` 两个新字段上抛,`loop.run()` 读到即发新事件 `context_pressure`(喂 ⑦ 看板)。`max_context_tokens=0` 时安全阀关闭(subagent / 既有测试零行为变化)。

**Tech Stack:** Python / pydantic(ChatLoopState)/ pytest(L0 单测)。

参见设计 spec:`docs/superpowers/specs/2026-06-12-chatloop-context-pressure-valve-design.md`

---

### Task 1: ChatLoopState 加压力信号字段

**Files:**
- Modify: `backend/app/chatloop/state.py:158`(`downgraded_msg_indices` 之后)
- Test: `backend/tests/unit/chatloop/test_state.py`

- [ ] **Step 1: 写失败测试**

在 `test_state.py` 末尾追加:

```python
def test_context_pressure_fields_default():
    from app.chatloop.state import ChatLoopState

    st = ChatLoopState(user_id="u", session_id="s", request_id="r", messages=[])
    assert st.context_pressure_passes == 0
    assert st.context_pressure_floor_hit is False
```

- [ ] **Step 2: 跑测试确认 fail**

Run: `pytest backend/tests/unit/chatloop/test_state.py::test_context_pressure_fields_default -q`
Expected: FAIL（AttributeError / ValidationError，无此字段）

- [ ] **Step 3: 加字段**

在 `state.py` `ChatLoopState` 的 `downgraded_msg_indices` 行后插入:

```python
    # ① 上下文压力安全阀:本圈按总量收紧降级跑了几轮(0=未触发);榨到下限仍超目标(best-effort)
    context_pressure_passes: int = 0
    context_pressure_floor_hit: bool = False
```

- [ ] **Step 4: 跑测试确认 pass**

Run: `pytest backend/tests/unit/chatloop/test_state.py::test_context_pressure_fields_default -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/chatloop/state.py backend/tests/unit/chatloop/test_state.py
git commit -m "feat(chatloop): ① ChatLoopState 加上下文压力信号字段"
```

---

### Task 2: 总量估算 helper

**Files:**
- Modify: `backend/app/chatloop/context.py`（`estimate_tokens` 之后）
- Test: `backend/tests/unit/chatloop/test_context.py`

- [ ] **Step 1: 写失败测试**

```python
def test_estimate_messages_tokens():
    from app.chatloop.context import _estimate_messages_tokens

    msgs = [
        {"role": "system", "content": "你好世界"},  # 4 CJK
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "query_kb", "arguments": '{"q":"abcd"}'}},
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": "result text here"},
    ]
    n = _estimate_messages_tokens(msgs)
    # 至少覆盖三条 content + tool_calls 文本,均为正
    assert n > 0
    # content=None / 缺 content 不报错
    assert _estimate_messages_tokens([{"role": "user"}]) == 0
```

- [ ] **Step 2: 跑测试确认 fail**

Run: `pytest backend/tests/unit/chatloop/test_context.py::test_estimate_messages_tokens -q`
Expected: FAIL（ImportError，无此函数）

- [ ] **Step 3: 实现 helper**

在 `context.py` `estimate_tokens` 函数之后插入:

```python
def _estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """粗估一组 OpenAI messages 的总 token(content + tool_calls 文本)。

    只用于安全阀的"逼近窗口"判定,不要求精确(真实值走 usage 回填)。
    """
    total = 0
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str):
            total += estimate_tokens(content)
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {})
            total += estimate_tokens(f"{fn.get('name', '')}{fn.get('arguments', '')}")
    return total
```

- [ ] **Step 4: 跑测试确认 pass**

Run: `pytest backend/tests/unit/chatloop/test_context.py::test_estimate_messages_tokens -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/chatloop/context.py backend/tests/unit/chatloop/test_context.py
git commit -m "feat(chatloop): ① 总量 token 估算 helper"
```

---

### Task 3: ContextDeps 加安全阀参数 + assemble_context 收紧循环

**Files:**
- Modify: `backend/app/chatloop/context.py`（`ContextDeps` + `assemble_context`）
- Test: `backend/tests/unit/chatloop/test_context.py`

- [ ] **Step 1: 写失败测试**

```python
def _state_with(messages):
    from app.chatloop.state import ChatLoopState

    return ChatLoopState(user_id="u", session_id="s", request_id="r", messages=list(messages))


def _tool_msg(call_id, content):
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def _assistant_calls(*ids):
    return {"role": "assistant", "content": "",
            "tool_calls": [{"id": i, "type": "function",
                            "function": {"name": "query_kb", "arguments": "{}"}} for i in ids]}


def test_pressure_valve_off_by_default():
    from app.chatloop.context import ContextDeps, assemble_context

    # 三条中等 tool 消息(每条 600 字符 < 1320 降级线),老圈
    msgs = [
        _assistant_calls("a1"), _tool_msg("a1", "甲" * 600),
        _assistant_calls("a2"), _tool_msg("a2", "乙" * 600),
        _assistant_calls("a3"), _tool_msg("a3", "丙" * 600),
        _assistant_calls("z1"), _tool_msg("z1", "最近" * 300),  # 最近一圈
    ]
    st = _state_with(msgs)
    deps = ContextDeps(system_prompt="sys")  # max_context_tokens 默认 0 = 关闭
    assemble_context(st, deps)
    # 安全阀关闭:中等消息全不降级
    assert "甲" * 600 in st.messages[1]["content"]
    assert st.context_pressure_passes == 0


def test_pressure_valve_squeezes_old_rounds():
    from app.chatloop.context import ContextDeps, assemble_context

    msgs = [
        _assistant_calls("a1"), _tool_msg("a1", "甲" * 600),
        _assistant_calls("a2"), _tool_msg("a2", "乙" * 600),
        _assistant_calls("a3"), _tool_msg("a3", "丙" * 600),
        _assistant_calls("z1"), _tool_msg("z1", "最近" * 300),  # 最近一圈,受保护
    ]
    st = _state_with(msgs)
    # 窗口设极小,逼安全阀启动
    deps = ContextDeps(system_prompt="sys", max_context_tokens=600, context_pressure_ratio=0.85)
    assemble_context(st, deps)
    # 老圈中等消息被降级(content 变 [全文已缓存 ...])
    assert st.messages[1]["content"].startswith("[全文已缓存")
    assert st.messages[3]["content"].startswith("[全文已缓存")
    # 最近一圈全文保护
    assert "最近" * 300 in st.messages[7]["content"]
    assert st.context_pressure_passes > 0


def test_pressure_valve_floor_hit_best_effort():
    from app.chatloop.context import ContextDeps, assemble_context

    # 只有最近一圈一条超大消息,老圈无可榨
    msgs = [_assistant_calls("z1"), _tool_msg("z1", "巨" * 5000)]
    st = _state_with(msgs)
    deps = ContextDeps(system_prompt="sys", max_context_tokens=100, context_pressure_ratio=0.85)
    # 不抛异常,正常返回
    result = assemble_context(st, deps)
    assert isinstance(result, list)
    # 最近一圈全文未动
    assert "巨" * 5000 in st.messages[1]["content"]
    assert st.context_pressure_floor_hit is True
```

- [ ] **Step 2: 跑测试确认 fail**

Run: `pytest backend/tests/unit/chatloop/test_context.py -k pressure_valve -q`
Expected: FAIL（ContextDeps 无 max_context_tokens / context_pressure_ratio 参数）

- [ ] **Step 3: 实现**

3a. `ContextDeps` 加三个字段(在 `oversize_result_char_threshold` 行后):

```python
    max_context_tokens: int = 0  # 0 = 安全阀关闭;chat_runner 传模型窗口实际值
    context_pressure_ratio: float = 0.85  # 拼完总量超 ratio*window 启动收紧
    downgrade_floor_threshold: int = 200  # 收紧时降级阈值下限(最近一圈仍永久保护)
```

3b. 把现有 `assemble_context` 的区一~区四拼装抽成 helper `_assemble_regions`,`assemble_context` 改成"降级 + 收紧循环 + 拼装":

```python
def _assemble_regions(state: ChatLoopState, deps: ContextDeps) -> list[dict[str, Any]]:
    """四区拼装(不含降级)——纯读 state.messages。"""
    result: list[dict[str, Any]] = []
    result.append({"role": "system", "content": deps.system_message_content})
    result.extend(deps.history_block)
    result.extend(state.messages)
    remaining = max(0.0, deps.max_cny - state.budget_spent_cny)
    tail_content = f"(第 {state.step + 1}/{deps.max_steps} 步,预算剩 ¥{remaining:.2f}。)"
    result.append({"role": "user", "content": tail_content})
    return result


def assemble_context(state: ChatLoopState, deps: ContextDeps) -> list[dict[str, Any]]:
    """state → OpenAI messages。

    先按基准阈值降级,再拼四区;若 max_context_tokens>0 且总量逼近窗口,
    逐级调小降级阈值多榨老圈(最近一圈永久全文保护),榨到下限仍超则
    best-effort 照发并置 context_pressure_floor_hit。
    """
    # 重置本圈压力信号
    state.context_pressure_passes = 0
    state.context_pressure_floor_hit = False

    threshold = deps.downgrade_char_threshold
    _downgrade_old_tool_messages(state, threshold)
    result = _assemble_regions(state, deps)

    if deps.max_context_tokens > 0:
        target = int(deps.context_pressure_ratio * deps.max_context_tokens)
        while (
            _estimate_messages_tokens(result) > target
            and threshold > deps.downgrade_floor_threshold
        ):
            threshold = max(deps.downgrade_floor_threshold, threshold // 2)
            _downgrade_old_tool_messages(state, threshold)
            result = _assemble_regions(state, deps)
            state.context_pressure_passes += 1
        if _estimate_messages_tokens(result) > target:
            state.context_pressure_floor_hit = True

    return result
```

> 注:删掉原 `assemble_context` 里区一~区四的内联拼装(已移入 `_assemble_regions`)。`_downgrade_old_tool_messages` / `_estimate_messages_tokens` 保持不变。

- [ ] **Step 4: 跑测试确认 pass(含既有 test_context 回归)**

Run: `pytest backend/tests/unit/chatloop/test_context.py -q`
Expected: PASS（新增 3 个 + 既有全过；既有用例 deps 不传 max_context_tokens=默认 0,行为不变）

- [ ] **Step 5: 提交**

```bash
git add backend/app/chatloop/context.py backend/tests/unit/chatloop/test_context.py
git commit -m "feat(chatloop): ① assemble_context 总量压力安全阀(逐级收紧降级,最近一圈保护)"
```

---

### Task 4: 新增 context_pressure 事件 + loop 发射

**Files:**
- Modify: `backend/app/chatloop/events.py:13`（EventType Literal）
- Modify: `backend/app/chatloop/loop.py`（主循环 `assemble_context` 之后)
- Test: `backend/tests/unit/chatloop/test_loop.py`

- [ ] **Step 1: 写失败测试**

在 `test_loop.py` 加(复用既有 `FakeLLM`/`FakeToolHub`/`_Collector`;若既有 helper 名不同,对齐本文件内既有 scenario 的构造方式):

```python
async def test_context_pressure_event_emitted(...):
    # 构造:deps.max_context_tokens 设极小 + state.messages 预置多条中等老 tool 消息,
    # 使第一圈 assemble_context 触发收紧(context_pressure_passes>0)。
    # FakeLLM 第一圈即出 stop(无 tool_calls)自然收尾,聚焦验事件。
    # 断言:collector 收到 type=="context_pressure" 的事件,且 data 带 passes>0 / floor_hit 键。
    ...
```

> 实现时按 `test_loop.py` 既有 scenario 的真实 fixture 名与 ToolLoop 构造签名落地;断言核心:`any(e.type == "context_pressure" and e.data.get("passes", 0) > 0 for e in collector.events)`。

- [ ] **Step 2: 跑测试确认 fail**

Run: `pytest backend/tests/unit/chatloop/test_loop.py::test_context_pressure_event_emitted -q`
Expected: FAIL（无 context_pressure 事件 / EventType 不含该值）

- [ ] **Step 3: 实现**

3a. `events.py` EventType Literal 末尾(`"dispatch_end",` 后)加:

```python
    "context_pressure",
```

3b. `loop.py` 主循环里,`messages = assemble_context(state, self._deps)`(约 167 行)之后紧接:

```python
            if state.context_pressure_passes > 0:
                await self._emit(
                    "context_pressure",
                    state.step + 1,
                    passes=state.context_pressure_passes,
                    floor_hit=state.context_pressure_floor_hit,
                )
```

- [ ] **Step 4: 跑测试确认 pass**

Run: `pytest backend/tests/unit/chatloop/test_loop.py::test_context_pressure_event_emitted -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/chatloop/events.py backend/app/chatloop/loop.py backend/tests/unit/chatloop/test_loop.py
git commit -m "feat(chatloop): ① context_pressure 事件 + loop 发射(喂⑦看板)"
```

---

### Task 5: chat_runner 接线模型窗口

**Files:**
- Modify: `backend/app/tasks/chat_runner.py:255`（ContextDeps 构造)

- [ ] **Step 1: 确认 os 已导入**

Run: `grep -n "^import os\|^import os$" backend/app/tasks/chat_runner.py`
若无,在导入区加 `import os`。

- [ ] **Step 2: 接线**

`ContextDeps(...)` 构造里追加一行(`max_cny=...` 之后):

```python
        max_context_tokens=int(os.getenv("CHATLOOP_MAX_CONTEXT_TOKENS", "100000")),
```

- [ ] **Step 3: 跑 chat_runner 相关单测确认不破**

Run: `pytest backend/tests/unit/chatloop/ -q`
Expected: PASS（全绿）

- [ ] **Step 4: 提交**

```bash
git add backend/app/tasks/chat_runner.py
git commit -m "feat(chatloop): ① chat_runner 接线 CHATLOOP_MAX_CONTEXT_TOKENS(默认 100k)"
```

---

### Task 6: 全量验收 + 静态检查

- [ ] **Step 1: chatloop 全单测**

Run: `pytest backend/tests/unit/chatloop/ -q`
Expected: 全绿

- [ ] **Step 2: ruff + mypy**

Run:
```bash
ruff format --check backend/app/chatloop/ backend/app/tasks/chat_runner.py backend/tests/unit/chatloop/
ruff check backend/app/chatloop/ backend/app/tasks/chat_runner.py backend/tests/unit/chatloop/
mypy backend/app/chatloop/ backend/app/tasks/chat_runner.py
```
Expected: 无新增问题（format 不达标先 `ruff format` 再提交)

- [ ] **Step 3: 提交(若有 format 改动)**

```bash
git add -u backend/app/chatloop/ backend/app/tasks/chat_runner.py backend/tests/unit/chatloop/
git commit -m "style(chatloop): ① ruff format 对齐"
```

---

## Self-Review

- **Spec 覆盖**:总量估算(T2)/ 收紧循环 + 最近一圈保护 + 下限 best-effort(T3)/ 压力信号字段(T1)/ context_pressure 事件(T4)/ 模型窗口接线(T5)—— spec 全部要点有对应 task。
- **占位扫描**:T4 Step1 测试用例按"实现时对齐既有 fixture"描述而非死代码,因 `test_loop.py` 既有 scenario 的 fixture 名需现场核对——这是该文件的已知约定(④⑤ 同款),非占位失败;核心断言已给死。其余步骤代码完整。
- **类型一致**:`context_pressure_passes`(int)/`context_pressure_floor_hit`(bool)/`max_context_tokens`(int)/`context_pressure_ratio`(float)/`downgrade_floor_threshold`(int) 跨 task 命名一致;`_estimate_messages_tokens` / `_assemble_regions` 签名一致。

# Chat Loop 终止闸精度修补 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 chatloop 补两道终止闸精度(跨签名连续失败 + 分发前预算预检)并让收尾原因对模型人话化,堵住"换参数硬试烧满 12 圈"与"单圈把预算花爆"两个真实漏洞。

**Architecture:** 判定逻辑全进 `gates.py` 纯谓词(零 I/O),`loop.py` 只加几行编排;新增的连续失败计数落在 `state.py` 的 `ToolLedger`。不碰打转闸本体与预算闸圈首逻辑,只新增互补的第二道。

**Tech Stack:** Python / pydantic / pytest(L0 纯函数+编排单测,沿用 `backend/tests/unit/chatloop/` 既有 Fake 模式)。

**Spec:** `docs/superpowers/specs/2026-06-11-chatloop-termination-gate-precision-design.md`

**共享 checkout 纪律:** 工作区有并发 session 的未提交改动。每次 commit **只 `git add` 本计划点名的文件**,绝不 `git add -A`/`git add .`。

---

## File Structure

- `backend/app/chatloop/state.py` — `ToolLedger` 加 `trailing_failure_count()` 纯方法;`ChatLoopState.halt_reason` 注释补 `repeated_failures`。
- `backend/app/chatloop/gates.py` — `GateConfig` 加两字段;`check_gates` 追加 `repeated_failures`;新增 `budget_margin_exhausted` 纯谓词。
- `backend/app/chatloop/loop.py` — `run` 在 dispatch 前插预算预检编排;加 `_budget_skipped_result` 静态方法;加 `_HALT_REASON_TEXT` 映射并用于 `_force_conclude` 系统消息;import 补 `budget_margin_exhausted`。
- `backend/tests/unit/chatloop/test_state.py` — 加 `trailing_failure_count` 3 测。
- `backend/tests/unit/chatloop/test_gates.py` — 加 `repeated_failures` 3 测 + `budget_margin_exhausted` 3 测。
- `backend/tests/unit/chatloop/test_loop.py` — 加预算跳过 2 测;改 `test_scenario_4` 收尾文案断言(raw 码→人话)。

---

### Task 1: (a) ToolLedger.trailing_failure_count

**Files:**
- Modify: `backend/app/chatloop/state.py`(在 `fail_count` 之后加方法)
- Test: `backend/tests/unit/chatloop/test_state.py`

- [ ] **Step 1: Write the failing tests**

在 `test_state.py` 末尾追加(文件顶部已 `from app.chatloop.state import ChatLoopState, ToolLedger, ...`;若未导入 `ToolLedger` 则补):

```python
def test_trailing_failure_count_counts_tail_failures():
    ledger = ToolLedger()
    ledger.record(step=1, tool_name="a", args={"x": 1}, digest="", success=False)
    ledger.record(step=2, tool_name="a", args={"x": 2}, digest="", success=True)
    ledger.record(step=3, tool_name="a", args={"x": 3}, digest="", success=False)
    ledger.record(step=4, tool_name="a", args={"x": 4}, digest="", success=False)
    # 末尾两条失败,中间成功截断计数
    assert ledger.trailing_failure_count() == 2


def test_trailing_failure_count_zero_when_tail_success():
    ledger = ToolLedger()
    ledger.record(step=1, tool_name="a", args={"x": 1}, digest="", success=False)
    ledger.record(step=2, tool_name="a", args={"x": 2}, digest="", success=True)
    assert ledger.trailing_failure_count() == 0


def test_trailing_failure_count_empty_ledger():
    assert ToolLedger().trailing_failure_count() == 0
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest backend/tests/unit/chatloop/test_state.py -k trailing_failure_count -q`
Expected: FAIL — `AttributeError: 'ToolLedger' object has no attribute 'trailing_failure_count'`

- [ ] **Step 3: Implement**

在 `state.py` `ToolLedger.fail_count` 之后加:

```python
    def trailing_failure_count(self) -> int:
        """从台账末尾往回数连续 success=False 的条数(跨签名乱试判据)。

        任意一次成功即截断计数。被烧签名拒绝的调用不进台账,故不污染此计数;
        只有真分发并失败的调用计入——抓的是"一直在失败",不是"调用频率"。
        """
        count = 0
        for entry in reversed(self.entries):
            if entry.success:
                break
            count += 1
        return count
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest backend/tests/unit/chatloop/test_state.py -k trailing_failure_count -q`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/chatloop/state.py backend/tests/unit/chatloop/test_state.py
git commit -m "feat(chatloop): ToolLedger.trailing_failure_count — 跨签名连续失败计数"
```

---

### Task 2: (a) check_gates 追加 repeated_failures

**Files:**
- Modify: `backend/app/chatloop/gates.py`(`GateConfig` + `check_gates`)
- Modify: `backend/app/chatloop/state.py`(`halt_reason` 注释)
- Test: `backend/tests/unit/chatloop/test_gates.py`

- [ ] **Step 1: Write the failing tests**

在 `test_gates.py` 末尾追加(失败记账直接用 `state.ledger.record(..., success=False)`):

```python
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
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest backend/tests/unit/chatloop/test_gates.py -k repeated_failures -q`
Expected: FAIL — `TypeError: ... unexpected keyword argument 'max_consecutive_failures'`(GateConfig 还没该字段)

- [ ] **Step 3: Implement**

`gates.py` `GateConfig` 加字段:

```python
    burn_threshold: int = 3  # 同签名失败 N 次后烧掉
    max_consecutive_failures: int = 5  # 跨签名尾部连续失败 N 次 → repeated_failures(乱试)
```

`check_gates` 在 spinning 块之后、`return None` 之前加:

```python
        if cur and cur == prev:
            return "spinning"
    if state.ledger.trailing_failure_count() >= cfg.max_consecutive_failures:
        # 跨签名连续失败(换参数硬试):打转闸/烧签名都漏检的乱试模式
        return "repeated_failures"
    return None
```

`state.py` 的 `halt_reason` 注释更新:

```python
    halt_reason: str | None = None  # natural|max_steps|budget|spinning|repeated_failures|escalate
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest backend/tests/unit/chatloop/test_gates.py -q`
Expected: 全部 passed(原有 + 新增 3 条)

- [ ] **Step 5: Commit**

```bash
git add backend/app/chatloop/gates.py backend/app/chatloop/state.py backend/tests/unit/chatloop/test_gates.py
git commit -m "feat(chatloop): repeated_failures 闸 — 跨签名连续失败触发收尾"
```

---

### Task 3: (b) budget_margin_exhausted 纯谓词

**Files:**
- Modify: `backend/app/chatloop/gates.py`(`GateConfig` + 新函数)
- Test: `backend/tests/unit/chatloop/test_gates.py`

- [ ] **Step 1: Write the failing tests**

`test_gates.py` 顶部 import 补 `budget_margin_exhausted`:

```python
from app.chatloop.gates import (
    GateConfig,
    budget_margin_exhausted,
    check_gates,
    filter_burned,
    update_burned,
)
```

末尾追加:

```python
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
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest backend/tests/unit/chatloop/test_gates.py -k budget_margin -q`
Expected: FAIL — `ImportError: cannot import name 'budget_margin_exhausted'`

- [ ] **Step 3: Implement**

`gates.py` `GateConfig` 加字段:

```python
    max_consecutive_failures: int = 5  # 跨签名尾部连续失败 N 次 → repeated_failures(乱试)
    budget_dispatch_margin_ratio: float = 0.2  # 分发前预检:剩余低于上限此比例 → 跳过整轮工具
```

在 `update_burned` 之后加函数:

```python
def budget_margin_exhausted(state: ChatLoopState, cfg: GateConfig) -> bool:
    """分发前预检:剩余预算(cny 或 token 任一)低于安全余量 → True。

    用在"本圈 LLM 成本已入账、即将分发工具"的点上:据最新预算决定是否还要再起
    一轮工具(工具执行 + 又一轮 LLM)。预留的余量(上限 * ratio)给收尾那次 LLM 调用。
    """
    cny_remaining = cfg.max_cny - state.budget_spent_cny
    tokens_remaining = cfg.max_tokens - state.budget_spent_tokens
    return (
        cny_remaining < cfg.max_cny * cfg.budget_dispatch_margin_ratio
        or tokens_remaining < cfg.max_tokens * cfg.budget_dispatch_margin_ratio
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest backend/tests/unit/chatloop/test_gates.py -q`
Expected: 全部 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/chatloop/gates.py backend/tests/unit/chatloop/test_gates.py
git commit -m "feat(chatloop): budget_margin_exhausted 纯谓词 — 分发前预算余量判定"
```

---

### Task 4: (b) loop 分发前预算预检编排

**Files:**
- Modify: `backend/app/chatloop/loop.py`(import / `run` / 新静态方法 / 模块常量)
- Test: `backend/tests/unit/chatloop/test_loop.py`

- [ ] **Step 1: Write the failing tests**

`test_loop.py` 末尾追加(复用本文件已有的 `FakeLLM`/`FakeToolHub`/`_Collector`/`_deps`/`_make_state`/`_call`/`_ok_result`/`_step`):

```python
async def test_budget_margin_skips_dispatch_and_concludes():
    """本圈 LLM 成本把余量打到不足 → 整轮工具被跳过,直接 force_conclude。"""
    args = {"ts_code": "600519.SH"}
    llm = FakeLLM(
        [
            # 入账后 spent=0.09,剩 0.01 < 0.02(0.10*0.2)→ 余量不足
            _step(tool_calls=[_call("get_stock_quote", args)], cost_cny=0.09),
            _step(content="预算紧张,基于已有信息:茅台估值偏高。", finish_reason="stop"),
        ]
    )
    hub = FakeToolHub(results_per_round=[])  # dispatch 不应被调用
    emit = _Collector()
    loop = ToolLoop(llm=llm, tool_hub=hub, context_deps=_deps(), emit=emit)
    state = await loop.run(_make_state())

    assert hub.dispatched_calls == []  # 整轮工具被跳过
    halts = emit.of("loop_halt")
    assert len(halts) == 1 and halts[0].data["reason"] == "budget"
    # 协议红线:assistant(tool_calls) 后每个 tool_call_id 都有 tool 消息
    tool_msgs = [m for m in state.messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["content"].startswith("[ERROR]") and "预算" in tool_msgs[0]["content"]
    # 走 force_conclude:终圈 tool_choice=none,done.stop_reason=budget
    assert llm.received_tool_choice[-1] == "none"
    assert state.halt_reason == "budget"
    assert emit.of("done")[0].data["stop_reason"] == "budget"


async def test_budget_sufficient_dispatches_normally():
    args = {"ts_code": "600519.SH"}
    llm = FakeLLM(
        [
            _step(tool_calls=[_call("get_stock_quote", args)], cost_cny=0.001),
            _step(content="茅台 1600 元。", finish_reason="stop"),
        ]
    )
    hub = FakeToolHub(results_per_round=[[_ok_result("get_stock_quote", args)]])
    emit = _Collector()
    loop = ToolLoop(llm=llm, tool_hub=hub, context_deps=_deps(), emit=emit)
    state = await loop.run(_make_state())

    assert len(hub.dispatched_calls) == 1  # 正常分发
    assert emit.of("loop_halt") == []
    assert state.halt_reason == "natural"
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest backend/tests/unit/chatloop/test_loop.py -k budget -q`
Expected: FAIL — `test_budget_margin_skips_dispatch_and_concludes` 失败(现无预检,dispatch 仍被调用 / 无 loop_halt)

- [ ] **Step 3: Implement**

`loop.py` import 行补 `budget_margin_exhausted`:

```python
from app.chatloop.gates import (
    GateConfig,
    budget_margin_exhausted,
    check_gates,
    filter_burned,
    update_burned,
)
```

模块常量区(`_BURNED_REJECT_ERROR` 旁)加:

```python
# 分发前预算余量不足时,为本圈每个工具调用喂回的指导文案(不带 [ERROR],apply_results 会加)。
_BUDGET_SKIP_ERROR = "预算余量不足,本轮工具未执行;请基于已有信息作答,不要再调用工具"
```

`run` 里,`allowed, _rejected = filter_burned(...)` 之后、`results = await self._tool_hub.dispatch(...)` 之前插入:

```python
            allowed, _rejected = filter_burned(step_result.tool_calls, state)

            # ④(b) 分发前预算预检:本圈 LLM 成本已入账,若余量不足则整轮跳过工具、
            #      直接收尾——避免单圈重型工具(+随后又一轮 LLM)把预算炸穿。
            #      给每个 tool_call 回预算指导占位,守住协议红线(每个 id 必有 tool 消息)。
            if budget_margin_exhausted(state, self._gate_cfg):
                await self._emit("loop_halt", state.step, reason="budget")
                skipped = [self._budget_skipped_result(c) for c in step_result.tool_calls]
                state = apply_results(state, skipped, step_result.tool_calls)
                return await self._force_conclude(state, "budget")

            # 12. 工具分发(hub 负责 gather/缓存/记账/tool_start/tool_end)
            results = await self._tool_hub.dispatch(allowed, state)
```

加静态方法(在 `_burned_result` 之后):

```python
    @staticmethod
    def _budget_skipped_result(call: StepToolCall) -> ToolResult:
        """预算余量不足时,为被跳过的工具调用产出的指导性占位结果。"""
        try:
            args = call.parsed_args
        except ValueError:
            args = {}
        return ToolResult(
            tool_name=call.name,
            args=args,
            success=False,
            output=None,
            error=_BUDGET_SKIP_ERROR,
            latency_ms=0,
        )
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest backend/tests/unit/chatloop/test_loop.py -q`
Expected: 全部 passed(原有 + 新增 2 条)

- [ ] **Step 5: Commit**

```bash
git add backend/app/chatloop/loop.py backend/tests/unit/chatloop/test_loop.py
git commit -m "feat(chatloop): 分发前预算预检 — 余量不足整轮跳过工具直接收尾"
```

---

### Task 5: (c) 收尾原因人话化

**Files:**
- Modify: `backend/app/chatloop/loop.py`(模块常量 + `_force_conclude`)
- Test: `backend/tests/unit/chatloop/test_loop.py`(改 `test_scenario_4` 断言)

- [ ] **Step 1: Update existing test to new expectation(先改断言使其失败)**

`test_loop.py` `test_scenario_4_max_steps_force_conclude` 里这两行:

```python
    user_contents = [m["content"] for m in state.messages if m.get("role") == "user"]
    assert any("已达执行上限" in c and "max_steps" in c for c in user_contents)
```

改为(收尾文案不再含 raw 码,改含人话短语):

```python
    user_contents = [m["content"] for m in state.messages if m.get("role") == "user"]
    assert any("已达执行上限" in c and "已达步数上限" in c for c in user_contents)
    assert all("max_steps" not in c for c in user_contents)  # raw 码不出现在给模型的文案里
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest backend/tests/unit/chatloop/test_loop.py -k scenario_4 -q`
Expected: FAIL — 当前文案仍是 raw `max_steps`,新断言找不到"已达步数上限"

- [ ] **Step 3: Implement**

`loop.py` 模块常量区加:

```python
# 撞闸原因 → 给模型看的人话短语(事件层 reason/stop_reason 仍用 raw 码做看板归因)。
_HALT_REASON_TEXT = {
    "max_steps": "已达步数上限",
    "budget": "已达预算上限",
    "spinning": "检测到原地重复调用",
    "repeated_failures": "检测到连续多次工具失败",
}
```

`_force_conclude` 里把 append 的系统消息改为用人话短语:

```python
    async def _force_conclude(self, state: ChatLoopState, reason: str) -> ChatLoopState:
        """撞闸后逼模型基于已有信息收尾(spec § 1.3)。"""
        state.halt_reason = reason
        reason_text = _HALT_REASON_TEXT.get(reason, reason)
        state.messages.append(
            {
                "role": "user",
                "content": (
                    f"(系统:已达执行上限({reason_text}),请基于已有信息直接给出最终回答,"
                    "不要再调用任何工具。)"
                ),
            }
        )
        state.tool_choice = "none"
```

(其余行不变。)

- [ ] **Step 4: Run to verify pass**

Run: `pytest backend/tests/unit/chatloop/test_loop.py -q`
Expected: 全部 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/chatloop/loop.py backend/tests/unit/chatloop/test_loop.py
git commit -m "feat(chatloop): 收尾原因人话化 — 喂模型用中文短语,事件层 raw 码不变"
```

---

### Task 6: 全量门禁 + 收束

**Files:** 无新增

- [ ] **Step 1: 全 chatloop 单测**

Run: `pytest backend/tests/unit/chatloop/ -q`
Expected: 全绿

- [ ] **Step 2: lint + 类型(对齐 CI 全仓口径)**

Run: `ruff format --check backend/app/chatloop backend/tests/unit/chatloop`
Run: `ruff check backend/app/chatloop backend/tests/unit/chatloop`
Run: `mypy backend/app/chatloop`
Expected: 三项均无错误(若 format 报需格式化,先 `ruff format` 同路径再提交)

- [ ] **Step 3: 浏览器实测(goal 要求)**

起本分支专属队列 worker,在前端发一条能触发"换参数硬试"或长对话的消息,确认 SSE 出 `loop_halt(repeated_failures|budget)` 且 UI 不卡死。具体启动方式见 dogfood 记录,沿用 PR #145 的独占队列隔离手法。

- [ ] **Step 4: 推分支 + 开 PR**

```bash
git push -u origin chatloop-termination-gate-precision
gh pr create --title "feat(chatloop): 终止闸精度 — 跨签名连续失败 + 分发前预算预检 + 收尾原因人话化" --body "<决策点④ 三件改动 + 测试 + 浏览器实测说明>"
```

- [ ] **Step 5: CI 绿后合入**

轮询 `lint-and-fast-tests`;conclusion=success 后 squash 合入 main。

---

## Self-Review

**Spec coverage:** (a) → Task 1+2;(b) 谓词 → Task 3,编排 → Task 4;(c) → Task 5;验收门禁 → Task 6。spec 的"不做"项(打转闸本体/圈首预算/选择性跳过/事件 raw 码)在各 Task 实现里均未触碰。✓

**Placeholder scan:** 无 TBD/TODO;每个改代码步骤都给了完整代码块。Task 6 Step 3 浏览器实测的"具体启动方式"指向 dogfood 记录而非内联——这是运行环境操作非代码,实施时按实际 worker 启动命令执行。✓

**Type consistency:** `trailing_failure_count()->int`、`budget_margin_exhausted(state,cfg)->bool`、`_budget_skipped_result(call)->ToolResult`、`_HALT_REASON_TEXT: dict[str,str]`、`GateConfig.max_consecutive_failures:int=5` / `budget_dispatch_margin_ratio:float=0.2` 在 Task 间引用一致;reason 码 `repeated_failures`/`budget` 全程一致。✓

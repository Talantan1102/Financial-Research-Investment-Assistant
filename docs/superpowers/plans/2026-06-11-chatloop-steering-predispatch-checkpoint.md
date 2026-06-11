# Chat Loop 分发前插话检查点 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 chatloop 在"LLM 已决定本轮工具、尚未 dispatch"的缝隙加一道插话检查点,让改方向型插话立即取消白跑的工具批并重规划,把插话延迟从"整圈"缩到"当前 LLM 流"那段。

**Architecture:** `loop.run()` 在预算预检后、dispatch 前插一道 `pop_all()`;有插话则给本轮 tool_calls 占位(复用 ④b 机制守协议)、并入插话、`continue` 回圈首重规划。占位不进 ledger,圈首 pop_all 保留互补。

**Tech Stack:** Python / pytest(L0 编排单测,复用 `backend/tests/unit/chatloop/test_loop.py` 既有 Fake)。

**Spec:** `docs/superpowers/specs/2026-06-11-chatloop-steering-predispatch-checkpoint-design.md`

**共享 checkout 纪律:** 工作区有并发 session 改动。每次 commit 只 `git add` 点名文件,绝不 `git add -A`。测试走 WSL fria-venv:`wsl.exe -- bash -lc 'cd /mnt/d/mys/Financial-Research-Investment-Assistant && set -a && source .env && set +a && cd backend && ~/fria-venv/bin/python -m pytest ...'`(退出码 0 = 过;summary 行会被 warnings 冲掉,看 EXIT)。

---

## File Structure

- `backend/app/chatloop/loop.py` — 模块常量 `_STEER_INTERRUPT_ERROR`;`run()` 插入步 11.6 分发前插话检查点;新增静态方法 `_steer_interrupted_result`。
- `backend/tests/unit/chatloop/test_loop.py` — 改 `test_scenario_6_steering` 喂值(补一个 `[]` 给新增的分发前 pop_all);加 2 条新测。

---

### Task 1: 写失败测试(分发前插话 + 回归)+ 修 scenario_6

**Files:**
- Modify: `backend/tests/unit/chatloop/test_loop.py`

- [ ] **Step 1: 修 `test_scenario_6_steering` 喂值**

`FakeSteerSource` 已是**按调用序**喂(每次 `pop_all` 推进一格,`per_round` 是历史命名)。新增分发前 pop_all 后,有工具的圈每圈调 `pop_all` 两次。scenario_6 是"圈1有工具 / 圈2自然停":调用序为 `圈1圈首 / 圈1分发前 / 圈2圈首`。原意是"圈2圈首注入",故喂值要从 `[[], ["先看负债率"]]` 改为在中间插一个 `[]`:

把
```python
    steer = FakeSteerSource(per_round=[[], ["先看负债率"]])
```
改为
```python
    # 每个有工具的圈现在调 pop_all 两次(圈首 + 分发前)。
    # 调用序:圈1圈首[] / 圈1分发前[] / 圈2圈首["先看负债率"](原意=圈2边界注入)。
    steer = FakeSteerSource(per_round=[[], [], ["先看负债率"]])
```
(其余断言不变:圈1正常 dispatch,插话在圈2圈首注入。)

- [ ] **Step 2: 加新测 `test_steer_predispatch_cancels_batch_and_replans`**

在 `test_scenario_6_steering` 之后追加:

```python
async def test_steer_predispatch_cancels_batch_and_replans():
    """LLM 出 tool_calls 后、dispatch 前到达插话 → 取消本轮工具批 + 并入插话 + 重规划。"""
    args = {"ts_code": "600519.SH"}
    llm = FakeLLM(
        [
            _step(tool_calls=[_call("get_stock_quote", args)]),  # 圈1:决定调工具
            _step(content="好的,只看高端白酒。", finish_reason="stop"),  # 圈2:重规划后收尾
        ]
    )
    hub = FakeToolHub(results_per_round=[])  # dispatch 不应被调用(批被取消)
    # 调用序:圈1圈首[] / 圈1分发前["只看高端,别碰区域酒"] / 圈2圈首(越界→[])
    steer = FakeSteerSource(per_round=[[], ["只看高端,别碰区域酒"]])
    emit = _Collector()
    loop = ToolLoop(llm=llm, tool_hub=hub, context_deps=_deps(), emit=emit, steer_source=steer)
    state = await loop.run(_make_state())

    assert hub.dispatched_calls == []  # 本轮工具批被取消,未 dispatch
    # 协议红线:被取消的 tool_call 有占位 tool 消息
    tool_msgs = [m for m in state.messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["content"].startswith("[ERROR]") and "未执行" in tool_msgs[0]["content"]
    # 插话并入 + 事件
    assert any(
        m.get("role") == "user" and m.get("content") == "只看高端,别碰区域酒"
        for m in state.messages
    )
    merged = emit.of("steer_merged")
    assert len(merged) == 1 and merged[0].data["preview"] == "只看高端,别碰区域酒"
    # 重规划:LLM 被调用两次,最终 natural 收尾
    assert len(llm.received_tool_choice) == 2
    assert state.halt_reason == "natural"


async def test_no_steer_predispatch_dispatches_normally():
    """分发前无插话 → 正常 dispatch(回归)。"""
    args = {"ts_code": "600519.SH"}
    llm = FakeLLM(
        [
            _step(tool_calls=[_call("get_stock_quote", args)]),
            _step(content="茅台 1600 元。", finish_reason="stop"),
        ]
    )
    hub = FakeToolHub(results_per_round=[[_ok_result("get_stock_quote", args)]])
    steer = FakeSteerSource(per_round=[])  # 所有 pop_all 越界→[]
    emit = _Collector()
    loop = ToolLoop(llm=llm, tool_hub=hub, context_deps=_deps(), emit=emit, steer_source=steer)
    state = await loop.run(_make_state())

    assert len(hub.dispatched_calls) == 1  # 正常分发
    assert emit.of("steer_merged") == []
    assert state.halt_reason == "natural"
```

- [ ] **Step 3: 跑测试确认失败**

Run: `wsl.exe -- bash -lc 'cd /mnt/d/mys/Financial-Research-Investment-Assistant && set -a && source .env && set +a && cd backend && ~/fria-venv/bin/python -m pytest tests/unit/chatloop/test_loop.py -k "predispatch or scenario_6" -q -p no:cacheprovider > /tmp/pt.txt 2>&1; echo EXIT=$?; head -3 /tmp/pt.txt'`
Expected: `test_steer_predispatch_cancels_batch_and_replans` 失败(现无分发前检查点 → dispatch 仍被调用 / 无 steer_merged);`scenario_6` 失败(喂值多一个 `[]`,但分发前 pop_all 现在不存在 → 仍按旧调用序,插话被圈2分发前消费而非圈2圈首,断言错位)。

- [ ] **Step 4: Commit(失败测试先入)**

```bash
git add backend/tests/unit/chatloop/test_loop.py
git commit -m "test(chatloop): 分发前插话检查点失败测试 + scenario_6 喂值适配"
```

---

### Task 2: 实施分发前插话检查点

**Files:**
- Modify: `backend/app/chatloop/loop.py`

- [ ] **Step 1: 加模块常量**

在 `_BUDGET_SKIP_ERROR` 之后加:

```python
# 分发前插话到达时,为被取消的本轮工具调用喂回的占位文案(不带 [ERROR],apply_results 会加)。
_STEER_INTERRUPT_ERROR = "用户插话,本轮工具未执行,请结合新指令重新决定"
```

- [ ] **Step 2: run() 插入分发前插话检查点**

把
```python
            if budget_margin_exhausted(state, self._gate_cfg):
                await self._emit("loop_halt", state.step, reason="budget")
                skipped = [self._budget_skipped_result(c) for c in step_result.tool_calls]
                state = apply_results(state, skipped, step_result.tool_calls)
                return await self._force_conclude(state, "budget")

            # 12. 工具分发(hub 负责 gather/缓存/记账/tool_start/tool_end)
            results = await self._tool_hub.dispatch(allowed, state)
```
改为(在 budget 块与 `# 12` 之间插入 11.6):
```python
            if budget_margin_exhausted(state, self._gate_cfg):
                await self._emit("loop_halt", state.step, reason="budget")
                skipped = [self._budget_skipped_result(c) for c in step_result.tool_calls]
                state = apply_results(state, skipped, step_result.tool_calls)
                return await self._force_conclude(state, "budget")

            # 11.6 ⑤ 分发前插话检查点:LLM 已决定本轮工具但尚未 dispatch 时,
            #      若此刻有插话到达 → 取消本轮工具批(占位守协议红线)、并入插话、
            #      回圈首让模型结合新指令重新决定。把改方向型插话的延迟从"整圈"
            #      缩到"当前 LLM 流"那段,并立省一整批可能已不需要的工具。
            #      圈首 pop_all 保留(管上一圈工具执行期间到达的插话),两点互补。
            if self._steer is not None:
                steers = await self._steer.pop_all()
                if steers:
                    interrupted = [
                        self._steer_interrupted_result(c) for c in step_result.tool_calls
                    ]
                    state = apply_results(state, interrupted, step_result.tool_calls)
                    for msg in steers:
                        state.messages.append({"role": "user", "content": msg})
                        await self._emit("steer_merged", state.step + 1, preview=msg[:80])
                    continue

            # 12. 工具分发(hub 负责 gather/缓存/记账/tool_start/tool_end)
            results = await self._tool_hub.dispatch(allowed, state)
```

- [ ] **Step 3: 加静态方法 `_steer_interrupted_result`**

在 `_budget_skipped_result` 之后加:

```python
    @staticmethod
    def _steer_interrupted_result(call: StepToolCall) -> ToolResult:
        """分发前插话到达时,为被取消的工具调用产出的占位结果(守协议红线)。"""
        try:
            args = call.parsed_args
        except ValueError:
            args = {}
        return ToolResult(
            tool_name=call.name,
            args=args,
            success=False,
            output=None,
            error=_STEER_INTERRUPT_ERROR,
            latency_ms=0,
        )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `wsl.exe -- bash -lc 'cd /mnt/d/mys/Financial-Research-Investment-Assistant && set -a && source .env && set +a && cd backend && ~/fria-venv/bin/python -m pytest tests/unit/chatloop/test_loop.py -q -p no:cacheprovider > /tmp/pt.txt 2>&1; echo EXIT=$?; head -3 /tmp/pt.txt'`
Expected: EXIT=0,全过(含改后的 scenario_6 + 2 条新测)。

- [ ] **Step 5: Commit**

```bash
git add backend/app/chatloop/loop.py
git commit -m "feat(chatloop): 分发前插话检查点 — 改方向型插话立取消工具批重规划"
```

---

### Task 3: 全量门禁 + 浏览器实测 + PR + 合入

**Files:** 无新增

- [ ] **Step 1: 全 chatloop 单测**

Run: `wsl.exe -- bash -lc 'cd /mnt/d/mys/Financial-Research-Investment-Assistant && set -a && source .env && set +a && cd backend && ~/fria-venv/bin/python -m pytest tests/unit/chatloop/ -q -p no:cacheprovider > /tmp/pt.txt 2>&1; echo EXIT=$?; tail -2 /tmp/pt.txt'`
Expected: EXIT=0。

- [ ] **Step 2: lint + 类型(对齐 CI 全仓口径)**

Run: `wsl.exe -- bash -lc 'cd /mnt/d/mys/Financial-Research-Investment-Assistant && cd backend && ~/fria-venv/bin/ruff format --check app/chatloop/loop.py tests/unit/chatloop/test_loop.py; ~/fria-venv/bin/ruff check app/chatloop/loop.py tests/unit/chatloop/test_loop.py; ~/fria-venv/bin/mypy app/chatloop tests/unit/chatloop/test_loop.py'`
Expected: format already formatted / All checks passed / mypy Success。format 报需格式化则先 `ruff format` 同路径再提交。

- [ ] **Step 3: 浏览器实测(独占队列隔离 worker)**

复用 ④ 的 `_tmp_enqueue_<branch>.py` + 独占队列手法(memory `backend-runtime-env-wsl-fria-venv` 有完整 playbook):起 `-Q steerprec` worker(`run_in_background:true` 前台进程,非 nohup&),enqueue 一条对话,浏览器开 `http://127.0.0.1:8000/api/v0/chat/stream/<task_id>` 看 SSE。重点验:正常对话不被分发前检查点误伤(无插话→正常 dispatch→natural 收尾);若能在跑动中 `POST /api/v0/chat/steer/<task_id>` 推一条插话,观察 `steer_merged` + 工具批被取消。实测后删临时脚本、停 worker。

- [ ] **Step 4: 推分支 + 开 PR**

```bash
git push -u origin chatloop-steering-predispatch-checkpoint
gh pr create --title "feat(chatloop): ⑤ 分发前插话检查点 — 改方向型插话立取消工具批重规划" --body "<决策点⑤ 现状核对(rec2/4已做·rec3 non-issue)+ 分发前检查点 + 测试 + 浏览器实测>"
```

- [ ] **Step 5: CI 绿后合入**

`gh run watch <run-id> --exit-status`;`lint-and-fast-tests` conclusion=success → `gh pr merge <n> --squash --delete-branch`。

---

## Self-Review

**Spec coverage:** 分发前检查点(spec 核心)→ Task 2;占位机制/常量/helper → Task 2;FakeSteerSource 调用序回归 + 新测 → Task 1;门禁/实测/PR → Task 3。spec 的"不做"项(rec2/3/4、圈首 pop_all、预算预检、终止闸、事件 schema)在各 Task 均未触碰。✅

**Placeholder scan:** 无 TBD/TODO;改代码步骤均有完整代码块。Task 3 Step 3 浏览器实测指向 memory playbook(运行环境操作非代码),按实际命令执行。✅

**Type consistency:** `_steer_interrupted_result(call: StepToolCall) -> ToolResult`、`_STEER_INTERRUPT_ERROR: str`、复用 `apply_results`/`pop_all`/`steer_merged` 签名与现码一致;`FakeSteerSource(per_round=...)` 按调用序喂(已有语义,未改类)。✅

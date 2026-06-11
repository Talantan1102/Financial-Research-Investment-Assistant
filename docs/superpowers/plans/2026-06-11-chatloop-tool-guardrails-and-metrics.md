# Chatloop 工具护栏与对话账单 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 chatloop runtime 加三道低风险护栏——数据工具超时、超大工具结果截断(可取回)、对话账单度量(含 KV-cache 命中率 + 稳定前缀 CI 回归)。

**Architecture:** ③④ 落在工具执行路径(`tool_hub`)与输出整形(`loop`),② 复用既有"截断+回指针"缓存闭环;⑦ 在 `state`/`loop`/`chat_runner` 把已有但从未聚合的 token 数据攒成 turn 汇总,并加一条 CI 测试钉死前缀稳定性。三件互相独立,可分别提交。

**Tech Stack:** Python 3.12 / asyncio / pydantic / pytest(L0 单测,真 PG 由 `db_session` fixture,但本计划三件全是纯逻辑,无需 DB)。

设计依据:`docs/superpowers/specs/2026-06-11-chatloop-tool-guardrails-and-metrics-design.md`

---

## Task 1: ③ 数据工具超时

**Files:**
- Modify: `backend/app/chatloop/tool_hub.py`(构造参数 + `_dispatch_one_inner` step 5 包 `wait_for`)
- Test: `backend/tests/unit/chatloop/test_tool_hub.py`

设计:单一默认超时 30s,只施加给 **非 in-process** 工具(数据/MCP);in-process(记忆/技能/控制)豁免。超时抛 `TimeoutError`,落进现有 `except BaseException → _guidance_error`("[超时] 稍后重试或换数据源"),无新机制。

- [ ] **Step 1: 写失败测试 — 数据工具超时 + in-process 豁免**

在 `test_tool_hub.py` 末尾追加。注:`FakeInProcessTool` 当前无 sleep,先给它加一个 sleep 能力(同文件内改其 `__init__` 加 `sleep: float = 0.0`、`run_with_state` 里 `if self._sleep: await asyncio.sleep(self._sleep)`)。

```python
async def test_data_tool_timeout_returns_guidance_error() -> None:
    hub = ToolHub(emit=None, tool_timeout_s=0.05)
    hub.register_registry(FakeRegistry([FakeTool("slow_quote", sleep=0.3)]))
    state = ChatLoopState(user_id="u", session_id="s", request_id="r", messages=[])
    call = StepToolCall(id="c1", name="slow_quote", arguments=json.dumps({"ts_code": "x"}))
    [res] = await hub.dispatch([call], state)
    assert res.success is False
    assert res.error.startswith("[超时]")


async def test_inprocess_tool_exempt_from_timeout() -> None:
    hub = ToolHub(emit=None, tool_timeout_s=0.05)
    hub.register_inprocess([FakeInProcessTool("mem_write", sleep=0.3, output={"ok": True})])
    state = ChatLoopState(user_id="u", session_id="s", request_id="r", messages=[])
    call = StepToolCall(id="c1", name="mem_write", arguments=json.dumps({"ts_code": "x"}))
    [res] = await hub.dispatch([call], state)
    assert res.success is True          # 未被超时打断
    assert res.output == {"ok": True}


async def test_data_tool_under_timeout_succeeds_and_isolates() -> None:
    hub = ToolHub(emit=None, tool_timeout_s=0.5)
    hub.register_registry(FakeRegistry([
        FakeTool("fast", sleep=0.0, output={"v": 1}),
        FakeTool("slowish", sleep=0.05, output={"v": 2}),
    ]))
    state = ChatLoopState(user_id="u", session_id="s", request_id="r", messages=[])
    calls = [
        StepToolCall(id="c1", name="fast", arguments=json.dumps({"ts_code": "a"})),
        StepToolCall(id="c2", name="slowish", arguments=json.dumps({"ts_code": "b"})),
    ]
    r1, r2 = await hub.dispatch(calls, state)
    assert (r1.success, r1.output) == (True, {"v": 1})
    assert (r2.success, r2.output) == (True, {"v": 2})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `wsl -e bash -lc "cd /mnt/d/mys/Financial-Research-Investment-Assistant/backend && ~/fria-venv/bin/python -m pytest tests/unit/chatloop/test_tool_hub.py -k timeout -x"`
Expected: FAIL —— `ToolHub.__init__() got an unexpected keyword argument 'tool_timeout_s'`

- [ ] **Step 3: 加构造参数 + 模块常量**

`tool_hub.py` 顶部常量区(`_ERR_MSG_LEN` 附近)加:

```python
DEFAULT_TOOL_TIMEOUT_S = 30.0  # 数据工具单次执行超时(in-process 豁免)
```

`ToolHub.__init__` 加形参与赋值:

```python
    def __init__(
        self,
        *,
        emit: EmitFn | None = None,
        cache: ToolResultCache | None = None,
        seq_counter: SeqCounter | None = None,
        progressive: bool = True,
        tool_timeout_s: float = DEFAULT_TOOL_TIMEOUT_S,
    ) -> None:
        ...
        self._tool_timeout_s = tool_timeout_s
```

- [ ] **Step 4: 给非 in-process 执行包 `wait_for`**

`_dispatch_one_inner` step 5 的执行块(`tool_hub.py:319-333`)改为按 `is_inprocess` 分流,非 in-process 包超时:

```python
        is_cache_hit = False
        try:
            if not is_inprocess:
                async def _run_data_tool() -> dict[str, Any]:
                    nonlocal is_cache_hit, cache_key
                    if self._cache is not None:
                        cache_key = ToolResultCache.cache_key(state.user_id, name, args)
                        out, cache_status = await self._cache.get_or_compute(
                            user_id=state.user_id, tool_name=name, args=args, compute_fn=_compute,
                        )
                        is_cache_hit = cache_status == CacheHit.HIT
                        return out
                    return await _compute()

                output = await asyncio.wait_for(_run_data_tool(), timeout=self._tool_timeout_s)
            else:
                # in-process(状态变更 / 本地)豁免超时,直接执行
                output = await _compute()
        except BaseException as e:  # noqa: BLE001 — hub 不抛:全包成指导性错误
            error = self._guidance_error(tool, e)
            ...（其余不变）
```

(`_guidance_error` 已映射 `asyncio.TimeoutError/TimeoutError → "[超时] ..."`,无需改。)

- [ ] **Step 5: 跑测试确认通过 + 全量 hub 测试不回归**

Run: `wsl -e bash -lc "cd /mnt/d/mys/Financial-Research-Investment-Assistant/backend && ~/fria-venv/bin/python -m pytest tests/unit/chatloop/test_tool_hub.py -x"`
Expected: PASS(含新 3 个 + 既有全绿)

- [ ] **Step 6: Commit**

```bash
git add backend/app/chatloop/tool_hub.py backend/tests/unit/chatloop/test_tool_hub.py
git commit -m "feat(chatloop): 数据工具单次超时(默认30s,in-process豁免)落进现有[超时]指导错误"
```

---

## Task 2: ② 超大工具结果截断(只截能取回的)

**Files:**
- Modify: `backend/app/chatloop/context.py`(`ContextDeps` 加阈值字段)
- Modify: `backend/app/chatloop/loop.py`(`_extract_and_emit_charts` 末尾加截断)
- Test: `backend/tests/unit/chatloop/test_loop_oversize_cap.py`(新建)

设计:剥完 figures 后,对**有 cache ref**(`state.ledger.find_success` 查得 `cache_key`)的成功 dict 输出,`json.dumps` 字符数超阈值则换成"前~600字 digest + ref"。无 ref 不截 + log 警告(in-process / load_skill / 无缓存天然豁免)。阈值默认 4000,进 `ContextDeps` 可配。

- [ ] **Step 1: ContextDeps 加阈值字段**

`context.py` `ContextDeps` 加(与 `downgrade_char_threshold` 并列):

```python
    oversize_result_char_threshold: int = 4000  # 单条工具结果进窗口的字符上限(超则截断+回指针)
```

- [ ] **Step 2: 写失败测试**

新建 `backend/tests/unit/chatloop/test_loop_oversize_cap.py`:

```python
"""② ToolLoop 输出整形 — 超大工具结果截断(只截能取回的)。"""
from __future__ import annotations

import json
from typing import Any

import pytest

from app.agents.schemas import ToolResult
from app.chatloop.context import ContextDeps
from app.chatloop.events import LoopEvent, SeqCounter
from app.chatloop.loop import ToolLoop
from app.chatloop.state import ChatLoopState

pytestmark = pytest.mark.asyncio


def _loop(events: list[LoopEvent], threshold: int = 4000) -> ToolLoop:
    async def _emit(ev: LoopEvent) -> None:
        events.append(ev)

    class _Hub:
        def schemas_for_llm(self) -> list[dict[str, Any]]:
            return []

        async def dispatch(self, calls: Any, state: Any) -> list[ToolResult]:  # pragma: no cover
            return []

    deps = ContextDeps(system_prompt="s", oversize_result_char_threshold=threshold)
    return ToolLoop(llm=object(), tool_hub=_Hub(), context_deps=deps,
                    emit=_emit, seq_counter=SeqCounter())


def _state() -> ChatLoopState:
    return ChatLoopState(user_id="u", session_id="s", request_id="req-1", messages=[])


async def test_oversize_with_ref_is_truncated() -> None:
    events: list[LoopEvent] = []
    loop = _loop(events, threshold=200)
    st = _state()
    args = {"q": "白酒政策"}
    big = {"chunks": ["政策正文" * 200]}        # 远超 200 字
    # ledger 里有同 (tool, args) 的成功条目,带 cache_key → 可取回
    st.ledger.record(step=1, tool_name="query_kb", args=args,
                     digest="d", success=True, cache_key="u:query_kb:abc")
    results = [ToolResult(tool_name="query_kb", args=args, success=True, output=big, latency_ms=5)]

    await loop._extract_and_emit_charts(results, st)

    out = results[0].output
    assert out["ref"] == "u:query_kb:abc"
    assert "truncated_digest" in out and "read_cached_result" in out["note"]
    assert out["original_chars"] > 200
    assert "chunks" not in out                      # 原文已换出


async def test_oversize_without_ref_kept_intact() -> None:
    events: list[LoopEvent] = []
    loop = _loop(events, threshold=200)
    st = _state()
    big = {"text": "技能方法论" * 200}
    # ledger 无对应成功条目 → 无 ref → 不截
    results = [ToolResult(tool_name="load_skill", args={"name": "x"}, success=True,
                          output=big, latency_ms=5)]
    await loop._extract_and_emit_charts(results, st)
    assert results[0].output == big                 # 原样留存


async def test_small_result_untouched() -> None:
    events: list[LoopEvent] = []
    loop = _loop(events, threshold=4000)
    st = _state()
    args = {"ts": "x"}
    st.ledger.record(step=1, tool_name="quote", args=args, digest="d",
                     success=True, cache_key="k")
    results = [ToolResult(tool_name="quote", args=args, success=True,
                          output={"price": 100}, latency_ms=5)]
    await loop._extract_and_emit_charts(results, st)
    assert results[0].output == {"price": 100}


async def test_figures_not_counted_toward_size() -> None:
    events: list[LoopEvent] = []
    loop = _loop(events, threshold=200)
    st = _state()
    args = {"ts": "x"}
    st.ledger.record(step=1, tool_name="run_python", args=args, digest="d",
                     success=True, cache_key="k")
    # 正文小、figures 大:剥 figures 后不应触发截断
    big_fig = {"data": [{"x": list(range(500))}], "layout": {}}
    results = [ToolResult(tool_name="run_python", args=args, success=True,
                          output={"result": {"corr": 0.8}, "figures": [big_fig]}, latency_ms=5)]
    await loop._extract_and_emit_charts(results, st)
    assert results[0].output["result"] == {"corr": 0.8}
    assert results[0].output["charts_rendered"] == 1
    assert "truncated_digest" not in results[0].output
```

- [ ] **Step 3: 跑测试确认失败**

Run: `wsl -e bash -lc "cd /mnt/d/mys/Financial-Research-Investment-Assistant/backend && ~/fria-venv/bin/python -m pytest tests/unit/chatloop/test_loop_oversize_cap.py -x"`
Expected: FAIL(`out["ref"]` KeyError —— 尚未截断)

- [ ] **Step 4: loop 加截断逻辑**

`loop.py` 顶部加 `import json` 与 `import logging` + `logger = logging.getLogger(__name__)`(若无)。`_extract_and_emit_charts` 末尾(`r.output.pop("figures", ...)` 整理之后)对每个成功 dict 结果追加大小检查。把方法尾部循环体改为:

```python
        for ridx, r in enumerate(results):
            if not (r.success and isinstance(r.output, dict)):
                continue
            figures = r.output.get("figures")
            if isinstance(figures, list) and figures:
                for fidx, fig in enumerate(figures):
                    chart_id = f"{state.request_id}-{state.step}-{ridx}-{fidx}"
                    await self._emit("chart", state.step, chart_id=chart_id, figure=fig)
                r.output.pop("figures", None)
                r.output["charts_rendered"] = len(figures)
            else:
                r.output.pop("figures", None)
            # ② 超大结果截断(figures 已剥,量真正进窗口的体积)
            self._cap_oversized_output(r, state)

    def _cap_oversized_output(self, r: ToolResult, state: ChatLoopState) -> None:
        """超阈值且能取回(有 cache ref)的 dict 结果 → 换成 digest+ref;取不回的不截。"""
        threshold = self._deps.oversize_result_char_threshold
        try:
            serialized = json.dumps(r.output, ensure_ascii=False)
        except (TypeError, ValueError):
            return
        if len(serialized) <= threshold:
            return
        entry = state.ledger.find_success(tool_name=r.tool_name, args=r.args)
        cache_key = entry.cache_key if entry is not None else None
        if cache_key is None:
            logger.warning(
                "oversize tool output without cache ref, kept intact: tool=%s chars=%d",
                r.tool_name, len(serialized),
            )
            return
        r.output = {
            "truncated_digest": serialized[:600],
            "note": "结果过大已截断,完整内容见 ref,需要更多可调 read_cached_result 取回",
            "ref": cache_key,
            "original_chars": len(serialized),
        }
```

(注:原 `_extract_and_emit_charts` 的 figures 分支逻辑保持等价,只是把"无 figures 也 pop"并进 else,并在循环体尾调 `_cap_oversized_output`。`state` 形参类型从宽松改为 `ChatLoopState` 以便 `.ledger`;`test_loop_chart_extract.py` 的 `_State` 替身无 ledger —— 那两个用例的结果体积小、不会进 cap 的 ledger 查询分支前会先被 `len<=threshold`(默认4000)挡掉,不受影响。)

- [ ] **Step 5: 跑测试确认通过 + chart 既有测试不回归**

Run: `wsl -e bash -lc "cd /mnt/d/mys/Financial-Research-Investment-Assistant/backend && ~/fria-venv/bin/python -m pytest tests/unit/chatloop/test_loop_oversize_cap.py tests/unit/chatloop/test_loop_chart_extract.py -x"`
Expected: PASS(新建全过 + chart 既有全绿)

- [ ] **Step 6: Commit**

```bash
git add backend/app/chatloop/context.py backend/app/chatloop/loop.py backend/tests/unit/chatloop/test_loop_oversize_cap.py
git commit -m "feat(chatloop): 超大工具结果截断(默认4000字,只截有cache ref可取回的)"
```

---

## Task 3: ⑦ 对话账单度量

**Files:**
- Modify: `backend/app/chatloop/state.py`(累计字段 + `turn_summary` 纯函数)
- Modify: `backend/app/chatloop/loop.py`(两处 done 带汇总 + cost_update 单圈 delta)
- Modify: `backend/app/tasks/chat_runner.py:546`(escalate done 带汇总)
- Test: `backend/tests/unit/chatloop/test_state.py`、`test_loop.py`、`test_context.py`

### 3a. state 累计器 + turn_summary 纯函数

- [ ] **Step 1: 写失败测试(test_state.py 追加)**

```python
def test_apply_step_accumulates_token_breakdown() -> None:
    from app.chatloop.state import turn_summary
    st = ChatLoopState(user_id="u", session_id="s", request_id="r", messages=[])
    sr = StepResult(content="", tool_calls=[], finish_reason="tool_calls",
                    prompt_tokens=1000, completion_tokens=100, cached_tokens=800, cost_cny=0.01)
    apply_step(st, sr)
    apply_step(st, StepResult(content="", tool_calls=[], finish_reason="stop",
                              prompt_tokens=2000, completion_tokens=50,
                              cached_tokens=1900, cost_cny=0.02))
    assert st.prompt_tokens_total == 3000
    assert st.completion_tokens_total == 150
    assert st.cached_tokens_total == 2700
    s = turn_summary(st)
    assert s["llm_calls"] == 2
    assert s["prompt_tokens"] == 3000 and s["cached_tokens"] == 2700
    assert s["cache_hit_rate"] == round(2700 / 3000, 3)


def test_turn_summary_zero_prompt_no_div_zero() -> None:
    from app.chatloop.state import turn_summary
    st = ChatLoopState(user_id="u", session_id="s", request_id="r", messages=[])
    assert turn_summary(st)["cache_hit_rate"] == 0.0
```

- [ ] **Step 2: 跑确认失败**

Run: `wsl -e bash -lc "cd /mnt/d/mys/Financial-Research-Investment-Assistant/backend && ~/fria-venv/bin/python -m pytest tests/unit/chatloop/test_state.py -k 'accumulat or turn_summary' -x"`
Expected: FAIL(`ChatLoopState` 无 `prompt_tokens_total` / `turn_summary` 未定义)

- [ ] **Step 3: 加字段 + 累加 + 纯函数**

`ChatLoopState` 加(`budget_spent_tokens` 之后):

```python
    prompt_tokens_total: int = 0
    completion_tokens_total: int = 0
    cached_tokens_total: int = 0
```

`apply_step` 内现有 `state.budget_spent_tokens += ...` 之后加:

```python
    state.prompt_tokens_total += step_result.prompt_tokens
    state.completion_tokens_total += step_result.completion_tokens
    state.cached_tokens_total += step_result.cached_tokens
```

`state.py` 末尾(`apply_results` 之后)加纯函数:

```python
def turn_summary(state: ChatLoopState) -> dict[str, Any]:
    """turn 级账单:成本/调用数/token 拆分/KV-cache 命中率。done 事件 data 用。"""
    p = state.prompt_tokens_total
    return {
        "cost_cny": round(state.budget_spent_cny, 4),
        "llm_calls": state.step,
        "tool_calls": len(state.ledger.entries),
        "prompt_tokens": p,
        "completion_tokens": state.completion_tokens_total,
        "cached_tokens": state.cached_tokens_total,
        "cache_hit_rate": round(state.cached_tokens_total / p, 3) if p else 0.0,
    }
```

- [ ] **Step 4: 跑确认通过**

Run: `wsl -e bash -lc "cd /mnt/d/mys/Financial-Research-Investment-Assistant/backend && ~/fria-venv/bin/python -m pytest tests/unit/chatloop/test_state.py -x"`
Expected: PASS

### 3b. loop 两处 done 带汇总 + cost_update 单圈 delta

- [ ] **Step 5: 写失败测试(test_loop.py 追加)**

参照 `test_loop.py` 既有 loop 构造与 ScriptedClient 模式(读该文件头部 helper)。断言:done 事件 data 含 `cache_hit_rate`/`llm_calls`/`tool_calls`;cost_update data 含 `step_prompt_tokens`。最小用例(自然停):

```python
async def test_done_event_carries_turn_summary() -> None:
    # 用 test_loop.py 既有的 ScriptedStepClient 造一个"无工具调用直接 stop"的单圈 turn
    # （沿用文件内 helper；此处给断言骨架）
    final_state, events = await _run_single_turn_no_tools(prompt_tokens=1000, cached_tokens=800)
    done = [e for e in events if e.type == "done"][-1]
    assert done.data["llm_calls"] == final_state.step
    assert done.data["cache_hit_rate"] == round(800 / 1000, 3)
    assert "tool_calls" in done.data
    cost = [e for e in events if e.type == "cost_update"][-1]
    assert cost.data["step_prompt_tokens"] == 1000
```

(实现 Step 时按 `test_loop.py` 真实 helper 命名补 `_run_single_turn_no_tools`;若无现成 helper,用文件内既有 ScriptedStepClient 直接构造,断言同上。)

- [ ] **Step 6: 跑确认失败** — Run 同区测试,Expected: FAIL(done.data 无这些键)

- [ ] **Step 7: 改 loop**

`loop.py` 顶部 import `turn_summary`:`from app.chatloop.state import ChatLoopState, apply_results, apply_step, turn_summary`。

两处 done(`loop.py:174` 自然停、`loop.py:299` force_conclude)的 data 改为带汇总:

```python
            # 自然停(line ~174)
            if not state.escalate_offered:
                await self._emit("done", state.step,
                                 stop_reason=state.halt_reason, **turn_summary(state))
```
```python
        # force_conclude(line ~299)
        if not state.escalate_offered:
            await self._emit("done", state.step, stop_reason=reason, **turn_summary(state))
```

cost_update(`loop.py:159-165`)加单圈 delta:

```python
            await self._emit(
                "cost_update", state.step,
                cny=state.budget_spent_cny, tokens=state.budget_spent_tokens,
                cached_tokens=step_result.cached_tokens,
                step_cost_cny=step_result.cost_cny,
                step_prompt_tokens=step_result.prompt_tokens,
                step_completion_tokens=step_result.completion_tokens,
            )
```

- [ ] **Step 8: 跑确认通过 + loop 既有不回归**

Run: `wsl -e bash -lc "cd /mnt/d/mys/Financial-Research-Investment-Assistant/backend && ~/fria-venv/bin/python -m pytest tests/unit/chatloop/test_loop.py -x"`
Expected: PASS

### 3c. runner escalate done 带汇总

- [ ] **Step 9: 改 chat_runner**

`chat_runner.py` import `turn_summary`(从 `app.chatloop.state`)。`:546` 处:

```python
            {"type": "done", "stop_reason": done_stop_reason, **turn_summary(final_state)},
```

`final_state` 在该函数已可用(`:477` 已用 `final_state.halt_reason`)。

- [ ] **Step 10: 跑 runner 集成测试不回归**

Run: `wsl -e bash -lc "cd /mnt/d/mys/Financial-Research-Investment-Assistant/backend && ~/fria-venv/bin/python -m pytest tests/integration/chatloop/test_chat_runner_loop.py -x"`
Expected: PASS

### 3d. 稳定前缀 CI 回归测试

- [ ] **Step 11: 写测试(test_context.py 追加)**

```python
def test_stable_prefix_byte_identical_across_steps() -> None:
    from app.chatloop.context import ContextDeps, assemble_context
    from app.chatloop.state import ChatLoopState, apply_step
    from app.services.llm_step import StepResult

    deps = ContextDeps(system_prompt="你是助手", persona_block="画像", skill_listing="## 技能")
    st = ChatLoopState(user_id="u", session_id="s", request_id="r",
                       messages=[{"role": "user", "content": "茅台财报"}])
    m1 = assemble_context(st, deps)
    apply_step(st, StepResult(content="好的", tool_calls=[], finish_reason="stop",
                              prompt_tokens=10, completion_tokens=2, cached_tokens=0, cost_cny=0.0))
    m2 = assemble_context(st, deps)
    assert m1[0] == m2[0]                       # 区一 system 消息逐字节相同
    assert m1[0]["role"] == "system"


def test_prefix_breaks_if_volatile_content_injected() -> None:
    """自证测试有效性:把会变的 step 注入 system_prompt → 前缀应不再恒定。"""
    from app.chatloop.context import ContextDeps, assemble_context
    from app.chatloop.state import ChatLoopState, apply_step
    from app.services.llm_step import StepResult

    st = ChatLoopState(user_id="u", session_id="s", request_id="r", messages=[])
    deps1 = ContextDeps(system_prompt=f"step={st.step}")
    m1 = assemble_context(st, deps1)
    apply_step(st, StepResult(content="", tool_calls=[], finish_reason="stop",
                              prompt_tokens=1, completion_tokens=1, cached_tokens=0, cost_cny=0.0))
    deps2 = ContextDeps(system_prompt=f"step={st.step}")
    m2 = assemble_context(st, deps2)
    assert m1[0] != m2[0]                       # 注入易变内容 → 前缀破裂(反证)
```

- [ ] **Step 12: 跑确认通过**

Run: `wsl -e bash -lc "cd /mnt/d/mys/Financial-Research-Investment-Assistant/backend && ~/fria-venv/bin/python -m pytest tests/unit/chatloop/test_context.py -x"`
Expected: PASS

- [ ] **Step 13: Commit ⑦**

```bash
git add backend/app/chatloop/state.py backend/app/chatloop/loop.py backend/app/tasks/chat_runner.py backend/tests/unit/chatloop/test_state.py backend/tests/unit/chatloop/test_loop.py backend/tests/unit/chatloop/test_context.py
git commit -m "feat(chatloop): turn 对话账单(成本/调用数/KV-cache命中率)+ cost_update单圈delta + 稳定前缀CI回归"
```

---

## Task 4: 全量回归 + 质量门

- [ ] **Step 1: chatloop 全量单测**

Run: `wsl -e bash -lc "cd /mnt/d/mys/Financial-Research-Investment-Assistant/backend && ~/fria-venv/bin/python -m pytest tests/unit/chatloop/ tests/integration/chatloop/ -q"`
Expected: 全绿(无回归)

- [ ] **Step 2: lint + 类型**

Run: `wsl -e bash -lc "cd /mnt/d/mys/Financial-Research-Investment-Assistant/backend && ~/fria-venv/bin/python -m ruff check app/chatloop/ app/tasks/chat_runner.py && ~/fria-venv/bin/python -m mypy app/chatloop/"`
Expected: All checks passed

---

## 测试计划汇总

| 件 | 测试文件 | 关键用例 |
|---|---|---|
| ③ | test_tool_hub.py | 数据工具超时→[超时];in-process豁免;同圈隔离 |
| ② | test_loop_oversize_cap.py(新) | 有ref→截断;无ref→留全;小结果不动;figures不计体积 |
| ⑦ | test_state.py / test_loop.py / test_context.py | 累计器+命中率+除零;done带汇总;cost_update delta;稳定前缀恒定+反证 |

## Self-Review 结论

- **Spec 覆盖**:③(Task1)/②(Task2)/⑦四件(Task3 a-d)/全量门(Task4)逐条对上 spec §2/§3/§4/§5。
- **占位符**:Step 5(3b)的 `_run_single_turn_no_tools` 标注"按 test_loop.py 真实 helper 补",非需求占位(测试脚手架,实现时对齐文件内既有 ScriptedStepClient)——其余步骤均含完整代码。
- **类型一致**:`turn_summary` 在 state.py 定义,loop.py / chat_runner.py 同名导入使用;`tool_timeout_s` / `oversize_result_char_threshold` / `prompt_tokens_total` 等命名前后一致。
- **取舍**:② 阈值 4000、③ 超时 30s 均为可配起点,调参数据出处 = ⑦ 账单(见 spec §7)。

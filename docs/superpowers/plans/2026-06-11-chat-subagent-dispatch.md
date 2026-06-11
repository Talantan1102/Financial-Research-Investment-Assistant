# Chat 内子 agent 派发与通信 (dispatch_subagents) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 chat 裸 while 循环上加一个 `dispatch_subagents` 只读扇出工具：主 AI 把"互不依赖的只读小任务"派给几个临时子循环（复用 `ToolLoop` 换受限依赖）并发跑、同步收齐、原文摘要综合，全程留痕到审计表，与深度研报彻底隔离。

**Architecture:** 子循环 = 同一个 `ToolLoop` 类，注入只读子 hub（flat schema 模式）+ `GateConfig(max_steps=4)` + `tier="fast"` + 共享 `SeqCounter` + lane 包装的 emit + 白纸 `ChatLoopState`。一个 `SubagentFactory`（per-turn 在 `build_turn_components` 构造，闭包持 llm/registry/cache/emit/seq_counter/gate_cfg）负责 spawn + gather + 预算回滚 + 审计落库 + dispatch 事件。一个 `DispatchSubagentsTool(InProcessTool)` 把 factory 包成工具、做护栏（个数上限/预算/只读由子 hub 天然保证）。留痕走新 ORM 表 `subagent_dispatch_runs`（一行=一个子循环）。

**Tech Stack:** Python 3.x / Pydantic / asyncio / SQLAlchemy ORM(PG, create_all 幂等) / pytest(L0 单测 + VCR cassette e2e) / 前端 React+valtio+Vite / Celery+Redis Streams(传输零改)。

**留痕范围说明（重要）:** 本 PR 的留痕 = 审计表 `subagent_dispatch_runs`（每子循环完整输入/输出/工具调用/成本永久落 PG，可查可断言）。**span 树成树（父子链）留作 follow-up**：chat turn 现状是每圈一个 `parent_id=None` 的扁平 span（`TraceTree.from_spans` 要求单根，当前 chat turn 已拼不成树），真要成树需先给整个 turn 建根 span，是一次独立重构，不在本 PR。

**与深度研报隔离铁律:** 子循环只读白名单**不含** `offer_deep_research` / `dispatch_subagents`（禁串门 + 禁递归）；子循环复用 `ToolLoop`（chat 机器）绝不碰 `research_graph`（LangGraph）。Task 12 有自动化回归守卫。

---

## 文件结构（落地要动/新建的文件）

**新建：**
- `backend/app/chatloop/subagent.py` — 数据契约（`SubtaskRequest` / `SubagentResult`）+ `SubagentFactory` + `DispatchSubagentsTool` + 子循环常量/系统提示 + 只读 hub builder。
- `backend/app/models/subagent_dispatch.py` — ORM `SubagentDispatchRun`（一行=一个子循环）。
- `backend/app/services/subagent_audit.py` — `SubagentAuditRepo`（best-effort 写审计行，默认用 sync `SessionLocal`，可注入 fake）。
- `backend/tests/unit/chatloop/test_subagent.py` — L0 单测（契约/factory/tool/护栏）。
- `backend/tests/unit/test_subagent_dispatch_model.py` — 审计表 roundtrip 单测。
- `frontend/src/components/chat/DispatchLanes.tsx` — N 条并行进度条。
- `frontend/src/components/chat/__tests__/DispatchLanes.test.tsx` — 前端组件测试。

**修改：**
- `backend/app/chatloop/tool_hub.py` — 加 `progressive: bool = True` 构造参数 + flat schema 分支 + `register_subset` 方法。
- `backend/app/chatloop/events.py` — `EventType` 加 `dispatch_start` / `dispatch_end`。
- `backend/app/chatloop/tool_docs.py` — `TOOL_DOCS` 加 `dispatch_subagents` 条目 + 进 `DEFERRED_TOOLS`。
- `backend/app/chatloop/worker_wiring.py` — `build_turn_components` 构造 `SubagentFactory` + 注册 `DispatchSubagentsTool`。
- `backend/app/models/__init__.py` — re-export `SubagentDispatchRun`。
- `backend/tests/e2e/test_chatloop_cassette.py` — 加 fan-out 主路径 cassette。
- `frontend/src/types/chat.ts` — 加 `DispatchStartEvent`/`DispatchEndEvent` + 给 tool 事件加 `lane?` 字段。
- `frontend/src/store/current-chat.ts` — switch 加两 case + `dispatchLanes` 状态。
- `frontend/src/components/chat/ChatPane.tsx` — 挂 `<DispatchLanes />`。

---

## Task 1: 数据契约 `SubtaskRequest` / `SubagentResult`

**Files:**
- Create: `backend/app/chatloop/subagent.py`
- Test: `backend/tests/unit/chatloop/test_subagent.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/chatloop/test_subagent.py
"""L0 — dispatch_subagents 子 agent 派发原语(契约/factory/tool/护栏)。"""

from __future__ import annotations

import pytest

from app.chatloop.subagent import SubagentResult, SubtaskRequest


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/unit/chatloop/test_subagent.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.chatloop.subagent'`

- [ ] **Step 3: Write minimal implementation (contracts only)**

```python
# backend/app/chatloop/subagent.py
"""dispatch_subagents — chat 内只读扇出子 agent 派发原语(spec 2026-06-11)。

子循环 = 同一个 ToolLoop 类换受限依赖(只读子 hub / max_steps=4 / tier=fast /
白纸 context)。与深度研报彻底隔离:子循环只读白名单不含 offer_deep_research /
dispatch_subagents(禁串门 + 禁递归)。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ── 护栏常量 ──────────────────────────────────────────────────────────────
MAX_SUBAGENTS = 8  # 个数上限(spec §4.2);超出让模型分批派
CHILD_MAX_STEPS = 4  # 子循环硬步数上限(spec §4.2)
CHILD_BUDGET_FRACTION = 0.6  # 给整批的预算占当轮剩余预算比例
CHILD_MIN_CNY = 0.005  # 单子循环预算下限(低于则拒派)
CHILD_TIER = "fast"

# 子循环只读白名单(MCP 数据工具) — 不含 memory_* / skill / control / dispatch
READONLY_SUBAGENT_TOOLS: list[str] = [
    "get_stock_quote",
    "get_financial_statements",
    "kb_search",
    "get_news",
    "web_search",
    "get_market_indicators",
    "get_corporate_actions",
]


class SubtaskRequest(BaseModel):
    """一个子任务的 LLM-facing 表(主 AI 填)。harness 补 subtask_id/tool_scope/tier/caps。"""

    goal: str
    target: str | None = None  # ts_code / 信息源标识
    output_hint: str = ""  # 想要的产出形状
    boundary: str | None = None  # 边界(如"只看近一年")


class SubagentResult(BaseModel):
    """一个子循环的回收结果(原文摘要直传,进程内对象)。"""

    model_config = ConfigDict(frozen=True)

    subtask_id: str
    target: str | None
    summary: str  # 子循环自己的终答原文(verbatim,不复述)
    evidence_refs: list[str] = Field(default_factory=list)
    status: Literal["ok", "partial", "failed"]
    gap_note: str | None = None
    tokens_spent: int = 0
    cost_cny: float = 0.0
    steps_used: int = 0
    tier: str = CHILD_TIER


__all__ = [
    "CHILD_BUDGET_FRACTION",
    "CHILD_MAX_STEPS",
    "CHILD_MIN_CNY",
    "CHILD_TIER",
    "MAX_SUBAGENTS",
    "READONLY_SUBAGENT_TOOLS",
    "SubagentResult",
    "SubtaskRequest",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/unit/chatloop/test_subagent.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/chatloop/subagent.py backend/tests/unit/chatloop/test_subagent.py
git commit -m "feat(chatloop): dispatch_subagents 数据契约 SubtaskRequest/SubagentResult"
```

---

## Task 2: ToolHub flat-schema 模式 + `register_subset`（子循环只读 hub 基建）

子循环需要一个**只挂 ~7 个只读工具、全完整 schema、无 search_tools/无渐进披露**的 hub。给 `ToolHub` 加 `progressive: bool = True` 开关 + `register_subset` 方法。

**Files:**
- Modify: `backend/app/chatloop/tool_hub.py:62-72`（`__init__`）、`schemas_for_llm`（:101-142）
- Test: `backend/tests/unit/chatloop/test_tool_hub_subset.py`（新建）

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/chatloop/test_tool_hub_subset.py
"""L0 — ToolHub flat-schema 模式 + register_subset(子循环只读 hub 基建)。"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from app.chatloop.tool_hub import ToolHub
from app.tools.base import Tool


class _QuoteArgs(BaseModel):
    ts_code: str


class _FakeTool(Tool):
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = f"fake {name}"
        self.args_schema = _QuoteArgs

    async def run(self, args: BaseModel) -> dict[str, Any]:
        return {"ok": True}


class _FakeRegistry:
    def __init__(self, names: list[str]) -> None:
        self._tools = {n: _FakeTool(n) for n in names}

    def list_for_llm(self) -> list[dict[str, Any]]:
        return [{"function": {"name": n}} for n in self._tools]

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)


def test_register_subset_only_registers_named() -> None:
    reg = _FakeRegistry(["get_stock_quote", "get_news", "compare_stocks"])
    hub = ToolHub(progressive=False)
    hub.register_subset(reg, ["get_stock_quote", "get_news"])
    schemas = hub.schemas_for_llm()
    names = [s["function"]["name"] for s in schemas]
    assert names == ["get_stock_quote", "get_news"]  # 不含 compare_stocks


def test_flat_mode_no_search_tools_full_schema() -> None:
    # progressive=False:不追加 search_tools,且每个工具出完整 schema(有 properties)
    reg = _FakeRegistry(["get_stock_quote"])
    hub = ToolHub(progressive=False)
    hub.register_subset(reg, ["get_stock_quote"])
    schemas = hub.schemas_for_llm()
    assert all(s["function"]["name"] != "search_tools" for s in schemas)
    params = schemas[0]["function"]["parameters"]
    assert "ts_code" in params["properties"]  # 完整 schema,非瘦条目


def test_register_subset_dup_fail_loud() -> None:
    reg = _FakeRegistry(["get_stock_quote"])
    hub = ToolHub(progressive=False)
    hub.register_subset(reg, ["get_stock_quote"])
    with pytest.raises(ValueError):
        hub.register_subset(reg, ["get_stock_quote"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/unit/chatloop/test_tool_hub_subset.py -q`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'progressive'`

- [ ] **Step 3: Modify `ToolHub.__init__` to add `progressive`**

In `backend/app/chatloop/tool_hub.py`, change `__init__` (around :62-72):

```python
    def __init__(
        self,
        *,
        emit: EmitFn | None = None,
        cache: ToolResultCache | None = None,
        seq_counter: SeqCounter | None = None,
        progressive: bool = True,
    ) -> None:
        self._tools: dict[str, Tool] = {}
        self._emit_fn = emit
        self._cache = cache
        self._seq_counter = seq_counter if seq_counter is not None else SeqCounter()
        self._progressive = progressive
```

- [ ] **Step 4: Add `register_subset` method (after `register_registry`, ~:95)**

```python
    def register_subset(self, registry: Any, names: list[str]) -> None:
        """只注册 registry 中指定名字的工具(子循环只读子集用)。重名 fail loud。

        registry 须暴露 list_for_llm()(取可用名)与 get(name)(取 Tool 实例)。
        不在 registry 中的名字静默跳过(白名单与实际可用工具求交集)。
        """
        available = {s["function"]["name"] for s in registry.list_for_llm()}
        for name in names:
            if name not in available:
                continue
            if name in self._tools:
                raise ValueError(f"duplicate tool name: {name}")
            self._tools[name] = registry.get(name)
```

- [ ] **Step 5: Add flat-schema branch to `schemas_for_llm` (top of method, ~:101)**

```python
    def schemas_for_llm(self) -> list[dict[str, Any]]:
        # 子循环用 flat 模式:全部已注册工具出完整 schema,无渐进披露/无 search_tools。
        if not self._progressive:
            return [self._tools[name].schema_for_llm() for name in self._tools]
        # ── 以下为原渐进披露三组逻辑(CORE/DEFERRED/search_tools),保持不变 ──
        ...  # 原有代码不动
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/unit/chatloop/test_tool_hub_subset.py tests/unit/chatloop/test_tool_hub.py -q`
Expected: PASS（新 3 个 + 原 tool_hub 测试不回归）

- [ ] **Step 7: Commit**

```bash
git add backend/app/chatloop/tool_hub.py backend/tests/unit/chatloop/test_tool_hub_subset.py
git commit -m "feat(chatloop): ToolHub flat-schema 模式 + register_subset(子循环只读 hub)"
```

---

## Task 3: `SubagentFactory.spawn_one`（起一个子循环）

**Files:**
- Modify: `backend/app/chatloop/subagent.py`（加 `CHILD_SYSTEM_PROMPT` / `build_child_tool_hub` / `SubagentFactory`）
- Test: `backend/tests/unit/chatloop/test_subagent.py`（追加）

- [ ] **Step 1: Write the failing test (用 FakeLLM 驱动一个子循环跑完一圈)**

```python
# 追加到 backend/tests/unit/chatloop/test_subagent.py 顶部 import
import json
from typing import Any

from app.agents.schemas import ToolResult
from app.chatloop.events import LoopEvent, SeqCounter
from app.chatloop.gates import GateConfig
from app.chatloop.state import ChatLoopState
from app.chatloop.subagent import SubagentFactory
from app.services.llm_step import StepResult, StepToolCall


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
        from app.tools.base import Tool
        from pydantic import BaseModel

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/unit/chatloop/test_subagent.py::test_spawn_one_returns_ok_result -q`
Expected: FAIL — `ImportError: cannot import name 'SubagentFactory'`

- [ ] **Step 3: Implement `CHILD_SYSTEM_PROMPT` / `build_child_tool_hub` / `SubagentFactory.spawn_one`**

追加到 `backend/app/chatloop/subagent.py`（import 段加 `from app.chatloop.context import ContextDeps`、`from app.chatloop.events import LoopEvent, SeqCounter`、`from app.chatloop.gates import GateConfig`、`from app.chatloop.loop import ToolLoop`、`from app.chatloop.state import ChatLoopState`、`from app.chatloop.tool_hub import ToolHub`、`from typing import Any, Awaitable, Callable`）：

```python
CHILD_SYSTEM_PROMPT = (
    "你是一个只读检索子助手。只做被指派的这一件查取任务,用给到的只读工具查清后,"
    "用最多 3 句话给出结论性摘要(含关键数字)。不要寒暄、不要展开分析、不要追问。"
    "查不到就直说缺什么。你看不到主对话历史,也不知道别的子任务在做什么。"
)


def _render_subtask(req: SubtaskRequest) -> str:
    lines = [f"任务目标:{req.goal}"]
    if req.target:
        lines.append(f"对象:{req.target}")
    if req.output_hint:
        lines.append(f"产出格式:{req.output_hint}")
    if req.boundary:
        lines.append(f"边界:{req.boundary}")
    return "\n".join(lines)


def build_child_tool_hub(
    registry: Any, *, emit: Any, seq_counter: SeqCounter, cache: Any
) -> ToolHub:
    """构造子循环的只读 hub(flat schema,只挂只读白名单工具)。"""
    hub = ToolHub(emit=emit, cache=cache, seq_counter=seq_counter, progressive=False)
    hub.register_subset(registry, READONLY_SUBAGENT_TOOLS)
    return hub


class SubagentFactory:
    """起子循环 + 收回 SubagentResult。per-turn 在 build_turn_components 构造。"""

    def __init__(
        self,
        *,
        llm: Any,
        registry: Any,
        cache: Any,
        emit: Callable[[LoopEvent], Awaitable[None]],
        seq_counter: SeqCounter,
        gate_cfg: GateConfig,
        audit_repo: Any | None,
    ) -> None:
        self._llm = llm
        self._registry = registry
        self._cache = cache
        self._emit = emit
        self._seq = seq_counter
        self._gate_cfg = gate_cfg
        self._audit = audit_repo

    def _lane_emit(self, subtask_id: str) -> Callable[[LoopEvent], Awaitable[None]]:
        async def _wrapped(ev: LoopEvent) -> None:
            tagged = ev.model_copy(update={"data": {**ev.data, "lane": subtask_id}})
            await self._emit(tagged)

        return _wrapped

    async def spawn_one(
        self, req: SubtaskRequest, parent: ChatLoopState, *, subtask_id: str,
        child_cny: float = CHILD_MIN_CNY, child_tokens: int = 20_000,
    ) -> SubagentResult:
        child_state = ChatLoopState(
            user_id=parent.user_id,
            session_id=parent.session_id,
            request_id=f"{parent.request_id}::sub::{subtask_id}",
            messages=[{"role": "user", "content": _render_subtask(req)}],
        )
        child_hub = build_child_tool_hub(
            self._registry, emit=self._lane_emit(subtask_id),
            seq_counter=self._seq, cache=self._cache,
        )
        deps = ContextDeps(
            system_prompt=CHILD_SYSTEM_PROMPT, persona_block="", skill_listing="",
            history_block=(), max_steps=CHILD_MAX_STEPS, max_cny=child_cny,
        )
        loop = ToolLoop(
            llm=self._llm, tool_hub=child_hub, context_deps=deps,
            gate_cfg=GateConfig(max_steps=CHILD_MAX_STEPS, max_cny=child_cny, max_tokens=child_tokens),
            emit=self._lane_emit(subtask_id), seq_counter=self._seq, tier=CHILD_TIER,
        )
        try:
            final = await loop.run(child_state)
        except Exception as exc:  # noqa: BLE001 — fail loud,包成 failed 结果不抛
            return SubagentResult(
                subtask_id=subtask_id, target=req.target, summary="",
                evidence_refs=[], status="failed", gap_note=f"子循环异常:{exc}",
                tokens_spent=0, cost_cny=0.0, steps_used=0, tier=CHILD_TIER,
            )
        status: str = "ok" if final.halt_reason in (None, "natural") else "partial"
        refs = [e.cache_key for e in final.ledger.entries if e.cache_key]
        gap = None if status == "ok" else f"子循环未自然收尾({final.halt_reason})"
        return SubagentResult(
            subtask_id=subtask_id, target=req.target,
            summary=final.final_response or "", evidence_refs=refs,
            status=status, gap_note=gap, tokens_spent=final.budget_spent_tokens,
            cost_cny=final.budget_spent_cny, steps_used=final.step, tier=CHILD_TIER,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/unit/chatloop/test_subagent.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/chatloop/subagent.py backend/tests/unit/chatloop/test_subagent.py
git commit -m "feat(chatloop): SubagentFactory.spawn_one 起一个只读子循环"
```

---

## Task 4: `SubagentFactory.dispatch`（N 路并发 + 预算回滚 + dispatch 事件）

**Files:**
- Modify: `backend/app/chatloop/subagent.py`（加 `dispatch` 方法）
- Test: `backend/tests/unit/chatloop/test_subagent.py`（追加）

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_dispatch_three_parallel_rolls_budget_and_emits() -> None:
    # 三个子任务各跑两圈(查→答)。共享一个 _FakeLLM 脚本(6 个 StepResult)
    script: list[StepResult] = []
    for _ in range(3):
        script.append(_step(tool_calls=[_call("get_stock_quote", {"ts_code": "x"})]))
        script.append(_step(content="结论 1700。", finish_reason="stop"))
    llm = _FakeLLM(script)
    events: list[LoopEvent] = []

    async def _emit(ev: LoopEvent) -> None:
        events.append(ev)

    factory = SubagentFactory(
        llm=llm, registry=_FakeRegistry(), cache=None, emit=_emit,
        seq_counter=SeqCounter(), gate_cfg=GateConfig(), audit_repo=None,
    )
    parent = _parent_state()
    reqs = [SubtaskRequest(goal=f"查{i}", target=f"t{i}") for i in range(3)]
    results = await factory.dispatch(reqs, parent)

    assert len(results) == 3
    assert all(r.status == "ok" for r in results)
    # 预算回滚进父 state(3 个子循环各烧了 token/钱)
    assert parent.budget_spent_tokens > 0
    assert parent.budget_spent_cny > 0
    # dispatch_start / dispatch_end 各一次
    assert sum(1 for e in events if e.type == "dispatch_start") == 1
    assert sum(1 for e in events if e.type == "dispatch_end") == 1


@pytest.mark.asyncio
async def test_dispatch_one_child_fails_others_survive() -> None:
    # 第二个子任务首圈就抛(FakeLLM 脚本耗尽 → pop IndexError)
    script = [
        _step(tool_calls=[_call("get_stock_quote", {"ts_code": "x"})]),
        _step(content="ok", finish_reason="stop"),
    ]
    llm = _FakeLLM(script)  # 只够 1 个子任务,第 2/3 个 pop 抛 → failed

    async def _emit(ev: LoopEvent) -> None:
        pass

    factory = SubagentFactory(
        llm=llm, registry=_FakeRegistry(), cache=None, emit=_emit,
        seq_counter=SeqCounter(), gate_cfg=GateConfig(), audit_repo=None,
    )
    results = await factory.dispatch(
        [SubtaskRequest(goal="a"), SubtaskRequest(goal="b"), SubtaskRequest(goal="c")],
        _parent_state(),
    )
    assert len(results) == 3  # 永远回 N 份,不抛
    assert any(r.status == "failed" for r in results)
    assert any(r.status == "ok" for r in results)
```

> 注：`_FakeLLM.stream_step` 在脚本耗尽时 `pop(0)` 抛 `IndexError`，正好模拟"子循环异常 → failed 结果"。并发下哪个子任务拿到唯一一对脚本不确定，但"至少一个 ok、至少一个 failed、共 3 份"恒成立。

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/unit/chatloop/test_subagent.py::test_dispatch_three_parallel_rolls_budget_and_emits -q`
Expected: FAIL — `AttributeError: 'SubagentFactory' object has no attribute 'dispatch'`

- [ ] **Step 3: Implement `dispatch`**

追加 import `import asyncio`、`from app.chatloop.events import EventType`（已 import LoopEvent）。在 `SubagentFactory` 内加：

```python
    async def dispatch(
        self, subtasks: list[SubtaskRequest], parent: ChatLoopState
    ) -> list[SubagentResult]:
        n = len(subtasks)
        # 预算切片:给整批 = 当轮剩余 × FRACTION,均分到每个子循环
        remaining_cny = max(0.0, self._gate_cfg.max_cny - parent.budget_spent_cny)
        remaining_tokens = max(0, self._gate_cfg.max_tokens - parent.budget_spent_tokens)
        child_cny = max(CHILD_MIN_CNY, (remaining_cny * CHILD_BUDGET_FRACTION) / n)
        child_tokens = max(5_000, int((remaining_tokens * CHILD_BUDGET_FRACTION) / n))

        await self._emit_plain(
            "dispatch_start", parent.step,
            n=n, subtasks=[{"subtask_id": f"sub-{i}", "goal": s.goal[:60]}
                           for i, s in enumerate(subtasks)],
        )
        results: list[SubagentResult] = await asyncio.gather(
            *(self.spawn_one(req, parent, subtask_id=f"sub-{i}",
                             child_cny=child_cny, child_tokens=child_tokens)
              for i, req in enumerate(subtasks))
        )
        # 预算回滚进父 state(ChatLoopState 字段可变)
        for r in results:
            parent.budget_spent_cny += r.cost_cny
            parent.budget_spent_tokens += r.tokens_spent
        # 审计落库(best-effort)
        if self._audit is not None:
            try:
                self._audit.record_batch(parent=parent, subtasks=subtasks, results=results)
            except Exception:  # noqa: BLE001 — 留痕非致命
                pass
        await self._emit_plain(
            "dispatch_end", parent.step,
            n=n, results=[{"subtask_id": r.subtask_id, "status": r.status} for r in results],
        )
        return results

    async def _emit_plain(self, type_: str, step: int, /, **data: Any) -> None:
        seq = self._seq.next()
        await self._emit(LoopEvent(type=type_, seq=seq, step=step, data=data))  # type: ignore[arg-type]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/unit/chatloop/test_subagent.py -q`
Expected: PASS（注：`dispatch_start`/`dispatch_end` 此时还不在 EventType Literal 里 — 见 Task 7。`LoopEvent` 用 `# type: ignore` 绕过 mypy；运行期 Pydantic 对 Literal 校验会拒未知 type → **本 Task 先把 EventType 扩了**。把 Task 7 Step "扩 EventType" 提前到这里执行：）

- [ ] **Step 5: 先扩 `EventType`（dispatch 事件依赖）**

在 `backend/app/chatloop/events.py:13-29` 的 `EventType` Literal 末尾加两项：

```python
    "dispatch_start",
    "dispatch_end",
```

重跑 Step 4 命令，Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add backend/app/chatloop/subagent.py backend/app/chatloop/events.py backend/tests/unit/chatloop/test_subagent.py
git commit -m "feat(chatloop): SubagentFactory.dispatch N路并发+预算回滚+dispatch事件"
```

---

## Task 5: `DispatchSubagentsTool`（InProcessTool 包装 + 护栏）

**Files:**
- Modify: `backend/app/chatloop/subagent.py`（加 `DispatchSubagentsArgs` / `DispatchSubagentsTool`）
- Test: `backend/tests/unit/chatloop/test_subagent.py`（追加）

- [ ] **Step 1: Write the failing test**

```python
from app.chatloop.subagent import DispatchSubagentsArgs, DispatchSubagentsTool
from app.tools.base import ToolError


class _StubFactory:
    def __init__(self) -> None:
        self.called_with = None

    async def dispatch(self, subtasks, parent):
        self.called_with = (subtasks, parent)
        return [
            SubagentResult(subtask_id=f"sub-{i}", target=s.target, summary=f"摘要{i}",
                           evidence_refs=[], status="ok", gap_note=None,
                           tokens_spent=100, cost_cny=0.001, steps_used=2, tier="fast")
            for i, s in enumerate(subtasks)
        ]


@pytest.mark.asyncio
async def test_dispatch_tool_returns_synthesizable_dict() -> None:
    factory = _StubFactory()
    tool = DispatchSubagentsTool(factory=factory)
    args = DispatchSubagentsArgs(
        reason="比三只票",
        subtasks=[SubtaskRequest(goal="查茅台", target="600519.SH"),
                  SubtaskRequest(goal="查五粮液", target="000858.SZ")],
    )
    out = await tool.run_with_state(args, _parent_state())
    assert out["dispatched"] == 2
    assert out["results"][0]["summary"] == "摘要0"
    assert out["results"][0]["status"] == "ok"


@pytest.mark.asyncio
async def test_dispatch_tool_rejects_empty() -> None:
    tool = DispatchSubagentsTool(factory=_StubFactory())
    with pytest.raises(ToolError):
        await tool.run_with_state(DispatchSubagentsArgs(reason="x", subtasks=[]), _parent_state())


@pytest.mark.asyncio
async def test_dispatch_tool_rejects_over_cap() -> None:
    tool = DispatchSubagentsTool(factory=_StubFactory())
    too_many = [SubtaskRequest(goal=f"g{i}") for i in range(MAX_SUBAGENTS + 1)]
    with pytest.raises(ToolError):
        await tool.run_with_state(
            DispatchSubagentsArgs(reason="x", subtasks=too_many), _parent_state())
```

（顶部 import 追加 `from app.chatloop.subagent import MAX_SUBAGENTS`。）

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/unit/chatloop/test_subagent.py -k dispatch_tool -q`
Expected: FAIL — `ImportError: cannot import name 'DispatchSubagentsArgs'`

- [ ] **Step 3: Implement the tool**

追加 import `from app.chatloop.inprocess import InProcessTool`、`from app.tools.base import ToolError`、`from pydantic import BaseModel`（已有）。追加：

```python
def _fail(error: str) -> ToolError:
    return ToolError(error)


class DispatchSubagentsArgs(BaseModel):
    reason: str
    subtasks: list[SubtaskRequest]


class DispatchSubagentsTool(InProcessTool):
    name = "dispatch_subagents"
    description = (
        "把一组互不依赖、各自只用查的子任务并发派给只读子助手,收回每个的摘要。"
        "多标的对比/多源检索/逐只持仓体检时用;有先后依赖的任务别用(留主循环串行)。"
    )
    args_schema = DispatchSubagentsArgs

    def __init__(self, *, factory: Any) -> None:
        self._factory = factory

    async def run_with_state(self, args: BaseModel, state: ChatLoopState) -> dict[str, Any]:
        args = DispatchSubagentsArgs.model_validate(args.model_dump())
        n = len(args.subtasks)
        if n == 0:
            raise _fail("[无子任务] subtasks 为空,无可派发。")
        if n > MAX_SUBAGENTS:
            raise _fail(f"[子任务过多] 一次最多 {MAX_SUBAGENTS} 个(给了 {n}),请分批派发。")
        results = await self._factory.dispatch(args.subtasks, state)
        return {
            "dispatched": len(results),
            "results": [
                {"target": r.target or r.subtask_id, "status": r.status,
                 "summary": r.summary, "gap": r.gap_note}
                for r in results
            ],
        }
```

并把 `DispatchSubagentsArgs`/`DispatchSubagentsTool`/`SubagentFactory`/`build_child_tool_hub`/`CHILD_SYSTEM_PROMPT` 加进 `__all__`。

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/unit/chatloop/test_subagent.py -q`
Expected: PASS（全部）

- [ ] **Step 5: Commit**

```bash
git add backend/app/chatloop/subagent.py backend/tests/unit/chatloop/test_subagent.py
git commit -m "feat(chatloop): DispatchSubagentsTool 包装 factory + 个数/空护栏"
```

---

## Task 6: 审计表 `subagent_dispatch_runs` ORM + Repo

**Files:**
- Create: `backend/app/models/subagent_dispatch.py`
- Modify: `backend/app/models/__init__.py`（re-export）
- Create: `backend/app/services/subagent_audit.py`
- Test: `backend/tests/unit/test_subagent_dispatch_model.py`

- [ ] **Step 1: Write the failing test (ORM roundtrip)**

```python
# backend/tests/unit/test_subagent_dispatch_model.py
"""L0 — subagent_dispatch_runs 审计表 roundtrip + 注册守卫。"""

from __future__ import annotations


def test_table_registered_in_metadata() -> None:
    import app.models  # noqa: F401 — barrel 触发注册
    from app.core.database import Base

    assert "subagent_dispatch_runs" in set(Base.metadata.tables.keys())


def test_roundtrip(db_session) -> None:
    from app.models import SubagentDispatchRun

    row = SubagentDispatchRun(
        id="row-1", batch_id="batch-1", parent_request_id="r1", turn_id="t1",
        scenario_type="multi_compare", subtask_id="sub-0",
        goal_packet={"goal": "查茅台", "target": "600519.SH"},
        tool_scope=["get_stock_quote", "get_news"],
        result_summary="茅台 1700。", result_refs=[], status="ok", gap_note=None,
        tokens=1200, cost_cny=0.003, steps_used=2, duration_ms=850, tier="fast",
    )
    db_session.add(row)
    db_session.flush()

    fetched = db_session.query(SubagentDispatchRun).filter_by(id="row-1").one()
    assert fetched.status == "ok"
    assert fetched.goal_packet["target"] == "600519.SH"
    assert fetched.tool_scope == ["get_stock_quote", "get_news"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/unit/test_subagent_dispatch_model.py -q`
Expected: FAIL — `ImportError: cannot import name 'SubagentDispatchRun' from 'app.models'`

- [ ] **Step 3: Create the ORM model (mirror `memory_calibration.py`)**

```python
# backend/app/models/subagent_dispatch.py
"""subagent_dispatch_runs — chat 内子 agent 派发审计表(spec 2026-06-11 §8.2)。

一行 = 一个子循环。批次字段(batch_id/scenario_type)去规范化到每行,聚合用。
create_all 幂等建表(项目不引 alembic)。
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.core.database import Base


class SubagentDispatchRun(Base):
    __tablename__ = "subagent_dispatch_runs"

    id = Column(String(64), primary_key=True)
    batch_id = Column(String(64), nullable=False)
    parent_request_id = Column(String(64), nullable=False)
    turn_id = Column(String(64), nullable=True)
    scenario_type = Column(String(32), nullable=True)
    subtask_id = Column(String(64), nullable=False)
    goal_packet = Column(JSONB(), nullable=False, default=dict)
    tool_scope = Column(JSONB(), nullable=False, default=list)
    result_summary = Column(Text, nullable=True)
    result_refs = Column(JSONB(), nullable=False, default=list)
    status = Column(String(16), nullable=False)
    gap_note = Column(Text, nullable=True)
    tokens = Column(Integer, nullable=False, default=0)
    cost_cny = Column(Float, nullable=False, default=0.0)
    steps_used = Column(Integer, nullable=False, default=0)
    duration_ms = Column(Integer, nullable=False, default=0)
    tier = Column(String(16), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_subagent_batch", "batch_id"),
        Index("idx_subagent_parent_req", "parent_request_id"),
        Index("idx_subagent_scenario", "scenario_type"),
        Index("idx_subagent_status", "status"),
        Index("idx_subagent_created", "created_at"),
    )
```

- [ ] **Step 4: Re-export in barrel**

In `backend/app/models/__init__.py`: add import line (near other model imports, ~:26) and `__all__` entry:

```python
from .subagent_dispatch import SubagentDispatchRun  # noqa: F401
```

Add `"SubagentDispatchRun",` to the `__all__` list.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/unit/test_subagent_dispatch_model.py -q`
Expected: PASS

- [ ] **Step 6: Write the SubagentAuditRepo test**

```python
# 追加到 backend/tests/unit/test_subagent_dispatch_model.py
import contextlib


def test_audit_repo_record_batch_writes_one_row_per_child(db_session) -> None:
    from app.chatloop.state import ChatLoopState
    from app.chatloop.subagent import SubagentResult, SubtaskRequest
    from app.models import SubagentDispatchRun
    from app.services.subagent_audit import SubagentAuditRepo

    repo = SubagentAuditRepo(session_factory=lambda: contextlib.nullcontext(db_session))
    parent = ChatLoopState(user_id="u1", session_id="s1", request_id="r1",
                           messages=[{"role": "user", "content": "比"}])
    subtasks = [SubtaskRequest(goal="查茅台", target="600519.SH"),
                SubtaskRequest(goal="查五粮液", target="000858.SZ")]
    results = [
        SubagentResult(subtask_id="sub-0", target="600519.SH", summary="a", evidence_refs=[],
                       status="ok", gap_note=None, tokens_spent=100, cost_cny=0.001,
                       steps_used=2, tier="fast"),
        SubagentResult(subtask_id="sub-1", target="000858.SZ", summary="b", evidence_refs=[],
                       status="partial", gap_note="超步", tokens_spent=200, cost_cny=0.002,
                       steps_used=4, tier="fast"),
    ]
    repo.record_batch(parent=parent, subtasks=subtasks, results=results,
                      scenario_type="multi_compare")
    db_session.flush()

    rows = db_session.query(SubagentDispatchRun).filter_by(parent_request_id="r1").all()
    assert len(rows) == 2
    assert {r.status for r in rows} == {"ok", "partial"}
    assert all(r.batch_id == rows[0].batch_id for r in rows)  # 同批共享 batch_id
```

- [ ] **Step 7: Implement `SubagentAuditRepo`**

```python
# backend/app/services/subagent_audit.py
"""SubagentAuditRepo — 把每个子循环写进 subagent_dispatch_runs(best-effort)。

默认用 sync SessionLocal(与 TraceService 同款,留痕非致命);测试注入
nullcontext(db_session)。id/batch_id 由调用方不传时用 request_id+index 拼,
避免依赖 Math.random/uuid(可测)。
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

from sqlalchemy.orm import Session

from app.models import SubagentDispatchRun


def _default_session_factory() -> AbstractContextManager[Session]:
    from app.core.database import SessionLocal

    return SessionLocal()


class SubagentAuditRepo:
    def __init__(
        self,
        session_factory: Callable[[], AbstractContextManager[Session]] | None = None,
    ) -> None:
        self._session_factory = session_factory or _default_session_factory

    def record_batch(
        self, *, parent: Any, subtasks: list[Any], results: list[Any],
        scenario_type: str | None = None,
    ) -> None:
        batch_id = f"{parent.request_id}::batch"
        with self._session_factory() as session:
            for i, (req, res) in enumerate(zip(subtasks, results, strict=False)):
                session.add(
                    SubagentDispatchRun(
                        id=f"{parent.request_id}::sub::{i}",
                        batch_id=batch_id,
                        parent_request_id=parent.request_id,
                        turn_id=parent.session_id,
                        scenario_type=scenario_type,
                        subtask_id=res.subtask_id,
                        goal_packet={"goal": req.goal, "target": req.target,
                                     "output_hint": req.output_hint, "boundary": req.boundary},
                        tool_scope=list(getattr(res, "tool_scope", [])) or
                        __import__("app.chatloop.subagent", fromlist=["READONLY_SUBAGENT_TOOLS"]).READONLY_SUBAGENT_TOOLS,
                        result_summary=res.summary,
                        result_refs=list(res.evidence_refs),
                        status=res.status,
                        gap_note=res.gap_note,
                        tokens=res.tokens_spent,
                        cost_cny=res.cost_cny,
                        steps_used=res.steps_used,
                        duration_ms=0,
                        tier=res.tier,
                    )
                )
            session.commit()
```

> 注：`tool_scope` 取常量 `READONLY_SUBAGENT_TOOLS`（子循环实际可用工具集）。上面的 `__import__` 写法可读性差，实施时改为顶部 `from app.chatloop.subagent import READONLY_SUBAGENT_TOOLS` 直接用（此处因避免循环 import 才示意延迟取；若无循环 import 问题，直接顶部 import）。先验证无循环 import：`subagent.py` 不 import `subagent_audit`，故 `subagent_audit` 顶部 import `subagent` 安全。**实施时用顶部 import。**

- [ ] **Step 8: Run audit repo test**

Run: `cd backend && python -m pytest tests/unit/test_subagent_dispatch_model.py -q`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add backend/app/models/subagent_dispatch.py backend/app/models/__init__.py backend/app/services/subagent_audit.py backend/tests/unit/test_subagent_dispatch_model.py
git commit -m "feat(留痕): subagent_dispatch_runs 审计表 ORM + SubagentAuditRepo"
```

---

## Task 7: 工具文档注册（`tool_docs.py`）

**Files:**
- Modify: `backend/app/chatloop/tool_docs.py`（`TOOL_DOCS` + `DEFERRED_TOOLS`）
- Test: `backend/tests/unit/chatloop/test_tool_docs_dispatch.py`（新建）

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/chatloop/test_tool_docs_dispatch.py
"""L0 — dispatch_subagents 进延迟组 + 有完整文档。"""

from __future__ import annotations

from app.chatloop.tool_docs import DEFERRED_TOOLS, TOOL_DOCS, thin_schema


def test_dispatch_in_deferred_with_doc() -> None:
    assert "dispatch_subagents" in DEFERRED_TOOLS
    assert "dispatch_subagents" in TOOL_DOCS
    doc = TOOL_DOCS["dispatch_subagents"]
    assert doc.group == "deferred"
    # subtasks 必填 → 瘦 schema 暴露它
    assert doc.thin_required is not None
    assert "subtasks" in doc.thin_required


def test_dispatch_thin_schema_has_required() -> None:
    schema = thin_schema(TOOL_DOCS["dispatch_subagents"])
    assert "subtasks" in schema["function"]["parameters"]["required"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/unit/chatloop/test_tool_docs_dispatch.py -q`
Expected: FAIL — `assert 'dispatch_subagents' in DEFERRED_TOOLS`

- [ ] **Step 3: Add to `DEFERRED_TOOLS` list (tool_docs.py:380-389)**

```python
DEFERRED_TOOLS: list[str] = [
    "get_market_indicators",
    "get_corporate_actions",
    "get_news",
    "web_search",
    "compare_stocks",
    "memory_write",
    "run_skill_script",
    "read_cached_result",
    "dispatch_subagents",
]
```

- [ ] **Step 4: Add `TOOL_DOCS` entry (in the `TOOL_DOCS` dict, ~:49-363)**

```python
    "dispatch_subagents": ToolDoc(
        name="dispatch_subagents",
        group="deferred",
        brief="把一组互不依赖、各自只用查的子任务并发派给只读子助手并收回摘要。多标的对比/多源检索/逐只持仓体检时用。",
        doc=(
            "把一组互不依赖、各自只用查的子任务一次性并发派给若干只读子助手,"
            "收回每个子助手的结论摘要,由你综合成最终回答。\n"
            "何时用:多标的横向对比(茅台五粮液宁德比一比)、多信息源广度检索"
            "(KB+新闻+泛网)、逐只持仓体检——这类'N 个同构独立的只读小任务'。\n"
            "何时不用:① 单个事实查询(直接调对应工具即可,别扇出);"
            "② 子任务之间有先后依赖(B 要先看 A 的产出,如先估值再辩论)——"
            "那种留给主循环逐圈串行,别派;③ 要做整份尽调 → 改用 offer_deep_research。\n"
            "参数:\n"
            "  reason(str,必填)—— 为什么要扇出的一句话。\n"
            "  subtasks(array,必填)—— 子任务列表(最多 8 个),每项:\n"
            "    goal(str,必填)、target(str,可选,ts_code/源标识)、"
            "output_hint(str,可选,想要的产出形状)、boundary(str,可选,边界)。\n"
            "示例:dispatch_subagents(reason='对比三只白酒', subtasks=["
            "{'goal':'查茅台现价与营收增速','target':'600519.SH'},"
            "{'goal':'查五粮液现价与营收增速','target':'000858.SZ'}])。\n"
            "硬约束:子助手只读、看不到主对话、互不通信;超过 8 个请分批派;"
            "子助手不会再派子助手、也不会升级深度研究。"
        ),
        thin_required={"subtasks": "array"},
    ),
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/unit/chatloop/test_tool_docs_dispatch.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/chatloop/tool_docs.py backend/tests/unit/chatloop/test_tool_docs_dispatch.py
git commit -m "feat(chatloop): dispatch_subagents 进延迟组 + 完整工具文档"
```

---

## Task 8: 装配（`worker_wiring.build_turn_components`）

**Files:**
- Modify: `backend/app/chatloop/worker_wiring.py`（import + `build_turn_components` 构造 factory + 注册 tool）
- Test: `backend/tests/unit/chatloop/test_worker_wiring_dispatch.py`（新建）

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/chatloop/test_worker_wiring_dispatch.py
"""L0 — build_turn_components 注册了 dispatch_subagents。"""

from __future__ import annotations

from typing import Any

import pytest

from app.chatloop.events import SeqCounter
from app.chatloop.gates import GateConfig
from app.chatloop.worker_wiring import HeavySingletons, build_turn_components


class _StubRegistry:
    def list_for_llm(self) -> list[dict[str, Any]]:
        return []

    def get(self, name: str) -> Any:
        return None


def _singletons() -> HeavySingletons:
    return HeavySingletons(
        llm=object(), registry=_StubRegistry(), memory=object(), loader=object(),
        executor=object(), cache=None, skill_listing="", gate_cfg=GateConfig(),
    )


@pytest.mark.asyncio
async def test_dispatch_tool_registered() -> None:
    async def _emit(ev: Any) -> None:
        pass

    components = build_turn_components(_singletons(), emit=_emit, seq_counter=SeqCounter())
    schemas = components.tool_hub.schemas_for_llm()
    names = [s["function"]["name"] for s in schemas]
    assert "dispatch_subagents" in names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/unit/chatloop/test_worker_wiring_dispatch.py -q`
Expected: FAIL — `assert 'dispatch_subagents' in names`

- [ ] **Step 3: Wire factory + tool in `build_turn_components`**

In `backend/app/chatloop/worker_wiring.py`:
- Add import (top, ~:28-40): `from app.chatloop.subagent import DispatchSubagentsTool, SubagentFactory`
- Add import: `from app.services.subagent_audit import SubagentAuditRepo`
- In `build_turn_components` (after `hub = ToolHub(...)`, before/within the `register_inprocess` list, ~:200-220):

```python
    subagent_factory = SubagentFactory(
        llm=singletons.llm,
        registry=singletons.registry,
        cache=singletons.cache,
        emit=emit,
        seq_counter=seq_counter,
        gate_cfg=singletons.gate_cfg,
        audit_repo=SubagentAuditRepo(),
    )
```

Add `DispatchSubagentsTool(factory=subagent_factory),` to the `hub.register_inprocess([...])` list.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/unit/chatloop/test_worker_wiring_dispatch.py -q`
Expected: PASS

- [ ] **Step 5: Run full chatloop unit suite (regression)**

Run: `cd backend && python -m pytest tests/unit/chatloop/ -q`
Expected: PASS (no regressions)

- [ ] **Step 6: Commit**

```bash
git add backend/app/chatloop/worker_wiring.py backend/tests/unit/chatloop/test_worker_wiring_dispatch.py
git commit -m "feat(chatloop): 装配 SubagentFactory + 注册 dispatch_subagents 工具"
```

---

## Task 9: cassette e2e fan-out 主路径

**Files:**
- Modify: `backend/tests/e2e/test_chatloop_cassette.py`（`_FAKE_RESULTS` + 新测试）

- [ ] **Step 1: Add fake result + test (write first, will skip until cassette recorded)**

In `backend/tests/e2e/test_chatloop_cassette.py`:
- In `_FAKE_RESULTS` dict (~:93-128) ensure read-only tool fakes exist (`get_stock_quote` etc already do). No new entry needed for `dispatch_subagents` itself because it's an InProcessTool that must run for real (it spawns children) — but in cassette mode children call the SAME `_FakeTool` read-only tools, which is what we want. **However** the cassette harness `_build_chatloop_agent` registers fakes via `register_inprocess([_FakeTool(name, ...) for name in fake_names])` where `fake_names` excludes `offer_deep_research`. Since `dispatch_subagents` is now in `DEFERRED_TOOLS`, it would be faked too — wrong. Exclude it and register the REAL tool wired to a real factory:

Modify `_build_chatloop_agent` (~:131-164) — exclude `dispatch_subagents` from fakes and wire a real one whose factory shares the same fake-tool registry:

```python
    fake_names = [n for n in (*CORE_TOOLS, *DEFERRED_TOOLS)
                  if n not in ("offer_deep_research", "dispatch_subagents")]
    hub.register_inprocess([_FakeTool(name, _FAKE_RESULTS[name]) for name in fake_names])
    hub.register_inprocess([OfferDeepResearchTool()])
    # 子循环复用 fake 只读工具:用一个 minimal registry 暴露 fake 工具给子 hub
    from app.chatloop.subagent import DispatchSubagentsTool, SubagentFactory, READONLY_SUBAGENT_TOOLS

    class _FakeReg:
        def __init__(self) -> None:
            self._t = {n: _FakeTool(n, _FAKE_RESULTS[n]) for n in READONLY_SUBAGENT_TOOLS}
        def list_for_llm(self):
            return [{"function": {"name": n}} for n in self._t]
        def get(self, name):
            return self._t.get(name)

    factory = SubagentFactory(llm=llm, registry=_FakeReg(), cache=None, emit=_noop_emit,
                              seq_counter=SeqCounter(), gate_cfg=GateConfig(), audit_repo=None)
    hub.register_inprocess([DispatchSubagentsTool(factory=factory)])
```

（`_noop_emit` / `SeqCounter` import 按需补；`_FAKE_RESULTS` 须含 `READONLY_SUBAGENT_TOOLS` 全部名字的预设——补齐 `get_market_indicators`/`get_corporate_actions`/`get_news`/`web_search` 若缺。）

- Add the test:

```python
@pytest.mark.vcr
@pytest.mark.asyncio
async def test_chatloop_fanout_compare() -> None:
    _skip_if_no_cassette("test_chatloop_fanout_compare")
    agent = _build_chatloop_agent()
    out = await agent.run("贵州茅台、五粮液、宁德时代三只一起比一比基本面",
                          request_id="cassette-fanout")
    tool_names = [tc.tool_name for tc in out.tool_calls]
    assert "dispatch_subagents" in tool_names
    assert out.response_text  # 主 AI 综合出了回答
```

- [ ] **Step 2: Run to verify it skips (no cassette yet)**

Run: `cd backend && python -m pytest tests/e2e/test_chatloop_cassette.py::test_chatloop_fanout_compare -q`
Expected: SKIPPED ("cassette missing")

- [ ] **Step 3: Record the cassette (needs DASHSCOPE_API_KEY; WSL fria-venv)**

Run (WSL): `cd backend && VCR_RECORD_MODE=once DASHSCOPE_API_KEY=$DASHSCOPE_API_KEY python -m pytest tests/e2e/test_chatloop_cassette.py::test_chatloop_fanout_compare -q`
Expected: PASS, creates `backend/tests/fixtures/cassettes/test_chatloop_cassette/test_chatloop_fanout_compare.yaml`

> 若真 LLM 不肯调 `dispatch_subagents`（提示词不够明确），微调 query 更直白（"分别查这三只的现价和营收增速再对比"）或在 system prompt/工具 brief 加触发引导，重录。

- [ ] **Step 4: Replay offline to verify deterministic**

Run: `cd backend && python -m pytest tests/e2e/test_chatloop_cassette.py::test_chatloop_fanout_compare -q`
Expected: PASS (offline replay)

- [ ] **Step 5: Commit**

```bash
git add backend/tests/e2e/test_chatloop_cassette.py backend/tests/fixtures/cassettes/test_chatloop_cassette/test_chatloop_fanout_compare.yaml
git commit -m "test(e2e): chatloop fan-out 主路径 cassette"
```

---

## Task 10: 前端 N 条并行进度条

**Files:**
- Modify: `frontend/src/types/chat.ts`
- Modify: `frontend/src/store/current-chat.ts`
- Create: `frontend/src/components/chat/DispatchLanes.tsx`
- Modify: `frontend/src/components/chat/ChatPane.tsx`
- Test: `frontend/src/components/chat/__tests__/DispatchLanes.test.tsx`

- [ ] **Step 1: Add event types + lane field (`types/chat.ts`)**

Add interfaces (near `ToolStartEvent`, ~:78):

```typescript
export interface DispatchStartEvent extends BaseEvent {
  type: 'dispatch_start'
  n: number
  subtasks: { subtask_id: string; goal: string }[]
}

export interface DispatchEndEvent extends BaseEvent {
  type: 'dispatch_end'
  n: number
  results: { subtask_id: string; status: 'ok' | 'partial' | 'failed' }[]
}
```

Add `lane?: string` to `ToolStartEvent` / `ToolEndEvent` / `ToolCallEvent` / `ToolErrorEvent` (~:71-95). Add `DispatchStartEvent | DispatchEndEvent` to the `SSEEvent` union (~:193-217) and `'dispatch_start' | 'dispatch_end'` to `SSEEventType` (~:219).

- [ ] **Step 2: Write the failing store test**

```typescript
// frontend/src/store/__tests__/current-chat-dispatch.test.ts
import { describe, it, expect, beforeEach } from 'vitest'
import { currentChatState, currentChatActions } from '../current-chat'

describe('dispatch lanes', () => {
  beforeEach(() => currentChatActions.reset())

  it('builds lanes from dispatch_start and updates on tool_end', () => {
    currentChatActions.beginStreaming()
    currentChatActions.dispatchEvent({
      type: 'dispatch_start', seq: 1, n: 2,
      subtasks: [{ subtask_id: 'sub-0', goal: '查茅台' }, { subtask_id: 'sub-1', goal: '查五粮液' }],
    } as any)
    expect(currentChatState.dispatchLanes.length).toBe(2)
    currentChatActions.dispatchEvent({ type: 'tool_end', seq: 2, lane: 'sub-0', tool: 'get_stock_quote' } as any)
    const lane0 = currentChatState.dispatchLanes.find((l) => l.subtask_id === 'sub-0')
    expect(lane0?.toolCount).toBeGreaterThan(0)
    currentChatActions.dispatchEvent({
      type: 'dispatch_end', seq: 3, n: 2,
      results: [{ subtask_id: 'sub-0', status: 'ok' }, { subtask_id: 'sub-1', status: 'partial' }],
    } as any)
    expect(currentChatState.dispatchLanes.find((l) => l.subtask_id === 'sub-1')?.status).toBe('partial')
  })
})
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd frontend && pnpm test current-chat-dispatch -- --run`
Expected: FAIL — `dispatchLanes` undefined / cases not handled

- [ ] **Step 4: Add `dispatchLanes` state + cases (`store/current-chat.ts`)**

Add to `CurrentChatState` (~:49-70): `dispatchLanes: DispatchLane[]`. Define type:

```typescript
export interface DispatchLane {
  subtask_id: string
  goal: string
  toolCount: number
  status: 'running' | 'ok' | 'partial' | 'failed'
}
```

Add `dispatchLanes: []` to `INITIAL` (~:72-87) and ensure `reset`/`resetStreaming`/`beginStreaming`/`setSession` clear it (~:108-298).

In `dispatchEvent` switch (~:161-259) add:

```typescript
      case 'dispatch_start':
        currentChatState.dispatchLanes = (ev as DispatchStartEvent).subtasks.map((s) => ({
          subtask_id: s.subtask_id, goal: s.goal, toolCount: 0, status: 'running',
        }))
        currentChatState.toolEvents.push(ev)
        break
      case 'dispatch_end':
        for (const r of (ev as DispatchEndEvent).results) {
          const lane = currentChatState.dispatchLanes.find((l) => l.subtask_id === r.subtask_id)
          if (lane) lane.status = r.status
        }
        currentChatState.toolEvents.push(ev)
        break
```

And in the existing `tool_end` case, increment the lane counter when `ev.lane` present:

```typescript
      case 'tool_end': {
        const laneId = (ev as ToolEndEvent).lane
        if (laneId) {
          const lane = currentChatState.dispatchLanes.find((l) => l.subtask_id === laneId)
          if (lane) lane.toolCount += 1
        }
        currentChatState.toolEvents.push(ev)
        break
      }
```

(Import `DispatchStartEvent`/`DispatchEndEvent`/`DispatchLane` types.)

- [ ] **Step 5: Run store test to verify pass**

Run: `cd frontend && pnpm test current-chat-dispatch -- --run`
Expected: PASS

- [ ] **Step 6: Create `DispatchLanes.tsx` + its test**

```tsx
// frontend/src/components/chat/DispatchLanes.tsx
import { useSnapshot } from 'valtio'
import { currentChatState } from '../../store/current-chat'

const STATUS_ICON: Record<string, string> = {
  running: '⏳', ok: '✓', partial: '◐', failed: '✗',
}

export function DispatchLanes() {
  const snap = useSnapshot(currentChatState)
  if (snap.dispatchLanes.length === 0) return null
  return (
    <div className="dispatch-lanes" data-testid="dispatch-lanes">
      <div className="dispatch-lanes__title">并行子助手 ({snap.dispatchLanes.length})</div>
      {snap.dispatchLanes.map((lane) => (
        <div key={lane.subtask_id} className="dispatch-lane" data-status={lane.status}>
          <span className="dispatch-lane__icon">{STATUS_ICON[lane.status] ?? '•'}</span>
          <span className="dispatch-lane__goal">{lane.goal}</span>
          <span className="dispatch-lane__count">{lane.toolCount} 次取数</span>
        </div>
      ))}
    </div>
  )
}
```

```tsx
// frontend/src/components/chat/__tests__/DispatchLanes.test.tsx
import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { DispatchLanes } from '../DispatchLanes'
import { currentChatActions } from '../../../store/current-chat'

describe('DispatchLanes', () => {
  beforeEach(() => currentChatActions.reset())

  it('renders nothing when no lanes', () => {
    const { container } = render(<DispatchLanes />)
    expect(container.firstChild).toBeNull()
  })

  it('renders one row per lane with status', () => {
    currentChatActions.dispatchEvent({
      type: 'dispatch_start', seq: 1, n: 2,
      subtasks: [{ subtask_id: 'sub-0', goal: '查茅台' }, { subtask_id: 'sub-1', goal: '查五粮液' }],
    } as any)
    render(<DispatchLanes />)
    expect(screen.getByTestId('dispatch-lanes')).toBeInTheDocument()
    expect(screen.getByText('查茅台')).toBeInTheDocument()
    expect(screen.getByText('查五粮液')).toBeInTheDocument()
  })
})
```

- [ ] **Step 7: Mount in `ChatPane.tsx`**

In `frontend/src/components/chat/ChatPane.tsx`, import `DispatchLanes` and render it next to `<StreamingIndicator />` (~:144):

```tsx
        <StreamingIndicator />
        <DispatchLanes />
```

- [ ] **Step 8: Run frontend tests**

Run: `cd frontend && pnpm test DispatchLanes current-chat-dispatch -- --run`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add frontend/src/types/chat.ts frontend/src/store/current-chat.ts frontend/src/components/chat/DispatchLanes.tsx frontend/src/components/chat/__tests__/DispatchLanes.test.tsx frontend/src/components/chat/ChatPane.tsx frontend/src/store/__tests__/current-chat-dispatch.test.ts
git commit -m "feat(frontend): dispatch_subagents N条并行进度条(DispatchLanes)"
```

---

## Task 11: 浏览器端到端真测

**Files:** 无新代码——真实环境验证 + GIF 录制。

- [ ] **Step 1: 起中间件 (PG + Redis)**

Run: `./start-services.sh start && ./start-services.sh status`
Expected: PostgreSQL + Redis healthy。

- [ ] **Step 2: 起后端 web (WSL fria-venv)**

Run (WSL, background): `cd backend && python app/app_main.py`
Expected: FastAPI 起在 :8000；日志 "PostgreSQL 表初始化完成"（确认 `subagent_dispatch_runs` 建表）。

验证建表：`psql -h localhost -U postgres -d industry_assistant -c "\d subagent_dispatch_runs"`（密码 postgres123）。

- [ ] **Step 3: 起 Celery worker (WSL fria-venv)**

Run (WSL, background): `cd backend && celery -A app.tasks.celery_app worker -Q default,llm --concurrency 4 --loglevel INFO`
Expected: worker ready；MCP chat_tools subprocess 起。

- [ ] **Step 4: 起前端 dev server (Windows)**

Run (background): `cd frontend && pnpm dev`
Expected: Vite 起在 :5183。

- [ ] **Step 5: 浏览器真测（加载 chrome 工具，录 GIF）**

用 mcp__claude-in-chrome 工具：
1. `tabs_context_mcp` → `tabs_create_mcp` 开新 tab → `navigate` 到 `http://localhost:5183/chat`（如需登录先过 `/login`）。
2. 开 `gif_creator` 录制，命名 `dispatch-subagents-e2e.gif`。
3. 在输入框发："贵州茅台、五粮液、宁德时代三只一起比一比基本面"。
4. 观察：SSE 出现 `dispatch_start` → DispatchLanes 渲染 3 条并行进度条 → 每条 `tool_end` 累加取数次数 → `dispatch_end` 三条变 ✓ → 主 AI 综合出对比回答。
5. `read_console_messages` 确认无报错；`read_network_requests` 确认 SSE 帧含 `dispatch_start`/`dispatch_end`/带 `lane` 的 tool 事件。
6. 停 GIF。

Expected: 3 条 lane 并行进度可见，最终一条对比回答落地。

- [ ] **Step 6: 验证审计落库**

Run: `psql -h localhost -U postgres -d industry_assistant -c "SELECT subtask_id, status, tokens, cost_cny FROM subagent_dispatch_runs ORDER BY created_at DESC LIMIT 5;"`
Expected: 看到刚才那轮的 3 行子循环审计记录（status/tokens/cost 非空）。

- [ ] **Step 7: 记录结果**

把 GIF 路径 + psql 输出 + 截图贴进 PR 描述草稿（Task 12 用）。若任一环失败 → 回到对应 Task 修，不在此硬扛（遵"避免 rabbit hole"）。

---

## Task 12: 隔离回归守卫 + eval golden + 收尾提 PR

**Files:**
- Test: `backend/tests/unit/chatloop/test_subagent_isolation.py`（隔离铁律守卫）
- Modify: chat 工具选择 golden（`backend/eval/tool_selection/golden.jsonl` 或对应路径）

- [ ] **Step 1: 隔离铁律回归守卫测试**

```python
# backend/tests/unit/chatloop/test_subagent_isolation.py
"""L0 — 隔离铁律守卫:子循环只读、禁串门(无 offer_deep_research)、禁递归。"""

from __future__ import annotations

from app.chatloop.subagent import READONLY_SUBAGENT_TOOLS


def test_readonly_whitelist_excludes_write_and_escalation_and_recursion() -> None:
    forbidden = {
        "memory_write", "offer_deep_research", "dispatch_subagents",
        "run_skill_script", "load_skill", "compare_stocks",
    }
    assert forbidden.isdisjoint(set(READONLY_SUBAGENT_TOOLS)), (
        "子循环白名单泄漏了写/升级/递归工具,违反隔离铁律"
    )


def test_whitelist_all_readonly_data_tools() -> None:
    # 白名单只含只读数据工具
    assert set(READONLY_SUBAGENT_TOOLS) == {
        "get_stock_quote", "get_financial_statements", "kb_search",
        "get_news", "web_search", "get_market_indicators", "get_corporate_actions",
    }
```

- [ ] **Step 2: Run it**

Run: `cd backend && python -m pytest tests/unit/chatloop/test_subagent_isolation.py -q`
Expected: PASS

- [ ] **Step 3: 加 2 条工具选择 golden（该派 / 不该派）**

在 chat 工具选择 golden 数据集追加（格式照该文件现有条目）：
- 该派：query="茅台五粮液宁德三只比一比基本面" → expected tool 含 `dispatch_subagents`。
- 不该瞎派：query="茅台现在多少钱" → expected tool=`get_stock_quote`，**不含** `dispatch_subagents`。

（具体 JSONL 字段照 `backend/eval/tool_selection/golden.jsonl` 现有条目结构填；先 Read 该文件确认 schema 再追加。）

- [ ] **Step 4: 全量回归 + 静态检查**

Run (WSL fria-venv):
```bash
cd backend && python -m pytest tests/unit/chatloop/ tests/unit/test_subagent_dispatch_model.py -q
cd backend && python -m mypy app/chatloop/subagent.py app/models/subagent_dispatch.py app/services/subagent_audit.py
cd backend && python -m ruff check app/chatloop/subagent.py app/models/subagent_dispatch.py app/services/subagent_audit.py
cd frontend && pnpm test -- --run && pnpm tsc --noEmit
```
Expected: 全绿。

- [ ] **Step 5: 推分支 + 提 PR**

```bash
git push -u origin design/chat-subagent-dispatch
gh pr create --title "feat(chatloop): chat 内 dispatch_subagents 只读扇出子 agent + 通信三层 + 审计留痕" --body "<见下>"
```

PR body 要点：
- 摘要：dispatch_subagents 只读扇出原语；主↔子原文直传、子↔子不通信、子→前端 lane 进度；审计表留痕；与深度研报隔离铁律。
- 对照 spec `docs/superpowers/specs/2026-06-11-chat-subagent-dispatch-design.md` 与 plan 本文件。
- 测试证据：L0 全绿 + cassette fan-out 主路径 + 浏览器 e2e（贴 Task 11 的 GIF + psql 审计输出）。
- 已知非目标/follow-up：span 树成树（需先给 turn 建根 span，单独重构）、多模型真分档（tier 当前 no-op）、异步早停、监控→chat。
- 结尾：🤖 Generated with [Claude Code](https://claude.com/claude-code)

- [ ] **Step 6: 确认 PR 绿**

Run: `gh pr checks`
Expected: CI 通过（或本地全绿，CI 跑起后复核）。

---

## Self-Review（计划自审）

**Spec 覆盖核对（对照 `2026-06-11-chat-subagent-dispatch-design.md`）：**
- §四 dispatch_subagents 原语 → Task 1/3/4/5 ✓
- §四五 五护栏（深度1禁递归/只读/fast/步数4/预算切片+个数上限）→ Task 3(gate_cfg+tier)/4(预算切片)/5(个数闸)/12(只读+禁递归+禁串门守卫) ✓
- §五 子循环复用 ToolLoop 注入受限依赖 → Task 3 ✓；只读 flat hub → Task 2 ✓
- §六1 主↔子派活表+原文直传回收+摘要进窗口 → Task 3/4/5 ✓（全文进缓存按需取回：子 hub 复用 ToolResultCache，主循环现有 read_cached_result 已覆盖）
- §六2 子↔子不通信 → Task 3（白纸 context，子循环互不传）✓
- §六3 子→前端 lane 进度 + 共享 SeqCounter + dispatch 事件 → Task 4(事件)/10(前端) ✓
- §七 失败兜底（包不抛）/预算回滚/同步收齐 → Task 3/4 ✓
- §八 留痕 = 审计表 → Task 6 ✓（span 树成树明确 deferred，header 已标注）
- §十 评测（该派/不该派 + 不变量守卫）→ Task 12 ✓
- §三 隔离铁律 → Task 12 守卫 + header 声明 ✓

**Placeholder 扫描：** 无 TBD/TODO。Task 6 Step 7 的 `__import__` 写法已显式标注"实施时改顶部 import"。Task 9 录制步骤标注"真 LLM 不调时微调 query 重录"。Task 11 失败处置标注"回对应 Task 修，不硬扛"。

**类型一致性核对：** `SubtaskRequest`(goal/target/output_hint/boundary)、`SubagentResult`(subtask_id/target/summary/evidence_refs/status/gap_note/tokens_spent/cost_cny/steps_used/tier)、`SubagentFactory`(spawn_one/dispatch/_lane_emit/_emit_plain)、`DispatchSubagentsTool.run_with_state`、`SubagentAuditRepo.record_batch(parent/subtasks/results/scenario_type)`、`ToolHub(progressive=)`/`register_subset` —— 全文签名一致。前端 `DispatchLane`(subtask_id/goal/toolCount/status)、`dispatchLanes` 状态、`DispatchStartEvent`/`DispatchEndEvent` 一致。

**已知风险点（实施期留意）：**
1. Task 9 cassette 依赖真 LLM 肯调 `dispatch_subagents`——提示词触发力是变量，备选是调 query/加 brief 引导。
2. `ContextDeps` 确切字段以实际 `context.py` 为准（计划用 cassette `_build_chatloop_agent` 观察到的 6 字段；Step 3 实施前 Read `context.py` 核对，若有出入按实际调）。
3. 并发子循环共享一个 `SeqCounter` + 一个 `emit`（async 单线程，await 交错安全）；若 emit 内有非异步安全副作用需复核——现状 `_emit` 只 append + xadd，安全。

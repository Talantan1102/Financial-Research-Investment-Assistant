# Chatloop 可观测性补齐 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 chatloop 每次工具调用写一条 trace span,后端聚合成跨请求指标并暴露只读 API,看板新增一页实时展示——落地 spec `2026-06-11-chatloop-observability-design.md`。

**Architecture:** 复用现有 trace span 机制(工具 span 与 LLM span 同 `request_id` 落 PG `trace_spans`)。后端新增聚合服务(SQL over `trace_spans`)+ 只读 FastAPI 路由;看板新增 Starlette 路由,HTTP 实时拉聚合 API 渲染。分两期:第一期后端(Task 1-3),第二期看板(Task 4)。

**Tech Stack:** Python / SQLAlchemy(sync Session + raw SQL `percentile_cont`)/ FastAPI / Pydantic / Starlette + Jinja2(看板)/ PostgreSQL JSONB。

---

## 文件结构

**第一期(后端):**
- 改 `backend/app/chatloop/tool_hub.py` — `ToolHub.__init__` 加可选 `trace`;`_dispatch_one` 包一层写 span(覆盖所有返回路径)。
- 改 `backend/app/chatloop/worker_wiring.py` — `HeavySingletons` 加 `trace` 字段 + 默认构造;`build_turn_components` 注入 ToolHub。
- 改 `backend/app/chatloop/subagent.py` — `build_child_tool_hub` 透传 `trace`(子循环工具也可观测)。
- 建 `backend/app/services/trace_analytics.py` — 聚合服务 + Pydantic 结果模型。
- 建 `backend/app/router/observability_router.py` — 只读 API。
- 改 `backend/app/app_main.py` — 注册路由。

**第二期(看板):**
- 建 `dashboard/derive/observability.py` — HTTP 拉后端聚合 API。
- 改 `dashboard/server.py` — 新 handler + Route。
- 建 `dashboard/templates/chatloop_observability.html` — 渲染。

**测试:**
- `backend/tests/unit/chatloop/test_tool_hub_spans.py`(Task 1,无需 PG,注入捕获用 trace)
- `backend/tests/integration/test_trace_analytics.py`(Task 2,真 PG seed span)
- `backend/tests/integration/test_observability_api.py`(Task 3,API + 隐私断言)
- `dashboard/tests/integration/test_chatloop_observability_page.py`(Task 4,stub 后端 + 降级)

---

## 已知接口事实(实现时直接用,无需再查)

- `ToolResult`(`backend/app/agents/schemas.py:105-114`)字段:`tool_name / args / success / output / error / latency_ms / cached`。
- `Span`(`backend/app/services/trace_models.py:37-49`)字段:`span_id / request_id / parent_id / name / inputs / outputs / metadata / started_at / ended_at / error`,校验 `ended_at >= started_at`。
- `TraceSpanRow`(同文件 :142)PG 表 `trace_spans`,JSONB 列 Python attr `attrs_json`、**PG 列名 `metadata`**。
- `TraceService(session_factory)`(`backend/app/services/trace_service.py`),`session_factory: () -> CM[Session]`,生产传 `SessionLocal`。
- `SessionLocal` 在 `backend/app/core/database.py:21`。
- chat LLM span `name = "LLMService.stream_step"`,metadata 带 `prompt_tokens/completion_tokens/cached_tokens/cost_cny/latency_ms`(`backend/app/services/llm_service.py:222-246`)。
- `_dispatch_one`(`backend/app/chatloop/tool_hub.py:234`)包住所有分发路径,恒返回 `ToolResult`。
- 路由注册在 `backend/app/app_main.py:370-381`。
- 看板是 Starlette,模板用 `templates.get_template(...).render(...)`,sibling 范例 `chatloop_live_view`(`dashboard/server.py:726`)。

---

# 第一期:后端

### Task 1: ToolHub 每次工具调用写一条 span

**Files:**
- Modify: `backend/app/chatloop/tool_hub.py`(`__init__` + `_dispatch_one` + 新私有方法 `_write_tool_span`)
- Modify: `backend/app/chatloop/worker_wiring.py:60-205`
- Modify: `backend/app/chatloop/subagent.py:91-97`
- Test: `backend/tests/unit/chatloop/test_tool_hub_spans.py`

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/unit/chatloop/test_tool_hub_spans.py`:

```python
"""ToolHub 工具 span 写入 — 成功/失败/缓存命中三态 + 非致命。"""
from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.chatloop.state import ChatLoopState
from app.chatloop.tool_hub import ToolHub
from app.services.llm_step import StepToolCall


class _CapturingTrace:
    def __init__(self) -> None:
        self.spans: list = []

    def write_span(self, span) -> None:
        self.spans.append(span)


class _Args(BaseModel):
    pass


class _FakeQuoteTool:
    """非 InProcessTool → 走数据工具路径(无 cache 直跑)。"""
    name = "get_quote"
    args_schema = _Args

    async def run(self, validated) -> dict:
        return {"price": 42}


def _state() -> ChatLoopState:
    return ChatLoopState(
        user_id="u1", session_id="s1", request_id="req-1",
        messages=[], step=3,
    )


def _call() -> StepToolCall:
    return StepToolCall(id="c1", name="get_quote", arguments="{}")


@pytest.mark.asyncio
async def test_success_writes_one_tool_span() -> None:
    trace = _CapturingTrace()
    hub = ToolHub(trace=trace)
    hub.register_inprocess([_FakeQuoteTool()])  # type: ignore[list-item]
    await hub.dispatch([_call()], _state())

    assert len(trace.spans) == 1
    span = trace.spans[0]
    assert span.name == "tool:get_quote"
    assert span.request_id == "req-1"
    assert span.parent_id is None
    assert span.metadata["kind"] == "tool"
    assert span.metadata["success"] is True
    assert span.metadata["cached"] is False
    assert span.metadata["step"] == 3
    assert span.metadata["latency_ms"] >= 0
    assert span.error is None
    # 隐私:inputs/outputs 不带工具结果原文
    assert "price" not in str(span.outputs)


@pytest.mark.asyncio
async def test_unknown_tool_writes_failed_span() -> None:
    trace = _CapturingTrace()
    hub = ToolHub(trace=trace)  # 不注册任何工具
    await hub.dispatch([_call()], _state())

    assert len(trace.spans) == 1
    span = trace.spans[0]
    assert span.name == "tool:get_quote"
    assert span.metadata["success"] is False
    assert span.error is not None


@pytest.mark.asyncio
async def test_trace_write_failure_is_nonfatal() -> None:
    class _BoomTrace:
        def write_span(self, span) -> None:
            raise RuntimeError("db down")

    hub = ToolHub(trace=_BoomTrace())
    hub.register_inprocess([_FakeQuoteTool()])  # type: ignore[list-item]
    results = await hub.dispatch([_call()], _state())  # 不得抛
    assert results[0].success is True


@pytest.mark.asyncio
async def test_no_trace_writes_nothing() -> None:
    hub = ToolHub()  # trace=None
    hub.register_inprocess([_FakeQuoteTool()])  # type: ignore[list-item]
    results = await hub.dispatch([_call()], _state())
    assert results[0].success is True  # 行为不变
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest backend/tests/unit/chatloop/test_tool_hub_spans.py -v`
Expected: FAIL —— `ToolHub.__init__() got an unexpected keyword argument 'trace'`

- [ ] **Step 3: 实现 — `tool_hub.py` 加 trace + 写 span**

在 `backend/app/chatloop/tool_hub.py` 顶部 import 区补:

```python
from datetime import UTC, datetime
from uuid import uuid4

from app.services.trace_models import Span
```

`__init__`(:65)签名末尾加参数并存:

```python
        tool_timeout_s: float = DEFAULT_TOOL_TIMEOUT_S,
        trace: Any = None,  # TraceService | None —— 写工具 span(可观测性);None 则不写
    ) -> None:
        ...
        self._tool_timeout_s = tool_timeout_s
        self._trace = trace
```

把 `_dispatch_one`(:234)整体替换为(外包计时 + 写 span):

```python
    async def _dispatch_one(self, call: StepToolCall, state: ChatLoopState) -> ToolResult:
        """单 call 协程 —— 全包不抛;dispatch 后写一条工具 span(非致命)。"""
        started_at = datetime.now(UTC)
        try:
            result = await self._dispatch_one_inner(call, state)
        except BaseException as e:  # noqa: BLE001 — hub 不抛硬契约:双保险兜底
            args = self._safe_parsed_args(call)
            error = f"[执行失败] {type(e).__name__}: {str(e)[:_ERR_MSG_LEN]}"
            self._safe_record(state, call.name, args, error, success=False, cache_key=None)
            result = self._fail_result(call.name, args, error)
        self._write_tool_span(state, result, started_at)
        return result

    def _write_tool_span(
        self, state: ChatLoopState, result: ToolResult, started_at: datetime
    ) -> None:
        """每次工具调用写一条 span(同 request_id)。trace=None 不写;写失败非致命。

        隐私:inputs 只放参数 key 名、outputs 留空 —— 不落工具结果/参数值原文。
        """
        if self._trace is None:
            return
        try:
            span = Span(
                span_id=f"{state.request_id}-tool-{uuid4().hex[:8]}",
                request_id=state.request_id,
                parent_id=None,
                name=f"tool:{result.tool_name}",
                inputs={"arg_keys": sorted(result.args.keys())},
                outputs={},
                metadata={
                    "kind": "tool",
                    "tool_name": result.tool_name,
                    "latency_ms": int(result.latency_ms),
                    "cached": bool(result.cached),
                    "success": bool(result.success),
                    "step": state.step,
                },
                started_at=started_at,
                ended_at=datetime.now(UTC),
                error=None if result.success else result.error,
            )
            self._trace.write_span(span)
        except Exception:  # noqa: BLE001 — 观测写入非致命,绝不打断工具调用
            logger.warning("tool span write failed (non-fatal)", exc_info=True)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest backend/tests/unit/chatloop/test_tool_hub_spans.py -v`
Expected: PASS(4 passed)

- [ ] **Step 5: 接线 — `worker_wiring.py` 注入真 TraceService**

`HeavySingletons`(:60)加字段:

```python
    session_factory: Any = None
    trace: Any = None  # TraceService —— ToolHub 写工具 span 用
```

`build_heavy_singletons` 返回前(:173 `return HeavySingletons(` 之前)构造默认 trace:

```python
    from app.core.database import SessionLocal
    from app.services.trace_service import TraceService

    trace = TraceService(SessionLocal)
```

并在 `return HeavySingletons(...)` 里加 `trace=trace,`。

`build_turn_components` 的 ToolHub 构造(:205)加 `trace`:

```python
    hub = ToolHub(
        emit=emit, cache=singletons.cache, seq_counter=seq_counter, trace=singletons.trace
    )
```

- [ ] **Step 6: 接线 — `subagent.py` 子 hub 透传 trace**

`build_child_tool_hub`(`backend/app/chatloop/subagent.py:91`)签名加 `trace`,构造透传:

```python
def build_child_tool_hub(
    registry: Any, *, emit: Any, seq_counter: SeqCounter, cache: Any, trace: Any = None
) -> ToolHub:
    """构造子循环的只读 hub(flat schema,只挂只读白名单工具)。"""
    hub = ToolHub(
        emit=emit, cache=cache, seq_counter=seq_counter, progressive=False, trace=trace
    )
    hub.register_subset(registry, READONLY_SUBAGENT_TOOLS)
    return hub
```

调用方 `SubagentFactory` 若已持有 trace 则传入;暂无则保持 `None`(子工具 span 留待 SubagentFactory 接 trace 时开启,不阻塞本 Task)。

- [ ] **Step 7: 跑全量 chatloop 单测确认无回归**

Run: `pytest backend/tests/unit/chatloop/ -q`
Expected: PASS(原有用例全绿 + 新 4 个)

- [ ] **Step 8: Commit**

```bash
git add backend/app/chatloop/tool_hub.py backend/app/chatloop/worker_wiring.py backend/app/chatloop/subagent.py backend/tests/unit/chatloop/test_tool_hub_spans.py
git commit -m "feat(chatloop): 工具调用写 trace span — 补全 trace 时间线"
```

---

### Task 2: Chatloop trace 聚合服务

**Files:**
- Create: `backend/app/services/trace_analytics.py`
- Test: `backend/tests/integration/test_trace_analytics.py`

- [ ] **Step 1: 写失败测试(真 PG seed span)**

新建 `backend/tests/integration/test_trace_analytics.py`:

```python
"""ChatloopTraceAnalytics —— seed 模型/工具 span,断言聚合正确。"""
from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

from app.services.trace_analytics import ChatloopTraceAnalytics
from app.services.trace_models import TraceSpanRow


def _span(db_session, *, span_id, request_id, name, metadata, secs_ago=10, dur_ms=100):
    end = datetime.now(UTC) - timedelta(seconds=secs_ago)
    start = end - timedelta(milliseconds=dur_ms)
    db_session.add(TraceSpanRow(
        span_id=span_id, request_id=request_id, parent_id=None, name=name,
        inputs={}, outputs={}, attrs_json=metadata, started_at=start, ended_at=end, error=None,
    ))


def test_aggregate_tool_and_model(db_session) -> None:
    # 两条 model span(同一 request),两条 tool span(get_quote 慢、search 快)
    _span(db_session, span_id="s1", request_id="r1", name="LLMService.stream_step",
          metadata={"prompt_tokens": 1000, "completion_tokens": 50,
                    "cached_tokens": 800, "cost_cny": 0.04, "latency_ms": 3000})
    _span(db_session, span_id="s2", request_id="r1", name="tool:get_quote",
          metadata={"kind": "tool", "latency_ms": 8000, "cached": False, "success": True})
    _span(db_session, span_id="s3", request_id="r1", name="tool:search_kb",
          metadata={"kind": "tool", "latency_ms": 200, "cached": True, "success": True})
    db_session.flush()

    analytics = ChatloopTraceAnalytics(lambda: nullcontext(db_session))
    agg = analytics.aggregate("7d")

    tools = {t.tool_name: t for t in agg.tool_latency}
    assert tools["get_quote"].p95_ms >= 8000 - 1
    assert tools["search_kb"].cache_hit_rate == 1.0
    # 模型 vs 工具:model=3000, tool=8200
    assert round(agg.model_ms) == 3000
    assert round(agg.tool_ms) == 8200
    assert 0 < agg.model_share < 1
    # KV-cache 命中率 = 800/1000
    assert abs(agg.cache_hit_rate - 0.8) < 1e-6
    assert agg.turn_count == 1
    assert agg.avg_llm_calls == 1
    assert agg.avg_tool_calls == 2


def test_invalid_window_raises(db_session) -> None:
    analytics = ChatloopTraceAnalytics(lambda: nullcontext(db_session))
    try:
        analytics.aggregate("99y")
        assert False, "should raise"
    except ValueError:
        pass
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest backend/tests/integration/test_trace_analytics.py -v`
Expected: FAIL —— `ModuleNotFoundError: app.services.trace_analytics`

- [ ] **Step 3: 实现聚合服务**

新建 `backend/app/services/trace_analytics.py`:

```python
"""ChatloopTraceAnalytics —— 跨请求聚合 over trace_spans(spec § 4.2)。

判据:模型 span name = 'LLMService.stream_step';工具 span name LIKE 'tool:%'。
窗口参数白名单映射到固定 interval 字面量,作为 bound param 安全传入(防注入)。
只产出数字,绝不回 span inputs/outputs 原文。
"""
from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

_WINDOWS: dict[str, str] = {"1d": "1 day", "7d": "7 days", "30d": "30 days"}

_TOOL_SQL = text("""
SELECT replace(name, 'tool:', '') AS tool_name,
       count(*) AS calls,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY (metadata->>'latency_ms')::numeric) AS p50_ms,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY (metadata->>'latency_ms')::numeric) AS p95_ms,
       max((metadata->>'latency_ms')::numeric) AS max_ms,
       avg(CASE WHEN (metadata->>'success')::boolean THEN 1.0 ELSE 0.0 END) AS success_rate,
       avg(CASE WHEN (metadata->>'cached')::boolean THEN 1.0 ELSE 0.0 END) AS cache_hit_rate
FROM trace_spans
WHERE name LIKE 'tool:%' AND started_at >= now() - (:interval)::interval
GROUP BY tool_name ORDER BY p95_ms DESC
""")

_MVT_SQL = text("""
SELECT
  COALESCE(sum(CASE WHEN name = 'LLMService.stream_step'
                    THEN (metadata->>'latency_ms')::numeric ELSE 0 END), 0) AS model_ms,
  COALESCE(sum(CASE WHEN name LIKE 'tool:%'
                    THEN (metadata->>'latency_ms')::numeric ELSE 0 END), 0) AS tool_ms
FROM trace_spans
WHERE started_at >= now() - (:interval)::interval
  AND (name = 'LLMService.stream_step' OR name LIKE 'tool:%')
""")

_CACHE_SQL = text("""
SELECT COALESCE(sum((metadata->>'cached_tokens')::numeric), 0) AS cached,
       COALESCE(sum((metadata->>'prompt_tokens')::numeric), 0) AS prompt
FROM trace_spans
WHERE name = 'LLMService.stream_step' AND started_at >= now() - (:interval)::interval
""")

_TURN_SQL = text("""
WITH per_req AS (
  SELECT request_id,
         sum((metadata->>'cost_cny')::numeric) AS cost,
         extract(epoch from (max(ended_at) - min(started_at))) * 1000 AS wall_ms,
         count(*) FILTER (WHERE name = 'LLMService.stream_step') AS llm_calls,
         count(*) FILTER (WHERE name LIKE 'tool:%') AS tool_calls
  FROM trace_spans
  WHERE started_at >= now() - (:interval)::interval
    AND (name = 'LLMService.stream_step' OR name LIKE 'tool:%')
  GROUP BY request_id
)
SELECT COALESCE(avg(cost), 0) AS avg_cost,
       COALESCE(avg(wall_ms), 0) AS avg_wall_ms,
       COALESCE(avg(llm_calls), 0) AS avg_llm_calls,
       COALESCE(avg(tool_calls), 0) AS avg_tool_calls,
       count(*) AS turn_count
FROM per_req
""")


class ToolLatencyStat(BaseModel):
    tool_name: str
    calls: int
    p50_ms: float
    p95_ms: float
    max_ms: float
    success_rate: float
    cache_hit_rate: float


class ChatloopAggregates(BaseModel):
    window: str
    tool_latency: list[ToolLatencyStat]
    model_ms: float
    tool_ms: float
    model_share: float
    cache_hit_rate: float
    avg_cost_cny: float
    avg_wall_ms: float
    avg_llm_calls: float
    avg_tool_calls: float
    turn_count: int


class ChatloopTraceAnalytics:
    def __init__(self, session_factory: Callable[[], AbstractContextManager[Session]]) -> None:
        self._sf = session_factory

    def aggregate(self, window: str = "7d") -> ChatloopAggregates:
        interval = _WINDOWS.get(window)
        if interval is None:
            raise ValueError(f"invalid window: {window!r} (allowed: {sorted(_WINDOWS)})")
        params = {"interval": interval}
        with self._sf() as s:
            tool_rows = s.execute(_TOOL_SQL, params).mappings().all()
            mvt = s.execute(_MVT_SQL, params).mappings().one()
            cache = s.execute(_CACHE_SQL, params).mappings().one()
            turn = s.execute(_TURN_SQL, params).mappings().one()

        model_ms = float(mvt["model_ms"] or 0)
        tool_ms = float(mvt["tool_ms"] or 0)
        total = model_ms + tool_ms
        prompt = float(cache["prompt"] or 0)
        cached = float(cache["cached"] or 0)
        return ChatloopAggregates(
            window=window,
            tool_latency=[
                ToolLatencyStat(
                    tool_name=r["tool_name"], calls=int(r["calls"]),
                    p50_ms=float(r["p50_ms"] or 0), p95_ms=float(r["p95_ms"] or 0),
                    max_ms=float(r["max_ms"] or 0),
                    success_rate=float(r["success_rate"] or 0),
                    cache_hit_rate=float(r["cache_hit_rate"] or 0),
                )
                for r in tool_rows
            ],
            model_ms=model_ms, tool_ms=tool_ms,
            model_share=(model_ms / total) if total else 0.0,
            cache_hit_rate=(cached / prompt) if prompt else 0.0,
            avg_cost_cny=float(turn["avg_cost"] or 0),
            avg_wall_ms=float(turn["avg_wall_ms"] or 0),
            avg_llm_calls=float(turn["avg_llm_calls"] or 0),
            avg_tool_calls=float(turn["avg_tool_calls"] or 0),
            turn_count=int(turn["turn_count"] or 0),
        )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest backend/tests/integration/test_trace_analytics.py -v`
Expected: PASS(2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/trace_analytics.py backend/tests/integration/test_trace_analytics.py
git commit -m "feat(chatloop): trace 聚合服务 — 最慢工具/模型vs工具/KV-cache命中率/每轮均值"
```

---

### Task 3: 只读可观测性 API

**Files:**
- Create: `backend/app/router/observability_router.py`
- Modify: `backend/app/app_main.py:370-381`
- Test: `backend/tests/integration/test_observability_api.py`

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/integration/test_observability_api.py`:

```python
"""只读可观测性 API —— 返回聚合 JSON,且不泄漏 span 原文。"""
from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.router.observability_router import router
from app.services.trace_models import TraceSpanRow


def _seed(db_session) -> None:
    end = datetime.now(UTC) - timedelta(seconds=5)
    db_session.add(TraceSpanRow(
        span_id="s1", request_id="r1", parent_id=None, name="tool:get_quote",
        inputs={"secret_arg": "茅台"}, outputs={"price": 1688},
        attrs_json={"kind": "tool", "latency_ms": 500, "cached": False, "success": True},
        started_at=end - timedelta(milliseconds=500), ended_at=end, error=None,
    ))
    db_session.flush()


def _client(db_session) -> TestClient:
    import app.router.observability_router as mod
    mod._SESSION_FACTORY = lambda: nullcontext(db_session)  # 测试缝
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_aggregates_endpoint_returns_json(db_session) -> None:
    _seed(db_session)
    resp = _client(db_session).get("/api/v0/observability/chatloop/aggregates?window=7d")
    assert resp.status_code == 200
    body = resp.json()
    assert body["window"] == "7d"
    assert any(t["tool_name"] == "get_quote" for t in body["tool_latency"])


def test_response_leaks_no_span_content(db_session) -> None:
    _seed(db_session)
    resp = _client(db_session).get("/api/v0/observability/chatloop/aggregates?window=7d")
    raw = resp.text
    assert "secret_arg" not in raw
    assert "茅台" not in raw
    assert "1688" not in raw


def test_invalid_window_400(db_session) -> None:
    resp = _client(db_session).get("/api/v0/observability/chatloop/aggregates?window=99y")
    assert resp.status_code == 400
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest backend/tests/integration/test_observability_api.py -v`
Expected: FAIL —— `ModuleNotFoundError: app.router.observability_router`

- [ ] **Step 3: 实现路由**

新建 `backend/app/router/observability_router.py`:

```python
"""只读可观测性 API —— chatloop trace 聚合(内部观测端点,不带用户 PII)。

sync def 路由 → FastAPI 在 threadpool 跑同步 SQL,不阻塞事件循环。
只返回聚合数字,绝不返回 span inputs/outputs 原文(隐私边界,spec § 6)。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.core.database import SessionLocal
from app.services.trace_analytics import ChatloopAggregates, ChatloopTraceAnalytics

router = APIRouter(prefix="/api/v0/observability", tags=["observability"])

# 测试缝:测试用 nullcontext(db_session) 覆盖,生产用 SessionLocal。
_SESSION_FACTORY = SessionLocal


@router.get("/chatloop/aggregates", response_model=ChatloopAggregates)
def chatloop_aggregates(window: str = Query("7d")) -> ChatloopAggregates:
    analytics = ChatloopTraceAnalytics(_SESSION_FACTORY)
    try:
        return analytics.aggregate(window)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
```

- [ ] **Step 4: 注册路由**

`backend/app/app_main.py`,在 :381 `app.include_router(persona_router)` 之后加:

```python
from app.router.observability_router import router as observability_router
app.include_router(observability_router)  # chatloop 可观测性(只读聚合)
```

(import 若项目惯例集中在文件顶部,则把 import 放到顶部 import 区,只保留 `app.include_router(...)` 在此。)

- [ ] **Step 5: 跑测试确认通过**

Run: `pytest backend/tests/integration/test_observability_api.py -v`
Expected: PASS(3 passed)

- [ ] **Step 6: Commit**

```bash
git add backend/app/router/observability_router.py backend/app/app_main.py backend/tests/integration/test_observability_api.py
git commit -m "feat(chatloop): 只读可观测性 API + 隐私边界(只出数字不出原文)"
```

---

# 第二期:看板

### Task 4: 看板可观测性页(实时拉后端 API)

**Files:**
- Create: `dashboard/derive/observability.py`
- Modify: `dashboard/server.py`(新 handler + Route)
- Create: `dashboard/templates/chatloop_observability.html`
- Test: `dashboard/tests/integration/test_chatloop_observability_page.py`

- [ ] **Step 1: 写失败测试**

新建 `dashboard/tests/integration/test_chatloop_observability_page.py`:

```python
"""看板可观测性页 —— stub 后端聚合返回正常渲染;后端不可达走降级。"""
from __future__ import annotations

import dashboard.derive.observability as obs
from starlette.testclient import TestClient

from dashboard.server import app

_FAKE = {
    "window": "7d",
    "tool_latency": [
        {"tool_name": "get_quote", "calls": 12, "p50_ms": 300, "p95_ms": 8000,
         "max_ms": 9000, "success_rate": 0.9, "cache_hit_rate": 0.3},
    ],
    "model_ms": 3000, "tool_ms": 8200, "model_share": 0.27, "cache_hit_rate": 0.8,
    "avg_cost_cny": 0.05, "avg_wall_ms": 12000, "avg_llm_calls": 3,
    "avg_tool_calls": 2, "turn_count": 5,
}


def test_page_renders_aggregates(monkeypatch) -> None:
    monkeypatch.setattr(obs, "load_aggregates", lambda *a, **k: _FAKE)
    resp = TestClient(app).get("/eval/chatloop-observability")
    assert resp.status_code == 200
    assert "get_quote" in resp.text
    assert "命中率" in resp.text


def test_page_degrades_when_backend_down(monkeypatch) -> None:
    def _boom(*a, **k):
        raise OSError("connection refused")
    monkeypatch.setattr(obs, "load_aggregates", _boom)
    resp = TestClient(app).get("/eval/chatloop-observability")
    assert resp.status_code == 200
    assert "未连接" in resp.text or "暂无数据" in resp.text
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest dashboard/tests/integration/test_chatloop_observability_page.py -v`
Expected: FAIL —— `ModuleNotFoundError: dashboard.derive.observability` 或路由 404

- [ ] **Step 3: 实现 HTTP 拉取**

新建 `dashboard/derive/observability.py`:

```python
"""看板实时拉后端聚合 API(stdlib urllib,无新依赖)。"""
from __future__ import annotations

import json
import urllib.request


def load_aggregates(backend_url: str, window: str = "7d") -> dict:
    url = (
        f"{backend_url.rstrip('/')}"
        f"/api/v0/observability/chatloop/aggregates?window={window}"
    )
    with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310 — 内部固定后端
        return json.loads(resp.read().decode("utf-8"))
```

- [ ] **Step 4: 实现 handler + Route**

`dashboard/server.py`,在 `chatloop_live_view`(:726)之后加 handler:

```python
async def chatloop_observability_view(request: Request) -> HTMLResponse:
    """GET /eval/chatloop-observability — chatloop 运行时可观测性聚合(实时拉后端 API)。"""
    from dashboard.derive.observability import load_aggregates

    backend = os.getenv("BACKEND_BASE_URL", "http://localhost:8000")
    window = request.query_params.get("window", "7d")
    try:
        agg = load_aggregates(backend, window)
    except Exception as e:  # noqa: BLE001 — 后端不可达降级,不崩页
        logger.warning("observability fetch failed: %s", e)
        agg = None
    template = templates.get_template("chatloop_observability.html")
    return HTMLResponse(template.render(agg=agg, window=window, active_nav="eval"))
```

在 routes 列表(:751 `Route("/eval/chatloop-live", ...)` 之后)加:

```python
        Route("/eval/chatloop-observability", chatloop_observability_view, methods=["GET"]),
```

- [ ] **Step 5: 实现模板**

新建 `dashboard/templates/chatloop_observability.html`:

```html
<!doctype html>
<html lang="zh">
<head>
  <meta charset="utf-8" />
  <title>Chatloop 运行时可观测性</title>
  <style>
    body { font-family: -apple-system, "Segoe UI", sans-serif; margin: 32px; color: #1a1d21; }
    h1 { font-size: 20px; } h2 { font-size: 15px; margin-top: 28px; color: #5d6875; }
    .empty { padding: 24px; background: #fbf4f2; border: 1px solid #e8b4a8; border-radius: 8px; }
    table { border-collapse: collapse; width: 100%; max-width: 760px; font-size: 13px; }
    th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid #eee; }
    .bar { height: 6px; background: #1d4ed8; border-radius: 3px; }
    .cards { display: flex; gap: 16px; flex-wrap: wrap; }
    .card { border: 1px solid #e8e4dc; border-radius: 8px; padding: 14px 18px; min-width: 130px; }
    .v { font-size: 18px; font-weight: 700; font-family: ui-monospace, monospace; }
    .k { font-size: 11px; color: #8a96a3; text-transform: uppercase; letter-spacing: .05em; }
  </style>
</head>
<body>
  <h1>Chatloop 运行时可观测性 · 最近 {{ window }}</h1>
  {% if agg is none %}
    <div class="empty">后端未连接或暂无数据 —— 请确认后端在线(BACKEND_BASE_URL)。</div>
  {% else %}
    <h2>每轮均值 / 缓存命中率</h2>
    <div class="cards">
      <div class="card"><div class="k">KV-cache 命中率</div>
        <div class="v">{{ '%.0f' % (agg.cache_hit_rate * 100) }}%</div></div>
      <div class="card"><div class="k">模型 vs 工具</div>
        <div class="v">{{ '%.0f' % (agg.model_share * 100) }}% / {{ '%.0f' % ((1 - agg.model_share) * 100) }}%</div></div>
      <div class="card"><div class="k">每轮均价</div>
        <div class="v">¥{{ '%.4f' % agg.avg_cost_cny }}</div></div>
      <div class="card"><div class="k">每轮耗时</div>
        <div class="v">{{ '%.1f' % (agg.avg_wall_ms / 1000) }}s</div></div>
      <div class="card"><div class="k">每轮调用</div>
        <div class="v">{{ '%.1f' % agg.avg_llm_calls }}模型 / {{ '%.1f' % agg.avg_tool_calls }}工具</div></div>
      <div class="card"><div class="k">样本轮数</div>
        <div class="v">{{ agg.turn_count }}</div></div>
    </div>

    <h2>最慢工具(按 p95 排序)</h2>
    {% set maxp95 = (agg.tool_latency | map(attribute='p95_ms') | list | max) if agg.tool_latency else 1 %}
    <table>
      <tr><th>工具</th><th>调用数</th><th>p50</th><th>p95</th><th>p95 分布</th><th>成功率</th><th>缓存率</th></tr>
      {% for t in agg.tool_latency %}
      <tr>
        <td>{{ t.tool_name }}</td>
        <td>{{ t.calls }}</td>
        <td>{{ '%.0f' % t.p50_ms }}ms</td>
        <td>{{ '%.0f' % t.p95_ms }}ms</td>
        <td><div class="bar" style="width: {{ (t.p95_ms / maxp95 * 200) | round }}px"></div></td>
        <td>{{ '%.0f' % (t.success_rate * 100) }}%</td>
        <td>{{ '%.0f' % (t.cache_hit_rate * 100) }}%</td>
      </tr>
      {% endfor %}
    </table>
  {% endif %}
</body>
</html>
```

- [ ] **Step 6: 跑测试确认通过**

Run: `pytest dashboard/tests/integration/test_chatloop_observability_page.py -v`
Expected: PASS(2 passed)

- [ ] **Step 7: Commit**

```bash
git add dashboard/derive/observability.py dashboard/server.py dashboard/templates/chatloop_observability.html dashboard/tests/integration/test_chatloop_observability_page.py
git commit -m "feat(dashboard): chatloop 可观测性页 — 实时拉后端聚合 API 渲染"
```

---

## 收尾(执行 pipeline,非 TDD 任务)

- [ ] 全量回归:`pytest backend/tests/unit/chatloop/ backend/tests/integration/test_trace_analytics.py backend/tests/integration/test_observability_api.py -q` 全绿;`ruff check` + `mypy`(按项目 CI 口径)。
- [ ] 浏览器测试:起后端 + 看板,打开 `/eval/chatloop-observability`,跑一两轮真实 chat 产生 span 后刷新,确认页面出数(截图为准)。
- [ ] 提 PR(base `main`),CI 绿后合入。

---

## Self-Review 记录

- **Spec 覆盖**:工具 span 写入(Task 1)/ 聚合四指标:最慢工具·模型vs工具·KV-cache命中率·每轮均值(Task 2)/ 只读 API + 隐私边界(Task 3)/ 看板实时拉页(Task 4)—— spec § 4.1/4.2/4.3 全覆盖。非目标(父子树/散户前端 token/新建表/研报每-agent)均未触碰。
- **Placeholder 扫描**:每个 code step 都有完整代码与确切命令,无 TBD。
- **类型一致**:`ChatloopAggregates`/`ToolLatencyStat` 字段在 Task 2 定义、Task 3 `response_model` 复用、Task 4 模板按同名字段渲染,一致;`_SESSION_FACTORY` 测试缝在 Task 3 测试与实现同名。

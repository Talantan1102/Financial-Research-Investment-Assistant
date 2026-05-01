# v0 Chat Agent Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the v0 chat agent skeleton —— LangGraph 状态图(planner→tool→responder)+ 2 typed actor agents + 3 tools + SQLite checkpointer + SSE streaming HTTP +接 Plan C `EvalRunner` SUT swap。一并清理 brainstorming archive list 上的 7 文件 + 2 目录旧实现。

**Architecture:**
- **LangGraph 状态图** as orchestration backbone:`StateGraph(GraphState)` + `add_conditional_edges`(planner 后根据 `plan.direct_response` 分支)+ `SqliteSaver` checkpointer。
- **2 typed Pydantic actor agents**:`ChatPlanner`(`tier="balanced"`)+ `Responder`(`tier="fast"`)。两者都继承 `app.agents.base.Agent` 抽象基类(含 DispatchSubAgent 接口占位但 v0 不真用,留 v0.5 Critic)。
- **3 个 v0 工具**通过 `ToolRegistry` 注册:`get_stock_quote` / `get_financials` / `get_news`,数据源全走改造后的 `mock_tushare_service`(改造为通过 `LLMService` 调,符合 Plan B/C/D "不 import openai" 契约,Q1 决议 A)。
- **SUT Protocol 抽象**让 Plan C `EvalRunner` 同时兼容 bare `LLMService`(老测试)和 `ChatAgent`(v0 新)。
- **Memory v0 = LangGraph SqliteSaver only**(Q2 决议 B:不写 history truncate,YAGNI;v1 Semantic 一并改)。

**Tech Stack:**
- 已就位(Plan A→D):Python 3.11 + uv,Pydantic v2 strict,`openai>=1.40` (httpx-based),pytest-recording,mypy strict on `app.services.*`,poethepoet,pre-commit
- 已在 deps 但 v0 第一次真用:**LangGraph >= 0.2**,**LangGraph 自带 SqliteSaver**(`langgraph.checkpoint.sqlite`)
- v0 不引入新 runtime deps;`tiktoken` 已在 deps 但 v0 也不真用(Q2 决议:不 truncate)

**Status inherited from Plans A→D:**
- `LLMService(client, tier_router=None, trace_service=None, cost_budget=None)` —— v0 ChatPlanner / Responder 通过它调 LLM,**不 import openai**
- `LLMResponse(content, request_id, ..., cost_cny>0)` —— Plan D 已消除 stub
- `TraceService(db_path).write_span / get_trace` —— v0 LangGraph node 级 + agent step 级 span 走它
- `EvalRunner(sut, judge, trace_service, recorder)` —— v0 把 sut 类型从 `LLMService` 升为 `SUT` Protocol
- `MockLLMClient.from_fixture_dir(path)` + `__recorded__:` redirect —— v0 L1 测试注入
- `app/services/llm_mock_client.py` 的 dispatch 逻辑 —— v0 不动
- `backend/.env`(`DASHSCOPE_API_KEY` 已设)+ `backend/.env.example`(`EVAL_COST_LIMIT_CNY=20`)
- mypy strict tier 已含 `app.services.*` `app.agents.*` `app.tools.*` `app.orchestration.*`(Plan A 配置时已预留 4 个,但 `agents/` `tools/` `orchestration/` v0 才首次有源文件)

**Memory inputs (Plans A→D sediment + brainstorming):**
- `feedback_plan_specificity` — plan 写"意图 + 约束",不写最终 config / 列表
- `feedback_pytest_layer_env` — autouse fixture + monkeypatch.setenv,layer conftest 已就位
- `feedback_third_party_plugin_defaults` — LangGraph 0.2.x 的 `astream_events(version="v2")` 必须 spike 验证(Task 0)
- `feedback_test_env_modeling` — proxy unset 已在 e2e conftest autouse,v0 SSE 测试沿用
- `feedback_cassette_dynamic_prompt_values` — ChatAgent 跑出来的 trace_summary 含 latency,L2 cassette 必须 not-match-body
- `feedback_type_ignore_with_typed_signature` — 不预防式加 type:ignore;mypy 跑全 backend
- `feedback_python_m_path_dual_context` — v0 不新增 `python -m` 调用,无需重蹈 Plan D 的 sys.path hack
- `project_llm_service_contract` — `LLMService.chat` 是稳定契约,v0 不破坏
- `project_eval_pipeline_contract` — `EvalRunner` SUT swap 是 v0 acceptance criteria
- `project_agents_layer` — 7 agent 总图,v0 落 2(ChatPlanner + Responder),DispatchSubAgent 接口占位
- `project_architecture_choice` — 方案 C(LangGraph + Typed Actor + 4 横切),tools 不 import openai,LLM 调用必经 LLMService
- `project_dual_mode` — v0 = chat-only,research(A 模式)留 v0.5
- `project_scope_decisions` — Auth 保留(user_id 作为 thread_id 一部分),KB / Web 搜索 v0 占位不接入

---

## File Structure

| Path | Purpose | Created/Modified/Deleted |
|---|---|---|
| **新增 — agents/** | | |
| `backend/app/agents/__init__.py` | package marker | Create |
| `backend/app/agents/schemas.py` | `GraphState` / `Plan` / `ToolCall` / `ToolResult` / `StepResult` Pydantic | Create |
| `backend/app/agents/base.py` | `Agent` ABC + DispatchSubAgent 接口占位 | Create |
| `backend/app/agents/chat_planner.py` | `ChatPlanner(Agent)` | Create |
| `backend/app/agents/responder.py` | `Responder(Agent)` | Create |
| `backend/app/agents/chat_agent.py` | `ChatAgent` SUT-friendly wrapper | Create |
| **新增 — tools/** | | |
| `backend/app/tools/__init__.py` | package marker | Create |
| `backend/app/tools/base.py` | `Tool` ABC + `ToolError` + `ToolNotFoundError` | Create |
| `backend/app/tools/registry.py` | `ToolRegistry` | Create |
| `backend/app/tools/get_stock_quote.py` | `StockQuoteTool` + `StockQuoteArgs` | Create |
| `backend/app/tools/get_financials.py` | `GetFinancialsTool` + `FinancialsArgs` | Create |
| `backend/app/tools/get_news.py` | `GetNewsTool` + `NewsArgs` | Create |
| **新增 — orchestration/** | | |
| `backend/app/orchestration/__init__.py` | package marker | Create |
| `backend/app/orchestration/checkpointer.py` | `make_chat_checkpointer(db_path)` factory | Create |
| `backend/app/orchestration/nodes.py` | `planner_node` / `tool_node` / `responder_node` | Create |
| `backend/app/orchestration/chat_graph.py` | `build_chat_graph(...)` 装配 + `CompiledStateGraph` 工厂 | Create |
| **新增 — router/** | | |
| `backend/app/router/chat.py` | `POST /api/v0/chat` SSE 流式 | Create |
| **新增 — services/(扩展)** | | |
| `backend/app/services/eval_runner.py` | **Modify**:加 `SUT` Protocol + `_LLMServiceSUT` adapter + 兼容 ChatAgent | Modify |
| **改造 — service/(单数,legacy)** | | |
| `backend/app/service/mock_tushare_service.py` | **Modify**:`import openai` → 通过 `LLMService` 调(Q1 决议 A)| Modify |
| **删除 — brainstorming archive list** | | |
| `backend/app/service/chat_service.py` | | Delete |
| `backend/app/service/chat_service_v2.py` | | Delete |
| `backend/app/service/mcp_chat_service.py` | | Delete |
| `backend/app/service/react_controller.py` | | Delete |
| `backend/app/service/smart_analyzer.py` | | Delete |
| `backend/app/service/dr_g.py` | | Delete |
| `backend/app/router/chat_router.py` | | Delete(替换为新 `app/router/chat.py`)|
| `backend/app/mcp_server/` | 整目录 | Delete |
| `backend/app/mcp_client/` | 整目录 | Delete |
| **测试 — unit/** | | |
| `backend/tests/unit/test_agents_schemas.py` | L0:Plan / GraphState / ToolCall / ToolResult invariants | Create |
| `backend/tests/unit/test_agent_base.py` | L0:Agent ABC + StepResult | Create |
| `backend/tests/unit/test_tool_registry.py` | L0:Tool register / get / execute / list_for_llm | Create |
| `backend/tests/unit/test_v0_tools.py` | L0:3 工具 args schema validation | Create |
| `backend/tests/unit/test_chat_planner.py` | L0:ChatPlanner prompt 构造 + Plan 解析 | Create |
| `backend/tests/unit/test_responder.py` | L0:Responder prompt 构造 + 输出格式 | Create |
| `backend/tests/unit/test_orchestration_nodes.py` | L0:planner_node / tool_node / responder_node 单元行为 | Create |
| `backend/tests/unit/test_chat_graph.py` | L0:graph 装配正确性(节点 + 边)| Create |
| `backend/tests/unit/test_chat_checkpointer.py` | L0:SqliteSaver factory + thread_id 隔离 | Create |
| **测试 — integration/** | | |
| `backend/tests/integration/test_chat_agent_e2e_mock.py` | L1:ChatAgent 端到端跑(MockLLMClient SUT + mock tools)| Create |
| `backend/tests/integration/test_eval_runner_chat_agent_sut.py` | L1:EvalRunner SUT = ChatAgent,3 golden case 跑通 | Create |
| `backend/tests/integration/test_chat_router_sse.py` | L1:HTTP SSE 流式正确(用 FastAPI TestClient + 模拟流)| Create |
| **测试 — e2e/** | | |
| `backend/tests/e2e/test_chat_agent_cassette.py` | L2:ChatAgent 真打 LLM cassette 录 + replay | Create |
| **配置** | | |
| `pyproject.toml` | **Modify**:`langgraph` deps 锁 `>=0.2,<0.3`;mock_tushare mypy override 调整;poe 加 `serve` 任务 | Modify |
| **数据** | | |
| `backend/data/chat.sqlite` | (gitignored,运行时创建)checkpointer | Created at runtime |

> **Notes**: v0 plan 涉及 ~20 新文件 + 1 改造 + 9 删除/移除。粗算 +2k 行(agent/tool/graph 骨架)+ -3-5k 行(archive list)= **净瘦身 ~1-3k 行**。

---

## Pre-flight check (Task 0 — done before dispatching Task 1)

> **3 个 spike,合计 ≤ 5 分钟。** Plan B/C/D 沉淀的 `feedback_third_party_plugin_defaults` 教训应用到 LangGraph + DashScope tool-calling。

### Spike 1: DashScope OpenAI tool-calling 兼容性(Q3 决议 A)

```bash
unset all_proxy https_proxy http_proxy
uv run python - <<'PY'
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv("backend/.env")
client = OpenAI(
    api_key=os.environ["DASHSCOPE_API_KEY"],
    base_url=os.environ.get("DASHSCOPE_BASE_URL"),
)
r = client.chat.completions.create(
    model="deepseek-v4-flash",
    messages=[{"role": "user", "content": "查一下茅台股价"}],
    tools=[{
        "type": "function",
        "function": {
            "name": "get_stock_quote",
            "description": "获取 A 股股票当前行情",
            "parameters": {
                "type": "object",
                "properties": {"ts_code": {"type": "string"}},
                "required": ["ts_code"],
            },
        },
    }],
    max_tokens=200,
)
msg = r.choices[0].message
print("HAS_TOOL_CALLS:", bool(msg.tool_calls))
print("TOOL_CALLS:", msg.tool_calls)
print("CONTENT:", msg.content)
print("USAGE:", r.usage)
PY
```

**3 种结果对应行为**:

- **A. `HAS_TOOL_CALLS=True`,`tool_calls` 非空** → DashScope 支持 OpenAI tool-calling 标准。Task 7 ChatPlanner 用 `client.chat.completions.create(..., tools=[...])` 路径。
- **B. `HAS_TOOL_CALLS=False`,`content` 是 JSON 字符串** → DashScope 不支持但 model 能按 schema 输出 JSON。Task 7 ChatPlanner 改用 prompt 让 LLM 直接输出 `{"tool_calls": [...]}` JSON,Pydantic 解析。
- **C. 抛 API error** → 模型不支持。降级 B 路径(prompt-engineered JSON)。

记录结果在 plan 末尾 "Task 0 spike result" 区。

### Spike 2: LangGraph 0.2.x astream_events v2 事件类型

```bash
uv run python - <<'PY'
from typing import TypedDict
from langgraph.graph import StateGraph, START, END

class S(TypedDict):
    msg: str
    out: str

def planner(s: S) -> dict: return {"out": "p"}
def responder(s: S) -> dict: return {"out": s["out"] + "r"}

g = StateGraph(S)
g.add_node("p", planner)
g.add_node("r", responder)
g.add_edge(START, "p")
g.add_edge("p", "r")
g.add_edge("r", END)
app = g.compile()

import asyncio
async def go():
    seen_types = set()
    async for ev in app.astream_events({"msg": "hi", "out": ""}, version="v2"):
        seen_types.add(ev["event"])
    print("EVENT_TYPES:", sorted(seen_types))

asyncio.run(go())
PY
```

期望输出包含 `on_chain_start`、`on_chain_end`、`on_chain_stream` 等事件类型。如果实际类型与 spec § 5 假设不符,Task 11(SSE 适配)需要 sync。

### Spike 3: LangGraph SqliteSaver 基础语义

```bash
uv run python - <<'PY'
import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver

conn = sqlite3.connect(":memory:", check_same_thread=False)
saver = SqliteSaver(conn)
print("SAVER:", saver)
print("METHODS:", [m for m in dir(saver) if not m.startswith("_")][:10])
PY
```

期望:无 import 错误,`SqliteSaver` 可实例化。如果 LangGraph 0.2.x 把 SqliteSaver 移到 `langgraph_checkpoint_sqlite` 独立 package,需要 plan Task 9 改 import + 加 dep。

---

## Task 1: Archive list — 删除 brainstorming 决议要砍的旧代码

> **第一个 task 就大手笔删 ~3-5k 行**。这是 plan A 的"先删 benchmark 再做"模式延续。删完跑 ci,确认没有残留 import 引用。

**Files:**
- Delete: `backend/app/service/chat_service.py`
- Delete: `backend/app/service/chat_service_v2.py`
- Delete: `backend/app/service/mcp_chat_service.py`
- Delete: `backend/app/service/react_controller.py`
- Delete: `backend/app/service/smart_analyzer.py`
- Delete: `backend/app/service/dr_g.py`
- Delete: `backend/app/router/chat_router.py`
- Delete (整目录): `backend/app/mcp_server/`
- Delete (整目录): `backend/app/mcp_client/`
- Modify: `backend/app/app_main.py`(移除被删 router 的 include)
- Modify: 任何还 import 上述模块的剩余文件(Task 1 grep 一遍)

- [ ] **Step 1: pre-grep — 列出所有引用待删模块的文件**

```bash
echo "=== chat_service refs ===" && grep -rn "from app.service.chat_service\|from app.service.chat_service_v2\|from app.service.mcp_chat_service\|from app.service.react_controller\|from app.service.smart_analyzer\|from app.service.dr_g" backend/ --include="*.py" 2>&1 | head -30
echo ""
echo "=== chat_router refs ===" && grep -rn "from app.router.chat_router\|chat_router" backend/app/app_main.py
echo ""
echo "=== mcp_server / mcp_client refs ===" && grep -rn "from app.mcp_server\|from app.mcp_client" backend/ --include="*.py" 2>&1 | head -30
```

记下所有引用文件,Step 4 一并处理。

- [ ] **Step 2: 执行 git rm**

```bash
git rm backend/app/service/chat_service.py
git rm backend/app/service/chat_service_v2.py
git rm backend/app/service/mcp_chat_service.py
git rm backend/app/service/react_controller.py
git rm backend/app/service/smart_analyzer.py
git rm backend/app/service/dr_g.py
git rm backend/app/router/chat_router.py
git rm -r backend/app/mcp_server
git rm -r backend/app/mcp_client
```

- [ ] **Step 3: 处理 app_main.py 的 chat_router include**

打开 `backend/app/app_main.py`,找到类似 `from app.router import chat_router` 或 `app.include_router(chat_router.router)` 的行。

**v0 处理**:暂时**注释掉**(添加 `# TODO(v0 plan Task 11): replaced by app.router.chat`),Task 11 创建新 `chat.py` 时 uncomment 改成新 import。这样 Task 1-10 期间应用仍然能 import。

- [ ] **Step 4: 处理 Step 1 grep 出的其他引用**

每个引用文件:
- 如果引用方也是要删的(双删),已被 git rm 覆盖
- 如果引用方是要保留的(`auth_router.py` 等),把 import 改成空(注释掉)或者 raise NotImplementedError 占位 + TODO,**绝不让 import 失败**

- [ ] **Step 5: 验证 import + ci**

```bash
uv run python -c "from app import app_main"  # 必须成功
uv run poe ci 2>&1 | tail -10
```

ci 必须仍全绿。如果 fail,继续清理引用直到绿。

- [ ] **Step 6: 记录瘦身数字**

```bash
git diff --shortstat HEAD~0  # 但已经 rm 了,不太对——
git diff --stat HEAD~0 -- backend/  # 看暂存区净 - LOC
```

或在 commit message 里写 `{N} files deleted, ~{LOC} LOC removed`。

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
chore: archive 7 legacy chat/research files + 2 mcp dirs (v0 prep)

Removes brainstorming-2026-04-29 archive list:
- chat_service.py / chat_service_v2.py / mcp_chat_service.py
- react_controller.py / smart_analyzer.py / dr_g.py
- router/chat_router.py (replaced by app/router/chat.py in Task 11)
- mcp_server/ + mcp_client/ (MCP demoted to v1 export-only per spec)

Net change: ~{N}k LOC removed.

原因 layer: chore
EOF
)"
```

---

## Task 2: Pydantic schemas (`agents/schemas.py`)

**Files:**
- Create: `backend/app/agents/__init__.py` (empty)
- Create: `backend/app/agents/schemas.py`
- Create: `backend/tests/unit/test_agents_schemas.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_agents_schemas.py
"""L0 — agent I/O schemas: Plan / ToolCall / ToolResult / GraphState / StepResult."""

import pytest
from pydantic import ValidationError

from app.agents.schemas import (
    GraphState,
    Plan,
    StepResult,
    ToolCall,
    ToolResult,
)


def test_plan_with_tools() -> None:
    p = Plan(
        tool_calls=[ToolCall(tool_name="get_stock_quote", args={"ts_code": "600519.SH"}, rationale="user asked")],
        direct_response=False,
        reasoning="single tool call for price query",
    )
    assert len(p.tool_calls) == 1


def test_plan_direct_response_no_tools() -> None:
    p = Plan(tool_calls=[], direct_response=True, reasoning="greeting")
    assert p.direct_response is True


def test_plan_direct_response_with_tools_rejected() -> None:
    with pytest.raises(ValidationError, match="direct_response=True"):
        Plan(
            tool_calls=[ToolCall(tool_name="x", args={}, rationale="r")],
            direct_response=True,
            reasoning="conflict",
        )


def test_plan_no_tools_no_direct_rejected() -> None:
    with pytest.raises(ValidationError, match="direct_response=False"):
        Plan(tool_calls=[], direct_response=False, reasoning="empty")


def test_tool_result_success() -> None:
    r = ToolResult(
        tool_name="get_stock_quote",
        args={"ts_code": "600519.SH"},
        success=True,
        output={"price": 1820.5},
        error=None,
        latency_ms=320,
    )
    assert r.output == {"price": 1820.5}
    assert r.error is None


def test_tool_result_failure() -> None:
    r = ToolResult(
        tool_name="x",
        args={},
        success=False,
        output=None,
        error="connection refused",
        latency_ms=5,
    )
    assert r.error == "connection refused"


def test_graph_state_minimal() -> None:
    s = GraphState(
        user_id="u1",
        session_id="s1",
        user_message="茅台股价?",
        request_id="req-abc12345",
    )
    assert s.plan is None
    assert s.tool_results == []
    assert s.final_response is None


def test_step_result_state_update() -> None:
    sr = StepResult(state_update={"plan": {"tool_calls": [], "direct_response": True, "reasoning": "x"}}, span_metadata={"k": "v"})
    assert "plan" in sr.state_update
```

- [ ] **Step 2: Run — expect fail**

```bash
uv run pytest backend/tests/unit/test_agents_schemas.py -v
```
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `agents/schemas.py`**

Create `backend/app/agents/__init__.py` (empty).

Create `backend/app/agents/schemas.py`:

```python
"""Agent I/O Pydantic schemas — stable v0~v3.

GraphState is the LangGraph state object (mutable across nodes).
Plan / ToolCall / ToolResult / StepResult are agent-level frozen contracts.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ToolCall(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool_name: str
    args: dict[str, Any]
    rationale: str


class ToolResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool_name: str
    args: dict[str, Any]
    success: bool
    output: dict[str, Any] | None = None
    error: str | None = None
    latency_ms: int = Field(ge=0)


class Plan(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool_calls: list[ToolCall]
    direct_response: bool
    reasoning: str

    @model_validator(mode="after")
    def _check_consistency(self) -> "Plan":
        if self.direct_response and self.tool_calls:
            raise ValueError("direct_response=True 时 tool_calls 必须为空")
        if not self.direct_response and not self.tool_calls:
            raise ValueError("direct_response=False 时 tool_calls 至少有 1 个")
        return self


class StepResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    state_update: dict[str, Any]
    span_metadata: dict[str, Any] = Field(default_factory=dict)


class GraphState(BaseModel):
    """LangGraph state — mutable across nodes."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_id: str
    session_id: str
    user_message: str
    enable_web_search: bool = False  # v0 placeholder
    enable_kb_search: bool = False   # v0 placeholder

    plan: Plan | None = None
    tool_results: list[ToolResult] = Field(default_factory=list)

    final_response: str | None = None
    final_response_streamed: bool = False

    request_id: str
    span_stack: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Verify**

```bash
uv run pytest backend/tests/unit/test_agents_schemas.py -v
uv run mypy backend/app/agents/schemas.py
```
Expected: 8 PASS, mypy clean.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/__init__.py backend/app/agents/schemas.py backend/tests/unit/test_agents_schemas.py
git commit -m "$(cat <<'EOF'
feat(agents): add Pydantic schemas (GraphState/Plan/ToolCall/ToolResult/StepResult)

原因 layer: services
EOF
)"
```

---

## Task 3: `Agent` ABC + DispatchSubAgent placeholder

**Files:**
- Create: `backend/app/agents/base.py`
- Create: `backend/tests/unit/test_agent_base.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_agent_base.py
"""L0 — Agent ABC contract + DispatchSubAgent interface placeholder."""

from typing import Any

import pytest

from app.agents.base import Agent
from app.agents.schemas import GraphState, StepResult
from app.services.llm_mock_client import MockLLMClient
from app.services.llm_response import Tier
from app.services.llm_service import LLMService
from pathlib import Path


def _make_state() -> GraphState:
    return GraphState(
        user_id="u",
        session_id="s",
        user_message="hi",
        request_id="req-test1234",
    )


def test_agent_subclass_must_implement_step(mock_llm_client: MockLLMClient) -> None:
    class _Incomplete(Agent):
        name = "incomplete"
        model_tier: Tier = "fast"

    svc = LLMService(client=mock_llm_client)
    with pytest.raises(TypeError):
        _Incomplete(llm=svc)  # type: ignore[abstract]


def test_minimal_subclass_works(mock_llm_client: MockLLMClient) -> None:
    class _Minimal(Agent):
        name = "minimal"
        model_tier: Tier = "fast"

        def step(self, state: GraphState) -> StepResult:
            return StepResult(state_update={"final_response": "ok"}, span_metadata={})

    svc = LLMService(client=mock_llm_client)
    a = _Minimal(llm=svc)
    sr = a.step(_make_state())
    assert sr.state_update["final_response"] == "ok"


def test_dispatch_subagent_placeholder_raises() -> None:
    """v0: DispatchSubAgent 接口在 base 占位但默认 raise NotImplementedError —
    v0.5 启用 Critic 时再 override。"""
    class _A(Agent):
        name = "a"
        model_tier: Tier = "fast"

        def step(self, state: GraphState) -> StepResult:
            return StepResult(state_update={})

    from app.services.llm_mock_client import MockLLMClient
    fixture_dir = Path("backend/tests/fixtures/llm_mocks")
    a = _A(llm=LLMService(client=MockLLMClient.from_fixture_dir(fixture_dir)))
    with pytest.raises(NotImplementedError, match="v0.5"):
        a.dispatch_subagent(name="critic", state=_make_state())
```

- [ ] **Step 2: Run — expect fail**

```bash
uv run pytest backend/tests/unit/test_agent_base.py -v
```

- [ ] **Step 3: Implement `agents/base.py`**

```python
"""Agent ABC — all agents are stateless typed actors.

DispatchSubAgent interface lives here as a placeholder per
project_agents_layer.md memory: v0 doesn't dispatch sub-agents (no use
case), but the interface is reserved so v0.5 Critic can implement
multi-dimension parallel scoring without changing the base class.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.agents.schemas import GraphState, StepResult
from app.services.llm_response import Tier
from app.services.llm_service import LLMService


class Agent(ABC):
    """Stateless typed actor with strict Pydantic I/O.

    Subclasses must:
    - Set class attribute `name: str` (used for trace span names)
    - Set class attribute `model_tier: Tier` ("fast"|"balanced"|"deep")
    - Implement `step(state) -> StepResult`
    """

    name: str
    model_tier: Tier

    def __init__(self, llm: LLMService) -> None:
        self._llm = llm

    @abstractmethod
    def step(self, state: GraphState) -> StepResult:
        """Run one step: read graph state, optionally call LLM/tools, return state_update."""

    def dispatch_subagent(self, name: str, state: GraphState) -> StepResult:
        """Placeholder for v0.5 sub-agent dispatch.

        v0 does not have multi-dimension parallel scoring (Critic), so this
        method always raises. v0.5 Critic will override or this base method
        will gain a real implementation tied to a SubAgentRegistry.
        """
        raise NotImplementedError(
            f"DispatchSubAgent ({name!r}) is reserved for v0.5+; v0 has no use case."
        )
```

- [ ] **Step 4: Verify**

```bash
uv run pytest backend/tests/unit/test_agent_base.py -v
uv run mypy backend/app/agents/base.py
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/base.py backend/tests/unit/test_agent_base.py
git commit -m "$(cat <<'EOF'
feat(agents): add Agent ABC + DispatchSubAgent v0.5 placeholder

原因 layer: services
EOF
)"
```

---

## Task 4: `Tool` ABC + `ToolRegistry`

**Files:**
- Create: `backend/app/tools/__init__.py`
- Create: `backend/app/tools/base.py`
- Create: `backend/app/tools/registry.py`
- Create: `backend/tests/unit/test_tool_registry.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_tool_registry.py
"""L0 — Tool registration / get / execute / list_for_llm."""

import pytest
from pydantic import BaseModel

from app.agents.schemas import ToolCall, ToolResult
from app.tools.base import Tool, ToolError, ToolNotFoundError
from app.tools.registry import ToolRegistry


class _EchoArgs(BaseModel):
    text: str


class _EchoTool(Tool):
    name = "echo"
    description = "Echo back the input."
    args_schema = _EchoArgs

    async def run(self, args: _EchoArgs) -> dict:
        return {"echoed": args.text}


class _FailTool(Tool):
    name = "always_fail"
    description = "Always raises ToolError."
    args_schema = _EchoArgs

    async def run(self, args: _EchoArgs) -> dict:
        raise ToolError("intentional fail")


def test_register_then_get() -> None:
    reg = ToolRegistry()
    reg.register(_EchoTool())
    assert reg.get("echo").name == "echo"


def test_duplicate_register_rejected() -> None:
    reg = ToolRegistry()
    reg.register(_EchoTool())
    with pytest.raises(ValueError, match="duplicate"):
        reg.register(_EchoTool())


def test_get_unknown_raises() -> None:
    reg = ToolRegistry()
    with pytest.raises(ToolNotFoundError):
        reg.get("nonexistent")


@pytest.mark.asyncio
async def test_execute_success() -> None:
    reg = ToolRegistry()
    reg.register(_EchoTool())
    call = ToolCall(tool_name="echo", args={"text": "hi"}, rationale="r")
    result = await reg.execute(call)
    assert result.success
    assert result.output == {"echoed": "hi"}
    assert result.latency_ms >= 0


@pytest.mark.asyncio
async def test_execute_tool_error_caught() -> None:
    reg = ToolRegistry()
    reg.register(_FailTool())
    call = ToolCall(tool_name="always_fail", args={"text": "x"}, rationale="r")
    result = await reg.execute(call)
    assert not result.success
    assert "intentional fail" in (result.error or "")


@pytest.mark.asyncio
async def test_execute_invalid_args_caught() -> None:
    reg = ToolRegistry()
    reg.register(_EchoTool())
    call = ToolCall(tool_name="echo", args={"wrong_field": 1}, rationale="r")
    result = await reg.execute(call)
    assert not result.success
    assert "validation" in (result.error or "").lower()


def test_list_for_llm() -> None:
    reg = ToolRegistry()
    reg.register(_EchoTool())
    schemas = reg.list_for_llm()
    assert len(schemas) == 1
    assert schemas[0]["function"]["name"] == "echo"
    assert "parameters" in schemas[0]["function"]
```

- [ ] **Step 2: Run — expect fail**

- [ ] **Step 3: Implement `tools/base.py`**

```python
"""Tool ABC + tool-related exceptions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class ToolError(Exception):
    """Raised by Tool.run on a recoverable execution failure (network /
    parse / domain error). ToolRegistry.execute catches this and wraps
    in ToolResult(success=False)."""


class ToolNotFoundError(LookupError):
    """Raised by ToolRegistry.get when a tool name isn't registered."""


class Tool(ABC):
    name: str
    description: str
    args_schema: type[BaseModel]

    @abstractmethod
    async def run(self, args: BaseModel) -> dict[str, Any]:
        """Execute the tool. args is a Pydantic-validated instance of args_schema."""

    def schema_for_llm(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args_schema.model_json_schema(),
            },
        }
```

- [ ] **Step 4: Implement `tools/registry.py`**

```python
"""ToolRegistry — central registry + uniform execute path with timing + error wrap."""

from __future__ import annotations

import time
from typing import Any

from pydantic import ValidationError

from app.agents.schemas import ToolCall, ToolResult
from app.tools.base import Tool, ToolError, ToolNotFoundError


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise ToolNotFoundError(f"no tool registered with name={name!r}")
        return self._tools[name]

    def list_for_llm(self) -> list[dict[str, Any]]:
        return [tool.schema_for_llm() for tool in self._tools.values()]

    async def execute(self, call: ToolCall) -> ToolResult:
        started = time.perf_counter()
        try:
            tool = self.get(call.tool_name)
        except ToolNotFoundError as e:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return ToolResult(
                tool_name=call.tool_name,
                args=call.args,
                success=False,
                error=str(e),
                latency_ms=latency_ms,
            )

        try:
            args = tool.args_schema.model_validate(call.args)
        except ValidationError as e:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return ToolResult(
                tool_name=call.tool_name,
                args=call.args,
                success=False,
                error=f"args validation failed: {e}",
                latency_ms=latency_ms,
            )

        try:
            output = await tool.run(args)
        except ToolError as e:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return ToolResult(
                tool_name=call.tool_name,
                args=call.args,
                success=False,
                error=str(e),
                latency_ms=latency_ms,
            )

        latency_ms = int((time.perf_counter() - started) * 1000)
        return ToolResult(
            tool_name=call.tool_name,
            args=call.args,
            success=True,
            output=output,
            latency_ms=latency_ms,
        )
```

- [ ] **Step 5: Verify + commit**

```bash
uv run pytest backend/tests/unit/test_tool_registry.py -v
uv run mypy backend/app/tools/
```

```bash
git add backend/app/tools/__init__.py backend/app/tools/base.py backend/app/tools/registry.py backend/tests/unit/test_tool_registry.py
git commit -m "$(cat <<'EOF'
feat(tools): add Tool ABC + ToolRegistry with uniform execute path

原因 layer: services
EOF
)"
```

---

## Task 5: 改造 `mock_tushare_service.py` 走 LLMService(Q1 决议 A)

**Files:**
- Modify: `backend/app/service/mock_tushare_service.py`

> **Why**: 当前 `mock_tushare_service.py` 直接 `from openai import OpenAI` + 自管 cost 估算,违反 Plan B/C/D "agents/tools/services 不 import openai" 架构契约。改造后:走 `LLMService` → 自动获得 trace span + cost_budget + price-table cost 计算。**接口不变**(同样的 `MockTushareService.daily(...) / income_statement(...) / etc`),只是底层换。

- [ ] **Step 1: Read current `mock_tushare_service.py` + grep callers**

```bash
wc -l backend/app/service/mock_tushare_service.py
grep -rn "MockTushareService\|mock_tushare_service" backend/ --include="*.py" | head -20
```

注意:这是个 ~110KB 文件,但 `import openai` 应该集中在 1-3 个 LLM 调用点。**不重写整个文件,只换 LLM 调用方式**。

- [ ] **Step 2: 局部替换 LLM 调用代码**

文件里所有 `openai.ChatCompletion.create(...)` 或 `client.chat.completions.create(...)` 形态的调用点,改为:

```python
from app.services.llm_service import LLMService

class MockTushareService:
    def __init__(self, llm: LLMService) -> None:
        self._llm = llm

    def _call_llm_for_mock_data(self, prompt: str) -> str:
        r = self._llm.chat(prompt=prompt, tier="fast")
        return r.content
```

`__init__` 加 `llm: LLMService` 参数,所有 caller 注入(目前应该只有 v0 工具会创建 MockTushareService 实例)。

> **关键约束**:**只删 `import openai`**;mock_tushare 的业务逻辑(数据 schema / prompt 模板 / parse 逻辑)不动。

- [ ] **Step 3: 跑 mypy 看是否 strict 净**

```bash
uv run mypy backend/app/service/mock_tushare_service.py
```

由于 `app.service.*`(单数)在 Plan A 已被设为 mypy `ignore_errors`,这一步只是 sanity check 不强制 strict。但**避免新增 mypy red**。

- [ ] **Step 4: 跑 sanity test 确保功能没坏**

如果 `mock_tushare_service.py` 有现有测试(在 archive 之外),跑一遍。如果没有,Step 6 的 v0 工具测试会覆盖。

- [ ] **Step 5: Commit**

```bash
git add backend/app/service/mock_tushare_service.py
git commit -m "$(cat <<'EOF'
refactor(service): mock_tushare uses LLMService instead of direct openai

Aligns with Plan B/C/D contract that no service/tool/agent imports openai
directly. Mock now goes through LLMService, automatically gaining trace
spans + cost_budget enforcement + price-table cost computation.

原因 layer: services
EOF
)"
```

---

## Task 6: 3 个 v0 工具

**Files:**
- Create: `backend/app/tools/get_stock_quote.py`
- Create: `backend/app/tools/get_financials.py`
- Create: `backend/app/tools/get_news.py`
- Create: `backend/tests/unit/test_v0_tools.py`

- [ ] **Step 1: Write the L0 test**

```python
# backend/tests/unit/test_v0_tools.py
"""L0 — args-schema validation for the 3 v0 tools."""

import pytest
from pydantic import ValidationError

from app.tools.get_financials import FinancialsArgs
from app.tools.get_news import NewsArgs
from app.tools.get_stock_quote import StockQuoteArgs


def test_stock_quote_args_valid() -> None:
    args = StockQuoteArgs(ts_code="600519.SH")
    assert args.ts_code == "600519.SH"


def test_stock_quote_args_missing_code_rejected() -> None:
    with pytest.raises(ValidationError):
        StockQuoteArgs()  # type: ignore[call-arg]


def test_financials_args_valid_periods() -> None:
    for p in ("latest", "quarterly", "annual"):
        FinancialsArgs(ts_code="600519.SH", period=p)


def test_financials_args_invalid_period_rejected() -> None:
    with pytest.raises(ValidationError):
        FinancialsArgs(ts_code="600519.SH", period="weekly")  # type: ignore[arg-type]


def test_news_args_default() -> None:
    args = NewsArgs()
    assert args.ts_code is None
    assert args.n == 5
    assert args.days_back == 7


def test_news_args_negative_n_rejected() -> None:
    with pytest.raises(ValidationError):
        NewsArgs(n=-1)
```

- [ ] **Step 2: Implement the 3 tools**

> **Note**: 工具的 `run()` 内部调 `MockTushareService` 拿 mock 数据。Plan 不写 `MockTushareService` 真实查询的具体方法名(那需要读 110KB 文件),implementer 在实施时用 `grep` 找最接近的方法。**Plan 写 intent + constraint**:

每个 tool 的 `run` 方法:
- 接受已 Pydantic 验证的 `args` 实例
- 通过 `MockTushareService` 拿数据(mock_tushare 在 Task 5 已改造为接受 `LLMService` 注入)
- 把 mock_tushare 返回的 raw 数据转成 dict(JSON 可序列化)
- 失败时 raise `ToolError(message)`,registry 自动 wrap

`StockQuoteTool.run`:
- 调 `mock_tushare.daily(ts_code=args.ts_code)` 或类似方法
- 返回 `{"ts_code": ..., "price": ..., "change_pct": ..., "volume": ...}`

`GetFinancialsTool.run`:
- 调 `mock_tushare.income_statement(...)` 或 `mock_tushare.fin_indicator(...)`
- 返回 `{"ts_code": ..., "period": ..., "revenue": ..., "net_profit": ..., "roe": ..., "pe": ...}`

`GetNewsTool.run`:
- 调 `mock_tushare.news(...)` 或 `mock_bocha_service.search(...)`(看哪个更接近,implementer 决定)
- 返回 `{"items": [{"title": ..., "summary": ..., "url": ..., "published_at": ...}, ...]}`

每个 tool 文件 ~50-80 行(含 args schema + class + 错误处理)。

- [ ] **Step 3: Verify + commit**

```bash
uv run pytest backend/tests/unit/test_v0_tools.py -v
uv run mypy backend/app/tools/
```

```bash
git add backend/app/tools/get_stock_quote.py backend/app/tools/get_financials.py backend/app/tools/get_news.py backend/tests/unit/test_v0_tools.py
git commit -m "$(cat <<'EOF'
feat(tools): add 3 v0 tools (get_stock_quote / get_financials / get_news)

All three tools use MockTushareService as data source; real Tushare
integration deferred to v1. Args schemas + error handling fully typed.

原因 layer: services
EOF
)"
```

---

## Task 7: `ChatPlanner` 实现

**Files:**
- Create: `backend/app/agents/chat_planner.py`
- Create: `backend/tests/unit/test_chat_planner.py`
- Possibly modify: `backend/tests/fixtures/llm_mocks/agent_decisions.yaml`(加 ChatPlanner mock entry)

> **Plan branching by Task 0 spike result**:
> - **Spike A** (DashScope tool-calling 兼容):用 `client.chat.completions.create(..., tools=[...])` 路径,LLM 直接返回 `tool_calls`
> - **Spike B/C** (不兼容):用 prompt-engineered JSON 路径,prompt 末尾加"输出 JSON: `{"tool_calls": [...], "direct_response": false, "reasoning": "..."}`",Pydantic 解析

> **Note**: 当前 `LLMService.chat(prompt, tier, schema=None)` 接口不带 `tools` 参数。**Spike A 路径下 v0 plan 需要扩展 LLMService**。但这是 Plan B/C/D 已稳契约的扩展点 —— 加 `tools: list[dict] | None = None` 参数(additive,默认 None 则原行为不变)。

> 我倾向 **Spike B/C 路径**(prompt-engineered JSON),即使 spike 显示 A 兼容也用 B,理由:**复用 Plan B 的 Judge 已走通的"prompt + JSON parse"模式**,不引入 LLMService 新参数,代码更对称。Implementer 看 spike 结果后决定。

- [ ] **Step 1: Write the L0 test**

```python
# backend/tests/unit/test_chat_planner.py
"""L0 — ChatPlanner prompt construction + Plan parsing."""

from pathlib import Path

import pytest

from app.agents.chat_planner import ChatPlanner, build_planner_prompt
from app.agents.schemas import GraphState, Plan, ToolCall
from app.services.llm_mock_client import MockLLMClient
from app.services.llm_service import LLMService
from app.tools.registry import ToolRegistry
from app.tools.get_stock_quote import StockQuoteTool


def _state(msg: str) -> GraphState:
    return GraphState(user_id="u", session_id="s", user_message=msg, request_id="req-test1234")


def test_build_prompt_includes_tools() -> None:
    reg = ToolRegistry()
    reg.register(StockQuoteTool(mock_tushare=None))  # type: ignore[arg-type]
    prompt = build_planner_prompt(state=_state("茅台股价?"), registry=reg)
    assert "茅台股价" in prompt
    assert "get_stock_quote" in prompt
    assert "tool_calls" in prompt  # JSON output schema mentioned


# More tests for the parse path; require fixture-tied MockLLMClient response
# returning valid Plan JSON. Plan implementer adds these fixtures + tests.
```

- [ ] **Step 2: Implement `chat_planner.py`**

Module surface:

```python
class ChatPlanner(Agent):
    name = "ChatPlanner"
    model_tier: Tier = "balanced"

    def __init__(self, llm: LLMService, registry: ToolRegistry) -> None:
        super().__init__(llm)
        self._registry = registry

    def step(self, state: GraphState) -> StepResult:
        prompt = build_planner_prompt(state=state, registry=self._registry)
        r = self._llm.chat(
            prompt=prompt,
            tier=self.model_tier,
            request_id=state.request_id,
        )
        plan = _parse_plan(r.content)
        return StepResult(
            state_update={"plan": plan},
            span_metadata={"agent": "ChatPlanner", "model": r.model, "cost_cny": r.cost_cny},
        )


def build_planner_prompt(state: GraphState, registry: ToolRegistry) -> str:
    """Build the planner prompt with available tool schemas + JSON output instructions."""
    ...


def _parse_plan(content: str) -> Plan:
    """Strip markdown code fences if any, then Pydantic-validate."""
    ...
```

**Prompt template constraint**:
- 系统角色:金融研究助手 planner
- 列出可用工具(从 `registry.list_for_llm()` 拿,转成人读友好的 markdown 列表)
- 给当前用户 message
- 给当前 chat history(目前 v0 不实现 history 在 GraphState,直接 user_message 即可)
- 末尾约束:仅输出 JSON,formatted as `Plan` schema

- [ ] **Step 3: 加 MockLLMClient fixture entry**

在 `backend/tests/fixtures/llm_mocks/agent_decisions.yaml` 加一个 pattern entry:
- 匹配 ChatPlanner prompt 中的"金融研究助手 planner"prefix
- 返回 JSON 字符串 `{"tool_calls": [{"tool_name": "get_stock_quote", "args": {"ts_code": "600519.SH"}, "rationale": "user asked"}], "direct_response": false, "reasoning": "single tool"}`(用 Plan B Task 7 加的 `__recorded__:` redirect 形式或直接 inline)

- [ ] **Step 4: Verify + commit**

---

## Task 8: `Responder` 实现

**Files:**
- Create: `backend/app/agents/responder.py`
- Create: `backend/tests/unit/test_responder.py`

Responder 接受 GraphState(已含 `tool_results`),拼一段 prompt 调 LLM 让其总结成自然语言回答。**v0 不用真 streaming chat,只用 LLMService.chat 一次性出文本**(LangGraph 的 stream API 在 graph 装配层负责把 `responder_node` 的输出按 token 切流出去)。

surface:

```python
class Responder(Agent):
    name = "Responder"
    model_tier: Tier = "fast"

    def step(self, state: GraphState) -> StepResult:
        prompt = build_responder_prompt(state=state)
        r = self._llm.chat(prompt=prompt, tier=self.model_tier, request_id=state.request_id)
        return StepResult(
            state_update={"final_response": r.content},
            span_metadata={"agent": "Responder", "model": r.model, "cost_cny": r.cost_cny},
        )
```

L0 测试:prompt 含 user_message + tool_results 摘要 + 输出格式约束。

---

## Task 9: `orchestration/checkpointer.py` + `nodes.py`

**Files:**
- Create: `backend/app/orchestration/__init__.py`
- Create: `backend/app/orchestration/checkpointer.py`
- Create: `backend/app/orchestration/nodes.py`
- Create: `backend/tests/unit/test_chat_checkpointer.py`
- Create: `backend/tests/unit/test_orchestration_nodes.py`

`checkpointer.py`:

```python
from pathlib import Path
import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver

DEFAULT_DB_PATH = Path("backend/data/chat.sqlite")


def make_chat_checkpointer(db_path: Path = DEFAULT_DB_PATH) -> SqliteSaver:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    return SqliteSaver(conn)
```

`nodes.py`:

```python
async def planner_node(state: GraphState, planner: ChatPlanner) -> dict[str, Any]:
    sr = planner.step(state)
    return sr.state_update


async def tool_node(state: GraphState, registry: ToolRegistry) -> dict[str, Any]:
    if state.plan is None:
        return {}
    results = []
    for call in state.plan.tool_calls:
        results.append(await registry.execute(call))
    return {"tool_results": results}


async def responder_node(state: GraphState, responder: Responder) -> dict[str, Any]:
    sr = responder.step(state)
    return sr.state_update
```

L0 测试覆盖每个节点:用 mock agent / mock registry,传 state,assert 返回的 state_update 正确。

---

## Task 10: `chat_graph.py` + `ChatAgent` SUT wrapper

**Files:**
- Create: `backend/app/orchestration/chat_graph.py`
- Create: `backend/app/agents/chat_agent.py`
- Create: `backend/tests/integration/test_chat_agent_e2e_mock.py`
- Create: `backend/tests/unit/test_chat_graph.py`

`chat_graph.py`:

```python
from functools import partial
from langgraph.graph import StateGraph, START, END
from langgraph.graph.state import CompiledStateGraph

from app.agents.chat_planner import ChatPlanner
from app.agents.responder import Responder
from app.agents.schemas import GraphState
from app.orchestration.checkpointer import make_chat_checkpointer
from app.orchestration.nodes import planner_node, tool_node, responder_node
from app.tools.registry import ToolRegistry


def _route_after_planner(state: GraphState) -> Literal["tool_node", "responder_node"]:
    if state.plan is None:
        return "responder_node"  # planner failed gracefully — let responder explain
    return "tool_node" if state.plan.tool_calls else "responder_node"


def build_chat_graph(
    planner: ChatPlanner,
    responder: Responder,
    registry: ToolRegistry,
    *,
    db_path: Path | None = None,
) -> CompiledStateGraph:
    g: StateGraph = StateGraph(GraphState)
    g.add_node("planner_node", partial(planner_node, planner=planner))
    g.add_node("tool_node", partial(tool_node, registry=registry))
    g.add_node("responder_node", partial(responder_node, responder=responder))

    g.add_edge(START, "planner_node")
    g.add_conditional_edges("planner_node", _route_after_planner, {
        "tool_node": "tool_node",
        "responder_node": "responder_node",
    })
    g.add_edge("tool_node", "responder_node")
    g.add_edge("responder_node", END)

    checkpointer = make_chat_checkpointer(db_path) if db_path else None
    return g.compile(checkpointer=checkpointer)
```

`chat_agent.py`(SUT-friendly wrapper for EvalRunner):

```python
class ChatAgent:
    def __init__(
        self,
        graph: CompiledStateGraph,
        trace_service: TraceService | None = None,
    ) -> None:
        self._graph = graph
        self._trace = trace_service

    async def run(self, user_input: str, request_id: str) -> SUTOutput:
        config = {"configurable": {"thread_id": f"eval:{request_id}"}}
        initial = GraphState(
            user_id="eval",
            session_id=request_id,
            user_message=user_input,
            request_id=request_id,
        )
        final: dict[str, Any] = await self._graph.ainvoke(initial.model_dump(), config=config)
        plan = final.get("plan")
        return SUTOutput(
            request_id=request_id,
            response_text=final.get("final_response") or "",
            tool_calls=plan.tool_calls if plan else [],
        )
```

`test_chat_agent_e2e_mock.py`(L1 集成):
- 用 MockLLMClient + 注册 3 工具(用 mock_tushare 也用 MockLLMClient,即 MockTushareService(llm=svc_mock))
- 创建 ChatPlanner / Responder / ToolRegistry
- 装配 graph(无 checkpointer,纯 in-memory)
- 跑用户查询 "查一下 600519.SH 的股价"
- assert final state 含 `final_response`(非空),`tool_results` 含 1 条 success

---

## Task 11: HTTP `POST /api/v0/chat` SSE 路由

**Files:**
- Create: `backend/app/router/chat.py`
- Modify: `backend/app/app_main.py`(uncomment + 改新 import)
- Create: `backend/tests/integration/test_chat_router_sse.py`

`chat.py` surface:

```python
@router.post("/api/v0/chat")
async def chat(
    req: ChatRequest,
    user: User = Depends(get_current_user),
    chat_agent_graph: CompiledStateGraph = Depends(get_chat_graph),
) -> StreamingResponse:
    return StreamingResponse(
        _stream_chat(req, user, chat_agent_graph),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _stream_chat(req: ChatRequest, user: User, graph: CompiledStateGraph) -> AsyncIterator[str]:
    request_id = f"req-{uuid4().hex[:12]}"
    initial = GraphState(
        user_id=user.id,
        session_id=req.session_id,
        user_message=req.message,
        request_id=request_id,
    )
    config = {"configurable": {"thread_id": f"{user.id}:{req.session_id}"}}

    async for ev in graph.astream_events(initial.model_dump(), config=config, version="v2"):
        sse = _adapt_event(ev)
        if sse is not None:
            yield f"data: {sse.model_dump_json()}\n\n"
```

`_adapt_event` 函数把 LangGraph 内部事件类型(`on_chain_start` / `on_chain_end` / `on_chat_model_stream`)翻成 v0 自定义的 6 种 `StreamEvent.type`(plan / tool_start / tool_end / token / done / error)。

> **依赖 Task 0 Spike 2 结果**确定确切事件类型 set。Plan implementer 用 spike 输出指导 _adapt_event 实现。

L1 测试用 FastAPI TestClient 模拟 SSE,验证事件 framing 正确(每行 `data: <json>\n\n`,事件 type 在 6 种之内)。

---

## Task 12: `EvalRunner` SUT swap

**Files:**
- Modify: `backend/app/services/eval_runner.py`(加 `SUT` Protocol + adapter)
- Modify: `backend/app/services/eval_models.py`(加 `SUTOutput` Pydantic)
- Create: `backend/tests/integration/test_eval_runner_chat_agent_sut.py`

> **Plan B/C 契约保持**:`EvalRunner(sut, judge, ...)` 现有的 `LLMService` SUT 路径必须仍然 work(向后兼容)。

`eval_models.py` 加:

```python
class SUTOutput(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: str
    response_text: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
```

`eval_runner.py` 改:

```python
class SUT(Protocol):
    async def run(self, user_input: str, request_id: str) -> SUTOutput: ...


class _LLMServiceSUT:
    """Adapter: wraps bare LLMService as a SUT (backward compat for Plan C tests)."""

    def __init__(self, llm: LLMService) -> None:
        self._llm = llm

    async def run(self, user_input: str, request_id: str) -> SUTOutput:
        r = self._llm.chat(prompt=user_input, tier="balanced", request_id=request_id)
        return SUTOutput(request_id=r.request_id or request_id, response_text=r.content, tool_calls=[])


class EvalRunner:
    def __init__(
        self,
        sut: SUT | LLMService,  # accepts either; if LLMService, wraps with _LLMServiceSUT
        judge: Judge,
        trace_service: TraceService,
        recorder: EvalRecorder,
    ) -> None:
        self._sut: SUT = sut if not isinstance(sut, LLMService) else _LLMServiceSUT(sut)
        ...

    async def run_one(self, case: GoldenCase) -> EvalResult:
        request_id = f"eval-{case.case_id}-{uuid4().hex[:8]}"
        sut_output = await self._sut.run(user_input=case.user_input, request_id=request_id)
        trace = self._trace.get_trace(request_id) if ... else None
        scores, judge_meta = self._judge.score(
            case=case,
            sut_response=sut_output.response_text,
            trace_summary=...
        )
        ...
```

> **Important**: Plan C 的 `EvalRunner.run_one` 是 sync;改 async 是个 breaking change 给 Plan C 老测试。**Plan D EvalRunner 已有 sync run_one**,本任务保留 sync `run_one` 包装异步 SUT(用 `asyncio.run` or sync wrapper),具体形态 implementer 看 Plan C 现有 signature 决定。

L1 测试:
- 用 ChatAgent SUT 跑 1 个 GoldenCase,assert `eval_result.scores.tool_correctness is not None`(因为 ChatAgent 真用 tool)
- 用 bare LLMService SUT 跑 1 个 GoldenCase,assert `eval_result.scores.tool_correctness is None`(向后兼容)

---

## Task 13: L2 cassette + final integration

**Files:**
- Create: `backend/tests/e2e/test_chat_agent_cassette.py`
- Create: `backend/tests/fixtures/cassettes/test_chat_agent_cassette/...yaml`
- Modify: `pyproject.toml`(LangGraph 版本锁 `>=0.2,<0.3`,新增 `serve` poe task)

L2 cassette 录制(类似 Plan B/C/D 的方式):
- 测试用真 OpenAIClient 注入到 LLMService(走 ChatAgent 全图)
- 第一次 `VCR_RECORD_MODE=once` 录制(成本 ~¥0.01,预期 3 次 LLM 调用)
- 验证 cassette ≤ 100KB,sanitize hook 通过
- replay run 验证 ≤ 1s(3 次 interactions vs Plan C 2 次)

`pyproject.toml` 改动:

```toml
# Plan A 已有 langgraph>=0.2,Plan D 收紧上限避免 0.3 breaking
"langgraph>=0.2,<0.3",

# 新加 serve poe task
[tool.poe.tasks]
serve = "uvicorn app.app_main:app --reload --port 8000 --app-dir backend"
```

---

## Task 14: Final ci + Plan retrospective

- [ ] Final ci sweep:`uv run poe ci`(预期 ~95+ 测试全绿,mypy 全 strict 含 agents/tools/orchestration)
- [ ] 跑一次完整 nightly-local 模拟:`uv run poe nightly-local`(用 ChatAgent 跑 eval)
- [ ] 跑 EvalRunner over 3 starter golden cases with ChatAgent SUT,记录 EvalResult.scores.factuality / tool_correctness 平均分,跟 bare LLMService SUT 对比
- [ ] 填 retrospective(同 Plan B/C/D 模板:对的 3 / 错的 3 / 下个 3 / memory 沉淀 / subagent 节奏 / v0.5 启动条件)

---

## Acceptance Criteria

- [ ] `uv run poe ci` green
- [ ] LLM_MODE branching 仍只 1 处(Plan B 沉淀的架构契约保持)
- [ ] services/agents/tools/orchestration 任意 .py 不 `import openai`(grep 确认)
- [ ] LangGraph 状态图能 SqliteSaver + thread_id 正确隔离(L1 测试)
- [ ] HTTP SSE 流式正确(测试用 TestClient 验证 framing + event types)
- [ ] EvalRunner ChatAgent SUT 跑通,`tool_correctness != None`
- [ ] EvalRunner bare LLMService SUT 仍兼容(向后)
- [ ] L2 cassette ≤ 100KB,sanitized,replay ≤ 1s
- [ ] Old code archive list 全删,~3-5k LOC 净减少
- [ ] Plan retrospective 填写

---

## Test plan (run on completion)

- Local: `uv run poe ci`
- Local: `uv run poe nightly-local`
- Local: `uv run poe serve` 起 uvicorn,curl `POST /api/v0/chat` SSE 真流(用浏览器 EventSource API 也行)
- Local: `unset VCR_RECORD_MODE && uv run pytest backend/tests/e2e/test_chat_agent_cassette.py -v`(replay-only)
- Cloud: PR triggers `pr.yml` —— ≤ 5min ci 全绿(包括 v0 新测试)
- Cloud: 下次 nightly cron 跑 `nightly.yml`,EvalResult 表里多 N 行 ChatAgent SUT 评分

---

## Notes for the implementer

- **3 个 spike(Task 0)是真 5 分钟,不要跳**。后续 task 的代码路径依赖 spike 结果(尤其 Task 7 ChatPlanner 的 prompt 形态、Task 9 SqliteSaver 的 import 路径、Task 11 SSE 的 _adapt_event)。
- **删除 Task 1 是大手笔**,先 grep 后删,清理 import 引用别留 broken state。
- **mock_tushare 改造(Task 5)是局部替换,不是重写**。grep 出 `import openai` 行,只动那几处。其他业务逻辑不动。
- **LangGraph 0.2.x 可能把某些子模块挪到独立 package**(比如 langgraph-checkpoint-sqlite)。Spike 3 验证;如果挪了,plan 实施时新增 dep。
- **Plan B/C/D 契约保持是 acceptance criteria**:任何破坏性改动需要 explicit justify。

---

## Plan retrospective — Task 0 spike result

> Filled in by implementer at Task 0.

### Spike 1: DashScope OpenAI tool-calling 兼容性
- **Date probed**: 2026-05-01
- **Result**: **A** — DashScope native supports OpenAI tool-calling
- **HAS_TOOL_CALLS**: `True`,返回 `ChatCompletionMessageFunctionToolCall(function=Function(arguments='{"ts_code": "600519.SH"}', name='get_stock_quote'))`,LLM 准确识别意图 + 提取参数
- **Model probed**: `deepseek-v4-flash` via `https://dashscope.aliyuncs.com/compatible-mode/v1`
- **Usage**: 283 prompt tokens + 77 completion tokens
- **Action taken**: Task 7 决定走 **B 路径**(prompt-engineered JSON),即使 Spike 显示 A 兼容。理由:复用 Plan B Judge 已验证的 "prompt + JSON parse" 模式,LLMService 契约保持不破坏(不加 `tools=` 参数),代码对称性更好;Spike 1 已证 deepseek-v4-flash 智能足以 handle B 路径。如果 B 路径 prompt-engineered 路由率不达标(< 70%),再切 A 并扩展 LLMService。

### Spike 2: LangGraph astream_events v2 事件类型
- **Date probed**: 2026-05-01
- **LangGraph version**: **1.1.10**(plan 假设的 0.2.x 已大幅 outdated;pyproject 已收紧到 `>=1.0,<2`)
- **EVENT_TYPES**: `['on_chain_end', 'on_chain_start', 'on_chain_stream']`(3 种 chain-level 事件,与 spec § 5 假设大致一致)
- **Event order**(2 节点 toy graph,共 10 events):`on_chain_start/LangGraph` → `on_chain_start/p` → `on_chain_stream/p` → `on_chain_end/p` → `on_chain_stream/LangGraph` → `on_chain_start/r` → ... 节点级嵌套清晰,`name` 字段区分节点
- **Action taken**: Task 11 `_adapt_event` 按 (event, name) tuple 分发:`on_chain_start/<node>` → `plan` / `tool_start` 事件;`on_chain_end/<node>` → `tool_end` 事件。父级 `on_chain_start/LangGraph` 滤掉(否则 SSE 重复)。LLM token 流(`on_chat_model_stream`)Task 11 实施时再验(本 toy 无 LLM 节点未触发)。

### Spike 3: LangGraph SqliteSaver
- **Date probed**: 2026-05-01
- **Import path**: `from langgraph.checkpoint.sqlite import SqliteSaver`(与 spec § 2 一致,但 **该 module 不在 langgraph 主 package 中**,而是在独立的 `langgraph-checkpoint-sqlite==3.0.3` package)
- **公共方法**: `aget_tuple` / `aput` / `aput_writes` / `alist` / `delete_thread` / `acopy_thread` 等齐全,`thread_id` based 跨 session 隔离原生支持
- **Action taken**: pyproject 加 dep `langgraph-checkpoint-sqlite>=3.0,<4`(已加,uv lock 已更新)。Task 9 `checkpointer.py` import 路径与 plan 草拟一致,无需调整。

### Spike outcome summary
- **Plan 大致 intact**:9 个核心决策无需调整,只是 LangGraph 大版本升级(0.2 → 1.1)+ checkpoint 拆分独立 package。
- **pyproject deps 已更新**:`langgraph>=1.0,<2` + 新增 `langgraph-checkpoint-sqlite>=3.0,<4`(原 plan Task 13 计划做的版本锁同步前移到 Task 0)。
- **Task 7 (ChatPlanner) 路径决议**:走 prompt-engineered JSON(B 路径),保持 LLMService 契约稳定。
- **Task 13 pyproject 改动**:不再需要(版本锁已在 Task 0 完成);Task 13 仍要加 `serve` poe task。

---

## Retrospective

> Filled in by implementer at Task 14.

**Implementation completion date**: 2026-05-01
**Branch**: `feat/v0-chat-skeleton`
**Total commits**: 19(13 个 feat/refactor/test + 4 个 chore format/deps + 1 个 spec/plan 提交 + 1 个 follow-up cleanup)
**Total LOC delta**: 82 文件 / +6,056 / -13,094 = **净瘦身 -7,038 行**(超出 spec 估算的"-3-5k 行")
**Total time**: ~3 小时主对话(subagent-driven cadence,约 14 个 subagent 派发,每次 implementer + 0-1 次 reviewer)
**Final ci**: 143 tests pass(82 baseline + 61 新),mypy strict 154 源文件干净,ruff 干净,L2 cassette 18KB 0 drift ¥0.0005

### 对的设计(3 条)

1. **B 路径(prompt-engineered JSON)即使 Spike A 兼容也保留** — Spike 1 证 DashScope deepseek-v4-flash 原生支持 OpenAI tool-calling,但 Task 7 仍选 B 路径。**收益**:LLMService 契约保持(没新增 `tools=` 参数),复用 Plan B Judge 已稳的 prompt+JSON parse 模式,代码对称。**实测验证**:cassette 真打跑通,Plan JSON 解析没问题,planner 路由到 `get_stock_quote` 正确。

2. **SUT Protocol + adapter 兼容 Plan C 老测试零修改** — Task 12 `EvalRunner.__init__(sut: SUT | LLMService, ...)` + `_LLMServiceSUT` adapter 让 Plan C/D 现有 EvalRunner tests 不需要改一行,同时新加 ChatAgent SUT 路径解锁 `tool_correctness` 评分维度。**这是"additive 不破坏"的教科书示例**,值得在 v0.5 spec 推广(ResearchAgent 加 SUT 时同模式)。

3. **Task 0 spike 真值 5 分钟 + plan retrospective 显式填写** — 3 个 spike(DashScope tool-calling / LangGraph 事件类型 / SqliteSaver import 路径)在 Task 1 之前 5 分钟跑完,**直接修正了 plan 的 LangGraph 版本假设(0.2 → 1.1)+ 提前发现 SqliteSaver 已拆 separate package**。如果不 spike,Task 9 实施时撞到 ImportError 才发现,plan revision 成本高得多。

### 错的设计 / plan 漏了什么(3 条)

1. **Plan Step 4 "绝不让 import 失败" 在 Task 1 第一次执行没彻底** — implementer 第一次提交后,`research_router.py:11` + `tool_executor.py:28` 仍有 unguarded import of deleted modules。**spec compliance reviewer 抓出来才修(commit `6c2562d`)**。教训:删除型 task 的 implementer prompt 要把"grep 验证"作为 explicit self-review checklist,不只是 plan 内文字契约。

2. **`_llm_adapter.py` 一开始放在 `app.data` 是 architectural smell** — Task 5 implementer 为了让 `tushare_client.py`(legacy)不破坏,新建 `app/data/_llm_adapter.py` 但其中含 `from openai import OpenAI`,违反"agents/tools/services 不 import openai"契约的精神(虽然 `app.data` 不在 list 里)。**Task 11 移到 `app/services/openai_client.py` 才正名**。教训:Plan B/C/D 把 LLMService 契约写得很死(只 LLMService 能 import openai),但**没说真 LLM client adapter 该住哪里**,Task 13(cassette)前迟早要建,plan 应该在 Task 5 / 11 之间 explicit 化。

3. **ruff 0.6.9(pre-commit pinned)vs 0.15.12(venv resolved)version drift** — pyproject 的 `ruff>=0.6` 让 venv 装最新,但 .pre-commit-config.yaml 仍 pin 0.6.9。两版对 `assert (...) , msg` 多行 wrap 模式 disagree,**Task 10/12/13 各撞了一次,3 个 chore(format) 跟进 commit**。教训:dev-tooling 版本应该 pin 一致(下次 spec 在"开发环境"一节加"version-pin alignment between pyproject + pre-commit")。

### 下个 spec / plan 要避免(3 条)

1. **删除型 task 必须 plan 阶段嵌一个"unguarded reference 自动 grep"步骤** — 不能只靠 implementer 看 plan Step 4 的契约文字。模板:
   ```
   STEP X.Y: 自动 grep 全 backend/ 寻找 N 个被删模块的 unguarded references
   - 命令固定写在 plan 里
   - implementer 要把 grep 输出贴在 self-review report 里
   - 任何 unguarded match 都要 stub/comment/import-guard,不能合并
   ```

2. **跨 task 共享的"基础设施类组件"(如 OpenAIClient adapter)不能让 implementer 自己决定放哪** — plan 应该 explicit 标注"production wiring 组件应放 `app.services.<name>.py`",而不是依赖 implementer 灵感。下次 spec 加一节"基础设施落点表",每个共享组件标 module path + 谁先建谁负责。

3. **dev-tooling 版本 alignment 应该在 spec 一开头检查** — 下次 spec 第 0 节"开发环境"应包含一条 "verify pyproject `<tool>>=X.Y` lower-bound matches `.pre-commit-config.yaml` `rev: vX.Y.Z`",自动避免本次 ruff 0.6/0.15 漂移。

### 沉淀到 memory

需要新加的 memories:
- **`feedback_unguarded_imports_after_delete`**(feedback)— 删除型 task 必须 plan 阶段强制 grep N 个被删模块的 unguarded refs,不能只写"Step 4: 处理引用"(本 plan Task 1 教训,被 reviewer 抓出来)。
- **`feedback_dev_tool_version_pin_alignment`**(feedback)— pyproject `>=X.Y` lower-bound 与 `.pre-commit-config.yaml` `rev: vX.Y.Z` 必须 align,否则 hooks 与 venv runs 会 disagree(本 plan ruff 0.6 vs 0.15 教训)。
- **`project_v0_architecture_landed`**(project)— v0 chat agent skeleton 落地状态:LangGraph 1.1 + Pydantic agents + 3 tools + SSE + SqliteSaver checkpointer + EvalRunner SUT swap;`app.services.openai_client.build_llm_service_from_env()` 是真 LLM 入口;deepseek-v4-flash 是 v0 默认。
- 更新 **`project_eval_pipeline_contract`**:加 SUT Protocol + ChatAgent 作为新 SUT 类型,Plan C bare LLMService 仍兼容(`_LLMServiceSUT` adapter)。

### Subagent-driven-development 节奏复盘

- **总 14 个 task 的 subagent 派发**:Task 1 / 5 / 11 / 12 / 13 用了 implementer + 1 spec reviewer 双步,其他 task(Task 2 / 3 / 4 / 6 / 7 / 8 / 9 / 10)用 implementer 单步 + 主控 spot-check。**Task 1 双步 catch 到 BLOCKING import 缺口,值回票价**;**Task 5 双步 catch 到 architectural smell(_llm_adapter 放错位置),defer 到 Task 11 修**。
- **subagent 报告偶有不准**(Task 5 implementer 报"101 tests" 实际 100,Task 10 报 "ci 绿" 但 ruff format 没跑过)。**主控必须独立 verify**(`uv run poe ci`),不能盲信 implementer self-report。
- **格式漂移成本**:每次 ruff 0.6/0.15 撞车需要一个 follow-up `chore(format)` commit;3 次共消耗 ~10 分钟主对话。如果当时直接 fix `.pre-commit-config.yaml` 的 ruff `rev: v0.15.x` 会一次性解决,但担心引发其他 file 的 reformatting 涟漪,选了 "撞一个修一个" 路径。下次正经修。
- **subagent 选择 sonnet 全程够用**:14 次 implementer + 5 次 reviewer,均跑通,没有需要升级到 opus 的场景(因为 plan 写得够具体,implementer 只需 follow + grep + 局部判断)。

### v0.5 启动条件

v0 完成后,v0.5 research mode spec 可以起草。依赖就位:
- ✅ LangGraph + checkpointer 已用过

v0 完成后,v0.5 research mode spec 可以起草。依赖就位:
- ✅ LangGraph + checkpointer 已用过
- ✅ Agent ABC + DispatchSubAgent placeholder 已就位(v0.5 Critic 可以开始用)
- ✅ ToolRegistry + 3 工具(v0.5 加 web_search / kb_search 工具)
- ✅ EvalRunner SUT swap 模式已建立(v0.5 加 ResearchAgent 满足 SUT)
- ✅ SSE 流式经验已积累(v0.5 research 长流程更需要流式 progress 反馈)

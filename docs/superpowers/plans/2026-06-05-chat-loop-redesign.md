# Chat 模式 Agent Loop 重设计 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 chat 模式从 LangGraph supervisor 单程图替换为裸 Python while 工具调用循环(单 LLM、原生 function calling、四道终止闸、工具渐进披露、steering 插话),直接替换、老图退役。

**Architecture:** 新包 `backend/app/chatloop/`(纯函数核 + 不纯壳)承载循环;`LLMService.stream_step` 是唯一底座扩展;ToolHub 统一 MCP 与 in-process 双后端;传输层(Celery + Redis Streams + SSE)与持久化(PG 三表)零改接入;turn 原子语义(重试=整 turn 重跑,无中途恢复)。设计 SoT:`docs/superpowers/specs/2026-06-05-chat-loop-redesign-design.md`(实施者必读)。

**Tech Stack:** Python 3.12 / FastAPI / Celery / Redis / PG15 / openai SDK(DashScope compatible-mode,默认模型 deepseek-v4-flash)/ React + valtio 前端。

**测试命令约定**(后端一律走 WSL fria-venv,见 CLAUDE.md 跨机约定):

```bash
wsl bash -c "cd /mnt/d/mys/Financial-Research-Investment-Assistant && source ~/fria-venv/bin/activate && set -a && source .env && set +a && python -m pytest <PATH> -q --no-header"
```

PG 已验证可达(15.18);`.env` 含 DASHSCOPE_API_KEY(冒烟测试与 cassette 录制用)。前端命令在 `frontend/` 下 `pnpm test` / `pnpm build`。dashboard 测试用 Windows 根 `.venv`(与本计划无关)。

**关键既有接口**(实施者据此对接,改前先读源文件):

- `LLMService`(`backend/app/services/llm_service.py`):`chat(prompt, tier, schema, request_id, parent_span_id) -> LLMResponse`;构造注入 `client: ChatClient`(Protocol,只有 `chat(prompt, model, schema)`)、`tier_router`、`trace_service`、`cost_budget`。
- `_OpenAIAdapter`(`backend/app/services/openai_client.py:47`):真实 ChatClient,持 `openai.OpenAI`;`build_llm_service_from_env()` 是工厂。
- `MockLLMClient`(`backend/app/services/llm_mock_client.py`):fixture 驱动 mock,返回 `_RawCompletion`。
- `ToolRegistry`(`backend/app/tools/registry.py`):`list_for_llm() -> list[dict]`(OpenAI function 格式)、`execute(ToolCall) -> ToolResult`、`get(name)`;`register_mcp_client_async(mcp_client)` 从 MCP 子进程灌入工具。
- `ToolResult` / `ToolCall`(`backend/app/agents/schemas.py`)。
- `ToolResultCache`(`backend/app/services/tool_result_cache.py`):`get_or_compute(user_id, tool_name, args, compute_fn) -> (dict, hit_status)`;cache_key 形如 `{user_id}::{tool_name}::{sha256(args)[:32]}`。
- chat 持久化:`ChatSessionRepo`(`backend/app/services/chat_session_repo.py`)、`ChatTaskRepo`、`finalize_task_persistence`(`backend/app/router/chat_finalize.py`)、ORM(`backend/app/models/chat.py`:ChatSession/ChatMessage/ChatTask)。
- 传输:`ChatEventBus`(`backend/app/services/chat_event_bus.py`,XADD/XREAD)、`ChatCancelBus`(`backend/app/services/chat_cancel_bus.py`,pub/sub)、Celery 入口 `run_chat_async`(`backend/app/tasks/chat_runner.py`)。
- 记忆:`HierarchicalMemory`(`backend/app/memory/`,worker 已构建实例)、注入分类器、`populate_persona_on_session_start`(`backend/app/router/chat.py:437-451`)。
- 技能:`SkillLoader` / `SkillExecutor`(`backend/app/services/skills/` 与 `backend/app/skills/`)。
- 升级:`EscalationExtractor`(`backend/app/agents/escalation_extractor.py`,签名收 history 文本 + cached_tool_results)。

---

## Phase 0:冒烟测试(一切的闸)

### Task 0.1: qwen/DashScope 原生 function calling 能力实测

**Files:**
- Create: `backend/scripts/smoke_native_tools.py`
- Create: `docs/superpowers/specs/2026-06-05-smoke-results.md`(结果记录)

- [ ] **Step 1: 写探针脚本**(直连 DashScope,逐项验 8 个能力点,每项独立 try 不互相阻塞):

```python
"""Smoke test: qwen/DashScope compatible-mode native function calling 能力实测.

跑法(WSL): python backend/scripts/smoke_native_tools.py
按 spec § 2.1 清单逐项验证,结果打印为 markdown 表格行。
"""
from __future__ import annotations

import json
import os

from openai import OpenAI

MODEL = os.getenv("SMOKE_MODEL", "deepseek-v4-flash")
client = OpenAI(
    api_key=os.environ["DASHSCOPE_API_KEY"],
    base_url=os.environ.get("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
)

TOOLS = [{
    "type": "function",
    "function": {
        "name": "get_stock_quote",
        "description": "查询单只 A 股实时行情。何时用:问现价/涨跌幅。ts_code 须带后缀如 600519.SH",
        "parameters": {"type": "object", "properties": {"ts_code": {"type": "string"}},
                        "required": ["ts_code"]},
    },
}, {
    "type": "function",
    "function": {
        "name": "get_news",
        "description": "查询个股最新新闻。",
        "parameters": {"type": "object", "properties": {"ts_code": {"type": "string"}},
                        "required": ["ts_code"]},
    },
}]
THIN_TOOL = [{  # 瘦 schema:开放参数声明(item 8)
    "type": "function",
    "function": {"name": "compare_stocks", "description": "对比多只股票。需先检索文档获取参数细节。",
                  "parameters": {"type": "object", "properties": {}}},
}]
MSG = [{"role": "user", "content": "贵州茅台现在股价多少?"}]
MSG_PARALLEL = [{"role": "user", "content": "同时查贵州茅台的股价和最新新闻"}]

def check(name: str, fn) -> None:
    try:
        ok, detail = fn()
        print(f"| {name} | {'PASS' if ok else 'FAIL'} | {detail} |")
    except Exception as e:  # noqa: BLE001
        print(f"| {name} | ERROR | {type(e).__name__}: {str(e)[:120]} |")

def t1_native_tool_call():
    r = client.chat.completions.create(model=MODEL, messages=MSG, tools=TOOLS)
    c = r.choices[0]
    return (c.finish_reason == "tool_calls" and bool(c.message.tool_calls),
            f"finish_reason={c.finish_reason}, calls={[t.function.name for t in (c.message.tool_calls or [])]}")

def t2_stream_delta_shape():
    s = client.chat.completions.create(model=MODEL, messages=MSG, tools=TOOLS, stream=True)
    frags: dict[int, dict] = {}
    finish = None
    for chunk in s:
        ch = chunk.choices[0] if chunk.choices else None
        if ch is None:
            continue
        finish = ch.finish_reason or finish
        for tc in ch.delta.tool_calls or []:
            f = frags.setdefault(tc.index, {"id": None, "name": None, "args": ""})
            if tc.id:
                f["id"] = tc.id
            if tc.function and tc.function.name:
                f["name"] = tc.function.name
            if tc.function and tc.function.arguments:
                f["args"] += tc.function.arguments
    parsed = {i: json.loads(f["args"]) for i, f in frags.items() if f["args"]}
    return (bool(frags) and all(f["name"] for f in frags.values()) and bool(parsed),
            f"finish={finish}, assembled={ {i: (f['name'], parsed.get(i)) for i, f in frags.items()} }")

def t3_parallel_calls():
    r = client.chat.completions.create(model=MODEL, messages=MSG_PARALLEL, tools=TOOLS)
    calls = r.choices[0].message.tool_calls or []
    return (len(calls) >= 2, f"n_calls={len(calls)}: {[t.function.name for t in calls]}")

def t4_thinking_roundtrip():
    # qwen thinking 形态探测:看响应里是否有 reasoning_content;有则记录,无则 N/A
    r = client.chat.completions.create(model=MODEL, messages=MSG, tools=TOOLS,
                                       extra_body={"enable_thinking": True})
    msg = r.choices[0].message
    rc = getattr(msg, "reasoning_content", None)
    return (True, f"reasoning_content={'present' if rc else 'absent'}(absent=不做 reasoning 折叠区,非失败)")

def t5_stream_usage():
    s = client.chat.completions.create(model=MODEL, messages=MSG, tools=TOOLS, stream=True,
                                       stream_options={"include_usage": True})
    usage = None
    for chunk in s:
        if chunk.usage:
            usage = chunk.usage
    return (usage is not None, f"prompt={getattr(usage, 'prompt_tokens', None)}")

def t6_cache_hit():
    big_sys = [{"role": "system", "content": "你是金融研究助手。" + "工具使用纪律细则。" * 200}] + MSG
    client.chat.completions.create(model=MODEL, messages=big_sys, tools=TOOLS)
    r2 = client.chat.completions.create(model=MODEL, messages=big_sys, tools=TOOLS)
    d = getattr(r2.usage, "prompt_tokens_details", None)
    cached = getattr(d, "cached_tokens", None) if d else None
    return (bool(cached), f"cached_tokens={cached}(0/None=隐式缓存未命中,记录但非阻塞)")

def t7_tool_choice_none():
    r = client.chat.completions.create(model=MODEL, messages=MSG, tools=TOOLS, tool_choice="none")
    c = r.choices[0]
    return (not c.message.tool_calls and bool(c.message.content),
            f"finish={c.finish_reason}, content_len={len(c.message.content or '')}")

def t8_thin_schema():
    r = client.chat.completions.create(
        model=MODEL, messages=[{"role": "user", "content": "对比茅台和五粮液"}], tools=TOOLS + THIN_TOOL)
    calls = r.choices[0].message.tool_calls or []
    return (True, f"calls={[t.function.name for t in calls]}(观察模型对瘦 schema 工具的调用行为)")

print(f"## Smoke results — model={MODEL}\n\n| item | result | detail |\n|---|---|---|")
for n, f in [("1 native tool_calls", t1_native_tool_call), ("2 stream delta 拼接", t2_stream_delta_shape),
             ("3 parallel calls", t3_parallel_calls), ("4 thinking 形态", t4_thinking_roundtrip),
             ("5 stream usage", t5_stream_usage), ("6 隐式缓存命中", t6_cache_hit),
             ("7 tool_choice=none", t7_tool_choice_none), ("8 瘦 schema 行为", t8_thin_schema)]:
    check(n, f)
```

- [ ] **Step 2: 跑探针**:`wsl bash -c "cd /mnt/d/... && source ~/fria-venv/bin/activate && set -a && source .env && set +a && python backend/scripts/smoke_native_tools.py"`。预期:打出 8 行表格。
- [ ] **Step 3: 结果写入 `docs/superpowers/specs/2026-06-05-smoke-results.md`**,并按 spec § 2.1 标注触发的降级路径(item 1 FAIL → stream_step 内部走 JSON 约束;item 7 FAIL → 收尾圈不传 tools;item 4 absent → 不做 reasoning 折叠区;item 6 未命中 → 缓存命中率指标仍记录,标注口径)。**若 item 1/2 任一 FAIL,先停下向用户汇报再继续**(它们决定主路径形态)。
- [ ] **Step 4: Commit**:`git add backend/scripts/smoke_native_tools.py docs/superpowers/specs/2026-06-05-smoke-results.md && git commit -m "test(smoke): qwen 原生 function calling 8 项能力实测"`

---

## Phase 1:LLM 层 stream_step

### Task 1.1: StepResult/StepDelta 类型 + Mock 支持(TDD)

**Files:**
- Create: `backend/app/services/llm_step.py`(类型,零依赖纯数据)
- Modify: `backend/app/services/llm_mock_client.py`(加 `stream_chat` 脚本化支持)
- Test: `backend/tests/unit/chatloop/test_llm_step_types.py`

- [ ] **Step 1: 失败测试**:

```python
"""StepResult/StepDelta 纯数据类型测试(L0,无 I/O)。"""
from app.services.llm_step import StepDelta, StepResult, StepToolCall


def test_step_result_natural_stop():
    r = StepResult(content="茅台现价 1700 元", tool_calls=[], finish_reason="stop",
                   prompt_tokens=100, completion_tokens=20, cached_tokens=80, cost_cny=0.001)
    assert not r.tool_calls and r.finish_reason == "stop"


def test_step_result_with_calls_parses_args():
    r = StepResult(content="我查一下", finish_reason="tool_calls", prompt_tokens=1, completion_tokens=1,
                   cached_tokens=0, cost_cny=0.0,
                   tool_calls=[StepToolCall(id="c1", name="get_stock_quote",
                                            arguments='{"ts_code": "600519.SH"}')])
    assert r.tool_calls[0].parsed_args == {"ts_code": "600519.SH"}


def test_step_tool_call_bad_json_raises_value_error():
    import pytest
    with pytest.raises(ValueError):
        StepToolCall(id="c1", name="x", arguments="{not json").parsed_args  # noqa: B018
```

- [ ] **Step 2: 跑测试确认失败**(模块不存在)。
- [ ] **Step 3: 实现 `llm_step.py`**:

```python
"""LLM 单圈调用的结果/增量类型 — chatloop 与 LLM 协议的解耦边界(spec § 2.1)。

降级路径(qwen 无原生 tool_calls 时)只换 stream_step 内部实现,
本模块类型不变,循环及以上零改。
"""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel


class StepToolCall(BaseModel):
    id: str
    name: str
    arguments: str  # 原始 JSON 串(流式分片拼接产物)

    @property
    def parsed_args(self) -> dict:
        try:
            parsed = json.loads(self.arguments or "{}")
        except json.JSONDecodeError as e:
            raise ValueError(f"tool_call arguments 不是合法 JSON: {self.arguments!r}") from e
        if not isinstance(parsed, dict):
            raise ValueError(f"tool_call arguments 须为 object: {self.arguments!r}")
        return parsed


class StepDelta(BaseModel):
    """流式增量 — emit 给 SSE 的最小单元。"""
    kind: Literal["content", "reasoning", "tool_call"]
    text: str = ""
    tool_name: str | None = None  # kind=tool_call 且 name 首次到达时携带


class StepResult(BaseModel):
    content: str
    tool_calls: list[StepToolCall]
    finish_reason: str  # stop | tool_calls | length | ...
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int  # KV-cache 命中(一等观测指标,spec § 2.4)
    cost_cny: float
```

- [ ] **Step 4: 跑测试确认通过。**
- [ ] **Step 5: MockLLMClient 加脚本化 stream_chat**(读 `llm_mock_client.py` 现有结构后增量加,不破坏现有 fixture 机制):新增 `ScriptedStepClient` 类(同文件或新文件 `backend/app/services/llm_scripted_client.py`,二选一以现有文件行数定,>300 行则新文件):

```python
class ScriptedStepClient:
    """L1 测试用:按预排剧本逐圈返回 StepResult,记录收到的 messages 供断言。

    用法:
        client = ScriptedStepClient(steps=[
            StepResult(content="查持仓", finish_reason="tool_calls", tool_calls=[...], ...),
            StepResult(content="综合来看…", finish_reason="stop", tool_calls=[], ...),
        ])
    """

    def __init__(self, steps: list[StepResult]) -> None:
        self._steps = list(steps)
        self.received_messages: list[list[dict]] = []
        self.received_tool_choice: list[str] = []

    async def stream_chat(self, *, messages, model, tools, tool_choice, on_delta=None):
        self.received_messages.append([dict(m) for m in messages])
        self.received_tool_choice.append(tool_choice)
        step = self._steps.pop(0)
        if on_delta is not None and step.content:
            from app.services.llm_step import StepDelta
            await on_delta(StepDelta(kind="content", text=step.content))
        return step
```

- [ ] **Step 6: 测试 ScriptedStepClient**(剧本弹出顺序、messages 记录)并跑过。
- [ ] **Step 7: Commit**:`feat(llm): StepResult/StepDelta 类型 + 脚本化 mock client`

### Task 1.2: LLMService.stream_step + _OpenAIAdapter 流式实现

**Files:**
- Modify: `backend/app/services/llm_service.py`(加 `stream_step`;旧 `chat` 零改)
- Modify: `backend/app/services/openai_client.py`(`_OpenAIAdapter` 加 `stream_chat`)
- Test: `backend/tests/unit/chatloop/test_stream_step.py`(用 ScriptedStepClient)
- Test: `backend/tests/integration/test_stream_step_adapter.py`(L1,mock OpenAI SDK 响应对象验拼接逻辑)

- [ ] **Step 1: 失败测试**(stream_step 经 mock client 返回 StepResult;预算 track 被调;span 写了 tool_calls metadata + cached_tokens):

```python
async def test_stream_step_returns_result_and_tracks_budget(scripted_client, budget_spy):
    svc = LLMService(client=scripted_client, cost_budget=budget_spy)
    r = await svc.stream_step(messages=[{"role": "user", "content": "hi"}], tools=None)
    assert r.finish_reason == "stop"
    assert budget_spy.tracked  # cost_cny 进了预算


async def test_stream_step_passes_tool_choice(scripted_client):
    svc = LLMService(client=scripted_client)
    await svc.stream_step(messages=[...], tools=[...], tool_choice="none")
    assert scripted_client.received_tool_choice == ["none"]
```

- [ ] **Step 2: 实现 `LLMService.stream_step`**:签名按 spec § 2.1;tier 经现有 `tier_router.resolve`;调 `self._client.stream_chat(...)`(ChatClient Protocol 加可选方法——用 `getattr` 探测 + 清晰报错,旧 client 不强制实现);cost 用 `compute_cost` + `self._budget.track`;span 复用现有写法,metadata 加 `tool_calls`(name+args 截断)与 `cached_tokens`。
- [ ] **Step 3: 实现 `_OpenAIAdapter.stream_chat`**:`stream=True` + `stream_options={"include_usage": True}`;按 Task 0.1 t2 验证过的分片形态拼接(`delta.content` 逐段回调 `on_delta(StepDelta(kind="content"))`;`delta.tool_calls[i]` 按 index 累积 id/name/arguments,name 首次到达回调 `StepDelta(kind="tool_call", tool_name=...)`;若 smoke 显示有 `reasoning_content` delta,同样回调 `kind="reasoning"`);组装 StepResult(cached_tokens 从 `usage.prompt_tokens_details.cached_tokens` 取,无则 0)。**若 smoke item 1 FAIL**:此处实现 JSON 约束降级(非流式 `response_format=json_object`,prompt 内嵌 `{content, tool_calls}` schema,解析出同样的 StepResult;content 部分不流式,整段一次回调)。
- [ ] **Step 4: L1 适配器测试**:不打真网——构造假的 OpenAI chunk 对象序列(SimpleNamespace 即可)喂给拼接逻辑(把拼接抽成模块级纯函数 `assemble_stream(chunks) -> (content, frags, finish, usage)` 以便直测),覆盖:多 chunk content / 双工具按 index 分片 / arguments 跨 chunk 切半个 JSON / usage 最后到达。
- [ ] **Step 5: 全部跑过,mypy/ruff 过(`python -m mypy backend/app/services/llm_step.py backend/app/services/llm_service.py`)。**
- [ ] **Step 6: Commit**:`feat(llm): stream_step — messages+tools 流式接口与 DashScope 适配`

---

## Phase 2:chatloop 核心(纯函数核全 L0)

### Task 2.1: events.py + state.py(LoopEvent / ChatLoopState / ToolLedger)

**Files:**
- Create: `backend/app/chatloop/__init__.py`、`backend/app/chatloop/events.py`、`backend/app/chatloop/state.py`
- Test: `backend/tests/unit/chatloop/test_state.py`

- [ ] **Step 1: 失败测试**(ledger 记账/签名指纹/去重查询/extractor 视图;state 折叠 apply_step/apply_results):

```python
from app.chatloop.state import ChatLoopState, LedgerEntry, ToolLedger


def test_ledger_signature_and_dedup():
    led = ToolLedger()
    led.record(step=1, tool_name="financial_statements", args={"ts_code": "600519.SH"},
               digest="毛利率 91.2%", success=True, cache_key="u1::fin::abc")
    assert led.find(tool_name="financial_statements", args={"ts_code": "600519.SH"}) is not None
    assert led.signature_set(step=1) == {led.entries[0].signature}


def test_ledger_extractor_view_only_success():
    led = ToolLedger()
    led.record(step=1, tool_name="a", args={}, digest="ok", success=True, cache_key="k1")
    led.record(step=2, tool_name="b", args={}, digest="err", success=False, cache_key=None)
    view = led.to_extractor_view()
    assert [v["cache_id"] for v in view] == ["k1"]


def test_apply_results_appends_tool_messages_keeping_pairing():
    state = ChatLoopState(user_id="u1", session_id="s1", request_id="r1",
                          messages=[{"role": "user", "content": "查茅台"}])
    # assistant(tool_calls) 由 apply_step 进,tool 消息由 apply_results 进,must 配对
    ...
```

- [ ] **Step 2: 实现**。`events.py`:

```python
"""LoopEvent — SSE 与 trace 的统一信封(spec § 5.1)。"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

EventType = Literal[
    "step_start", "token", "reasoning", "tool_call", "tool_start", "tool_end",
    "tool_error", "skill_load", "steer_merged", "loop_halt", "approval_request",
    "escalate_request", "cost_update", "done", "error",
]


class LoopEvent(BaseModel):
    type: EventType
    seq: int
    step: int
    data: dict[str, Any] = {}
```

`state.py` 核心(完整字段见 spec § 1/§ 4,实现时按此骨架):

```python
class LedgerEntry(BaseModel):
    step: int
    tool_name: str
    args_hash: str       # sha256(canonical json)[:16]
    digest: str          # ≤200 字摘要
    success: bool
    cache_key: str | None
    @property
    def signature(self) -> str: return f"{self.tool_name}:{self.args_hash}"


class ToolLedger(BaseModel):
    entries: list[LedgerEntry] = []
    searched_docs: set[str] = set()   # 渐进披露:本 turn 已检索过文档的工具
    def record(...)
    def find(tool_name, args) -> LedgerEntry | None
    def signature_set(step) -> set[str]
    def fail_count(signature) -> int
    def to_extractor_view() -> list[dict]   # [{tool_name, summary, cache_id}],仅 success


class ChatLoopState(BaseModel):
    user_id: str; session_id: str; request_id: str
    messages: list[dict]              # OpenAI 格式,single source of truth
    ledger: ToolLedger = ToolLedger()
    step: int = 0
    budget_spent_cny: float = 0.0
    budget_spent_tokens: int = 0
    burned_signatures: set[str] = set()
    halt_reason: str | None = None    # natural|max_steps|budget|spinning|escalate
    escalate_offered: bool = False
    escalate_reason: str | None = None
    tool_choice: str = "auto"         # 熔断收尾时置 "none"
    active_skill: str | None = None   # 活跃技能方法论不降级(spec § 3.4)
    final_response: str | None = None # = 最后一条 assistant content
```

加纯函数 `apply_step(state, step: StepResult) -> ChatLoopState`(追加 assistant 消息——含 tool_calls 原样转 OpenAI 格式;累计预算;step+1)与 `apply_results(state, results: list[ToolResult], calls) -> ChatLoopState`(按 tool_call_id 一一追加 tool 消息,**保证每个 call id 都有对应 tool 消息**——单测覆盖)。
- [ ] **Step 3: 跑过 + commit**:`feat(chatloop): LoopEvent/ChatLoopState/ToolLedger 纯数据核`

### Task 2.2: gates.py(四道闸 + 打转 + 烧签名)

**Files:**
- Create: `backend/app/chatloop/gates.py`
- Test: `backend/tests/unit/chatloop/test_gates.py`

- [ ] **Step 1: 失败测试**(每道闸一个谓词一组测试):

```python
from app.chatloop.gates import GateConfig, check_gates


CFG = GateConfig(max_steps=12, max_cny=0.10, max_tokens=120_000)

def test_under_limits_no_halt(state_factory):
    assert check_gates(state_factory(step=3, cny=0.01), CFG) is None

def test_max_steps_halts():
    assert check_gates(state_factory(step=12), CFG) == "max_steps"

def test_budget_cny_halts():
    assert check_gates(state_factory(cny=0.11), CFG) == "budget"

def test_spinning_two_identical_rounds():
    st = state_factory(step=4)
    st.ledger.record(step=3, tool_name="compare_stocks", args={"a": 1}, ...)
    st.ledger.record(step=4, tool_name="compare_stocks", args={"a": 1}, ...)
    assert check_gates(st, CFG) == "spinning"

def test_burned_signature_filtering():
    # filter_burned(calls, state) 把 burned 签名的调用剔除并产出 error result
    ...
```

- [ ] **Step 2: 实现**:`check_gates(state, cfg) -> str | None`(顺序:max_steps → budget → spinning);`spinning` = `step>=2 且 signature_set(step)==signature_set(step-1) 且非空`;`filter_burned(calls, state) -> (allowed, rejected_results)`;`should_burn(state, signature) -> bool`(fail_count >= 3)。零 I/O。
- [ ] **Step 3: 跑过 + commit**:`feat(chatloop): 四道闸/打转检测/烧签名纯谓词`

### Task 2.3: context.py(窗口组装 + 协议红线 + 降级)

**Files:**
- Create: `backend/app/chatloop/context.py`
- Test: `backend/tests/unit/chatloop/test_context.py`

- [ ] **Step 1: 失败测试**(分区顺序/尾部动态区/配对不切破/降级保护名单/token 估算):

```python
def test_zones_order_and_tail_dynamic():
    msgs = assemble_context(state, deps)
    assert msgs[0]["role"] == "system"                      # 角色+纪律
    assert "第 3/12 步" in msgs[-1]["content"]               # 闸提示在最尾
    assert "预算剩" in msgs[-1]["content"]

def test_stable_prefix_byte_identical_across_steps():
    a = assemble_context(state_step3, deps)
    b = assemble_context(state_step4, deps)
    # 前缀区(system+历史+本turn既有轨迹前缀)逐字节相同,只有尾部动态区变
    assert a[: len(a) - 1] == b[: len(b) - 2][: len(a) - 1]  # 按实现细化

def test_downgrade_keeps_tool_pairing_and_skeleton():
    # 老圈大 tool content 替换为 "[已缓存 ref=…] 摘要",role/tool_call_id 不动
    ...

def test_downgrade_protects_failures_and_active_skill():
    # success=False 的 tool 消息与 active_skill 的 load_skill 结果永不降级
    ...

def test_estimate_tokens_cjk():
    assert estimate_tokens("茅" * 165) >= 100   # 中文 1.65 字符/token 口径
```

- [ ] **Step 2: 实现**:`assemble_context(state, deps: ContextDeps) -> list[dict]`。`ContextDeps`(冻结 dataclass)带:`system_prompt: str`(角色+工具纪律+记忆/kb 启发式,组装期固定)、`persona_block: str`、`skill_listing: str`、`history_block: list[dict]`(rebuild 产物,Phase 4 注入;本 phase 测试直接给)、`gate_cfg`。窗口 = [system(三段合一,逐字节稳定)] + history + 本 turn messages(含降级处理)+ [尾部动态 user 消息:`(第 N/M 步,预算剩 ¥x.xx。)` + 可选技能提示]。降级:遍历本 turn tool 消息,`len(content) > 800*1.65 字符` 且非保护名单(失败/active_skill 装载/最近一圈)→ content 换 `[已缓存 ref={cache_key}] {digest}`(从 ledger 查),用 `downgraded_ids: set` 防重复处理。`estimate_tokens(text)`:`ceil(cjk_chars/1.65 + ascii_chars/4)`。
- [ ] **Step 3: 跑过 + commit**:`feat(chatloop): 窗口四区组装/降级保护名单/CJK token 估算`

### Task 2.4: loop.py(ToolLoop while 本体)

**Files:**
- Create: `backend/app/chatloop/loop.py`
- Test: `backend/tests/unit/chatloop/test_loop.py`(ScriptedStepClient + FakeToolHub,全内存)

- [ ] **Step 1: 失败测试**(六个剧本):

```python
async def test_multi_hop_two_steps_then_stop():   # 持仓多跳
async def test_natural_stop_first_step():          # 直答,一圈结束
async def test_error_feedback_then_retry():        # 报错喂回,第二圈修正
async def test_max_steps_force_conclude():         # 撞闸→喂回收尾指令→终圈 tool_choice=none
async def test_escalation_fuse():                  # offer 后下一圈 tool_choice=none,同 turn 二调被拒
async def test_steer_merged_at_loop_boundary():    # 圈边界 RPOP 并入,窗口尾部出现插话
```

FakeToolHub:`dispatch(calls) -> list[ToolResult]` 按预排表返回;FakeSteerSource:`pop_all() -> list[str]`。
- [ ] **Step 2: 实现 ToolLoop**(按 spec § 1.2 节拍;构造注入 `llm, tool_hub, gates_cfg, emitter, steer_source, cancel_event, context_deps`):`run(state) -> ChatLoopState`;`force_conclude`:append system 观察消息「已达上限({reason}),请基于已有信息直接作答」+ 置 `tool_choice="none"` 再调一次 stream_step 收尾 + emit loop_halt;cancel 检查:每圈边界 + on_delta 回调内(抛 `CancelledByUser`,由调用方处置);emit:step_start/token(经 on_delta)/tool_call/tool_start/tool_end/tool_error/cost_update/done。
- [ ] **Step 3: 跑过(六剧本全绿)+ mypy + commit**:`feat(chatloop): ToolLoop while 本体 — 多跳/自纠/熔断/插话六剧本`

---

## Phase 3:ToolHub 与周边接线

### Task 3.1: tool_hub.py 基座(双后端 + dispatch + 台账)

**Files:**
- Create: `backend/app/chatloop/tool_hub.py`
- Test: `backend/tests/unit/chatloop/test_tool_hub.py`

- [ ] 失败测试 → 实现 → 过 → commit。要点:
  - `register_inprocess(tools: list[Tool])` / `register_mcp(registry: ToolRegistry)`(MCP 工具经现有 registry 注册,复用其 `execute`);
  - `schemas_for_llm(groups) -> list[dict]`:三组渐进披露(Task 3.2 的分组配置);
  - `dispatch(calls, state) -> list[ToolResult]`:先 `filter_burned`;ledger 去重(同签名已 success → 直接回 digest 结果不重跑);`asyncio.gather(return_exceptions=True)` 并行;单工具异常包 `ToolResult(success=False, error=指导性文案)`(错误文案生成器:参数校验错→格式提示;未知工具→"先 search_tools";超时→换策略);写 ledger(digest = json 序列化截 200 字);ToolResultCache 接入沿用现状 `get_or_compute` 模式(user 隔离);
  - emit tool_start/tool_end(带 cached 标志)/tool_error。
  - Commit: `feat(chatloop): ToolHub 双后端分发/台账/指导性错误`

### Task 3.2: 渐进披露(三组 + search_tools + 工具文档)

**Files:**
- Create: `backend/app/chatloop/tool_docs.py`(14 个工具的完整使用文档 + description 全套,常量模块)
- Modify: `backend/app/chatloop/tool_hub.py`(分组 + search_tools 实现)
- Test: `backend/tests/unit/chatloop/test_progressive_disclosure.py`

- [ ] 要点:
  - `tool_docs.py`:每工具一条 `ToolDoc{name, group: core|deferred, brief(一句话触发描述), doc(完整文档:何时用/何时不用/参数 schema/示例/硬约束)}`。description 全部按 spec § 3.1 模板写齐(互斥边界——indicators vs financials vs compare、kb vs memory 那两对照 spec § 3.1 文案);
  - 核心组 6 + 延迟组 8 按 spec § 3.2;瘦条目 = `{"name", "description": brief, "parameters": {"type": "object", "properties": {}}}`;
  - `search_tools(query)`:in-process 工具;对 `ToolDoc.doc` 做关键词评分(分词按空格+中文 2-gram,无第三方依赖),返回 top-3 文档文本;ledger.searched_docs 记账,重复检索同工具直接回缓存文本;
  - 裸调延迟工具:dispatch 先按真实 schema(tool_docs 持有完整 parameters)校验,失败回"请先 search_tools('X')"指导错误;
  - 测试:瘦/全分组正确;search 命中;裸调校验错误文案;重复 search 去重。
  - Commit: `feat(chatloop): 工具渐进披露 — 三组 schema/search_tools/14 工具文档全套`

### Task 3.3: 记忆双工具 in-process(合并六件套 + 分类器收口)

**Files:**
- Create: `backend/app/chatloop/memory_tools.py`
- Test: `backend/tests/unit/chatloop/test_memory_tools.py`(HierarchicalMemory 用 Fake 替身)
- 先读:`backend/app/memory/` 的 HierarchicalMemory 公开方法签名、注入分类器调用点(c5 S1 卡:4 写入口)

- [ ] 要点:`MemorySearchTool(memory)`:scope 路由 archival→`archival_memory_search` / recall→recall 检索 / graph→traverse(query=实体名);`MemoryWriteTool(memory, classifier)`:action 路由三写;条件必填校验(core_replace 须 old_content、archival_insert 须 evidence_quote 且逐字在本 turn user 消息中——校验函数收 `state.messages`);分类器在 dispatch 前过(拒绝→ToolResult(success=False, error=分类器理由));与 Tool ABC(`backend/app/tools/base.py`)对齐使其可注册。Commit: `feat(chatloop): 记忆六件套合并为 search/write 双工具 + 注入分类器单入口收口`

### Task 3.4: 技能双工具 + offer_deep_research + read_cached_result

**Files:**
- Create: `backend/app/chatloop/skill_tools.py`、`backend/app/chatloop/control_tools.py`
- Test: `backend/tests/unit/chatloop/test_skill_tools.py`、`test_control_tools.py`
- 先读:SkillLoader/SkillExecutor 公开接口、技能清单(7 个 L1 元数据)

- [ ] 要点:
  - `load_skill(name, resource=None)`:resource 空→SKILL.md 全文 + 资源清单;非空→单资源(校验一级深:resource 必须在该技能资源清单内);成功后置 `state.active_skill = name`(经 dispatch 返回的 side-channel——ToolHub.dispatch 收 state 可变引用,文档化);
  - `run_skill_script`:包 SkillExecutor;结果结构化 `{stdout, stderr, return_code}` + 错误码(timeout/output_too_large);stdout > 800 token 等价字符 → 写 ToolResultCache 回摘要+键;
  - `offer_deep_research(reason)`:幂等(state.escalate_offered 已 True → success=False"已提议过");置 escalate_offered/reason + emit escalate_request + 返回 spec § 3.5 文案;**dispatch 后 ToolHub 把 state.tool_choice 置 "none"**;
  - `read_cached_result(ref, offset=0, limit=2000)`:校验 ref 的 user 前缀 == state.user_id;从 ToolResultCache 读原文切片。
  - 技能 L1 清单生成函数 `build_skill_listing(loader) -> str`(进稳定前缀;描述含触发判据,逐技能审一遍现有 description 是否含"何时用",缺则补)。
  - Commit: `feat(chatloop): 技能装载/脚本/升级信号/缓存取回四工具`

---

## Phase 4:传输替换(切换点)

### Task 4.1: chat_session_context 表 + rebuild_context + 跨 turn 压缩

**Files:**
- Modify: `backend/app/models/chat.py`(新增 ChatSessionContext ORM:session_id PK/FK、history_summary Text、summarized_upto UUID nullable、updated_at;create_all 幂等建表)
- Create: `backend/app/chatloop/rebuild.py`
- Test: `backend/tests/integration/test_rebuild_context.py`(真 PG,db_session fixture)

- [ ] 要点:`rebuild_context(session_id, repo, llm) -> list[dict]`:读 summary 行 + 最近 4 turn 的 user/assistant 消息(只取 role/content,assistant 取终答)→ 估算 token 超 70% 配额(配额常量 24_000 沿用现状)→ 用现有 `InSessionMemory.summarize` 的 prompt 风格做 LLM 总结(经 `llm.chat` 旧接口,fast tier)+ 结构化模板(spec § 2.3:意图/关键事实/定量数字带口径/错误/未决/下一步)→ 写回表推水位;幂等(summarized_upto 之前的消息不再参与)。L1 测试:造 6 turn 历史,断言窗口含摘要+最近 4 turn;水位推进;二次调用不重复总结(LLM spy 调用次数)。
- [ ] Commit: `feat(chatloop): chat_session_context 表与跨 turn 历史重建/压缩`

### Task 4.2: chat_runner 换引擎 + 新 SSE 适配

**Files:**
- Modify: `backend/app/tasks/chat_runner.py`(run_chat_async 主体)
- Test: `backend/tests/integration/test_chat_runner_loop.py`(eager 模式 + ScriptedStepClient + 真 PG/假 Redis spy)
- 先读:chat_runner.py 全文(单例区/cancel listener/finalize/TTL 框架**保留**)

- [ ] 要点:
  - `_build_chat_graph_for_worker` 换成 `_build_tool_loop_for_worker`:构建 LLMService(stream_step capable)、ToolHub(MCP chat_tools 子进程 + in-process 四类)、ContextDeps(persona 经现有 populate 函数、skill listing、system prompt 常量);
  - 主体:`state = ChatLoopState(messages=await rebuild_context(...) + [user msg])` → `final = await loop.run(state)`;emitter 直接 XADD LoopEvent(`_adapt_event_for_stream` 删除——事件已是最终形态;保留双字段 text/content 兼容);
  - steer:`SteerSource`(Redis List RPOP,Task 4.3 的 List 名);cancel:现有 listener 置 event,loop 内检查(已在 Task 2.4 实现),捕获 `CancelledByUser` → partial commit(沿用 mark_partial,**不再取 checkpoint_id**);
  - finalize:`final.final_response` 直接给 `finalize_task_persistence`;escalation 后处理:`escalate_offered` → EscalationExtractor(history=从 final.messages 拼文本,cached_tool_results=ledger.to_extractor_view())→ create_draft → XADD escalate_packet_draft(读现有 chat.py 中这段逻辑搬来,保持事件 payload 形状不变);
  - direct_response token 补发 hack 删除。
- [ ] L1 测试剧本:单工具 turn 端到端(消息落库/事件序列断言/task done);取消(partial 落库);升级(packet_draft 事件)。
- [ ] Commit: `feat(chatloop): chat_runner 换 ToolLoop 引擎 — 事件直发/checkpoint 退役`

### Task 4.3: steer 端点 + retry 改造

**Files:**
- Modify: `backend/app/router/chat.py`(新增 `POST /api/v0/chat/steer/{task_id}`;改 retry)
- Create: `backend/app/services/chat_steer_bus.py`(Redis List:`chat:steer:{tid}`,LPUSH/RPOP-all,TTL 1h)
- Test: `backend/tests/integration/test_steer_and_retry.py`

- [ ] 要点:steer 端点按 spec § 4.3:① ChatSessionRepo.append_message(role=user, task_id 关联)② LPUSH ③ task 已终态 → 返回 `{merged: false}`(前端转新 turn);retry:删 checkpoint 守卫;输入改为"该 turn 的 user 消息 + 关联到该 task 的全部 steer user 消息"(查 chat_messages);历史取到上一 turn(partial 不进)。差分测试三条(spec § 5.2):取消 partial 仅展示 / 重试含插话 / steer 竞态转新 turn。
- [ ] Commit: `feat(chat): steering 插话端点 + 重试 turn 原子化`

---

## Phase 5:前端适配

### Task 5.1: 事件协议 + 渲染

**Files:**
- Modify: `frontend/src/types/chat.ts`(删 PlanEvent;加 StepStart/ToolCall/ToolError/SteerMerged/LoopHalt 事件类型)
- Modify: `frontend/src/store/current-chat.ts`(dispatchEvent 分支)
- Modify: `frontend/src/components/chat/MessageList.tsx` 周边(ToolCallCard cached/error 样式)、`StreamingIndicator.tsx`(phase 由事件类型推导)
- Test: 现有前端测试框架下补 dispatchEvent 单测(若无测试框架则 `pnpm build` + tsc 过编译为门槛)

- [ ] 要点按 spec § 5.1;`loop_halt` 渲染提示条("已达 N 步上限,以下基于已查信息");`steer_merged` 渲染系统提示气泡。Commit: `feat(frontend): chatloop 新事件协议渲染`

### Task 5.2: steer 交互

**Files:**
- Modify: `frontend/src/api/chatApi.ts`(`steerChatTask(taskId, message)`)
- Modify: `frontend/src/components/chat/InputArea.tsx` + `frontend/src/hooks/useChatSSE.ts`(streaming 中发送 → steer;`{merged:false}` 回退为普通发送;长按/菜单"排队为新消息"可后置,本期只做默认 steer)

- [ ] Commit: `feat(frontend): streaming 中发送即插话(steering)`

---

## Phase 6:评测收束

### Task 6.1: SUT 适配 + golden 迁移

**Files:**
- Modify: `backend/app/services/eval_runner.py` 相关 ChatAgent SUT(tool_calls 从 final.ledger 抽,替代 plan.tool_calls)
- Modify: `backend/tests/integration/test_eval_runner_chat_agent_sut.py`
- 迁移 `backend/tests/fixtures/eval/golden_set_v0.jsonl` 三条 case 的跑法(行为应不变)

- [ ] Commit: `feat(eval): SUT 适配 ToolLoop — tool_calls 取自台账`

### Task 6.2: 工具选择 + 技能触发离线评测

**Files:**
- Create: `backend/eval/tool_selection/golden.jsonl`(≥20 条:8 金融工具各 1-2 正例 + memory/kb 互斥对 4 条 + offer_deep_research 正反各 3 条(轻问题不该升级)+ 延迟工具该搜先搜 2 条 + near-miss 负例)
- Create: `backend/eval/tool_selection/eval_runner.py`(AST 式比对:工具名 + 关键参数;RelAcc/IrrelAcc 双指标 + 按簇分桶;复用 ScriptedStepClient 之外的真 LLM 跑法,标注成本)
- Create: `backend/eval/skill_trigger/golden.jsonl`(每技能 ≥3 条,含共享关键词负例)

- [ ] Commit: `feat(eval): 工具选择/技能触发离线评测与金标准`

### Task 6.3: cassette 重录(live LLM)

- [ ] 重录三条主路径 cassette(单工具/多跳/升级)——沿用 `backend/tests/e2e/` 现有 VCR 配置与 header 过滤;老的 chat 图 cassette 删除。运行需 live key,在 WSL 带 .env 跑录制。Commit: `test(e2e): chatloop 主路径 cassette 重录`

---

## Phase 7:退役清理

### Task 7.1: 删老图 + 全量回归

**Files:**
- Delete: `backend/app/orchestration/chat_graph.py`、`backend/app/orchestration/context_node.py`、`backend/app/orchestration/memory_kb_router_node.py`
- Modify: `backend/app/orchestration/nodes.py`(删 planner_node/responder_node/tool_node;research 用的保留——先 grep 引用确认)
- Modify: `backend/app/agents/chat_planner.py`(删 run 与 chat 模板;留 step())、`backend/app/agents/responder.py`(同)、`backend/app/agents/schemas.py`(Plan 的 chat 专用字段:load_skill/load_resource/script_calls/direct_response 等——先 grep research 侧引用,共用则留)
- Modify: `backend/app/router/chat.py`(inline SSE 老路径段)

- [ ] 删除后全量:`python -m pytest backend/tests -q`(预期与 main 基线同绿;基线失败清单先记录再对比)+ mypy + ruff。Commit: `refactor(chat): 老 supervisor 图退役`

### Task 7.2: 知识卡沉淀

- [ ] Create: `docs/claude-context/chat-loop-redesign-done.md`(三段式:结论/Why/How to apply)+ CLAUDE.md 索引行。Commit: `docs: chat loop 重设计总卡`

---

## 收尾:浏览器端到端联调(由主会话执行,不进 plan 任务)

启动后端(WSL)+ Celery worker + 前端 dev server,浏览器逐项验:单工具问答流式 / 多跳(持仓比较)/ 步数进度 / 工具卡片(含 cached)/ 插话改向 / 取消与重试 / 升级确认流全链路 / loop_halt 提示。全部符合预期后提 PR(base: main,branch: feat/chat-loop-redesign)。

## Self-Review 记录

- Spec 覆盖:§1→Task 2.1-2.4;§2→1.1-1.2/2.3/4.1;§3→3.1-3.4;§4→4.1-4.3;§5→5.1-5.2/6.x/7.x;风险表的降级路径在 Task 0.1 Step 3 与 1.2 Step 3 落点。✓
- 类型一致:StepResult/StepToolCall/ChatLoopState/LedgerEntry 各 Task 引用一致;tool_choice 字段贯穿 2.1→2.4→3.4→4.2。✓
- 无 TBD/TODO;每个代码步给了代码或精确骨架 + 先读清单。✓

# v0 Chat Agent Skeleton 设计稿

| 字段 | 值 |
|---|---|
| 起草日期 | 2026-05-01 |
| 起草上下文 | brainstorming session a4ce0864(2026-04-29) + dev-test-loop spec(2026-04-29)落地完毕(Plans A→D)|
| 后续依赖此 spec 的 | v0.5 research-mode spec(紧接)+ v1+ Memory 子系统 / 多 model tier / KB+Web 搜索接入 |
| 实施周期估算 | 3-5 小时(plan 拆 12-15 task,subagent-driven 节奏)|
| 决策复盘截止 | plan 完成后填 retrospective |

---

## 0. 文档定位

### 为什么独立成 spec(而非内嵌 dev-test-loop 后半)

dev-test-loop spec(2026-04-29)已经把"测试基础设施 + cost / trace / drift"立完(Plans A→D 4 PR 全部 merged)。**v0 chat agent skeleton 是这套基础设施的第一个真业务 SUT** —— Plan C 的 EvalRunner 现在跑的是 bare `LLMService`(没有 agent),v0 落地后把 SUT swap 成 `ChatAgent`,eval pipeline 才有真意义。

独立成 spec 的理由:
- **业务边界清晰** —— dev-test-loop 是横切 infra,v0 chat agent 是纵切业务,两者按 layer 分开比 inline 合并更可讲。
- **复用经济性** —— v0 之后立刻起 v0.5 research-mode spec(用户决议 B 路径),两者共享 v0 spec 立的 LangGraph 图骨架 / Typed Actor 契约 / ToolRegistry 接入,share 越多 v0.5 越薄。
- **Eval pipeline 真接入** —— Plan C 的 SUT swap 是 v0 spec 的 acceptance criteria 之一,跨 spec 联动需要明确边界。

### 在 roadmap 中的位置

```
2026-04-29 brainstorming (架构方案 C / 7 agent / 双模式 / 4 横切服务)
  ├─ dev-test-loop spec [DONE 2026-04-30] (Plans A→D)
  ├─ v0 chat agent skeleton spec [本 spec, 2026-05-01]   ← 现在这里
  │     └─ v0 plan [next]
  ├─ v0.5 research-mode spec [紧接 v0]
  │     └─ v0.5 plan [next-next]
  └─ v1+ specs (Memory 深做 / multi-model tier / KB+Web 搜索接入)
```

### Scope

**v0 包括**:
- LangGraph 状态图(planner → tool → responder),SQLite checkpointer
- 2 个 typed actor agent:`ChatPlanner` / `Responder`(`base.py:Agent` 抽象类含 DispatchSubAgent 接口占位但 v0 不真用)
- 3 个 tool 接入 ToolRegistry:`get_stock_quote` / `get_financials` / `get_news`(数据源 v0 全用 mock_tushare,真 Tushare v1 接入)
- HTTP `POST /api/v0/chat`,SSE 流式响应
- Plan B/C/D 横切服务全接入:`LLMService`(含 trace + cost_budget DI)、`TraceService`、`CostBudget`
- Plan C `EvalRunner` SUT 从 `LLMService` swap 到 `ChatAgent`
- Old code 删除:`chat_service.py` / `chat_service_v2.py` / `mcp_chat_service.py` / `react_controller.py` / `smart_analyzer.py` / `dr_g.py` / `mcp_server/` / `mcp_client/`(spec § 11 archive list)

**v0 不包括**(留 v0.5+ 或 v1+):
- 研报模式(A)的 ResearchPlanner / Analyst / Writer / Critic(留 v0.5)
- DispatchSubAgent 真用例(留 v0.5,Critic 多维度评分场景)
- Memory 的 Semantic / CrossUserCache / Eval 子模块(留 v1)
- KB / Web 搜索的 agent 接入(产品页面保留,但 ChatPlanner v0 不调)
- Multi-model tier 切换(留 v1,Plan B `TierRouter` 接口已就位)
- 真 Tushare API 接入(留 v1,v0 用 mock)

---

## 1. 现状摸底

### dev-test-loop 已建好的依赖盘点

v0 实施时,以下已就位,**直接复用,不重建**:

| 来自 | 提供的 | v0 怎么用 |
|---|---|---|
| Plan B `app/services/llm_service.py` | `LLMService(client, tier_router=None, trace_service=None, cost_budget=None)` + `chat(prompt, tier, schema, request_id, parent_span_id)` | ChatPlanner / Responder 通过 LLMService 调 LLM,**不 import openai** |
| Plan B `app/services/llm_response.py` | `LLMResponse` Pydantic 契约 | agent I/O 之间的标准 LLM 返回壳 |
| Plan B `app/services/tier_router.py` | `TierRouter` v0 全 v4-flash | ChatPlanner 用 `tier="balanced"` Responder 用 `tier="fast"` |
| Plan B `app/services/llm_mock_client.py` | `MockLLMClient` MC1+MC2+MC4 | L1 测试注入 mock LLM |
| Plan B `tests/fixtures/cassettes/` | pytest-recording cassette + sanitize hook | L2 测试录 ChatAgent 真打 |
| Plan C `app/services/trace_service.py` | `TraceService(db_path).get_trace / write_span` | LangGraph 节点 trace + agent step trace 落 SQLite |
| Plan C `app/services/eval_*.py` | `EvalRunner(sut, judge, ...)` | Plan C SUT swap:bare LLMService → ChatAgent |
| Plan D `app/services/pricing.py` | `compute_cost(model, in, out)` | LLMService 内部已用,agent 不直接调 |
| Plan D `app/services/cost_budget.py` | `CostBudget(limit_cny)` | nightly 跑 ChatAgent 时注入,fail-fast |

### 既有遗留代码盘点(待删)

| 文件 | LOC | 处置 |
|---|---|---|
| `backend/app/service/chat_service.py` | ~? | **删除** |
| `backend/app/service/chat_service_v2.py` | ~? | **删除** |
| `backend/app/service/mcp_chat_service.py` | ~? | **删除** |
| `backend/app/service/react_controller.py` | ~? | **删除** |
| `backend/app/service/smart_analyzer.py` | ~? | **删除** |
| `backend/app/service/dr_g.py` | ~? | **删除** |
| `backend/app/service/deep_research_v2/` | ~? | **暂保留**(v0.5 spec 决定如何接入,不在 v0 范围)|
| `backend/app/mcp_server/` | ~? | **删除整目录** |
| `backend/app/mcp_client/` | ~? | **删除整目录** |
| `backend/app/router/chat_router.py` | ~? | **删除**(替换为新 `app/router/chat.py`)|
| `backend/app/service/mock_bocha_service.py` | ~? | **保留**(KB / Web 搜索的 mock 数据源,虽然 v0 不接入但产品页面用)|
| `backend/app/service/mock_tushare_service.py` | ~110 KB | **保留 + 改造**(v0 工具的数据源,见决策三)|

> **Note**: 具体 LOC 数字在 plan 阶段 grep 填充;此处只标决议。**保守估算被删的 7 个文件 + 2 个目录共 ~3-5k LOC,这是 portfolio 上"瘦身"的故事点**。

---

## 2. 决策一:LangGraph 图形态

### ① 问题陈述

v0 ChatAgent 的执行流程是"plan → tool calls → respond"。**用什么 orchestration 形态**?直接 typed actor 顺序调?LangGraph 状态图?还是 LCEL(LangChain Expression Language)?这决定了:
- checkpointer 能不能用(LangGraph 自带,纯 actor 要自建)
- streaming 形态(LangGraph stream API vs FastAPI 直接 yield)
- 跨 session resume(graph state 是否持久)
- 代码"工程感"(LangGraph 是行业 portfolio 信号)

### ② 业界 alternatives

| 编号 | 形态 | 代表 |
|---|---|---|
| O1. Pure typed actor(顺序调用)| 自建 `Pipeline.run(state)` |
| O2. LangChain LCEL(`Runnable | Runnable`)| `chain = prompt | llm | parser` |
| **O3. LangGraph 状态图**(选)| `StateGraph(GraphState).add_node().add_edge()` |
| O4. 自建状态机框架 | 重复造轮子 |

### ③ 选择:**O3 LangGraph 状态图 + SQLite checkpointer**

**节点**:
- `planner_node`:调 `ChatPlanner.plan(state)` → 返回 `Plan(tool_calls=[...])` 或 `Plan(tool_calls=[], direct_response=True)`(无需工具的简单问题直接回答)
- `tool_node`:批量执行 `tool_calls`,返回 `tool_results: list[ToolResult]` 写回 state
- `responder_node`:调 `Responder.respond(state)` → 流式产出最终 response(LangGraph stream API 沿边发出 chunks)

**边**:
```
START → planner_node
planner_node → tool_node     [if state.plan.tool_calls]
planner_node → responder_node [if state.plan.direct_response]
tool_node → responder_node
responder_node → END
```

**checkpointer**:`SqliteSaver(conn=sqlite3.connect("backend/data/chat.sqlite"))`
- **不与 Plan C eval.sqlite 共用**(checkpoint 是高频写,eval 是只读,分文件避免 lock 竞争)
- 路径在 `.gitignore` 已覆盖 `backend/data/`(Plan C 加的)
- thread_id = `f"{user_id}:{session_id}"`(跨用户隔离 + 跨 session 区分,Auth 决议保留 user_id)

**stream 形态**:LangGraph 的 `astream_events(config={"configurable": {"thread_id": ...}})` API 提供 fine-grained event stream(node-start / node-end / llm-token);`responder_node` 内部用 `LLMService` 的 streaming 模式(待 v0 在 LLMService 加 `chat_stream` 方法)。

### ④ 量化评估方案

- **图复杂度**: v0 共 3 节点 + 4 边(START / END 不计),手画一图能讲透
- **Checkpoint 写入开销**: planner_node 完成 + tool_node 完成 + responder_node 完成 = 每个 chat 请求 3 次 sqlite write,目标 ≤ 50ms 总计
- **Resume 正确性**:从 checkpoint 恢复后,继续跑剩余节点,最终 LLMResponse 与不中断版本一致(L2 测试覆盖)
- **跨 session 隔离**: 同 user_id 的两个 session_id thread 互不污染(L1 测试)
- **Streaming P50 latency**: 第一个 token 到达 ≤ 800ms(real LLM,不含网络)

### ⑤ 风险与未解问题

- **LangGraph 版本锁定**: v0 用 `langgraph>=0.2`(已在 pyproject deps),lock 到 0.2.x;0.3 升级风险评估留 v1
- **SqliteSaver 并发**: 单进程 + WAL mode 应该 OK,多进程并发 v0 不考虑(单 uvicorn worker 起步)
- **LangGraph 学习曲线**: implementer 第一次用 LangGraph,plan 阶段嵌一个 30s spike 让 implementer 在 worktree 跑通最小 hello world,验证 import / syntax / SqliteSaver 语义

---

## 3. 决策二:Agent I/O 契约

### ① 问题陈述

`ChatPlanner.plan` 输入什么、输出什么?`Responder.respond` 输入什么、输出什么?**契约稳定性是 v0~v3 的承诺**(`project_llm_service_contract` memory 强调过 LLMService 那一层,agent 这一层同样适用)。schema 一旦定下,v0.5 + v1+ 增加新字段是 additive,改/删字段 = 破坏。

### ② 业界 alternatives

| 编号 | I/O 形态 | 代表 |
|---|---|---|
| AC1. dict 输入输出 | LangChain `dict[str, Any]`,弱类型 |
| **AC2. Pydantic v2 BaseModel + frozen=True**(选)| 跟 Plan B/C/D 横切服务一致 |
| AC3. dataclass | 简单但无 JSON schema 自动生成 |
| AC4. TypedDict | mypy 友好但 runtime 无验证 |

### ③ 选择:**AC2 Pydantic v2 frozen,strict I/O**

**`GraphState`**(LangGraph 状态,跨节点传递):

```python
class GraphState(BaseModel):
    model_config = ConfigDict(frozen=False)  # LangGraph 需要 mutable

    # 入参(来自 HTTP)
    user_id: str
    session_id: str
    user_message: str
    enable_web_search: bool = False  # v0 占位,不真用
    enable_kb_search: bool = False   # v0 占位,不真用

    # planner 输出
    plan: Plan | None = None

    # tool 输出
    tool_results: list[ToolResult] = Field(default_factory=list)

    # responder 输出
    final_response: str | None = None
    final_response_streamed: bool = False  # 用于 stream 路径标记

    # trace + budget(横切)
    request_id: str  # 全 graph run 共享一个 request_id,所有 LLM/tool span 挂在它下
    span_stack: list[str] = Field(default_factory=list)  # 当前调用栈的 span_id
```

**`Plan`**(ChatPlanner 输出):

```python
class Plan(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool_calls: list[ToolCall]  # 空列表 = 直接回答
    direct_response: bool       # True 时 tool_calls 必须为空,planner 已可直接答(简单问题/打招呼)
    reasoning: str              # 1-2 句 plan 思路,记入 trace span 用于 debug

    @model_validator(mode="after")
    def _check_consistency(self) -> "Plan":
        if self.direct_response and self.tool_calls:
            raise ValueError("direct_response=True 时 tool_calls 必须为空")
        if not self.direct_response and not self.tool_calls:
            raise ValueError("direct_response=False 时 tool_calls 至少有 1 个")
        return self
```

**`ToolCall`**:

```python
class ToolCall(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool_name: str          # 例如 "get_stock_quote"
    args: dict[str, Any]    # 例如 {"ts_code": "600519.SH"}
    rationale: str          # 1 句话:为什么这个 tool / 这个参数
```

**`ToolResult`**:

```python
class ToolResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool_name: str
    args: dict[str, Any]
    success: bool
    output: dict[str, Any] | None = None  # 成功时有 payload
    error: str | None = None              # 失败时有 message
    latency_ms: int
```

**`Agent` 抽象基类**(`backend/app/agents/base.py`):

```python
class Agent(ABC):
    """Stateless typed actor — 任何 agent 必须 strict Pydantic I/O,不持有 state。
    
    v0: ChatPlanner / Responder
    v0.5+: ResearchPlanner / Analyst / Writer / Critic / DataCollector
    
    DispatchSubAgent 接口在 base 里占位,v0 不真用(无场景),
    v0.5 Critic 多维度并行评分时启用。
    """

    name: str
    model_tier: Tier  # 静态声明,LLMService 自动 route

    def __init__(self, llm: LLMService) -> None:
        self._llm = llm

    @abstractmethod
    def step(self, state: GraphState) -> StepResult:
        """每个 agent 的入口。子类约束输入 schema(state 的某些字段必须有值),
        输出新的 state 字段(返回 StepResult.state_update,LangGraph 节点合并)。
        """
        ...
```

**`StepResult`**:

```python
class StepResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    state_update: dict[str, Any]  # 字段名 → 新值,LangGraph 自动 merge 到 state
    span_metadata: dict[str, Any]  # agent 自己想记入 trace span 的 metadata
```

### ④ 量化评估方案

- **Schema 稳定性**: `Plan` / `ToolCall` / `ToolResult` / `GraphState` 各字段在 v0~v3 不删除/不改名
- **Pydantic 验证开销**: 单次 `Plan.model_validate(...)` ≤ 1ms(L0 测试)
- **mypy strict 覆盖**: `app.agents.*` 加入 strict tier(`disallow_untyped_defs=true`,跟 `app.services.*` 同级别)
- **JSON schema 自动生成**: 用 `Plan.model_json_schema()` 喂给 LLM 做 structured output(v0 用 OpenAI tool-calling 格式)

---

## 4. 决策三:工具集 + ToolRegistry

### ① 问题陈述

v0 接入 3 个工具(`get_stock_quote` / `get_financials` / `get_news`),**怎么注册、怎么分发、谁负责数据源**?这决定:
- ChatPlanner 看到的工具 schema(给 LLM 的 system prompt 包含工具列表)
- 工具执行时的错误处理(网络失败 / 参数错误)
- 工具计费 / 限速(横切关注点)
- 数据源切换(mock vs real)

### ② 业界 alternatives

| 编号 | 注册形态 | 代表 |
|---|---|---|
| TR1. import 直接调 | agent 里 `from tools import get_stock_quote; get_stock_quote(...)` |
| TR2. 装饰器注册 | `@tool def get_stock_quote(...): ...`(LangChain `@tool`)|
| **TR3. 显式 ToolRegistry**(选)| `ToolRegistry.register(StockQuoteTool())`,agent 通过 `registry.get(name).run(args)` |
| TR4. MCP server 暴露 | brainstorming 决议降级为 v1 对外导出 |

### ③ 选择:**TR3 显式 ToolRegistry**

**`Tool` 抽象基类**(`backend/app/tools/base.py`):

```python
class Tool(ABC):
    name: str
    description: str  # 给 LLM 的 system prompt 用,1-2 行说明用途
    args_schema: type[BaseModel]  # 输入参数 Pydantic schema

    @abstractmethod
    async def run(self, args: BaseModel) -> dict[str, Any]:
        """执行工具。args 是已经过 Pydantic 验证的实例。返回 dict 写入 ToolResult.output。
        异常:抛出 ToolError(message),由 ToolRegistry catch 并转为 ToolResult(success=False)。
        """
        ...

    def schema_for_llm(self) -> dict[str, Any]:
        """生成 OpenAI tool-calling 格式的 schema(给 ChatPlanner 用)。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args_schema.model_json_schema(),
            },
        }
```

**`ToolRegistry`**(`backend/app/tools/registry.py`):

```python
class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise ToolNotFoundError(name)
        return self._tools[name]

    def list_for_llm(self) -> list[dict[str, Any]]:
        """生成给 ChatPlanner 用的工具列表(OpenAI tool-calling 格式)。"""
        return [tool.schema_for_llm() for tool in self._tools.values()]

    async def execute(self, call: ToolCall) -> ToolResult:
        """统一执行入口:验证 args + 调 run + 包 ToolResult + 计时。"""
        ...
```

**3 个 v0 工具**:

```python
# backend/app/tools/get_stock_quote.py
class StockQuoteArgs(BaseModel):
    ts_code: str  # 例如 "600519.SH"

class StockQuoteTool(Tool):
    name = "get_stock_quote"
    description = "获取 A 股股票的当前行情(价格、涨跌、成交量)"
    args_schema = StockQuoteArgs

    async def run(self, args: StockQuoteArgs) -> dict[str, Any]:
        # v0 用 mock_tushare;v1 切到真 Tushare
        ...
```

```python
# backend/app/tools/get_financials.py
class FinancialsArgs(BaseModel):
    ts_code: str
    period: Literal["latest", "quarterly", "annual"]

class GetFinancialsTool(Tool):
    name = "get_financials"
    description = "获取公司财务数据(营收、利润、ROE、PE 等关键指标)"
    args_schema = FinancialsArgs
    # ...
```

```python
# backend/app/tools/get_news.py
class NewsArgs(BaseModel):
    ts_code: str | None = None  # 不指定时返回大盘资讯
    n: int = 5
    days_back: int = 7

class GetNewsTool(Tool):
    name = "get_news"
    description = "获取最近的财经资讯(可指定股票或大盘)"
    args_schema = NewsArgs
    # ...
```

**数据源**:
- v0 全部接 `app/service/mock_tushare_service.py`(brainstorming `feedback_scope_decisions` 提到保留作为 LLM-driven mock 资产)
- mock_tushare 本身用 LLM 生成数据(spec 决策三 `MC3. LLM-as-mock`,Plan B 沉淀)
- **真 Tushare API 接入留 v1**(改 1 行 import + adapter)

### ④ 量化评估方案

- **工具注册 LOC**: 每个工具 ~50 行(args schema + run + 错误处理),3 工具共 ~150 行
- **Plan→Tool 映射正确率**: ChatPlanner 在 mock LLM 下,3 个工具的 70% prompt 路由正确(L1 测试)
- **真 LLM 路由率**: deepseek-v4-flash 真打,30 个 chat-style golden case 中工具选择正确率 ≥ 85%(nightly eval)
- **工具执行 P50 latency**: mock 数据源 ≤ 500ms / call(LLM-driven mock 是慢路径,但是固定一次性)
- **工具失败处理**: tool_node 捕获 `ToolError`,写 `ToolResult(success=False)` 到 state,Responder 看到失败仍可生成"工具调用失败"回应(L1 测试)

---

## 5. 决策四:HTTP / Streaming 形态

### ① 问题陈述

`POST /api/v0/chat` 怎么把 LangGraph 的 stream events 流给前端?**SSE / WebSocket / polling**?事件颗粒度多粗?响应中是否包含 trace 信息?

### ② 业界 alternatives

| 编号 | 形态 | 代表 |
|---|---|---|
| **HS1. SSE(`text/event-stream`)**(选)| ChatGPT / Claude UI 主流 |
| HS2. WebSocket | 双向但 v0 不需要 server→client only |
| HS3. polling + chunks | 不流式,体验差 |

### ③ 选择:**HS1 SSE,事件粒度 = LangGraph node-level + LLM-token-level**

**Endpoint**:

```python
# backend/app/router/chat.py
@router.post("/api/v0/chat")
async def chat(req: ChatRequest, user: User = Depends(get_current_user)) -> StreamingResponse:
    return StreamingResponse(
        _stream_chat(req, user),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

**Request schema**:

```python
class ChatRequest(BaseModel):
    session_id: str  # 客户端生成 UUID,跨轮对话标识
    message: str
    enable_web_search: bool = False  # v0 占位
    enable_kb_search: bool = False   # v0 占位
```

**Stream event types**(每事件一行 `data: <json>\n\n`):

```python
class StreamEvent(BaseModel):
    type: Literal["plan", "tool_start", "tool_end", "token", "done", "error"]
    data: dict[str, Any]

# 实际事件示例:
# data: {"type": "plan", "data": {"tool_calls": [...], "reasoning": "..."}}
# data: {"type": "tool_start", "data": {"tool_name": "get_stock_quote", "args": {...}}}
# data: {"type": "tool_end", "data": {"tool_name": "get_stock_quote", "success": true, "latency_ms": 320}}
# data: {"type": "token", "data": {"text": "茅台"}}
# data: {"type": "token", "data": {"text": "(600519.SH)"}}
# ...
# data: {"type": "done", "data": {"request_id": "req-abc12345", "total_cost_cny": 0.0006, "total_latency_ms": 2340}}
```

**LangGraph stream → SSE 适配**:

```python
async def _stream_chat(req: ChatRequest, user: User) -> AsyncIterator[str]:
    request_id = f"req-{uuid4().hex[:12]}"
    initial_state = GraphState(
        user_id=user.id,
        session_id=req.session_id,
        user_message=req.message,
        request_id=request_id,
    )
    config = {"configurable": {"thread_id": f"{user.id}:{req.session_id}"}}
    
    async for event in chat_graph.astream_events(initial_state, config=config, version="v2"):
        sse_event = _adapt_langgraph_event(event)
        if sse_event is not None:
            yield f"data: {sse_event.model_dump_json()}\n\n"
```

`_adapt_langgraph_event` 是适配函数,把 LangGraph 的 `on_chain_start` / `on_chain_end` / `on_chat_model_stream` 等内部事件翻译成 v0 自定义的 6 种 `StreamEvent.type`。

### ④ 量化评估方案

- **事件粒度**: 每个 chat 请求约 ~30-100 个 SSE 事件(plan 1 + tools 2-6 + tokens ~50-100 + done 1)
- **首 token latency P50**: ≤ 800ms(planner_node + LLMService 调用 + 第一个 token 到达)
- **首 token latency P95**: ≤ 2000ms
- **事件 framing 正确率**: 每个事件单行 + `\n\n` 分隔,前端 EventSource API 100% 正确解析(L2 测试 + cassette)
- **不正常情况 framing**: error 事件结构与正常事件一致,客户端不需要特殊处理(L1 测试)

### ⑤ 已知风险

- **uvicorn buffering**: 部分代理服务器(nginx 默认配置)会 buffer SSE。v0 加 `X-Accel-Buffering: no` 头,生产环境 deploy 时需要 nginx/反向代理也禁 buffer。**v0 spec 不解决 deploy 问题,只保证本地 + GH Actions 跑通**。
- **断线重连**: 客户端断开后,LangGraph checkpointer 已写到中间状态,理论上下次请求带相同 thread_id 可 resume。**v0 不实现 client 端自动 resume**(只是 checkpoint 已记录),前端体验留 v1。

---

## 6. 决策五:Memory v0 范围

### ① 问题陈述

brainstorming 列了 4 个 Memory 子模块:Semantic / Checkpoint / CrossUserCache / Eval。v0 接入哪几个?Memory 接口是否独立成 `MemoryService`?

### ② 业界 alternatives

| 编号 | 范围 | 代价 |
|---|---|---|
| M1. 全 4 子模块 | 范围爆炸,Semantic + CrossUserCache 各自需要 embedding + retrieval 设计 |
| **M2. 仅 Checkpoint(LangGraph SqliteSaver)**(选)| 最薄,但 Memory 子系统的故事载体已立 |
| M3. Checkpoint + 简单 Semantic(对话总结)| 多写一段总结逻辑 |
| M4. 不接 Memory | LangGraph state 内存就丢,跨 session 完全无记忆 |

### ③ 选择:**M2 仅 LangGraph Checkpointer(SQLite)**

**接入点**:LangGraph `StateGraph.compile(checkpointer=SqliteSaver(conn))`,`thread_id = f"{user_id}:{session_id}"`。

**v0 不建独立 `MemoryService` 类** —— Checkpointer 已经是 LangGraph 原生概念,再包一层只会增加间接。**v1 Semantic / CrossUserCache 接入时再建 `MemoryService`**(那时它会是真聚合层,负责 Semantic 的 embedding lookup + Checkpoint 的 wrapper + CrossUserCache 的 LRU)。

**chat history**:由 LangGraph state 自带(`GraphState.user_message` 是当前轮,LangGraph 跨轮 thread 保持)。**v0 不主动总结对话历史**,直接把所有历史 message 塞 ChatPlanner 的 prompt(token 上限到时再切),Semantic 总结留 v1。

### ④ 量化评估方案

- **Checkpoint resume 正确性**: 同 thread_id 第二次请求,LangGraph 自动从最后一个 checkpoint 续(L2 测试覆盖)
- **跨用户隔离**: thread_id 含 `user_id:session_id`,SqliteSaver 按 thread_id 分隔(L1 测试 100% 隔离)
- **Storage 增长**: 单 chat 请求 3 checkpoint write × ~2KB ≈ 6KB / 请求;100 用户 × 10 session × 5 轮 = 5000 请求 ≈ 30MB,可接受
- **接口稳定**: v1 升 MemoryService 时,LangGraph checkpointer 接口不变(仍然在 graph.compile 里注入),业务代码无感

### ⑤ 风险

- **chat history token 爆炸**: 用户聊 50 轮后 ChatPlanner prompt 可能超长。v0 不解决,**plan 阶段加一个 hard limit** `MAX_HISTORY_MESSAGES=20`(超过 truncate 最旧的)。Semantic 总结(v1)会优雅处理。

---

## 7. 决策六:Eval Pipeline 接入(SUT swap)

### ① 问题陈述

Plan C `EvalRunner` 当前 SUT 是 bare `LLMService`(用例 prompt → LLMService.chat → judge)。v0 完成后,**SUT 必须 swap 成 ChatAgent**(用例 prompt → ChatAgent 跑全图 → 取 final_response → judge)。这涉及:
- `EvalRunner.__init__(sut: LLMService, ...)` 的 sut 类型如何泛化?
- ChatAgent 的"输入 prompt → 输出 response_text"接口怎么定?
- trace 怎么从 LangGraph state 写到 TraceService?(graph_node 级 + LLM_call 级 双层 span)

### ② 业界 alternatives

| 编号 | SUT 抽象 | 代价 |
|---|---|---|
| SU1. 改 `EvalRunner` 加 ChatAgent 类型 | 紧耦合 |
| **SU2. 定义 `SUT` Protocol**(选)| 解耦,LLMService / ChatAgent 都能满足 |
| SU3. 给 ChatAgent 加 `chat()` 方法模仿 LLMService 接口 | duck-typing,易出 bug |

### ③ 选择:**SU2 `SUT` Protocol + ChatAgent 实现**

**`SUT` Protocol**(在 `app/services/eval_runner.py` 加,Plan C 已有 EvalRunner):

```python
class SUT(Protocol):
    """系统-under-test 协议。EvalRunner 不关心 SUT 是 bare LLMService 还是
    ChatAgent —— 只关心给 prompt 拿 response_text + request_id。"""

    async def run(self, user_input: str, request_id: str) -> SUTOutput: ...


class SUTOutput(BaseModel):
    request_id: str
    response_text: str
    tool_calls: list[ToolCall] = Field(default_factory=list)  # 新加,Judge 用来评估 tool_correctness
```

**ChatAgent SUT 实现**(`app/agents/chat_agent.py`):

```python
class ChatAgent:
    """v0 chat agent — wraps the LangGraph 状态图 with a SUT-friendly interface."""

    def __init__(
        self,
        graph: CompiledStateGraph,
        trace_service: TraceService | None = None,
    ) -> None:
        self._graph = graph
        self._trace = trace_service

    async def run(self, user_input: str, request_id: str) -> SUTOutput:
        config = {"configurable": {"thread_id": f"eval:{request_id}"}}
        initial_state = GraphState(
            user_id="eval",
            session_id=request_id,
            user_message=user_input,
            request_id=request_id,
        )
        final_state: GraphState = await self._graph.ainvoke(initial_state, config=config)
        tool_calls = final_state.plan.tool_calls if final_state.plan else []
        return SUTOutput(
            request_id=request_id,
            response_text=final_state.final_response or "",
            tool_calls=tool_calls,
        )
```

**EvalRunner 改造**(Plan D 升级):
- `EvalRunner.__init__(sut: SUT, ...)` 类型从 `LLMService` 升为 `SUT` Protocol
- `EvalRunner.run_one(case)` 内部调 `self._sut.run(user_input, request_id)` 而不是 `self._sut.chat(...)`
- **bare LLMService 用 `_LLMServiceSUT` adapter** 实现 SUT Protocol(向后兼容 Plan C 老测试)

**Trace 双层 span**:
- LangGraph 节点级 span(name = `chat_graph.planner_node` / `chat_graph.tool_node` / `chat_graph.responder_node`),由 v0 自建一个 `LangGraphTraceCallback` 记录
- LLM 调用级 span(已 Plan B/C 落地,LLMService 内部写 span,parent_id 接 graph_node span)
- Tool 调用级 span(v0 在 `ToolRegistry.execute` 写 span,parent_id 接 tool_node)

### ④ 量化评估方案

- **SUT swap 兼容性**: Plan C 老测试(bare LLMService SUT)+ v0 新测试(ChatAgent SUT)同时跑通(回归测)
- **Trace 双层完整性**: 一个 chat 请求产生 1 root span(chat_graph) + 3 node span + N llm/tool span,所有 span share 同 request_id(L1 测试)
- **Eval 端到端**: v0 用 Plan C 既有 3 starter case 跑 ChatAgent,生成 EvalResult,**factuality + tool_correctness 维度都不为 None**(对比 bare LLMService 时 tool_correctness 总为 None)
- **Cassette 可复用性**: Plan B/C 录的 cassette 是 LLMService 直调 deepseek-v4-flash,v0 ChatAgent 内部 LLMService 调用走相同路径,**Plan B/C cassette 仍然 replay 通过**(L2 测试覆盖)

---

## 8. 决策七:Old code 处置

### ① 问题陈述

brainstorming 列了一长串待删的旧 chat 实现。v0 plan 里**一次删完**还是**渐进删**?

### ② 业界 alternatives

| 编号 | 形态 | 代价 |
|---|---|---|
| OC1. v0 spec explicit archive list,plan 第一个 task 一并删 | PR diff 巨大,但路径清晰 |
| OC2. v0 只新增,不删旧;旧代码留 v1+ 单独处理 | 双轨,维护成本翻倍 |
| OC3. 先 mark deprecated,半年后删 | 半年是无意义延迟 |

### ③ 选择:**OC1 explicit archive list,plan Task 1 一并删**

**Archive list**(plan Task 1 的 `git rm`):

```
backend/app/service/chat_service.py
backend/app/service/chat_service_v2.py
backend/app/service/mcp_chat_service.py
backend/app/service/react_controller.py
backend/app/service/smart_analyzer.py
backend/app/service/dr_g.py
backend/app/mcp_server/                    # 整目录
backend/app/mcp_client/                    # 整目录
backend/app/router/chat_router.py          # 替换为 app/router/chat.py(Task 5 新建)
```

**保留**(v0 不动):
- `backend/app/service/deep_research_v2/` —— 留 v0.5 spec 决定
- `backend/app/service/mock_tushare_service.py` —— v0 工具的数据源(决策三)
- `backend/app/service/mock_bocha_service.py` —— KB / Web 搜索 mock
- `backend/app/service/embedding_service.py` / `milvus_service.py` —— KB 后端(产品页面用)
- `backend/app/service/chart_generator.py` / `document_service.py` / `docmind_service.py` —— 周边能力
- 所有非 chat 模块(`auth` / `bidding` 因 brainstorming 决议保留 / `kb` / `news` 等)

### ④ 量化评估方案

- **删除 LOC**: 估 ~3-5k LOC(plan Task 1 实测填)
- **删除后 import 检查**: `python -c "import app.app_main"` 必须仍能 import 不报错(任何被删模块的引用必须同步清理)
- **测试通过率**: 删除后跑 `poe ci` 全绿(被删模块如有测试,Plan A 已删大部分,剩余在 archive list 同步处理)
- **Portfolio 信号**: PR description 列 `git diff --stat` 显示净 -3000 LOC,`Portfolio 上"瘦身 Nk 行"`故事点

---

## 9. 决策八:目录结构 / 模块路径

### ① 问题陈述

新增的 agents / tools / orchestration 放哪?跟现有 services / router 怎么协调?

### ② 选择(汇总)

```
backend/
├── app/
│   ├── agents/                 # NEW
│   │   ├── __init__.py
│   │   ├── base.py             # Agent 抽象基类 + StepResult + DispatchSubAgent 接口占位
│   │   ├── chat_planner.py     # ChatPlanner(继承 Agent)
│   │   ├── responder.py        # Responder(继承 Agent)
│   │   ├── chat_agent.py       # ChatAgent(SUT-friendly wrapper of LangGraph)
│   │   └── schemas.py          # Plan / ToolCall / ToolResult / GraphState / StepResult
│   │
│   ├── tools/                  # NEW
│   │   ├── __init__.py
│   │   ├── base.py             # Tool 抽象基类 + ToolError
│   │   ├── registry.py         # ToolRegistry
│   │   ├── get_stock_quote.py
│   │   ├── get_financials.py
│   │   └── get_news.py
│   │
│   ├── orchestration/          # NEW
│   │   ├── __init__.py
│   │   ├── chat_graph.py       # LangGraph StateGraph 装配
│   │   ├── nodes.py            # planner_node / tool_node / responder_node
│   │   └── checkpointer.py     # SqliteSaver factory
│   │
│   ├── services/               # 已存在(Plan B/C/D)
│   │   ├── llm_service.py      # 已存在
│   │   ├── trace_service.py    # 已存在
│   │   ├── eval_*.py           # 已存在
│   │   └── ...
│   │
│   ├── router/                 # 已存在
│   │   ├── chat.py             # NEW(替换 chat_router.py)
│   │   └── ...                 # 其他 router 不变
│   │
│   ├── service/                # 大幅瘦身,只保留 mock_tushare / mock_bocha / 周边能力
│   │
│   └── data/                   # NEW(运行时 sqlite 文件)
│       └── chat.sqlite         # checkpointer,gitignored
```

**mypy strict tier 扩展**:在 pyproject.toml 加 `app.agents.*` / `app.tools.*` / `app.orchestration.*` 进 strict tier(跟 `app.services.*` 同级别)。

### ③ 量化评估方案

- **新增目录**: 3 个(`agents/` / `tools/` / `orchestration/`)
- **新增源文件**: ~15 个(agent base + 2 agent + chat_agent + schemas + tool base + registry + 3 tool + graph + nodes + checkpointer + router/chat)
- **mypy 覆盖**: 100% strict 在 3 个新目录

---

## 10. 决策九:LangGraph 集成深度

### ① 问题陈述

LangGraph 在 v0 用得有多深?stream 模式 / 异步 / checkpointer 全用,还是只用基础 StateGraph?

### ② 选择(汇总)

| 特性 | v0 用 | 备注 |
|---|---|---|
| `StateGraph` + `add_node` + `add_edge` | ✅ | 基础 |
| `add_conditional_edges` | ✅ | planner_node 后根据 plan.direct_response 分支 |
| `SqliteSaver` checkpointer | ✅ | Memory v0 决议 |
| `astream_events(version="v2")` | ✅ | SSE 流式 |
| `interrupt()` / human-in-the-loop | ❌ | 留 v1+ |
| 子图(subgraph)| ❌ | 留 v0.5 research 模式 |
| `LangGraphServer` / Studio | ❌ | 不引入 |

### ③ 量化评估方案

- **LangGraph API 覆盖率**: v0 用上面 ✅ 的 4 个 API,v1+ 加 conditional + interrupt
- **版本锁定**: `langgraph>=0.2,<0.3`(在 pyproject 收紧)
- **第三方 plugin 默认行为**(per Plan B `feedback_third_party_plugin_defaults`): plan 阶段嵌一个 30s spike 验证 LangGraph 0.2.x 的 `astream_events(version="v2")` 实际事件类型与 doc 一致

---

## 11. 验收标准(本 spec 落地完成的判断标准)

- [ ] 3 个新目录(`agents/` / `tools/` / `orchestration/`)落地,15+ 新源文件,全部 mypy strict
- [ ] `POST /api/v0/chat` 能 SSE 流式返回 ChatAgent 的回答(本地 curl 验证)
- [ ] `chat.sqlite` checkpoint 跨 session 正确隔离(thread_id = `user_id:session_id`)
- [ ] LangGraph 图能从 checkpoint resume(中断后再请求继续完成)
- [ ] Plan B 22 个测试 + Plan C 17 个测试 + Plan D 12 个测试全部仍然通过
- [ ] **Plan C `EvalRunner` SUT swap 完成**:既能跑 bare LLMService(向后兼容),也能跑 ChatAgent
- [ ] Eval 跑 ChatAgent 时,EvalResult.scores.tool_correctness **不再是 None**(因为 ChatAgent 真用 tool)
- [ ] L2 cassette 录一条 ChatAgent 真打的完整流程(planner LLM call + 1 tool + responder LLM call,3 次真打)
- [ ] Old code 删除 ≥ 7 文件 + 2 目录,`poe ci` 全绿
- [ ] `app.agents.*` / `app.tools.*` / `app.orchestration.*` 加入 mypy strict tier
- [ ] Plan retrospective 填写

---

## 12. 风险与未解问题

### 已识别风险

1. **LangGraph 学习曲线**:implementer 第一次用 LangGraph,plan 必须嵌 30s spike 验证基本 API。
2. **SSE 在 nginx 部署的 buffering**:v0 spec 不解决 deploy,只保证 local + GH Actions 跑通。
3. **chat history token 爆炸**:v0 加 `MAX_HISTORY_MESSAGES=20` hard limit,Semantic 总结留 v1。
4. **mock_tushare LLM-driven 慢**:工具调用 P50 ~500ms,真 Tushare(v1)会快 ~10x。
5. **Cassette 录制 cost**:v0 L2 cassette 录一次 ChatAgent 完整流程 = 3 次真打 LLM(planner + 1 tool LLM-call inside mock + responder)≈ ¥0.005,nightly 跑一次完整 eval 仍 ≤ ¥0.10(Plan C/D Task 0 spike 沉淀)。

### 未解问题(留 plan / v0.5 决定)

- Q1. `mock_tushare_service.py` 当前内部直接 `from openai import OpenAI` 调 LLM —— 这违反 Plan B/C/D 的"agents/tools 不 import openai" 架构契约。**v0 plan 阶段决定**:要么把 mock_tushare 改造为通过 LLMService 调(干净但接口改动),要么 v0 接受这个例外(在 mypy override 里 ignore 它)。
- Q2. `MAX_HISTORY_MESSAGES=20` 是定值还是按 token 估算?v0 plan 阶段决定。
- Q3. ChatPlanner 用 OpenAI tool-calling 格式还是 v0 自己定一个 JSON schema?DashScope 的 deepseek-v4-flash 是否支持 OpenAI tool-calling?**spike 验证**(plan Task 0)。

---

## 附录 A:LangGraph 图 ASCII

```
                    ┌──────────────┐
            START → │ planner_node │
                    └──────┬───────┘
                           │
                  has_tool_calls?
                           │
              ┌────────────┴────────────┐
              │                         │
        yes (┌▼─────────┐)        no (┌▼─────────────┐)
             │ tool_node│             │ responder_node│ → END
             └────┬─────┘             └───────────────┘
                  │
                  ▼
            ┌─────────────┐
            │responder_node│ → END
            └──────────────┘
```

## 附录 B:Pydantic schema 全图

```python
# === graph state ===
GraphState
├── user_id: str
├── session_id: str
├── user_message: str
├── enable_web_search: bool      # placeholder
├── enable_kb_search: bool       # placeholder
├── plan: Plan | None
├── tool_results: list[ToolResult]
├── final_response: str | None
├── final_response_streamed: bool
├── request_id: str
└── span_stack: list[str]

# === agent I/O ===
Plan
├── tool_calls: list[ToolCall]
├── direct_response: bool
└── reasoning: str

ToolCall
├── tool_name: str
├── args: dict[str, Any]
└── rationale: str

ToolResult
├── tool_name: str
├── args: dict[str, Any]
├── success: bool
├── output: dict[str, Any] | None
├── error: str | None
└── latency_ms: int

StepResult
├── state_update: dict[str, Any]
└── span_metadata: dict[str, Any]

# === SUT ===
SUTOutput  # 给 EvalRunner 的标准输出
├── request_id: str
├── response_text: str
└── tool_calls: list[ToolCall]

# === HTTP ===
ChatRequest
├── session_id: str
├── message: str
├── enable_web_search: bool
└── enable_kb_search: bool

StreamEvent
├── type: Literal["plan", "tool_start", "tool_end", "token", "done", "error"]
└── data: dict[str, Any]
```

## 附录 C:模块依赖图

```
┌────────────────────────────────────────────┐
│  HTTP Layer: app/router/chat.py            │
└─────────────┬──────────────────────────────┘
              │
              ▼
┌────────────────────────────────────────────┐
│  Orchestration: app/orchestration/         │
│  ├── chat_graph.py (StateGraph)            │
│  ├── nodes.py     (planner/tool/responder) │
│  └── checkpointer.py (SqliteSaver)         │
└─────────┬───────────────────┬──────────────┘
          │                   │
          ▼                   ▼
┌─────────────────┐  ┌────────────────────┐
│  Agents:        │  │  Tools:            │
│  app/agents/    │  │  app/tools/        │
│  ├── base.py    │  │  ├── base.py       │
│  ├── schemas.py │  │  ├── registry.py   │
│  ├── chat_planner.py│ ├── get_stock_quote.py│
│  ├── responder.py│ │  ├── get_financials.py│
│  └── chat_agent.py│ │  └── get_news.py   │
└─────────┬────────┘  └─────────┬─────────┘
          │                     │
          └──────────┬──────────┘
                     ▼
┌────────────────────────────────────────────┐
│  Services: app/services/ (Plan B/C/D)      │
│  ├── llm_service.py                        │
│  ├── trace_service.py                      │
│  ├── eval_runner.py (SUT swap)             │
│  ├── pricing.py / cost_budget.py           │
│  └── ...                                   │
└────────────────────────────────────────────┘
```

---

## Retrospective

> Filled in after plan(s) implemented & merged.

**Implementation completion date**:
**Implementation plan(s)**:
**Total commits**:
**Total time**:

### 对的设计(3 条)

### 错的设计 / spec 漏了什么(3 条)

### 下个 spec 要避免(3 条)

### 沉淀到 memory

### v0.5 启动条件

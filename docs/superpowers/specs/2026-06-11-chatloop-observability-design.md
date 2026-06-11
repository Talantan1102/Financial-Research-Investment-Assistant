# Chatloop 可观测性补齐 — 设计文档

- 日期:2026-06-11
- 主题:把 chatloop 的"工具耗时 / turn 级聚合 / KV-cache 命中率"补成可落库、可聚合、可在看板查看
- 来源动机:落地 `dashboard/data/reports/chatloop-runtime-optimization-survey.yaml` 第 ⑦ 号决策点(可观测性缺口)
- 决策记录:载体复用 trace span / 访问路径走"后端聚合 API + 看板实时拉" / 分两期(先后端,再看板)

---

## 1. 背景与动机

`chatloop-runtime-optimization-survey.yaml` 的 ⑦ 号决策点原文:

> KV-cache 命中率有原始数据(cached_tokens)但从未度量,稳定前缀这个核心设计假设处于"没有评估就没有优化"状态,turn 级聚合指标(总成本/耗时/调用数)也缺。

再叠加 ③ 号(工具超时)留下的可观测性尾巴:工具到底跑了多久,数据层答不出。本设计就是把这两条的"观测"部分做实——让"某轮慢,是模型还是工具""缓存命中率多少""哪个工具最拖后腿"在数据层能查、能聚合、能在看板上看到。

类比锚点(口径统一):每次 LLM 调用 = 一张"计时小票"(span),已自动落库;工具调用现在掐了表但把小票扔了,本设计就是把工具那张小票也留下,再把一堆小票汇总成账、摆上看板。

---

## 2. 现状(带证据)

**已经在做的(不动):**

- 每次 LLM 调用写一条 span 进 PG `trace_spans` 表,按 `request_id` 串成一棵树。
  - chat 路径 span `name = "LLMService.stream_step"`,metadata 带 `prompt_tokens / completion_tokens / cached_tokens / cost_cny / latency_ms / tier`(`backend/app/services/llm_service.py:222-246`)。
  - 研报/agent 路径 span `name = "LLMService.chat"`(`llm_service.py:126-144`)。
  - 默认就挂了 `TraceService`:`build_llm_service_from_env(trace_service=None)` → `TraceService(SessionLocal)`(`backend/app/services/openai_client.py:243-277`)。
  - span 写入失败是非致命的:`try/except + logger.warning`,绝不打断主调用(`llm_service.py:147-150`,注释 C27)。
- `TraceService.write_span / query_spans / get_trace`(`backend/app/services/trace_service.py`),`query_spans` 用白名单列过滤防注入。
- turn 级账单其实已经算了:`turn_summary(state)` 给出 `cost_cny / llm_calls / tool_calls / prompt_tokens / completion_tokens / cached_tokens / cache_hit_rate`(`backend/app/chatloop/state.py:252-267`),并随 `done` 事件发出(`backend/app/chatloop/loop.py:202-205, 427`)。
- 前端已展示一部分:`ToolCallCard` 显示每个工具耗时(客户端用 start/end 事件墙钟算的近似值)、`⚡缓存` 角标;`CostMeter` 显示累计花费;研报侧 `CostLatencyMetrics` 显示总成本+总耗时+Critic 评分。

**缺口(本设计要补的):**

1. 工具耗时算了就丢。`tool_hub.py` 在 `_dispatch_one_inner` 里 `started = time.perf_counter()`(:313)、`latency_ms = ...`(:357),但只塞进了内存里的 `ToolResult`,既不进 `tool_end` 事件(:361 只带 tool/digest/cached)、也不进台账(`LedgerEntry` 字段只有 step/tool_name/args_hash/digest/success/cache_key,`state.py:37-51`,没有 duration)、更不进 trace。所以 `trace_spans` 这棵树只有"模型那半边",工具那半边是空的。
2. turn 级聚合 `turn_summary` 发到了 `done` 事件,但前端 reducer 只读 `stop_reason`、把其余字段丢了(`frontend/src/store/current-chat.ts:274-292`);且它是 in-memory、随 turn 结束消失,没有任何持久化、跨 turn 不可聚合。
3. KV-cache 命中率从没跨请求聚合过(单 turn 的 `turn_summary` 算了,但没汇总成"整体/趋势")。
4. 看板读的是本地 sqlite `backend/data/board.db`(`dashboard/server.py:45 DB_PATH`),根本不连后端 PG,拿不到 `trace_spans`。
5. `trace_spans` 现在只写不读:没有任何 HTTP 接口或看板视图暴露它,`query_spans/get_trace` 仅测试在用;研报 cost 聚合还挂着"待 v0.9.y TraceService 接入"的注释(`backend/app/router/reports.py:309-310, 386`)。

**已有先例(可参考的同款):** `subagent_dispatch_runs` 表已为"子 agent 扇出"每个子循环记了 `tokens / cost_cny / steps_used / duration_ms`(`backend/app/models/subagent_dispatch.py`)。说明"为每个执行单元记耗时+成本"在本仓库已有成熟模式;本设计是把同样的事用 trace span 这个更统一的载体补到工具粒度。

---

## 3. 目标与非目标

**目标:**

- 工具调用写 trace span,让 `trace_spans` 按 `request_id` 能拼出"模型+工具"完整时间线。
- 后端提供跨请求聚合(最慢工具排行 / 模型vs工具耗时占比 / KV-cache 命中率 / 每轮均值)与一个只读 API。
- 看板新增一页,实时拉聚合 API 渲染。

**非目标(显式不做,避免滑成大工程):**

- 不给散户前端(chat UI)加 token 数显示。token/命中率是开发者/看板的料,不推给终端用户。
- 不做 span 父子树。工具 span 用 `metadata.step` 归步、flat 摆放;严格"哪次模型思考叫出哪个工具"的父子链接留作可选 follow-up。
- 不改前端 `CostMeter`、不把 `done` 里的 `turn_summary` 接进前端 store(可选 follow-up:把后端精确 `latency_ms` 灌进 `tool_end` 事件、替换客户端墙钟近似值)。
- 研报"每 agent 拆分"UI 不在本次。研报 LLM 调用已有 span(数据在),但本期聚合默认只圈 chatloop(见 §4.2 的 span 判据);研报维度留 follow-up。
- 不引 alembic,建表用 `create_all()` 幂等(沿用 v0.9.x 约定)。本设计**不新增表**,只复用 `trace_spans`。

---

## 4. 设计

三个独立单元,各自能单测。命名自解释,不用代号。

### 4.1 单元一:工具 span 写入(后端,`tool_hub.py`)

**职责:** 每次工具调用(含缓存命中、含 search_tools)写一条 span 进 `trace_spans`,与 LLM span 同 `request_id`、同一棵 trace。

**接口变化:** `ToolHub.__init__` 增可选参 `trace: TraceService | None = None`;为 None 时**不**写 span(测试里 `ToolHub()` 无参构造完全不受影响)。生产由 `worker_wiring.build_turn_hub`(`backend/app/chatloop/worker_wiring.py:202`)与 `subagent.py:93` 注入;注入源默认 `TraceService(SessionLocal)`(与 `llm_service` 同款,无状态,按 `request_id` 写同一张表即同一条 trace,不要求与 LLM span 共用同一实例)。

**span 形状:**

- `span_id = f"{request_id}-tool-{uuid4().hex[:8]}"`,`request_id = state.request_id`,`parent_id = None`。
- `name = f"tool:{工具名}"`(聚合判据,见 §4.2);`metadata.kind = "tool"`。
- `metadata`:`{ "latency_ms", "cached"(bool), "success"(bool), "step", "tool_name" }`。
- `started_at / ended_at`:在 dispatch 前后各取一次 `datetime.now(UTC)`(现在只有 perf_counter,需补 wall-clock 时间戳;`latency_ms` 仍可用 perf_counter 求差以保精度)。
- 失败工具:`error` 字段填错误摘要,`metadata.success = False`。
- **inputs/outputs 不落原文**:只放工具名/参数 hash 这类非内容字段,避免把用户 prompt/数据写进可被聚合接口读到的地方(隐私边界,见 §6)。

**三个写入点(都要覆盖):** 缓存命中短路(`tool_hub.py:~287`,latency≈0、cached=true)、正常工具(`:~313-361`)、内置 search_tools(`:~397-412`)。

**失败容错:** span 写入包 `try/except + logger.warning`,trace/DB 挂掉绝不能让工具调用崩——照抄 `llm_service` 的 C27 处理。

**dispatch_subagents 说明:** 子 agent 扇出本身是父循环里的一个工具调用,它会得到一条工具 span(覆盖整次扇出的墙钟);子循环内部各自的 LLM span 照常落库,子循环明细另有 `subagent_dispatch_runs` 表。三者不冲突。

### 4.2 单元二:Trace 聚合服务 + 只读 API(后端)

**span 判据(模型 vs 工具,聚合的基石):**

- 模型 span:`name = "LLMService.stream_step"`(chatloop)。
- 工具 span:`name LIKE "tool:%"` 或 `metadata.kind = "tool"`。
- 本期聚合默认圈定 chatloop:`stream_step` + `tool:*`;研报的 `LLMService.chat` 不计入(留 follow-up)。

**聚合服务** `backend/app/services/trace_analytics.py`(新):纯 SQL/聚合 over `trace_spans`,返回 Pydantic 结果对象,构造方式同 `TraceService`(吃 session_factory)。JSONB 字段(`attrs_json`)里的 `latency_ms / tokens / cost / kind` 用 PG JSONB 取值 + cast;百分位用 `percentile_cont`。

跨请求聚合(带时间窗 `window`,如 7d):

- **每工具耗时分布**:按 `tool_name` → `count / p50 / p95 / max latency_ms / success_rate / cache_hit_rate`。
- **最慢工具 Top N**:按 p95 排序(看 95 分位而非均值,专抓偶发卡顿)。
- **模型 vs 工具 耗时占比**:`sum(模型 latency)` vs `sum(工具 latency)`。
- **KV-cache 命中率**:`sum(cached_tokens) / sum(prompt_tokens)`(over 模型 span;prompt=0 不除零)。
- **每轮均值**(按 `request_id` 分组再平均):`avg cost_cny / avg 墙钟(max(ended_at)-min(started_at)) / avg llm_calls / avg tool_calls`。

单请求时间线(顺带,几乎免费):薄封装 `TraceService.get_trace(request_id)`,返回这一轮 per-step 的 `(name, kind, latency_ms, tokens, cost)` 列表 + 该轮 turn 级小计。用于"查这一次到底慢在哪"。

**只读 API** `backend/app/router/observability_router.py`(新):

- `GET /observability/chatloop/aggregates?window=7d` → 上面的跨请求聚合 JSON。
- `GET /observability/chatloop/trace/{request_id}` → 单请求时间线(可选端点,薄封装)。
- 只读、只返回聚合数字与非内容字段,**绝不返回 span 的 inputs/outputs 原文**(隐私边界)。
- 鉴权:沿用现有 router 约定;因看板需无登录态拉取,该端点设为内部只读、不带用户 PII,可不挂用户鉴权(在文档与代码注释里写明"内部观测端点")。

### 4.3 单元三:看板可观测性页(看板,Phase 2)

**职责:** 看板新增一页,实时 fetch 后端聚合 API 渲染。

- `dashboard/server.py` 新增路由 + 新模板;后端 base URL 从 config/env 读。
- 渲染:最慢工具排行(表 + CSS 条形)、模型vs工具占比(条形)、KV-cache 命中率(数字 + 条)、每轮均值(数字卡)。用简单 HTML 表 + CSS 条形(参考 `CostLatencyMetrics` 的 div 进度条思路),**不引图表库**;沿用看板既有视觉(图例若需 SVG 走 `templates/figures/` 内联,见看板研报约定)。
- 后端不可达时优雅降级:显示"后端未连接/暂无数据",不报错崩页。
- 看板运行环境沿用既有约定(根 .venv,默认端口 8910)。

---

## 5. 数据流

写入(每 turn,实时):
LLM 调用 → `llm_service` 写模型 span;工具调用 → `tool_hub` 写工具 span。两者同 `request_id` 落 `trace_spans`。

读取(看板,按需):
看板页 →(HTTP)后端 `/observability/chatloop/aggregates` → `trace_analytics` 跑聚合 SQL over `trace_spans` → JSON → 看板渲染。

---

## 6. 错误处理与边界

- **span 写入非致命**:写失败只 warning,主流程(工具/对话)继续。
- **隐私边界**:工具 span 不落 inputs/outputs 原文;聚合 API 只出数字,不回 span 内容。防止"观测端点"变成"对话内容泄漏端点"。
- **看板降级**:后端不可达 → 看板页显示占位,不崩。
- **除零**:命中率/占比类在分母为 0 时取 0。
- **时间窗**:`window` 参数白名单(如 `1d/7d/30d`),非法值回 400 或回退默认,不拼裸 SQL(沿用 `query_spans` 的白名单防注入精神)。

---

## 7. 测试策略

测试库沿用全 PG + `db_session` transaction-rollback 隔离约定(`trace_spans` 在 PG)。

- **单元一**:`ToolHub` 注入一个捕获用的 `TraceService`,断言每次工具调用写出一条 span,覆盖三态——成功 / 失败(带 error)/ 缓存命中(latency≈0、cached=true);断言注入 None 时不写;断言 trace 写入抛异常时工具调用仍正常返回(非致命)。
- **单元二**:往 `trace_spans` 直接 seed 模型 span + 工具 span,断言 `trace_analytics` 算出的 p95 / 模型vs工具占比 / KV-cache 命中率 / 每轮均值正确;API 集成测试:命中端点断言 JSON 结构,并断言响应**不含** span inputs/outputs 原文。
- **单元三(Phase 2)**:看板集成测试,stub 后端聚合响应渲染断言;后端不可达走降级分支断言。

---

## 8. 分期

- **第一期(后端,数据完整可查):** 单元一(工具 span 写入)+ 单元二(聚合服务 + 只读 API)。交付即"trace 完整 + 能查能聚合",自身可独立验收。
- **第二期(看板):** 单元三(看板可观测性页)。

---

## 9. 关键决策记录

| 决策 | 选择 | 理由 / 放弃的备选 |
|---|---|---|
| 观测数据载体 | 复用 trace span | 与已有模型 span 同一棵树、同一套 `TraceService`/查询/树结构,不新增概念;放弃"新建扁表"(与 span 双轨、拼完整时间线要 union)和"只进台账不落库"(台账是每轮内存态、跨 turn 不可聚合,不满足监控目标) |
| 访问路径 | 后端聚合 API + 看板实时拉 | 数据路径最短、永远最新;放弃"定时 job 快照进 board.db"(多一个周期 job、非实时)和"看板直连后端 PG"(跨应用 DB 耦合最重) |
| 节奏 | 分两期(先后端再看板) | 第一期即数据完整可查、可独立交付;避免单次铺调太大 |
| 父子树 | 不做,flat by step | 父子链接要把 LLM span_id 一路穿进 tool_hub,工程量换回报低;带步号的 flat 列表已能答"时间花哪了" |
| 散户前端加 token | 不做 | token/命中率是开发者/看板的料,推给终端用户是噪音 |

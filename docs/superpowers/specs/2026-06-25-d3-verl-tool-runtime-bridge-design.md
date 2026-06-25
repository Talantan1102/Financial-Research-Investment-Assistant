# 设计:D3 verl 工具运行时桥接(训练工具 = 生产工具)

> 承 `2026-06-24-one-week-train-runbook.md` D3、`2026-06-09-verl-multistep-tool-rl-recipe.md`。
> 2026-06-25 实现 D3 时浮现的核心设计约束 —— 记录正确方向,作为工具层实现规格。

## 一句话

verl RL rollout 里模型能调的工具,**必须就是后端生产/评测用的那套 `app/tools` Tool**(同名、同 schema、同 `run()` 实现),否则训出来的 tool-calling 行为在真实系统里调不动 —— 训了也没法用在实际场景(用户 2026-06-25 指出)。**不能为 verl 手写一套 bespoke 工具。**

## 为什么(踩过的坑)

实现 D3 时一度手写了 verl 版 `get_daily`(BaseTool)和计划写"最小 run_python"。错:① 工具名/schema 跟后端 `app/tools` 不一致 → 模型学会调的工具生产没有;② run_python 用裸 exec,跟生产的 `CodeInterpreterTool`(沙箱 + data_refs + 缓存)行为不同。**作废,改为桥接后端运行时。**

## 后端工具运行时现状(已核验 file:line)

- `app/tools/base.py`:`Tool(ABC)` —— `.name` / `.args_schema`(pydantic)/ `async run(args) -> dict` / `schema_for_llm() -> dict`。十几个无状态数据工具(`get_stock_quote` / `get_index_daily` / `get_daily_basic` / `get_sector_daily` …)。
- `app/chatloop/code_interpreter_tool.py`:`CodeInterpreterTool` name=`run_python`,**有状态**:`run_with_state(args, ChatLoopState)`,靠 `data_refs` + redis 缓存传大数据,底层 `ExecutorBackend` 沙箱。
- `app/chatloop/tool_hub.py`:`ToolHub` 聚合 Tool、`schemas_for_llm()`(含渐进披露 `search_tools` 殿后)。
- `app/chatloop/eval_agent.py`:评测 SUT(`ChatLoopAgent`)用 `ToolLoop` + `tool_hub` —— **这是训练要对齐的目标工具面**。

## 设计:通用适配器,不重写工具

```
verl ToolAgentLoop ──create/execute──> VerlBackendToolAdapter(BaseTool)
                                              │ 包住一个后端 Tool 实例
                                              ├─ get_openai_tool_schema() = tool.schema_for_llm()   # 同 schema
                                              └─ execute(parameters)      = await tool.run(tool.args_schema(**parameters))  # 同实现
```

- **无状态数据工具**:适配器直接转发 `run()`,名字/schema/实现全等于生产 ✅
- **run_python(有状态)**:难点。需把 `ChatLoopState` + `data_refs` 缓存 + `ExecutorBackend` 沙箱在 rollout 内立起来。选项:(a) 每条 rollout 起一个轻量 ChatLoopState + 进程内沙箱 backend;(b) data_refs 缓存用进程内 dict 替 redis(rollout 内单会话,无需跨进程)。**需专门设计,不可省略**(run_python 是算指标的主力,且评测就用它)。

## 跨环境(verl env vs backend env)

verl rollout 跑在 verl conda env(torch/sglang),后端工具依赖 pydantic/tushare/redis/沙箱。两选项:
1. **把 backend 装进 verl env**(加 pydantic/tushare/redis 等;backend 进 PYTHONPATH)—— 适配器直接 import `app.tools`。
2. **工具走 cassette 回放**:训练前用真后端把每条 case 的工具输出冻盘,rollout 内适配器只回放(确定性 + 免限频 + 免跨 env 依赖)。**RL 训练更稳的路**,但要先建 cassette 采集。

推荐:**先 (1) 跑通对齐 + 真 smoke,再 (2) cassette 化做正式训练**。

## D3 完成判据(重申 runbook)

2-step GRPO 冒烟:① 不报错 ② 日志无 tokenization mismatch ③ **reward 非全 0**(工具真调通 + 有题答对)。**必须用对齐后的工具集**,否则 smoke 通过也无意义。

## 当前进度(2026-06-25)

- ✅ `to_verl.py`:题 → verl parquet(§2.7 格式),3 单测绿
- ✅ `oracle_reward.py`:verl 奖励函数,**复用评测同一套 `judge`**(已对齐),5 单测绿,verl env 可加载
- ⏳ 工具层(本文档):通用适配器 + run_python state 桥 + 跨 env 方案 —— **下一块**
- ⏳ 端到端 smoke:依赖工具层

## 补充(2026-06-25 核到 worker_wiring):runtime bridge 的真实依赖

`app/chatloop/worker_wiring.py` = 生产工具装配,两段:
1. `build_singletons(...)`:tushare 服务 + `SkillExecutorBackend`(run_python 沙箱,`app/skills/executor_backend.py`)+ TraceService(写 trace_spans,要 DB)等共享单例。
2. `build_turn_hub(singletons, emit, seq_counter)`:**per-turn** 轻 ToolHub,`register_inprocess([CodeInterpreterTool(run_python), 各数据工具…])`,持 turn 级 emit/seq/state。

→ 对齐 smoke 要在 verl rollout 内立起这套:**装 backend + 依赖进 verl env(pydantic/tushare/沙箱/DB 客户端),按 rollout 造 singletons + per-turn hub,用 `VerlBackendToolAdapter` 包每个 tool**。这是带 PG/沙箱/tushare 多服务依赖的子系统,集成风险高,需作为独立一阶专门做。**不在本 PR(#187)范围**;本 PR 落地的是 to_verl/oracle_reward/adapter 三件对齐底座 + 本设计。

## 方案定稿(2026-06-25,用户选 ② HTTP 工具服务 + 先做 smoke)

**架构**:verl rollout(verl env)的 `HttpToolProxy(BaseTool)` 经 HTTP 调 backend(fria env)的工具服务;真实工具在服务端跑,**零污染 verl env**。

**smoke 最小依赖**(不调 `build_turn_components`,避开 HeavySingletons 的 PG/Milvus/memory/llm):
- 数据工具:`StockQuoteTool(tushare=build_tushare_service())`(或 get_daily 同款)——返回**内联**价格
- `CodeInterpreterTool(backend=SkillExecutorBackend(SkillExecutor(skills_root,workdir_root)), cache=None)` —— **cache=None 关 data_refs**;数据内联进对话,模型直接把数字写进 run_python 算(2 价算涨幅)
- 二者都是生产同款工具类(对齐),SkillExecutor 构造轻(subprocess 沙箱)

**工具服务端点**(FastAPI,fria env 起):`GET /tools`(schema)/`POST /sessions`(建会话,持 per-题 tool 实例)/`POST /sessions/{id}/exec`{tool,args}/`DELETE /sessions/{id}`。会话隔离:每 rollout 轨迹一个 session;cache=None 下工具基本无状态,session 主要隔离并发。

**verl 侧**:`HttpToolProxy` create→POST /sessions、execute→/exec、release→DELETE;`tool_config.yaml` 两条(get_stock_quote / run_python),schema 从 `GET /tools` 取。

**smoke 范围**:2 工具 + stock_study 涨幅类子集 + 2 步 GRPO,过关=不报错+工具真被调+reward 非全 0。不做:全 14 工具 / search_tools 渐进披露 / data_refs / cassette / 并发优化。

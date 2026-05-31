# 金融研投助手

LLM 应用 portfolio 项目 — 把多 agent 编排、上下文工程、结构化输出、评测可观测在一个金融研究场景里跑通。

**当前版本**:v1.0(持仓监控 — Trade SoT + Position materialized + 5 endpoints + 三态机 service guard)+ **Harness Board**(复合型项目知识工具 — 按论文 ETCLOVG 7 维 × 87 capability 把本项目逐条拆解展示,DeepCard 深读卡 + 3 视图 Topology 关系图 `/` / 模块页 `/m/{dim}` / 故事时间线 `/story`,Milvus 相关推荐 + 34 张 hand-curated seed)

## 三个使用模式

| 模式 | 路径 | 说明 |
|---|---|---|
| **投资标的尽调 (B-1)** | `/research` | 5-agent 流程(Planner constrained router 4 选 1 → DataCollector → Analyst horizon-conditioned → Writer 6 字段驱动 + Python helper 决定论修正 → Critic 7 维评分 含 plan_correctness),产出 `InvestmentDueDiligenceReport` Pydantic schema;6 字段 form(ts_code + horizon + objective + risk_tolerance + 持仓 + 机构类型);LangGraph self-correcting retry edge(plan_correctness < 8.5 且 retry_count < 2 → 回 planner 重选,max 2 轮硬上限) |
| **对话模式 (Chat)** | `/chat` | ChatAgent + planner + tool registry,自然语言问答 + 工具调用(行情/财务/web/KB) |
| **持仓预警 (Monitoring, B-3)** | `/monitoring` | 5 SignalRule 并发评分 → 红色 alert 触发 5-agent deep_dive escalation → 邮件通知;支持手动 + cron 触发 |

## 架构

```
                    ┌──────────────────────────────────────────────────────────┐
                    │ FastAPI + LangGraph 1.x orchestration                    │
                    │   ├─ ResearchAgent (5-agent + Critic 7-dim subgraph + retry edge) │
                    │   │    InvestmentDueDiligenceReport schema (v0.8.4)      │
                    │   │    Planner(constrained router 4-id Literal) → Analyst(horizon-conditioned) │
                    │   │    Writer(6 sections + Python helpers 决定论修正)    │
                    │   │    Critic(7 scorer 含 plan_correctness LLM-as-judge) │
                    │   │    Self-correcting retry edge(plan_correctness < 8.5 → 回 planner, max 2 轮) │
                    │   │    financial_research/ skill bundle(17 components — Anthropic Skills 模式) │
                    │   ├─ ChatAgent     (planner + tool registry)             │
                    │   └─ MonitoringService (signal + escalation)             │
                    └──────────────────────────────────────────────────────────┘
                                          │
   ┌──────────────────────────────────────┼──────────────────────────────────────┐
   │ 横切服务 (app/services/) — 全部 Protocol + Real/Mock + factory             │
   ├──────────────────────────────────────┼──────────────────────────────────────┤
   │ LLMService   │ TushareService  │ BochaService     │ KBService              │
   │ (OpenAI 兼容) │ (13 接口 + 缓存)│ (Web 搜索 + 4 reliability) │ (Milvus 向量库) │
   │ TraceService │ EvalRunner      │ Judge            │ EmailNotifier (B-3)    │
   │ CostBudget   │ TierRouter      │ RateLimiter      │ CircuitBreaker          │
   └──────────────────────────────────────────────────────────────────────────────┘
                                          │
                              ┌───────────┴───────────┐
                              │ sqlite (本地持久化)    │
                              │  ├─ tushare_cache     │
                              │  ├─ monitoring        │
                              │  └─ eval / trace      │
                              └────────────────────────┘
```

**关键模式**:
- **Protocol+Real+Mock+factory**(全 9 次应用):`build_*_service_from_env()` 读 `*_MODE=real|mock` 切换。CI 全 mock,production 切 real。
- **VCR cassette e2e**:LLM/Tushare/Bocha 的真调用录成 yaml,replay 0.81s 跑 36 个 endpoint × 5 ts_code。代理 host 在录制时被 scrub 成官方 host(repo 不暴露代理 URL)。
- **mypy strict**:`app/services/*` `app/agents/*` `app/orchestration/*` 全 strict 通过。legacy `app/service/`(单数)mypy ignore_errors。
- **commit-msg layer 标记**:fix 类 commit body 必须含 `原因 layer: <impl|plan|spec>`(pre-commit hook 强制),溯源 bug 起源。
- **Constrained LLM router (v0.8.5)**:Planner 不自由生成 ResearchPlan,LLM 仅在 4 个 hardcode plan_id Literal(`capital_preservation` / `balanced` / `aggressive_growth` / `event_driven`)中四选一 + rationale ≤200 字符;subtask templates hardcode 在 `plan_registry`,LLM 不参与生成,保证 plan deterministic + golden case 可写。
- **Anthropic Skills bundle (v0.8.5)**:`backend/app/agents/research/financial_research/` 17 components — 11 .md methodology(solvency / profitability / growth / cashflow_quality / valuation / industry / shareholder_governance / short_term_capital_flow / event_driven / risk_factors / decision_framework)+ 3 references(industry_benchmarks.json + recommendation_rules.yaml + position_size_rules.yaml)+ 3 Python helpers(`compute_position_size` / `classify_recommendation` / `lookup_industry_benchmark`,纯函数 deterministic)。Writer 调 Python helper 算 recommendation + position_size_pct,LLM 仅生成 narrative,footer 标 "Python 决定论修正"。
- **Self-correcting retry edge (v0.8.5)**:LangGraph `add_conditional_edges`,plan_correctness < 8.5 AND retry_count < 2 → 回 `research_planner_node` 收 critic feedback 重选,max 2 轮硬上限,防 LLM judgment 错或 ambiguous case。

## 版本演进

| 版本 | 关键交付 | PR |
|---|---|---|
| v0 | LangGraph chat agent skeleton + 2 agents + 3 tools + SSE | #6 |
| v0.5 | Research mode 5-agent + Critic Send API subgraph + 7-event SSE | #7 |
| v0.6 | Bocha web 搜索接入 + ReliableBochaService(4 reliability layers) | #8 |
| v0.7 | KB Search + Milvus + 13 篇真 corpus ingest | #9 |
| v0.8.1 | Token-plan 重构 + v0.7 收尾 cassette | #10 |
| v0.8.2 | Credit investigation report schema + Writer 重构 + B-1 茅台 e2e | #11 |
| v0.8.3-pre | 项目个人化 + legacy 标识 + 设计语言对齐 | #12 |
| v0.8.3 | Tushare 真接 8 接口 + B-3 持仓预警引擎(signal + escalation + email + 3 前端页) | #13 |
| v0.8.4 | B-1 投资标的尽调极致 polish:InvestmentDueDiligenceReport + 产品定位 reframe(2 persona 共享底座)+ 5-agent prompt 改造 + 3 differential golden + /research 前端完整 user journey | #16 |
| **v0.8.5** | **Constrained LLM router(plan_id 4 选 1 schema enum)+ 17-component financial_research Anthropic Skills bundle + 第 7 critic plan_correctness + LangGraph self-correcting retry edge max 2 + tool inventory 5→13 + Writer 调 Python helper 替代 LLM 算数字** | #19 |
| **v0.9 (Plan 1)** | **Chat backend foundation: LangGraph supervisor topology + MCP single-mode tool layer + PG-persisted chat state + 5 chat REST endpoints + 6 MCP tools + in-session memory Protocol DI** | feat/v0.9-chat-c1c2 |
| **v0.9 (Plan 3)** | **Escalation channel (chat→research handoff): EscalationPacket 4-class schema + EscalationExtractor + escalate SSE endpoint + escalation_records PG table + research prompt upgrades + bidirectional report link** | feat/v0.9-chat-c1c2 |

### v0.9 Chat Mode (backend foundation, Plan 1 of 5)

Production-style chat agent with LangGraph supervisor topology + MCP single-mode tool layer + PG-persisted state.

- **Endpoints:**
  - `POST /api/v0/chat` — SSE streaming chat (19 event types: token / plan / tool_start / tool_end / cost_update / done / error / + Plan 2-3 extensions)
  - `POST /api/v0/chat/escalate` — SSE chat→research handoff (Plan 3); streams `escalate_request` → `escalate_packet_draft` → `research_*` events → `escalate_done`
  - `POST /api/v0/chats` — create new chat session
  - `GET /api/v0/chats/` — list user's chat sessions
  - `GET /api/v0/chats/{session_id}` — get session + messages
  - `DELETE /api/v0/chats/{session_id}` — delete session

- **6 MCP tools** (via stdio subprocess, `backend/app/mcp_server/`):
  - `get_stock_quote` (tushare A-share daily price)
  - `get_financials` (tushare financials)
  - `get_news` (tushare news)
  - `web_search` (Bocha)
  - `kb_search` (Milvus)
  - `compare_stocks` (composite — quote + financials for 2-5 stocks)

- **Persistence (PG):**
  - Business tables in `public` schema (chat_sessions, chat_messages, tool_result_cache)
  - LangGraph checkpoints in `langgraph_checkpoints` schema (AsyncPostgresSaver)

- **In-session memory (Q4 E):** tool-result dedup + token-guard summarization via `Memory` Protocol DI (extensible to D MemGPT in C.5)

- **Env vars:** Existing `DATABASE_URL` + `DASHSCOPE_API_KEY` + `DASHSCOPE_BASE_URL` — no new vars

### Escalation Channel — Plan 3 (chat → research handoff)

User-explicit-confirm pattern: LLM extracts signals from chat history → user reviews/edits → research pipeline runs with chat-derived context.

- **Endpoint:** `POST /api/v0/chat/escalate` — SSE, accepts `{session_id, confirmed_packet?}`
- **SSE event flow:** `escalate_request` → `escalate_packet_draft` (LLM-extracted `EscalationPacket`) → `research_planner_done` / `research_analyst_done` / `research_writer_done` / `research_critic_done` / `research_tool_start` / `research_tool_end` → `escalate_done` (or `escalate_error`)
- **EscalationPacket schema** (`backend/app/agents/escalation_protocol.py`): 4-class structure — `ExplicitTask` / `ChatDerivedSignals` (entities + preferences + known_tool_results) / `KnownFacts` / `SessionMetadata` + `MissingFieldHint` list
- **PG table `escalation_records`:** `packet_draft` / `packet_confirmed` / `user_edits` jsonb columns — captures LLM→user diffs for prompt-tuning trace
- **Bidirectional link:** `research_reports.source_chat_session_id` FK (ON DELETE SET NULL) + `ChatMessage(message_type="research_report")` double-write — report appears in chat history
- **Research prompts upgraded:** `ResearchPlanner` / `Analyst` / `Writer` honor chat-derived entities / preferences / known tool results
- **Failure rollback (E4):** research crash OR double-write failure → `escalate_error` SSE + `escalation_records.status=failed`
- **Plan 4 (TODO):** `<EscalationConfirmDialog>` frontend UI consuming `escalate_packet_draft` event

- **Plan 1 carryover (TODO before Plan 2 ship):**
  - MCP tool wiring into planner runtime ToolRegistry (currently legacy in-process tools wired)
  - Real `ToolResultCache` injection (currently `_NoOpCache` stub)
  - PG schema migration formalization (v0.9 columns added via manual ALTER during smoke; future via alembic in v1.x)

### Skill Loader (L1 + L2 + L3a)

The chat agent's `ChatPlanner` discovers skills via progressive disclosure:

| Layer | Content | When loaded |
|---|---|---|
| L1 | name + description (≤ 512 chars) | session start, every planner prompt |
| L2 | full SKILL.md body | planner emits `{"action": "load_skill", "name": "X"}` |
| L3a | resource files (yaml/json/md) | auto when SKILL.md links to `resources/...`, or on `{"action": "load_resource", ...}` |
| L3b | scripts/*.py executable | NOT IMPLEMENTED in v0.9 — see Plan 2b |

Caps:
- L3a resource: **50kB hard cap per file** (rejects with `ResourceTooLargeError`)
- Nested ref depth: **≤ 2** (SKILL.md → resource → resource is rejected)
- Resource path: must stay under `<skill>/resources/` (path-traversal blocked)

7 skills are L1-discoverable: `data_analysis`, `deep_research`, `financial_analysis`, `market_data`, `risk_assessment`, `sector_analysis`, `web_research`. `risk_assessment` is the L3a demo — its `resources/risk_thresholds.yaml` carries quantitative cuts referenced by SKILL.md.

SSE event `skill_load` is emitted at L2 and L3a load points with `{name, level, size_tokens, [ref]}` payload.

### Skill Scripts (L3b sandbox)

The chat agent can execute Anthropic-style skill scripts (`backend/claude_skills/<skill>/scripts/X.py`)
through a sandboxed `SkillExecutor`.

| Surface | Guarantee |
|---|---|
| Filesystem | `cwd` is a fresh tmp dir under `backend/data/skill_workdir/`, cleaned up after run |
| Memory | RLIMIT_AS cap of 256MB (configurable) |
| CPU / wall | 30s default / 5min max; SIGKILL on overrun |
| Environment | only `PATH`/`LANG`/`LC_*` passed through; no `DASHSCOPE_API_KEY` |
| Banned APIs | `os.system`, `subprocess.*`, `socket.socket`, `urlopen`, `requests.*`, `httpx.*`, `eval`, `exec`, `__import__` rejected by static AST scan |
| stdout/stderr | stderr truncated to 2kB; stdout must be valid JSON |

Demo: `backend/claude_skills/financial_analysis/scripts/calculate_dcf.py`

## 技术栈

| 层级 | 技术 |
|---|---|
| LLM | OpenAI 兼容协议(默认阿里云百炼 Qwen,可切 OpenAI / DeepSeek / 任意兼容端点) |
| 编排 | LangGraph 1.x(Pydantic state + Send API + subgraph) |
| 数据 | Tushare Pro(13 接口:8 base + 5 v0.8.5 财务/估值/资金信号)+ Bocha Web 搜索 + Milvus 向量库 |
| 持久化 | sqlite(monitoring / cache / trace / eval) + PostgreSQL(用户/会话,可选) + Redis(可选) |
| 后端 | FastAPI + httpx async + APScheduler(B-3 cron) |
| 前端 | React 18 + Vite + Antd 5 + TypeScript strict |
| 测试 | pytest + pytest-recording(VCR) + mypy strict + ruff |
| 包管理 | uv(不用 conda) |

## Quickstart

> 以下命令假设终端 cwd = 项目根目录。

### Prerequisites

- Python 3.11+
- Node.js 20+(前端)
- [uv](https://docs.astral.sh/uv/):`curl -LsSf https://astral.sh/uv/install.sh | sh`
- (可选)Docker Desktop — 仅在用 PostgreSQL/Milvus 时需要

### 安装

**完整安装**(推荐 — 含 KB feature):

```bash
uv sync --extra dev --extra kb
uv run pre-commit install --install-hooks
uv run pre-commit install --hook-type commit-msg
cp backend/.env.example backend/.env  # 然后编辑 DASHSCOPE_API_KEY、TUSHARE_TOKEN 等
cd frontend && npm install && cd ..
```

**精简安装**(磁盘紧张 / 不需要 KB 检索 + ingest 的开发场景,如 Codespaces 32GB):

```bash
uv sync --extra dev
# /knowledge-bases CRUD 仍可用(KB metadata 操作不依赖重型 ML deps)
# 只有 KB 检索(milvus 向量搜索)+ ingest(PDF 切片)在 agent 运行时调用会 ImportError
# 这种模式适合做 #3.5 类纯 DB / cache 等不碰 KB 检索的开发工作
```

KB feature 需要 ~5-8 GB ML libs(mineru / torch / cuda 等)。如果你不会用到 KB 检索或 ingest 工作流,可以走精简安装节省空间。

### 启动

```bash
# Terminal 1 — 后端(端口 8000,API 文档 /docs)
unset all_proxy https_proxy http_proxy
uv run poe serve

# Terminal 2 — 前端(端口 5173)
cd frontend && npm run dev

# (可选)Terminal 0 — Postgres 数据库(legacy auth / news / session router 需要;仅 chat / research / monitoring 路径无需启)
docker compose up -d postgres

# (可选)Terminal 0 — Milvus / Redis(KB / 持久会话用)
./start-services.sh start
```

默认 `*_MODE=mock`,**不烧钱**;切 `TUSHARE_MODE=real` / `BOCHA_MODE=real` 走真接入。

> v0.9.x:`uv run poe serve` 启动时若 PG 未起,只会 log warning 不再硬 crash(graceful degradation)。依赖 PG 的 router(auth/news/session/database)调用时会报 500;其余路由(chat / research / monitoring / KB)正常工作。

### v1.0 监控引擎部署(2026-05-08 起)

监控引擎从 v0.8.3 进程内 APScheduler 迁到 Celery + Redis 异步任务系统,部署模型变化:

```
docker-compose up postgres redis  # infra(已有)
# 应用层 3 个进程:
make backend    # web (FastAPI) - HTTP only
make worker     # Celery worker - detection / LLM 详情卡
make beat       # Celery beat - 30min cycle / 16:30 daily / 02:00 cleanup
```

调度时区:Asia/Shanghai。盘内时段(周一到周五 9:30-15:30 每 30 分钟)自动 detection cycle。

### 常用命令(uv + poe)

| 命令 | 作用 |
|---|---|
| `uv run poe serve` | 启后端(uvicorn,hot reload,port 8000) |
| `uv run poe lint` | ruff format check + ruff check + mypy strict |
| `uv run poe format` | ruff 自动格式化 |
| `uv run poe ci` | 本地模拟 PR CI(lint + L0+L1+L2 测试) |
| `uv run poe test` | L0 unit + L1 integration + L2 cassette(不含 slow / live) |
| `uv run poe test-all` | 包含 L3 真 LLM eval(烧钱) |
| `uv run poe trace-view` | 打开 trace 查看器 |
| `uv run poe eval` | 跑 golden case 评测 |
| `make board` | 起 Harness Board(localhost:8910,自动 `open`)+ 3 视图(`/` Topology 关系图 / `/m/{dim}` 模块页 / `/story` 故事时间线) |
| `make board-test` | 跑 dashboard/ 测试套 |
| `make board-stop` | lsof port-scoped kill 8910 |
| `make board-refresh` | curl -X POST /refresh,显式 invalidate snapshot cache |
| `uv run python -m app.scripts.seed_deep_cards --seed dashboard/data/deep_cards_seed.jsonl --db backend/data/board.db` | 载入 hand-curated DeepCard(server 启动时也会自动 insert-if-missing) |
| `uv run python -m app.scripts.prefill_deep_cards --caps <ids> --db backend/data/board.db` | LLM batch prefill DeepCard(需 OPENAI_API_KEY) |

## 测试分层

| Layer | LLM mode | 速度 | 何时跑 |
|---|---|---|---|
| **L0 unit** (`backend/tests/unit/`) | none | <5s | 每次保存,每个 PR |
| **L1 integration** (`backend/tests/integration/`) | mock(deterministic) | <30s | 每个 PR |
| **L2 e2e** (`backend/tests/e2e/`) | cassette(replay) | <2min | 每个 PR |
| **L3 eval** (`backend/tests/eval/`) | live(真 API,烧钱) | 5-15min | nightly + 手动 |

**当前状态**(v0.8.5):L0-L2 全 PASS,mypy strict + ruff clean。L3 含 4 differential golden case + B-1 茅台 e2e cassette。

## 环境变量

`backend/.env`(基于 `.env.example`,本地不进 git):

| 变量 | 必需 | 说明 |
|---|---|---|
| `DASHSCOPE_API_KEY` | ✅ | LLM API key(阿里百炼 / OpenAI 兼容);B-1 /research 路由必需 |
| `DASHSCOPE_BASE_URL` | ❌ | 默认 `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `KB_MODE` | ❌ | `mock`(默认)或 `real`;real 模式需 Milvus 启动 |
| `TUSHARE_MODE` | ❌ | `mock`(默认)或 `real` |
| `TUSHARE_TOKEN` | real 需要 | Tushare Pro token |
| `TUSHARE_BASE_URL` | ❌ | 默认 `http://api.tushare.pro`,自定义代理可覆盖 |
| `BOCHA_MODE` | ❌ | `mock`(默认)或 `real` |
| `BOCHA_API_KEY` | real 需要 | Bocha Web 搜索 key |
| `EMAIL_MODE` | ❌ | `mock`(默认)或 `real` |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_FROM` | real 需要 | SMTP 配置(465 SSL 或 587 STARTTLS) |
| `MONITORING_SCHEDULER_ENABLED` | ❌ | `false`(默认)或 `true`,APScheduler cron 启动开关 |
| `MONITORING_DOGFOOD_CUSTOMERS` | ❌ | dogfood 客户 ts_code 列表(逗号分隔) |
| `MONITORING_DAILY_BUDGET_CNY` | ❌ | 日 LLM 预算上限,默认 10 CNY |

完整列表见 `backend/.env.example`。

## 项目结构

```
financial-research-assistant/
├── backend/
│   ├── app/
│   │   ├── agents/              # 7 agent + portfolio_warning schema/renderer + credit_report
│   │   │   └── research/financial_research/  # v0.8.5 Anthropic Skills bundle (17 components)
│   │   │       ├── methodology/  # 11 .md (solvency / profitability / growth / ... / decision_framework)
│   │   │       ├── references/   # industry_benchmarks.json + recommendation_rules.yaml + position_size_rules.yaml
│   │   │       └── helpers/      # compute_position_size / classify_recommendation / lookup_industry_benchmark
│   │   ├── orchestration/       # LangGraph 装配(research_graph / chat_graph)
│   │   ├── services/            # 横切服务(全 Protocol + Real/Mock + factory)
│   │   │   ├── monitoring/      # B-3 v0.8.3 — signal_rules / escalation / scheduler / notifications
│   │   │   ├── tushare_*.py     # client + cache + service + factory + mock_adapter
│   │   │   ├── bocha_*.py       # client + reliable + factory
│   │   │   ├── kb_*.py / milvus_client.py / embedding_*
│   │   │   └── llm_service.py / trace_service.py / eval_runner.py / judge.py / cost_budget.py
│   │   ├── tools/               # tool registry(行情/财务/web/KB)
│   │   ├── router/              # FastAPI routers(chat / research / monitoring / kb / auth)
│   │   ├── core/database.py     # PG ORM + monitoring.sqlite 启动初始化
│   │   ├── scripts/             # init_monitoring_tables / ingest CLI
│   │   ├── kb/ingest/           # PDF 解析 + chunking + embedding pipeline
│   │   ├── service/             # legacy mock(单数,mypy ignore)
│   │   └── app_main.py          # FastAPI entry + lifespan(可选 scheduler)
│   ├── tests/
│   │   ├── unit/                # L0 — 411+ tests
│   │   ├── integration/         # L1 — 61 tests
│   │   ├── e2e/                 # L2 — cassette replay
│   │   ├── eval/                # L3 — golden cases + LLM-as-judge
│   │   └── fixtures/cassettes/  # VCR yaml(host scrubbed)
│   └── data/                    # sqlite(gitignored)
├── frontend/
│   └── src/
│       ├── pages/{chat,research(/research history·/research/new 6-字段 form·/research/:id D 输出),monitoring,knowledge,news,...}
│       ├── api/                 # typed fetch clients
│       ├── types/               # TS schema per module
│       └── components/markdown/ # 共享 markdown 渲染
├── dashboard/                   # Harness Board(dev meta-tool,sibling 顶级目录)
│   ├── server.py                # Starlette + Jinja(GET / + /m/{dim} + /story + /cap/{id}/{expand,status,field,screenshot,related} + /refresh + /docs·/screenshots mount)
│   ├── derive/                  # path_router / capability_resolver / snapshot_builder / topology_layout / story_builder / decision_extractor / refresh_pipeline(纯函数)
│   ├── state/                   # sqlite + SnapshotRepo + OverrideRepo + DeepCardRepo + Milvus collection
│   ├── config/{dimensions,capabilities}.yaml  # ETCLOVG 7 维 + 87 capability + 5 类 derive_rule
│   ├── templates/               # base / main / _board_nav / _topology_diagram / _module_page / _capability_chip / _deep_card_inline / _field_block / story / _story_card
│   ├── static/{style.css,htmx.min.js,marked.min.js,inline-expand,context-menu,render-field,modal,toast,refresh-panel,screenshot-upload}.js
│   └── tests/                   # unit / integration / e2e,mypy strict 清洁(含 test files)
├── Makefile                     # board / board-stop / board-test / board-refresh
├── docs/
│   ├── superpowers/{specs,plans}/  # 设计文档 + 实施计划(每版本一份)
│   ├── project-story.md / .html    # 项目故事(求职 / 面试用)
│   └── ...
├── scripts/                     # check_cassette_sanitize.py / trace_view CLI / 等
├── pyproject.toml               # uv + poe + ruff + mypy 配置
├── WORKING_AGREEMENT.md         # commit message 规范、fix layer 标记规则
└── README.md
```

## 工作约定

- **fix commit body 必须含 `原因 layer: <impl|plan|spec>`** — pre-commit `commit-msg` hook 强制(WORKING_AGREEMENT § 3)
- **每个非平凡决策必须按"业界 alternatives + tradeoff + 量化评估"三维评估**(spec § 决策格式四件套)
- **测试 cwd = 项目根目录**:`uv run pytest backend/tests/...` 而非 `cd backend && pytest`
- **不在公开文档(spec / README / PR / 简历 / 博客)写"代理 / 闲鱼"等数据采购渠道**
- 完整规范见 [WORKING_AGREEMENT.md](WORKING_AGREEMENT.md)

## 文档导航

| 文档 | 内容 |
|---|---|
| [WORKING_AGREEMENT.md](WORKING_AGREEMENT.md) | commit / fix 规范 + feedback SLA |
| [docs/superpowers/specs/](docs/superpowers/specs/) | 每版本设计文档(决策四件套格式) |
| [docs/superpowers/plans/](docs/superpowers/plans/) | 每版本实施计划(task-by-task checkbox) |
| [docs/project-story.md](docs/project-story.md) | 项目故事(求职 / 面试用) |
| `.claude/projects/.../memory/` | Claude session 跨会话记忆(协作约定 / 教训沉淀) |

## v0.9 chat mode (C.1 + C.2)

Chat-first dashboard with production-style multi-turn LLM agent + escalation channel to deep research.

**Architecture:**
- Backend: FastAPI + LangGraph 1.x supervisor (context_node → planner → tool/responder), 6 tools via MCP stdio, AsyncPostgresSaver checkpointer
- Skill L1/L2/L3 progressive disclosure (description / SKILL.md / resources+scripts)
- Escalation: chat → user explicit confirm (4-class EscalationPacket) → ResearchAgent
- Frontend: React 19 + valtio stores + useChatSSE hook + AppShell + ChatPane + EscalationConfirmDialog

**Endpoints:**
- `POST /api/v0/chat` — chat SSE (NEW v0.9)
- `POST /api/v0/chat/escalate` — escalate to research SSE (NEW v0.9)
- `GET /api/v0/chats` — multi-chat list (NEW v0.9)

**Run:**
```bash
docker compose up -d postgres redis
cd backend && uv run uvicorn app.app_main:app --port 8000 &
cd frontend && npm run dev   # http://localhost:5173/chat
```

**Tests:**
- L0 unit / L1 integration: `cd backend && uv run pytest tests/`
- Frontend vitest: `cd frontend && npm test`
- Golden differential: `cd backend && uv run pytest tests/eval/`

See `docs/claude-context/v0.9-chat-c1c2-architecture.md` for the long-form architecture card.

## 许可证

MIT License

## 免责声明

本系统提供的所有数据和分析仅供参考,不构成投资建议。投资有风险,入市需谨慎。

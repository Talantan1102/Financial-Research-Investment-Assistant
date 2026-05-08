# 金融研投助手

LLM 应用 portfolio 项目 — 把多 agent 编排、上下文工程、结构化输出、评测可观测在一个金融研究场景里跑通。

**当前版本**:v1.0(持仓监控 — Trade SoT + Position materialized + 5 endpoints + 三态机 service guard)

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
                              ┌────────────────────────┐
                              │ PostgreSQL (用户数据)  │
                              │  ├─ users / sessions  │
                              │  ├─ reports           │
                              │  ├─ trades  (v1.0)   │
                              │  └─ positions (v1.0) │
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
| v0.8.5 | Constrained LLM router(plan_id 4 选 1 schema enum)+ 17-component financial_research Anthropic Skills bundle + 第 7 critic plan_correctness + LangGraph self-correcting retry edge max 2 + tool inventory 5→13 + Writer 调 Python helper 替代 LLM 算数字 | #19 |
| **v1.0** | **持仓监控数据模型 + Onboarding:Trade(SoT)+ Position(materialized 决策 1)+ 三态机 service guard(决策 2)+ 5 endpoints(POST/DELETE/PATCH trades + GET positions + POST onboarding)+ cross-user ownership 隔离** | — |

## 技术栈

| 层级 | 技术 |
|---|---|
| LLM | OpenAI 兼容协议(默认阿里云百炼 Qwen,可切 OpenAI / DeepSeek / 任意兼容端点) |
| 编排 | LangGraph 1.x(Pydantic state + Send API + subgraph) |
| 数据 | Tushare Pro(13 接口:8 base + 5 v0.8.5 财务/估值/资金信号)+ Bocha Web 搜索 + Milvus 向量库 |
| 持久化 | sqlite(monitoring / cache / trace / eval) + PostgreSQL(用户/会话/reports/trades/positions) + Redis(可选) |
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

```bash
uv sync --extra dev
uv run pre-commit install --install-hooks
uv run pre-commit install --hook-type commit-msg
cp backend/.env.example backend/.env  # 然后编辑 DASHSCOPE_API_KEY、TUSHARE_TOKEN 等
cd frontend && npm install && cd ..
```

### 启动

```bash
# Terminal 1 — 后端(端口 8000,API 文档 /docs)
unset all_proxy https_proxy http_proxy
uv run poe serve

# Terminal 2 — 前端(端口 5173)
cd frontend && npm run dev

# Terminal 0 — Postgres(必需:auth / /reports 持久化 / 用户隔离 都依赖)
docker compose up -d postgres

# (可选)Terminal 0 — Milvus / Redis(KB / 持久会话用)
./start-services.sh start
```

默认 `*_MODE=mock`,**不烧钱**;切 `TUSHARE_MODE=real` / `BOCHA_MODE=real` 走真接入。

> **PG 是必需的**(`/reports` 持久化、`/auth`、用户隔离都依赖)。`uv run poe serve` 启动时若 PG 未起只 log warning 不硬 crash(graceful degradation),但依赖 PG 的 router 调用时会报 500。
>
> **测试用独立 db `industry_assistant_test`**,由 `docker/init-db/00-create-test-db.sql` 启动时自动创建,仅 `backend/tests/e2e/test_pg_serve_path_e2e.py` 使用 — 其他测试用 sqlite-override(per-test 临时 sqlite + `dependency_overrides[get_db]`)。
>
> **Schema 管理**:v0.9.x 用 SQLAlchemy `Base.metadata.create_all()` 启动时幂等创建。alembic 留到 roadmap #3.5(DB 统一)一并引入,见 `docs/superpowers/specs/2026-05-05-v0.9+-roadmap-and-long-running-task-scheduling.md` § 6 #3.5。

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

## 测试分层

| Layer | LLM mode | 速度 | 何时跑 |
|---|---|---|---|
| **L0 unit** (`backend/tests/unit/`) | none | <5s | 每次保存,每个 PR |
| **L1 integration** (`backend/tests/integration/`) | mock(deterministic) | <30s | 每个 PR |
| **L2 e2e** (`backend/tests/e2e/`) | cassette(replay) | <2min | 每个 PR |
| **L3 eval** (`backend/tests/eval/`) | live(真 API,烧钱) | 5-15min | nightly + 手动 |

**当前状态**(v1.0):L0-L2 全 PASS,mypy strict + ruff clean。L3 含 4 differential golden case + B-1 茅台 e2e cassette。v1.0 新增 portfolio L0 unit + L1 router + L2 e2e(PG container)。

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

## 许可证

MIT License

## 免责声明

本系统提供的所有数据和分析仅供参考,不构成投资建议。投资有风险,入市需谨慎。

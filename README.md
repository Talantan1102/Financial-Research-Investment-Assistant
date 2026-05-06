# 金融研投助手

LLM 应用 portfolio 项目 — 把多 agent 编排、上下文工程、结构化输出、评测可观测在一个金融研究场景里跑通。

**当前版本**:v0.8.4(B-1 投资标的尽调 + 产品定位 reframe + 5-agent prompt 改造 + 3 differential golden)

## 三个使用模式

| 模式 | 路径 | 说明 |
|---|---|---|
| **投资标的尽调 (B-1)** | `/research` | 5-agent 流程(Planner 4 模板路由 → DataCollector → Analyst horizon-conditioned → Writer 6 字段驱动 → Critic 6 维评分),产出 `InvestmentDueDiligenceReport` Pydantic schema;6 字段 form(ts_code + horizon + objective + risk_tolerance + 持仓 + 机构类型) |
| **对话模式 (Chat)** | `/chat` | ChatAgent + planner + tool registry,自然语言问答 + 工具调用(行情/财务/web/KB) |
| **持仓预警 (Monitoring, B-3)** | `/monitoring` | 5 SignalRule 并发评分 → 红色 alert 触发 5-agent deep_dive escalation → 邮件通知;支持手动 + cron 触发 |

## 架构

```
                    ┌──────────────────────────────────────────────────────────┐
                    │ FastAPI + LangGraph 1.x orchestration                    │
                    │   ├─ ResearchAgent (5-agent + Critic 6-dim subgraph)     │
                    │   │    InvestmentDueDiligenceReport schema (v0.8.4)      │
                    │   │    Planner(4 templates) → Analyst(horizon-conditioned)│
                    │   │    Writer(6 sections) → Critic(6 scorer)             │
                    │   ├─ ChatAgent     (planner + tool registry)             │
                    │   └─ MonitoringService (signal + escalation)             │
                    └──────────────────────────────────────────────────────────┘
                                          │
   ┌──────────────────────────────────────┼──────────────────────────────────────┐
   │ 横切服务 (app/services/) — 全部 Protocol + Real/Mock + factory             │
   ├──────────────────────────────────────┼──────────────────────────────────────┤
   │ LLMService   │ TushareService  │ BochaService     │ KBService              │
   │ (OpenAI 兼容) │ (8 接口 + 缓存) │ (Web 搜索 + 4 reliability) │ (Milvus 向量库) │
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
| **v0.8.4** | **B-1 投资标的尽调极致 polish:InvestmentDueDiligenceReport + 产品定位 reframe(2 persona 共享底座)+ 5-agent prompt 改造 + 3 differential golden + /research 前端完整 user journey** | **#16** |

## 技术栈

| 层级 | 技术 |
|---|---|
| LLM | OpenAI 兼容协议(默认阿里云百炼 Qwen,可切 OpenAI / DeepSeek / 任意兼容端点) |
| 编排 | LangGraph 1.x(Pydantic state + Send API + subgraph) |
| 数据 | Tushare Pro(8 接口)+ Bocha Web 搜索 + Milvus 向量库 |
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

# (可选)Terminal 0 — Postgres 数据库(legacy auth / news / session router 需要;仅 chat / research / monitoring 路径无需启)
docker compose up -d postgres

# (可选)Terminal 0 — Milvus / Redis(KB / 持久会话用)
./start-services.sh start
```

默认 `*_MODE=mock`,**不烧钱**;切 `TUSHARE_MODE=real` / `BOCHA_MODE=real` 走真接入。

> v0.9.x:`uv run poe serve` 启动时若 PG 未起,只会 log warning 不再硬 crash(graceful degradation)。依赖 PG 的 router(auth/news/session/database)调用时会报 500;其余路由(chat / research / monitoring / KB)正常工作。

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

**当前状态**(v0.8.4):582 passed + 4 documented skip,mypy 0 errors / 308 source files,cassette 36 episodes + B-1 茅台 e2e cassette(84KB)。3 differential golden case(LLM-as-judge ic_score ≥ 9.0)。

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

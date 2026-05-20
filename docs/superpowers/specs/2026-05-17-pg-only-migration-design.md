# PG-only Migration — Design Spec

> 2026-05-17 / brainstorm session / 触发: CodeRabbit systematic review 主题 1 反向

## 0 Context

仓库现状是 **PG 主 + sqlite-variant fallback 的混合模式**:
- 主 ORM(`memory/models.py`、`models/{escalation_record,user,monitoring,trade,chat,tool_result_cache}.py`)在 18+ 处用 `UUID(as_uuid=True).with_variant(String(36), "sqlite")` / `JSONB().with_variant(JSON, "sqlite")`。
- L0/L1 测试 sqlite-override(`tests/conftest.py` 写明 "sqlite-override tests don't read POSTGRES_DB at all")。
- L2.5 真 PG fixture(`docs/claude-context/pg-test-container-pattern.md` — session-scoped 外部已起则复用 / 自起负责拆)守护 serve path。
- 8 个独立 sqlite 文件子系统:trace_service、eval_recorder、tushare_cache、quota_counter、kb/ingest cache、kb/ingest state、mock_email_notifier、prefill_deep_cards。
- LangGraph checkpointer 部分已迁(`orchestration/postgres_checkpointer.py` AsyncPostgresSaver 工厂),`router/research.py` 仍有 5+ 处 `SqliteSaver` 读 `backend/data/research.sqlite` 残留。

CodeRabbit 2026-05-17 review 报告主题 1 建议补全 sqlite fallback,本主题决策**反向** — 完全废弃 sqlite。

---

## 1 Motivation

**运维/部署收敛**:消除测试 (sqlite) 与生产 (PG) 双套维护成本。

- 类型差异:`UUID` vs `String(36)` / `JSONB` vs `JSON` 在 L0/L1 不可见,只在 L2.5 才暴露。
- 索引设计:JSONB GIN 索引在 sqlite 下无效;查询计划差异 L0 看不到。
- 迁移脚本:任何 schema 变更要 sqlite 兼容性走查,工作量 2x。
- 并发行为:PG MVCC vs sqlite 单写锁,fixture 隐藏的并发 bug 只在生产暴露。

每一项都是已经撞过的工业问题或 review 报告已经命中的 critical(参见 `docs/archive/2026-05-17-coderabbit-systematic-review.md` 主题 1)。

非动机(显式排除):
- ❌ 不为"代码简洁"(`with_variant` 18 处删掉是副产品,非目标)。
- ❌ 不为"撞工业级 PG 测试基础设施学习"(虽然有这个 side benefit)。

---

## 2 现状摸底 — Sqlite Inventory

| 类 | 子系统 | 文件 | 用途 | 替换方案 |
|---|---|---|---|---|
| A | 主 ORM `with_variant` | `memory/models.py` + `models/{escalation_record,user,monitoring,trade,chat,tool_result_cache}.py` | L0/L1 测试降级 | 删 fallback,纯 PG 类型 |
| B-1 | TraceService | `services/trace_service.py` | spans 持久化 | 新 PG 表 `trace_spans` |
| B-1 | EvalRecorder | `services/eval_recorder.py` | eval_runs + eval_cases,request_id JOIN | 新 PG 表 `eval_runs` + `eval_cases` |
| B-2 | Tushare 缓存 | `services/tushare_cache.py` | API 调用结果缓存 | 新 PG 表 `tushare_cache_v1` + TTL 列 |
| B-2 | Bocha 配额计数 | `services/quota_counter.py` | 月限额 counter | 新 PG 表 `bocha_quota_counter` |
| B-2 | KB chunk 缓存 | `kb/ingest/cache.py` | chunk → embedding 缓存 | 新 PG 表 `kb_chunk_embed_cache` |
| B-3 | KB ingest state | `kb/ingest/state.py` | (doc_id, content_hash) 去重 | 新 PG 表 `kb_ingest_state` |
| B-4 | Mock email sink | `services/monitoring/notifications/mock_email_notifier.py` | 测试 mock | 改 in-memory list |
| B-4 | Prefill script | `scripts/prefill_deep_cards.py` | 一次性 script | 改读 PG `deep_cards` 表 |
| C | LangGraph SqliteSaver | `router/research.py` L285/L373/L509/L522-557/L622-643 | research_graph history 读取 | `AsyncPostgresSaver` (已有工厂),`backend/data/research.sqlite` 抛弃 |

---

## 3 Target State

代码层不再有 `import sqlite3` / `aiosqlite` / `SqliteSaver`。

```text
backend/app/
├── models/             # 纯 PG 类型 (UUID/JSONB/ARRAY)
├── memory/models.py    # _UUID = UUID(as_uuid=True),_JSONB = JSONB()
├── services/
│   ├── trace_service.py        # SQLAlchemy + PG SessionLocal
│   ├── eval_recorder.py        # 同
│   ├── tushare_cache.py        # 同
│   ├── quota_counter.py        # 同
│   └── monitoring/notifications/mock_email_notifier.py  # in-memory
├── kb/ingest/
│   ├── cache.py        # SQLAlchemy + PG
│   └── state.py        # 同
└── router/research.py  # make_async_chat_checkpointer() (已有工厂)
```

测试:
- 删除 `tests/conftest.py` 中 sqlite-override fixture。
- L0/L1 共用 L2.5 已有 PG fixture(`_postgres_alive` + `_postgres_url`)。
- isolation:**xdist 启用时 per-worker db**(`industry_assistant_test_w{worker_id}`,session CREATE/DROP),**xdist 未启用单 db + transaction rollback**。

CI:`.github/workflows/*.yml` 把 `services: postgres` 块抽到 reusable workflow,所有 unit / integration / e2e job 共用。

文档:
- 重写 `docs/claude-context/test-db-layered-strategy.md`("L0/L1 sqlite + L2.5 PG" → 全 PG)。
- `CLAUDE.md` 卡片索引同步。
- README 启动加 `docker compose up postgres` 前置。

---

## 4 4-PR Roadmap

### PR-A — 删 ORM `with_variant` + L0/L1 fixture 切 PG(~1.5 天)

**改动面**

- 删 `with_variant` 18+ 处(7 个 model 文件)。改完纯 PG 类型(`UUID(as_uuid=True)` / `JSONB()` / `ARRAY(Text)`)。
- 改 `tests/conftest.py`:
  - 删 sqlite-override 相关 fixture(`eval_sqlite_path` 等)。
  - 新增 session-scoped PG fixture `_pg_test_db`:
    - 若 `PYTEST_XDIST_WORKER` 在 env(xdist 启用)→ db name = `industry_assistant_test_w{worker_id}`,session start `CREATE DATABASE` + session end `DROP DATABASE`。
    - 否则 → 用 `industry_assistant_test`,session start `create_all()`,test class teardown `rollback nested transaction`。
- 改 unit/integration conftest:`db` fixture 改成 `connection.begin_nested()` rollback pattern。
- CI: 将现有 e2e job 的 `services: postgres` 抽到 `.github/workflows/_pg-services.yml`(reusable),unit job + integration job 都引用。

**特别约束**

- CodeRabbit 报告主题 1 的 4 个 critical(`models/{industry_data,knowledge,memory_calibration,news}.py` 缺 fallback)在这一步**变成不需要修**(纯 PG 不需要 fallback)— 同 PR 顺手把这几个文件统一到新 pattern。

**验收**

- backend unit (~1100 test) 全绿,跟 main 0 regression。
- backend integration 全绿。
- xdist 4-worker 跑通(`pytest -n 4`)。
- `grep -r with_variant backend/app` = 0 匹配。

**风险**

- unit 总测时间 ~20s → 估 ~45-60s 单 worker / ~25-35s 4-worker。**Acceptable**(CI ~5 min)。
- transaction rollback 有边角(savepoint 嵌套深 / autocommit 操作),用现有 L2.5 fixture pattern 模板,撞了再调。

### PR-B — TraceService + EvalRecorder 迁 PG 表(~1 天)

**改动面**

- 新增 PG 表 3 张(schema 1:1 镜像现 sqlite,sql 在 `backend/app/models/observability.py`):
  - `trace_spans`:`(request_id, span_id, parent_span_id, name, started_at, ended_at, attributes JSONB, ...)`
  - `eval_runs`:`(run_id, started_at, ended_at, config JSONB, ...)`
  - `eval_cases`:`(case_id, run_id, request_id, golden_id, scores JSONB, ...)`
- `TraceService` + `EvalRecorder` 改 SQLAlchemy:
  - `record_span(...)` / `record_eval_case(...)` 接口签名不变。
  - 共用 `SessionLocal`。
- 删除现 sqlite 文件路径 fallback。
- conftest 改:`trace_service` fixture 用 PG 而非 sqlite tmp file。

**特别约束**

- Eval Pipeline 契约(`docs/claude-context/c5-plan8-eval-tests-docs-done.md` 50 golden case + 4 metric)不变。
- dev 环境 `eval.sqlite` 历史数据**抛弃**(throwaway,不写迁移脚本)。

**验收**

- `eval_runner` CLI 能跑通 50 golden case eval。
- `TraceService.query_spans` 测试全绿。
- `grep -r "import sqlite3" backend/app/services/{trace_service,eval_recorder}.py` = 0。

### PR-C — 缓存 + ingest state 迁 PG 表(~1 天)

**改动面**

- 新增 PG 表 4 张:
  - `tushare_cache_v1`:`(api, cache_key TEXT, payload JSONB, expires_at, last_used_at)`
  - `bocha_quota_counter`:`(year_month TEXT PK, used_calls INT)`
  - `kb_chunk_embed_cache`:`(chunk_id TEXT, model TEXT, dim INT, vector JSONB, created_at, PRIMARY KEY (chunk_id, model, dim))`
  - `kb_ingest_state`:`(doc_id TEXT, content_hash TEXT, last_ingest_at, PRIMARY KEY (doc_id, content_hash))`
- 改 4 个 service / module:
  - `tushare_cache.py` / `quota_counter.py` / `kb/ingest/cache.py` / `kb/ingest/state.py` → SQLAlchemy session。
- `expires_at` 列由 Celery beat task `kb_cache_expire_sweep` 每 1h 清(沿用 `chat_stale_scanner` pattern)。
- ingest CLI 改造:删 `.embedding_cache.sqlite` / `.ingest_state.sqlite` 文件路径处理逻辑。

**特别约束**

- **新约束**:ingest CLI 现在必须连得到 PG(不能完全离线跑) — 跟动机 D 一致,**acceptable side effect**。
- dev 缓存数据抛弃。

**验收**

- 4 个 module 测试全绿。
- ingest CLI 真跑一遍 13 真 corpus(`docs/claude-context/v0.7 follow-up`)。
- `grep -r "import sqlite3" backend/app/services backend/app/kb` = 0。

### PR-D — LangGraph SqliteSaver 残留 + mock/scripts + 文档收尾(~0.5 天)

**改动面**

- `router/research.py` 5 处:
  - L285 `Uses AsyncSqliteSaver` 注释 → 改 `AsyncPostgresSaver`。
  - L373 `# AsyncSqliteSaver hangs ...` 注释 → 删除(不再适用)。
  - L509-557 `_list_research_runs` → 改 `make_async_chat_checkpointer()` + `AsyncPostgresSaver.list(None)`。
  - L600-643 `_get_research_run_by_request_id` → 同。
  - 删 `backend/data/research.sqlite` 文件 + `.gitignore` 同步。
- `services/monitoring/notifications/mock_email_notifier.py` → in-memory `list[EmailMessage]`(测试可直接 inspect)。
- `scripts/prefill_deep_cards.py` → 改读 PG `deep_cards` 表(`from app.core.database import SessionLocal`)。
- 文档:
  - 重写 `docs/claude-context/test-db-layered-strategy.md`。
  - 更新 `CLAUDE.md`(卡片索引同步)。
  - 更新 `README.md` 启动步骤(增加 `docker compose up postgres` 前置)。
  - 新增 `docs/claude-context/pg-only-migration-done.md`(总卡)。

**验收**

- `grep -rn "import sqlite3\|aiosqlite\|SqliteSaver" backend/app` = 0(除了可能的 dependency vendor)。
- `grep -rn "with_variant" backend/app` = 0。
- `backend/data/research.sqlite` 不存在。
- README + CLAUDE.md + test-db-layered-strategy.md 同步到新策略。

---

## 5 跨 PR 共通约束

- **每 PR 自带验收**:全量 unit + integration 跑通 + 跟当时 main 0 regression。
- **commit 规范**:`fix/feat/refactor + 原因 layer:` hook(`refactor` 类豁免 layer marker)。
- **每 PR 合完立即同步 README / docs/claude-context**:对齐 user memory `feedback_refresh_readme_per_version`。
- **PR sequence 必须 A → B → C → D**:A 是 fixture 基础设施,B/C 依赖 A 的 PG fixture;D 收尾。

---

## 6 Brainstorm 决策记录

| # | 决策 | 备选 | 取舍理由 |
|---|---|---|---|
| 1 | Fixture isolation = per-worker db (xdist 启用) + 单 db transaction rollback (fallback) | 全 testcontainers / 全 transaction rollback | per-worker 隔离最强,fallback 单 db 兼容无 xdist;复用 L2.5 已有 fixture,跟动机 D 一致 |
| 2 | dev 历史数据**全部抛弃**,不写迁移 | 写一次性迁移 script | dev 数据 throwaway;减少 PR 复杂度;production 数据本来就是 PG |
| 3 | 不引 alembic | 趁机引入 | 沿用 `create_all()` 幂等(`v0.9.x-no-alembic-until-db-unify.md`);alembic 推到独立 #3.5 主题 |
| 4 | ingest CLI 允许依赖 PG | 改 file-based json/parquet | 跟动机 D 一致;ingest 是 dev CLI,PG 起着是 acceptable side effect |
| 5 | `scripts/prefill_deep_cards.py` 改读 PG 不砍 | 直接 cleanup | 它是 harness-board 用,user portfolio 有 reference,改读 PG 保留 |
| 6 | PR-D 把 LangGraph + mock + 文档 + scripts 合一个 | 各拆 | 这些都是 ~0.5 天的收尾,单独 PR 性价比低 |

---

## 7 Risks / Mitigations

| 风险 | 应对 |
|---|---|
| L0/L1 测试在 PG 下个别 flaky(并发 / connection pool) | xdist 上限 4-worker;每 PR 之间合 main 重跑全套;撞了用 systematic-debugging skill |
| CI 跑时间从 ~2 分钟 → 估 5-7 分钟 | acceptable;后续加 pytest-xdist。CI 失败时间不超 10 分钟仍可接受 |
| 本地 dev 必须 `docker compose up postgres` | onboarding 文档强写;`make dev` 包一层启动脚本 |
| PR-A 之后 PR-B/C 还在,trace_service 等还在用独立 sqlite | acceptable 中间态;4 PR 共 ~4 天 wall time |
| PR-C ingest CLI 必须连 PG | 接受 trade-off(动机 D);文档明写 |

---

## 8 Out of Scope

- ❌ **alembic 引入**(独立 #3.5 主题)
- ❌ **dev sqlite 历史数据迁移**(throwaway)
- ❌ **pytest 性能极致优化**(TRUNCATE vs DROP/CREATE 等微调,等真撞到 CI 慢再做)
- ❌ **PG 生产配置硬化**(connection pool size、replication、WAL retention 等,跟本主题正交)
- ❌ **`vendor/` 第三方依赖里的 sqlite 用法**(LangGraph 等本身,无关 app code)

---

## 9 Success Criteria

- ✅ `grep -rn "import sqlite3\|aiosqlite\|SqliteSaver\|with_variant" backend/app` = 0(verified 4 次,每个 PR 一次)
- ✅ backend unit + integration 全绿,跟 baseline main 0 regression
- ✅ `eval_runner` CLI 跑 50 golden case 全绿
- ✅ ingest CLI 跑 13 真 corpus 全过
- ✅ `docker compose up postgres + uv run poe serve` 能起来 + 跟现状行为一致
- ✅ `docs/claude-context/test-db-layered-strategy.md` 已重写
- ✅ `docs/claude-context/pg-only-migration-done.md` 总卡已写

---

## 10 Estimated Wall Time

| PR | Wall Time | 累积 |
|---|---:|---:|
| PR-A | 1.5 天 | 1.5 |
| PR-B | 1 天 | 2.5 |
| PR-C | 1 天 | 3.5 |
| PR-D | 0.5 天 | 4 |

总计 **~4 天 wall time**(Claude Code 加速段)。

---

## 11 简历叙事

- "把 L0/L1 测试从 sqlite-override 切到真 PG,沿用 session-scoped fixture + xdist per-worker db isolation,撞了 transaction savepoint 嵌套 / connection pool exhaustion 等真实问题。" — 撞工业级 PG 测试基础设施。
- "废 sqlite-variant fallback,model 层纯 PG,简化跨方言 schema 维护成本。" — 运维收敛。
- "把 LangGraph checkpointer 从 SqliteSaver 统一到 AsyncPostgresSaver,跨 graph(chat / research)用同一 PG 实例存 checkpoint。" — 一致的 observability 底座。

---

## 12 Implementation Plan 入口

执行用 `superpowers:writing-plans` skill 拆每 PR 的 plan。

- PR-A plan → `docs/superpowers/plans/2026-05-17-pg-only-migration-pr-a-plan.md`
- PR-B plan → 同目录 `-pr-b-plan.md`
- ...

每个 plan 包含 task 拆分 + acceptance criteria + verify 命令。

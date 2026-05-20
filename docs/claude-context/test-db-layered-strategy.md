---
name: 测试 DB 策略 — 全 PG(PR-A 2026-05-17 起)
description: L0/L1/L2.5 全部连真 PG (industry_assistant_test),通过 db_session fixture transaction rollback 保 isolation;sqlite-override 时代终结
type: project
---
测试 DB 策略**统一 PG** — 所有需要 DB 的 unit/integration/e2e test 接受 `db_session` fixture(SQLAlchemy Session,fixture 末 rollback,跨 test isolation)。

**Why**(运维/部署收敛):消除测试 sqlite 与生产 PG 的双套维护成本(UUID/JSONB/ARRAY 类型差异、JSONB GIN 索引、PG MVCC 并发行为 — 之前全部要 sqlite/PG 各走一遍 schema 验证)。`with_variant(String(36), "sqlite")` 在 PR-A 全删,30+ 处 fallback 噪音清零。

**How to apply 决策树**:
- 任何需要 DB 的 unit/integration test → 接 `db_session: Session` fixture(`backend/tests/conftest.py:323`)
- Router test 用 FastAPI `TestClient` → `app.dependency_overrides[get_db] = lambda: db_session`
- L2.5 真 PG e2e(`test_pg_serve_path_e2e.py`) → 仍用 `pg_test_container` fixture(覆盖 serve path lifespan,db_session 不替代它)
- 数据层 cassette → L2 cassette(`backend/tests/e2e/test_*_cassette.py`,跟本主题正交)

**Fixture stack(`backend/tests/conftest.py:243+`)**:
- `pg_test_container` (session-scoped) — 启动 docker compose postgres,等 healthy,**返回 url dict**
- `pg_test_engine` (session-scoped) — 基于 url 起 SQLAlchemy engine + `DROP SCHEMA public CASCADE` + `create_all`(避免跨 session 旧 schema 残留)
- `db_session` (function-scoped) — `connection.begin()` outer transaction + `sessionmaker(bind=connection)` session + test 末 `rollback` + `connection.close()`

**xdist per-worker db isolation** 留 follow-up plan(pytest-xdist 未装,本 PR 只走单 db + transaction rollback)。

**本地启动**:`docker compose up -d postgres` 一次(或者直接让 `pg_test_container` fixture 自动起容器)。

参考 spec/plan:
- `docs/superpowers/specs/2026-05-17-pg-only-migration-design.md` § 4 PR-A
- `docs/superpowers/plans/2026-05-17-pg-only-migration-pr-a-plan.md`
- 残留 sqlite子系统(trace_service / eval_recorder / tushare_cache / quota_counter / kb_ingest_state / kb_chunk_embed_cache / mock_email_notifier / scripts/prefill_deep_cards 等)在 PR-B/C/D 处理。

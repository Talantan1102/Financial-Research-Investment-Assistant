---
name: PG-only Migration PR-A 落地
description: 主 ORM with_variant fallback 30+ 处全删 + L0/L1 测试 fixture 切真 PG + CI services 更新 + 19 个 unit test 文件迁 db_session
type: project
---
**结论**:删主 ORM 所有 `with_variant` fallback,L0/L1 测试切到真 PG(`pg_test_engine` + `db_session` fixture),CI services: postgres 已 cover。`grep -rn with_variant backend/app` = 0。

**Why**:运维/部署收敛(spec § 1)— 消除测试 sqlite 与生产 PG 的双套维护成本(类型差异 / 索引设计 / 迁移脚本 / 并发行为)。

**How to apply**:测试需 DB → 用 `db_session` fixture(`backend/tests/conftest.py:323`)。本地 dev 必须 `docker compose up -d postgres`(fixture 也会自动起,但 dev 一次性起着更快)。

**Wall time**:~1.5 天(实际 14 task,从摸底到 PR 全跑通)。

**Verify**:
- `grep -rn with_variant backend/app` = 0
- backend unit 1100+ pass,跟 main 0 regression
- ruff + mypy clean
- CI services: postgres + conftest `_ensure_test_db_exists` 自动建 test db,无需手动 init

**Out of scope(后续 PR)**:
- PR-B:TraceService + EvalRecorder 迁 PG 表
- PR-C:tushare_cache / quota_counter / kb_chunk_embed_cache / kb_ingest_state 迁 PG 表 + Celery beat expire sweep
- PR-D:LangGraph `SqliteSaver` 残留(`router/research.py` 5+ 处)+ mock_email_notifier in-memory + scripts/prefill_deep_cards 改读 PG + 文档收尾(写"PG-only 全部 done"总卡)

**xdist per-worker db**:本 PR 走单 db + transaction rollback(SQLAlchemy `connection.begin()` outer transaction)。pytest-xdist 未装,xdist isolation 留独立 follow-up。

参考:
- spec:`docs/superpowers/specs/2026-05-17-pg-only-migration-design.md`
- plan:`docs/superpowers/plans/2026-05-17-pg-only-migration-pr-a-plan.md`
- review 报告:`docs/archive/2026-05-17-coderabbit-systematic-review.md`(本 PR 主题 1 反向触发)

---
name: PG-only Migration PR-B 落地
description: TraceService + EvalRecorder 从 sqlite3 raw API 迁到 SQLAlchemy ORM + PG;顺手修 CodeRabbit SQLi critical
type: project
---
**结论**:`trace_service.py` + `eval_recorder.py` 从 sqlite3 raw API 迁到 SQLAlchemy ORM + PG。新增 `TraceSpanRow` + `EvalResultRow` ORM model 到 `app/services/trace_models.py`(跟 MCPToolCallLog 同文件)。所有 `import sqlite3` 在 trace/eval 子系统已清。

**Why**:PG-only migration spec § 4 PR-B(运维/部署收敛主线)。同时修 CodeRabbit 主题 4 critical:`query_spans` filter dict 原直接拼 SQL → SQL injection。新版用 `_ALLOWED_FILTER_KEYS` whitelist + ORM column filter,拒绝任意未声明 key。

**How to apply**:
- **新 API**:`TraceService(session_factory: Callable[[], Session])`,生产传 `SessionLocal`,测试传 `lambda: contextlib.nullcontext(db_session)`
- **schema**:`trace_spans` (PK span_id) + `eval_results` (PK eval_id),`request_id` 仍是 JOIN 桥(spec § 9 契约保留)
- **删 `tmp_eval_db` fixture**:8 个测试已迁,fixture 在 `backend/tests/conftest.py` 删
- **production caller 无需改**:`TraceService` / `EvalRecorder` 在生产代码只作 type hint 注入参数,没有构造点;改动只影响测试

**Verify**:
- `grep -rn "import sqlite3" backend/app/services/{trace_service,eval_recorder}.py` = 0
- backend unit + integration 0 regression(unit 2 pre-existing fail 跟 main 一致)
- ruff + mypy clean

**Out of scope(下个 PR)**:
- PR-C:tushare_cache / quota_counter / kb_chunk_embed_cache / kb_ingest_state 迁 PG 表
- PR-D:LangGraph `SqliteSaver` 残留 + mock/scripts + 文档总卡

参考:
- spec:`docs/superpowers/specs/2026-05-17-pg-only-migration-design.md` § 4 PR-B
- CodeRabbit review 主题 4 critical(`docs/archive/2026-05-17-coderabbit-systematic-review.md`)
- 基线 PR:#68(PR-A)

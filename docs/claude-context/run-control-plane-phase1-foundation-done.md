---
name: Run Control Plane Phase 1 foundation ship 完
description: Tenant、Run 数据骨架与六个 production v1 Run API 已落地；只提供 PostgreSQL 控制面基础，不执行模型或调度
type: project
---

**结论:** Run Control Plane Phase 1 foundation 已落地。production app 注册 Tenant API 与严格六个 Run API；PostgreSQL 持久化 Tenant、Session、Message、Run、Attempt、Pause、Event，服务层守住租户权限、幂等创建、同 Session 单活跃 Run、不可变修订关系与 durable lifecycle event。本阶段的 Run 只会进入 `queued` 或由测试 fake 驱动生命周期，不会执行模型。

**Why:**

- HTTP Run API 与旧 `ChatTask`/`/api/v0/chat` 并存但完全隔离；Phase 1 没有删除、重定向或迁移旧 chat 数据，切换和删除仍属于 Phase 3。
- PostgreSQL 是新控制面的唯一事实源。`POST /runs` 在一个 async transaction 中写 user message、queued Run 与 `run.created` event；同 Tenant/用户/idempotency key replay 返回同一 Run，不同 payload 冲突。
- production lifespan 先建立共享 `db_async_engine` 与 `async_session_factory`，再构造 `ChatSessionRepo`。因此 legacy repo 初始化失败不会清空 Run API 的 session factory；shutdown dispose 同一共享 engine。
- `app.models` barrel 注册 9 张 foundation tables，现有 `Base.metadata.create_all()` import chain 能看到全部新模型；本阶段不引入 Alembic。
- production OpenAPI 精确包含 6 个 Run operations：create、get、events、trace、cancel、resume，没有 steering 或 scheduler endpoint。

**How to apply:**

- Phase 1 的 Run API 可以用于创建、查询、读取 durable SSE snapshot/trace、取消和恢复；不要把 `queued` 解释成已有 worker 执行。
- 不要声称本卡交付了 Scheduler、Dispatcher、Outbox、Worker/lease/claim、Redis token stream、Celery Run 执行或 LLM 调用；这些均未接线、未验证。
- Phase 2 Scheduler 只读 `runs.status == "queued"` 候选，通过新 scheduling service 创建 Attempt/lease/Outbox，并调用 `RunService.transition_run()`；Worker claim 必须是原子接口，Worker 不直接更新 Run。
- Phase 2 的 scheduling/claim/recovery 继续复用 Run row lock 与 durable event append；cancel/resume Outbox 写入应加入现有事务，不能改 Phase 1 API path 或 response model。

**Phase 1 commits:**

| 范围 | commit |
|---|---|
| lifecycle types + exhaustive matrix | `76a4d577`, `23a49e72` |
| tenant model/service + final-owner serialization | `6cc3c744`, `82551e5c` |
| personal tenant bootstrap | `7cd8a81a` |
| tenant API + conflict narrowing | `b4e14401`, `86de225f` |
| Run models + provenance constraints | `e7791f42`, `5858cb20` |
| atomic create/query service | `566ca5e3` |
| durable lifecycle commands | `47eef16d` |
| six Run API + terminal SSE drain | `29f26601`, `b6b44bc2` |
| Task 8 evidence | `b4838864` |
| production wiring + final evidence | `feat(run): complete phase 1 foundation` |

**Verification evidence (2026-07-16):**

- Plan unit scope: `200 passed`, exit 0.
- Plan integration scope: `49 passed`, exit 0. This includes 4 production wiring/metadata/OpenAPI tests.
- `ruff format --check` on the exact plan scope: 547 files formatted, exit 0. The first run found two Tasks 5 files and they were mechanically formatted before rerun.
- `ruff check` on the exact plan scope: `All checks passed!`, exit 0.
- `mypy` on the exact plan scope: `Success: no issues found in 7 source files`, exit 0.
- Explicit production probe: `run_operation_count=6` and `missing_foundation_tables=[]`, exit 0.
- Wider `pytest backend/tests -q` was attempted but did not execute tests: collection stopped with 28 errors because the dev environment lacks KB optional dependencies (`langchain_text_splitters`, `pymilvus`) and Windows lacks the POSIX `resource` module used by the sandbox. Do not report the wider backend suite as passing.

**Observed warnings / boundaries:**

- Passing scoped pytest runs retain existing SQLAlchemy `declarative_base()`, Pydantic class config and `datetime.utcnow()` deprecation warnings.
- The first ad-hoc OpenAPI probe lacked `PYTHONPATH=backend` and failed to import `app`; the corrected probe set `PYTHONPATH` and passed. This was a command-environment error, not an application failure.
- No Scheduler, Worker, Redis, Celery Run execution or LLM live path was started by the Phase 1 acceptance commands.

**Anchors:**

- spec: `docs/superpowers/specs/2026-07-16-run-control-plane-design.md`
- plan: `docs/superpowers/plans/2026-07-16-run-control-plane-phase1-foundation.md`

---
name: Run Control Plane Phases 2-4 completion
description: Scheduler/worker execution, chat cutover, observability and legacy retirement are complete; acceptance evidence and remaining environment limits are recorded here.
type: project
---

**结论:** Run Control Plane Phase 2–4 已完成。PostgreSQL 是 Run/Attempt/Event/Outbox 的事实源；Redis 只承担可重放通知；两个 Scheduler、Dispatcher、两个 chat Worker 和 Run API 通过独立进程运行。Phase 4 完成迁移、cutover gate、观测、故障注入和 legacy chat execution retirement。旧 `/api/v0/chat` 执行路由、旧 ChatTask worker/bus/repository、旧清理脚本以及前端执行元数据已移除。

**Why:**

- 前端只提交 Run 命令并读取六个 Run API；执行不再绑定 FastAPI 请求进程或旧 ChatSession runner。
- 调度、租约、取消、暂停/恢复、人工审批和补充信息均落在可审计的 Run 状态机与事件流中，能够横向增加 Scheduler/Worker 副本。
- legacy 数据迁移采用持久化 mapping、租户/成员关系校验、隔离 quarantine、证据计数和受保护 cleanup；未知外部 FK 或缺少显式确认时 fail closed。

**进程拓扑:**

```text
React frontend
      │ six Run operations + SSE snapshot/cursor
Run API ─────── PostgreSQL (authoritative state)
      │                 │
      └──── Redis Streams (replayable notification only)
              ├─ Scheduler A / Scheduler B
              ├─ Dispatcher
              └─ Chat Worker A / Chat Worker B
```

**已交付提交:**

- Phase 2 scheduling: `553ab4bb` … `a3e8ff18`（含正式镜像/多进程验收提交 `416bba6b`, `da37e370`）。
- Phase 3 chat integration: `a47f9c91` … `f30a83e8`。
- Phase 4 Task 1 foundation: `3059b666`, `02c01b93`, `c95ea1f3`, `ca046dff`。
- Phase 4 Task 2 revision/fence/schema: `a89e434c`, `cb98a859`, `7e252e4b`, `8e104521`, `20740dfb`, `60e7dcd4`。
- Phase 4 Task 3 observability: `cc189614`, `f0847160`, `673d7d00`, `0ba2dfbd`, `2194d91`, `0ed72a81`, `779f6eb7`, `1cdc4285`。
- Phase 4 Task 4 chaos/evidence: `6a01480d`, `b76f91b3`, `644f173e`, `0b4431d4`, `236bad9d`, `ff64c708`, `2ab5f0ea`, `9380adfb`。
- Phase 4 Task 5 migration/cutover: `b905595a`, `ae40bc6e`, `c437b421`, `a83d840b`, `62fb6b73`, `6bc287fa`, `9ae7e4e4`, `3ad7f920`。
- Phase 4 Task 6 legacy retirement: `fd755973`, `d005710f`, `3a491699`。

**可复现验收证据:**

- Phase 2–3 计划范围与真实 Redis/多进程门禁：ledger 记录的最终分组均通过；Phase 3 Compose OS 多进程 harness `1 passed`，正式镜像 fresh 轮次为 `9 passed, 2 skipped`。
- Phase 4 Task 1：最终 focused unit/real-PG/router `151 passed`。
- Phase 4 Task 2：启动/Schema PG `50 passed`，后端受影响范围 `337`，前端受影响范围 `37/37`；全前端 `321/323`，剩余为既有 baseline failure。
- Phase 4 Task 3：metrics/log real-PG/API `11 passed`，并通过 scheduling/attempt 矩阵。
- Phase 4 Task 4：chaos/helper `14 passed`；13 个场景 wiring、bounded process-tree timeout、project-scoped cleanup 通过。
- Phase 4 Task 5：migration/cutover targeted `18/18`（当前 cutover/no-legacy 回归 `4 passed`）；changed-file Ruff、mypy 通过。
- Phase 4 Task 6：OpenAPI/import/gate `3 passed`；compileall、Ruff、mypy、frontend `tsc --noEmit` 和生产 `npm run build` 通过。
- 当前可重跑命令：

  ```powershell
  uv run pytest -q backend/tests/integration/test_no_legacy_chat_execution.py backend/tests/integration/test_run_cutover_gate.py --basetemp=.pytest-task7a
  uv run ruff check backend/app
  uv run mypy backend/app/scripts/verify_run_cutover.py backend/app/scripts/migrate_legacy_chat_to_runs.py
  cd frontend; npx tsc --noEmit; npm run build
  ```

**未运行或受环境阻塞的验收:**

- 本轮未虚报 live PostgreSQL/Compose green。一次 disposable PostgreSQL/Compose 尝试被 Docker containerd 的 PostgreSQL image blob I/O error 阻塞；已有容器也未提供可复用 host port。应在 Docker registry/daemon 恢复后重跑 Phase 4 Task 4/5 live suites。
- 真实 LLM/API smoke 需要租户、认证和模型凭据，本地未执行；cassette/mock 路径仍由 scoped tests 覆盖。
- 前端 build 有既有 Vite warning（`%VITE_TITLE%` 未定义、chunk 较大），不影响 exit 0。

**Operator commands:**

```powershell
docker compose --profile run-control up -d --wait run-api run-scheduler-a run-scheduler-b run-dispatcher run-worker-a run-worker-b
docker compose --profile run-control run --rm run-control-init
docker compose --profile run-control down --remove-orphans
$env:PYTHONPATH="backend"; uv run python -m app.scripts.verify_run_cutover --help
$env:PYTHONPATH="backend"; uv run python -m app.scripts.migrate_legacy_chat_to_runs --help
```

**Remaining Minor risks:**

- Compose/live PG proof must be repeated in a healthy Docker environment; this is an environment gate, not a claimed application failure.
- 默认 Compose executor 是 deterministic simulated mode；生产 chat executor 需显式设置 `RUN_EXECUTOR_MODE` 并提供对应 credentials。
- 历史 reports/agent schema 中保留少量名为 legacy 的数据字段兼容读取；它们不是执行路径，cutover gate 会持续阻止旧 router/worker/bus 重新注册。

**Anchors:**

- spec: `docs/superpowers/specs/2026-07-17-run-control-plane-phase4-cutover-chaos.md`
- plan: `docs/superpowers/plans/2026-07-17-run-control-plane-phase4-cutover-chaos.md`
- progress: `.superpowers/sdd/phases2-4-progress.md`

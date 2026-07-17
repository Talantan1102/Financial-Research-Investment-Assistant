---
name: Run Control Plane Phase 2 scheduling ship 完
description: PostgreSQL-authoritative Scheduler、Worker lease、Redis Outbox 与可自举多进程模拟执行链已落地
type: project
---

**结论:** Run Control Plane Phase 2 scheduling 已落地。queued Run 现在可由两个 Scheduler 公平分配，经 PostgreSQL Outbox 和 Redis Stream 通知两个独立 Worker；Worker 必须先原子 claim Attempt 才执行，执行期间续租，最终通过公共 AttemptService 完成。Redis 只做可丢失、可重复的加速通知，Run/Attempt/Event/Outbox 的最终事实仍在 PostgreSQL。本阶段只跑模拟 executor，不调用 Chat Loop、模型 API 或真实 token SSE。

**Why:**

- Scheduler 每轮先回收过期 lease，再调用 `schedule_once()` 直到没有即时工作；空闲时等 Redis wake Stream 或 PostgreSQL poll timeout。两个 Scheduler 同时运行仍由服务层行锁、`SKIP LOCKED`、Worker 容量复查和 Session 单活索引守住原子性。
- Worker 每次进程启动通过 WorkerRegistry 生成新 UUID，注册 heartbeat/capacity；Assignment 用 Redis consumer group + `XREADGROUP`，启动/重连时用 Task 5 `recover_pending()`，处理后用 `acknowledge_and_delete()`，正常 drain 后用 `delete_stream()`。进程代码不直接写 ORM。
- duplicate Assignment 必须再次调用 PostgreSQL claim；只有第一个 claim 可执行。旧 Worker 的 lease/token 过期后不能完成，Scheduler 最多自动 retry 一次。
- Compose `run-control` profile 提供 init、scheduler-a/b、dispatcher、worker-a/b。Worker UUID 不写在配置中；每个 Worker 在启动时注册。PG/Redis 容器名和宿主端口可覆盖，便于随机 project 隔离验收且默认开发配置不变。
- 轻量 run-control image 使用 `RUN_CONTROL_MINIMAL_IMPORTS=1`，只跳过 `app.models` legacy barrel 的 memory/业务重依赖；默认 web/test import 行为不变。User mapper 仍注册 Chat/Knowledge relationship target，避免 SQLAlchemy mapper 缺失。

**How to apply:**

- 启动：`docker compose --profile run-control up -d --wait run-scheduler-a run-scheduler-b run-dispatcher run-worker-a run-worker-b`。共享 PostgreSQL/Redis 参数走 `RUN_CONTROL_*`、`POSTGRES_*` 和 `REDIS_URL`；不要硬编码 Worker identity。
- 可复现 L2.5：设置 `RUN_CONTROL_COMPOSE_SELF_BOOTSTRAP=1` 后运行 `pytest backend/tests/integration/test_run_control_multi_process.py -q`。harness 会选择随机 project/container/宿主端口，从空 volume build/up，自动演练并发、duplicate、kill/retry、Redis restart/Outbox、同 Session 串行，最后无条件 `down -v --remove-orphans`。
- 模拟执行指令支持 delay/result/crash。delay 期间按固定间隔调用 `AttemptService.renew()`；result 只走 `complete_simulated()`；crash 不写终态，留给 lease recovery。
- Phase 3 才接真实 Chat Loop、steering/token stream、usage/trace 与 HTTP chat cutover。不要把本卡解释成真实 LLM 执行已上线。

**真实多进程验收（2026-07-17）:**

- 空环境 self-bootstrap Compose L2.5：`5 passed, 1 skipped`，55.3 秒。通过的 Compose case 实际启动 2 Scheduler + 1 Dispatcher + 2 Worker；skip 是另一个只审计外部预置事实的可选 case。
- 两个不同 Session 的 Run 分别由两个 Worker 完成，执行区间重叠；每个 Run 精确 1 Attempt、4 Event，Assignment Outbox delivered + acknowledged。
- 合法 duplicate envelope 再次 XADD 后 Stream `XLEN=0`、`XPENDING=0`；PG 仍是 1 Attempt、4 Event、1 个 `run.completed`。
- Worker 容器在 Attempt 1 running 时被 `docker kill`；lease 到期后 Attempt 1 `lost`、Run `run.requeued/retry_count=1`，Attempt 2 由另一 Worker 完成。另一次手工双 kill 演练得到 2 个 `lost` Attempt、7 Event 与最终 `failed/worker_lease_expired`。
- Dispatcher 停止时 Scheduler 仍把 Run/Attempt/Assignment Outbox 原子写入 PG，Outbox 为 `delivery_attempts=0/delivered=NULL/acknowledged=NULL`；真实重启 Redis 并恢复 Dispatcher 后，同一 Outbox 变为 `attempts=1/delivered=true/acknowledged=true`，Run 完成。
- 同 Session 的第一个 Run running 时插入第二个 active Run，PostgreSQL 精确报 `duplicate key value violates unique constraint "uq_run_one_nonterminal_per_session"`；第一个终态后第二个才可执行，时间区间无重叠。

**Verification:**

- Task 1–6 隔离 PostgreSQL/Redis 矩阵：`291 passed, 2 skipped`，151.5 秒。两个 skip 均为显式 opt-in Compose case；self-bootstrap case 已单独 fresh 运行。
- Task 6 deterministic 默认层：`4 passed`；self-bootstrap opt-in 层：`5 passed, 1 skipped`。
- Ruff format：`9 files already formatted`；Ruff lint：`All checks passed!`。
- mypy：`Success: no issues found in 6 source files`。
- PyYAML parse、`docker compose --profile run-control config --quiet`、`git diff --check`：exit 0。
- 所有随机验收 project/container/volume 已清理；原 `industry_postgres`、`industry_redis` 保持原 PID/容器并持续 healthy。
- 通过测试仍显示仓库既有 SQLAlchemy `declarative_base()`、`datetime.utcnow()`、Pydantic class-config 与 testcontainers decorator deprecation warnings。

**路径说明:** 计划指定 `docs/claude-context/`，目标分支现有 Phase 1 卡和全部长期卡也实际位于该目录；最新外部 AGENTS 文本写成 `docs/Codex-context/`。本卡遵循当前分支真实目录，未在同一仓库再创建第二套近似目录。

**Anchors:**

- spec: `docs/superpowers/specs/2026-07-17-run-control-plane-phase2-scheduling-design.md`
- plan: `docs/superpowers/plans/2026-07-17-run-control-plane-phase2-scheduling.md`
- acceptance: `backend/tests/integration/test_run_control_multi_process.py`

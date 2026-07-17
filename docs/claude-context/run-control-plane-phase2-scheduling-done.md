---
name: Run Control Plane Phase 2 scheduling ship 完
description: PostgreSQL 权威调度、可恢复多进程、取消流与正式镜像验收已落地
type: project
---

**结论:** Phase 2 scheduling control plane 已落地。Run 通过真实 FastAPI 创建后，由两套 Scheduler、Dispatcher 和 Worker 进程完成调度；PostgreSQL 保存 Run/Attempt/Event/Outbox 权威状态，Redis Stream 只做可重复、可恢复的通知加速。本阶段 executor 仍是确定性模拟实现，不接真实 Chat Loop 或模型 API。

**Why:**

- Scheduler、Dispatcher 对明确的 PostgreSQL/Redis 连接故障做有上限指数退避；未知编程异常继续抛出。进程健康 marker 只有在 PostgreSQL 与 Redis 都近期成功时才刷新，任一依赖失败立即删除。
- Compose health 使用 `python -S` 执行纯 stdlib marker freshness probe，不 import app、Redis 或 SQLAlchemy；本地正式镜像 5 次 cold probe 为 227–264ms，health timeout 为 3 秒。
- dependency freshness 默认值为 `2 * heartbeat interval + 1s`，显式配置必须至少为 heartbeat 的 2 倍；Compose 使用 0.5 秒 heartbeat 与 2 秒 freshness，给调度抖动留出余量。
- Worker 按 capacity 并发执行；满载时仍持续做数据库 heartbeat 与 Redis ping。SIGTERM 后先 drain，XREAD 已返回但尚未派发的消息不再 claim，再在 bounded grace 内等 in-flight，最后 offline，且不整删 assignment stream。
- 每个 claimed Attempt 同时消费 `run:attempt:{attempt_id}:control`。Cancel 会中止 executor，经 `AttemptService.acknowledge_cancel()` 落库，再走 Task 5 ack/delete；assignment/control 两类 Stream 在 Redis 重连后都会 ensure group 和 recover pending。
- renew interval 必须短于 lease duration。Worker kill 后过期 lease 最多重试一次；第二个 Attempt 也丢失时 Run 终止为 failed。

**How to apply:**

- 启动：`docker compose --profile run-control up -d --wait run-api run-scheduler-a run-scheduler-b run-dispatcher run-worker-a run-worker-b`。
- Fresh gate：设置 `RUN_CONTROL_COMPOSE_SELF_BOOTSTRAP=1` 后运行 `uv run pytest backend/tests/integration/test_run_control_multi_process.py -q`。harness 使用随机 project、随机端口和非默认 PG 用户/密码/库名；SQL 只 seed user、tenant、membership，Run 全部经 HTTP POST 创建并由 GET 校验。
- 镜像默认 base 已 pin 官方 `python:3.12.11-slim-bookworm` manifest digest `sha256:519591d...`。`RUN_CONTROL_PYTHON_IMAGE` 只用于显式信任的 registry mirror override。
- 依赖由 `uv.lock` 的 `run-control` group 通过 `uv sync --frozen --only-group run-control` 安装。镜像以 `runcontrol` non-root 用户运行，不复制 tests/helpers。
- PR workflow 有独立 `run-control-compose` job。当前证据是本地 CI-equivalent，不代表 GitHub Actions 远程 job 已经 green。
- harness 的跨事务 Outbox 断言统一使用 bounded eventual wait，并在超时时附带最后一条数据库事实。清理会 bounded retry `down -v --remove-orphans`，记录 stdout/stderr，并按 Compose project label 审计 containers、networks、volumes；场景失败与清理失败会同时保留。

**真实验收（2026-07-17）:**

- 正式 Dockerfile 结构镜像 locked build 成功。最终审计镜像 `financial-research-run-control:review4`，ID `sha256:825a976916efea7b5aa38aeacf4d35598476983e9ac68fc1931b7b6878ee5667`，运行时为 Python 3.12.13、用户为 `runcontrol`；history 含 `uv sync --frozen --only-group run-control --no-install-project`。
- 本地结构镜像使用显式信任的 mirror digest `sha256:57cd7c...`，其前四个 RootFS layer 与本地 mirror base 一致。默认供应链 pin 仍是 Docker Registry API 返回的官方 `python:3.12.11-slim-bookworm` digest `sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7`；本地从 mirror 拉取该官方 digest 因 TLS handshake timeout 失败，因此不声称本地镜像运行的是 3.12.11。
- 正式结构镜像、空随机 Compose 连续三轮 fresh 均为 `9 passed, 2 skipped`，总耗时 422.6 秒。两个 skip 分别是外部 fact IDs audit 与 cleanup failure injection；self-bootstrap 实际通过。
- 不同 Session 并行完成；duplicate Assignment 最终同时满足 `XLEN=0`、`XPENDING=0`，且只产生一次 Attempt/完成事件。同 Session 的第二个 active Run 由 API 返回 409。
- Worker kill 后 Attempt 1 lost、Attempt 2 完成；双 kill 得到两个 lost Attempt 和 failed Run，随后 Worker 重建。
- running Cancel 在 3 秒窗口内完成且 cancel Outbox acknowledged；单 Worker `capacity=2` 时两个 Run 真实重叠。
- Redis durable-Outbox 场景在 assigned 后捕获唯一原始 `attempt_id` 与 `outbox_id`，仅把该 Attempt lease 延长 90 秒以隔离 lease recovery；恢复时严格等待同一 Outbox 行 delivered/acknowledged，最终 Run 只有原始 Attempt。Redis stop 后相关进程仍 running 但 health 转非 healthy，恢复后同容器 ID 全 healthy。
- PostgreSQL stop 后六个服务仍 running 且 health 转非 healthy；恢复后同容器 ID、合法 RestartCount、全部 healthy，新 HTTP Run 完成。
- 单 Worker 满载执行 5 秒，跨过 3 秒 health TTL 仍保持 healthy，证明满载循环继续探测 PG/Redis。
- SIGTERM 时序测试明确输出 `claims_after_shutdown=0`；阻塞 executor 测试证明 drain 先发生、grace 内完成后才 offline，stream 未整删。
- cleanup failure injection 在 Compose `up/health` 后主动失败，finally 清理与资源审计实跑通过：`1 passed`，27.1 秒。fake runner 单测覆盖第一次 `down` 失败后重试成功，以及永久失败保留 stdout/stderr 与残留资源事实。
- Task 1–6 相关矩阵：331 passed，3 skipped，144.1 秒。true-Redis 显式使用 `REDIS_URL=redis://127.0.0.1:6379/15`。
- Ruff 全仓 format/lint 通过；本次 production process/executor targeted mypy 通过。Windows 全仓 mypy 的既有 POSIX/旧测试类型错误不计作本次通过。
- 随机验收 containers/networks/volumes 均已清理；原 `industry_postgres`、`industry_redis` 容器 ID 未变且保持 healthy。

**CI 口径:** 新增 workflow job 的构建参数、locked build 和 self-bootstrap 命令已在本地等价执行并通过；本轮没有触发 GitHub Actions，因此不声称远程 CI green。

**Anchors:**

- spec: `docs/superpowers/specs/2026-07-17-run-control-plane-phase2-scheduling-design.md`
- plan: `docs/superpowers/plans/2026-07-17-run-control-plane-phase2-scheduling.md`
- acceptance: `backend/tests/integration/test_run_control_multi_process.py`

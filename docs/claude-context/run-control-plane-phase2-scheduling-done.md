---
name: Run Control Plane Phase 2 scheduling ship 完
description: PostgreSQL 权威调度、可恢复多进程、取消流与自举验收已落地
type: project
---

**结论:** Phase 2 scheduling control plane 已落地。Run 通过真实 FastAPI 创建后，由两套 Scheduler、Dispatcher 和 Worker 进程完成调度；PostgreSQL 保存 Run/Attempt/Event/Outbox 权威状态，Redis Stream 只做可重复、可恢复的通知加速。本阶段 executor 仍是确定性模拟实现，不接真实 Chat Loop 或模型 API。

**Why:**

- Scheduler、Dispatcher 对明确的 PostgreSQL/Redis 连接故障做有上限指数退避；未知编程异常继续抛出。健康检查读取持续刷新的时间戳，不再依赖启动时一次性 ready 文件。
- Worker 注册 heartbeat/capacity，按 capacity 并发执行；收到退出信号后先 drain、停止新 claim，再在 bounded grace 内等待 in-flight，且不会删除仍可能包含未读消息或 PEL 的 assignment stream。
- 每个已 claim Attempt 同时消费 `run:attempt:{attempt_id}:control`。Cancel 会中止 executor，经 `AttemptService.acknowledge_cancel()` 落库，再走 Task 5 ack/delete；assignment/control 两类 Stream 在 Redis 重连后都会 ensure group 和 recover pending。
- renew interval 必须短于 lease duration，并在执行时间边界前续租。Worker kill 后过期 lease 最多重试一次；第二个 Attempt 也丢失时 Run 终止为 failed。
- Compose 服务均有 restart policy、真实 healthcheck 和一致的可覆盖 PG 参数。`run-api` 使用签名 JWT actor，并由 RunService 校验数据库 tenant membership。

**How to apply:**

- 启动：`docker compose --profile run-control up -d --wait run-api run-scheduler-a run-scheduler-b run-dispatcher run-worker-a run-worker-b`。
- Fresh gate：设置 `RUN_CONTROL_COMPOSE_SELF_BOOTSTRAP=1` 后运行 `uv run pytest backend/tests/integration/test_run_control_multi_process.py -q`。测试侧为收集阶段提供安全的本地 PG fallback，harness 内仍使用随机 project、随机端口、非默认 PG 用户/密码/库名。
- 镜像默认使用官方、版本固定且可覆盖的 Python base；依赖由 `uv.lock` 的 `run-control` group 通过 `uv sync --frozen --only-group run-control` 安装。镜像以 non-root 用户运行，不复制 tests/helpers。
- PR workflow 有独立 `run-control-compose` job，显式启用 self-bootstrap；默认测试文件仍包含 deterministic tests，不会出现整文件静默 skip。

**真实验收（2026-07-17）:**

- Fresh Compose：`7 passed, 1 skipped`，92.8 秒。skip 仅为另一项需要外部 fact IDs 的 opt-in audit；self-bootstrap 场景实际通过。
- 所有 Run 都由 HTTP `POST /api/v1/tenants/{tenant_id}/runs` 创建，并立即由 GET 校验；SQL 只 seed user、tenant、membership 前置条件。
- 两个不同 Session 并行完成且 duplicate Assignment 只产生一次 Attempt/完成事件；同一 Session 的第二个 active Run 由 API 返回 409，首个终态后才可创建下一 Run。
- Worker 1 被 kill 后 Attempt 1 lost、Attempt 2 在另一 Worker 完成；双 kill gate 得到两个 lost Attempt 和 failed Run，随后 Worker 被重新拉起。
- running Run 的 Cancel 在 3 秒窗口内完成，cancel Outbox acknowledged；单 Worker `capacity=2` 时两个 Run 在同一 Worker 上真实重叠执行。
- Redis restart 前 Assignment Outbox 为 generation 0 且未 delivered/acknowledged；恢复后 delivery attempts 至少 1，delivered/acknowledged 均为 true，Run 完成。
- PostgreSQL outage 时六个服务容器仍 running 且至少一个失去 healthy；恢复后同一容器 ID 全部 running+healthy，RestartCount 不倒退，新 HTTP Run 完成。
- Task 1–6 相关矩阵：314 passed，2 skipped，136.1 秒；true-Redis 用例显式使用 `REDIS_URL=redis://127.0.0.1:6379/15`，避免本机 Docker Hub/Ryuk 拉取故障。
- Ruff 全仓 format/lint 通过；本次 8 个 production process/executor 文件 targeted mypy 通过。Windows 全仓 mypy 的既有 POSIX/旧测试类型错误不计作本次通过。
- 随机验收 containers/volumes 均已清理；原 `industry_postgres`、`industry_redis` 容器 ID 未变且保持 healthy。

**构建说明:** 本机 Docker Desktop 无官方 registry HTTPS proxy，正式 locked build 的两次本地尝试分别在清华镜像下载 passlib、python-multipart 时网络超时。运行验收因此使用上一版控制面镜像覆盖当前 app 并补 API 依赖的临时本地镜像；容器 import smoke 已覆盖 run-api/scheduler/dispatcher/worker。正式 Dockerfile 的官方源构建由新增 CI job 执行，本卡不声称本机 production image build 已通过。

**Anchors:**

- spec: `docs/superpowers/specs/2026-07-17-run-control-plane-phase2-scheduling-design.md`
- plan: `docs/superpowers/plans/2026-07-17-run-control-plane-phase2-scheduling.md`
- acceptance: `backend/tests/integration/test_run_control_multi_process.py`

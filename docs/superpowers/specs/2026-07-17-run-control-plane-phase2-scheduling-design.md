# Run Control Plane Phase 2 Scheduling Design

## 1. 目标

在 Phase 1 持久化 Run 骨架之上交付可横向扩展的调度控制面。PostgreSQL 是唯一事实源；Redis 仅传递可重复的通知。Phase 2 使用模拟执行器证明租户公平、Worker 容量、原子 claim、lease 回收和 Outbox 恢复，不接真实 LLM。

## 2. 范围

本阶段交付：

- Chat Worker 注册、心跳、drain、capacity 和负载查询；
- Tenant 公平游标与 Scheduler 五段算法；
- Attempt 分配、claim、续租、完成、失败和 lease 回收；
- Assignment/Cancel/ScheduleWake Outbox 及 Redis Dispatcher；
- 两个 Scheduler、两个模拟 Worker 和真实 Redis/PostgreSQL 多进程验收；
- Phase 1 cancel/resume 命令在同一事务写入必要 Outbox。

本阶段不交付真实 Chat Loop、token SSE、usage、真实 trace、React 切换或旧 ChatTask 删除。

## 3. 核心不变量

1. Scheduler 只选择 `runs.status = queued` 的 Run。
2. 同一 Attempt 最多一个 Worker claim 成功。
3. Worker 未 claim PostgreSQL 前不得执行任务。
4. Worker 容量不得被并发 Scheduler 超卖。
5. Run 分配、Attempt、lease、Event 和 Outbox 同事务提交。
6. Redis 丢失或重复通知不能改变 PostgreSQL 事实。
7. lease 过期的旧 Worker 不能提交完成、失败或暂停结果。
8. Worker crash 最多自动重试一次；cancelled Run 不重试。

## 4. 数据模型

### 4.1 `run_workers`

- `id UUID`：每次 Worker 进程启动生成新 ID，不复用旧进程身份；
- `worker_type`：第一版固定 `chat`；
- `capacity`：正整数；
- `status`：`online/draining/offline`；
- `heartbeat_at`、`started_at`、`last_assigned_at`；
- `metadata JSONB`：进程、主机和版本信息，不参与调度正确性。

负载由有效 `assigned/running` Attempt 数量实时计算，不保存易漂移的 `active_slots` 计数。Scheduler 锁定 Worker 行后重新计算容量。

### 4.2 `run_tenant_scheduling`

- `tenant_id` 主键并外键到 Tenant；
- `last_dispatched_at`；
- `updated_at`。

记录租户轮询游标，只在成功分配事务中更新。

### 4.3 `run_outbox`

- `id`、`event_type`、`tenant_id`、`run_id`、`attempt_id`、`worker_id`；
- `payload JSONB`；
- `dedupe_key` 唯一；
- `available_at`、`claimed_at`、`claimed_by`；
- `delivered_at`、`acknowledged_at`、`next_attempt_at`；
- `delivery_attempts`、`last_error`、`created_at`。

Assignment 在 Worker 成功 claim 时确认；Cancel 在 Attempt 终态或 Worker 确认时确认。ScheduleWake 在成功发布后确认，因为 Scheduler 始终保留 PostgreSQL 轮询兜底。已发送但未确认的 Assignment/Cancel 允许重新投递。

### 4.4 `run_attempts` 扩展

增加 `claim_token UUID`、`claimed_at`、`last_heartbeat_at`。Worker 的续租和终结命令必须同时匹配 `attempt_id/worker_id/claim_token`，并验证 lease 尚未过期。

## 5. 事务内原语

从现有 `RunService` 提取 `RunMutationStore`：

- 接收调用者提供的 `AsyncSession`；
- 提供 lock、transition、append event 等原语；
- 永不 begin、commit 或 rollback。

`RunService`、`SchedulingService` 和 `AttemptService` 各自持有完整事务，避免嵌套提交和半成功。

## 6. Scheduler 五段算法

### Eligibility

Run 必须 queued、无未解决 Pause、未取消；Tenant 未超过 `max_running_runs`；至少一个 `online`、心跳有效且有容量的 Chat Worker。

### Fairness

从 eligible Tenant 中按 `last_dispatched_at` 最早选择，使用 `FOR UPDATE SKIP LOCKED`。成功分配后才更新游标。

### Priority

Tenant 内普通 Run 按 `queued_at` FIFO。`queue_reason = resume` 的 Run 使用 `queued_at - 30 seconds` 作为有效排队时间，获得有限优先但不能饿死普通 Run。

### Placement

Worker 按 `active_attempts/capacity`、`last_assigned_at`、`worker_id` 排序。锁定候选 Worker 后重新检查心跳、状态和容量；不满足则尝试下一个。

### Recovery

锁定 lease 过期 Attempt 和对应 Run：

- Run 为 `cancel_requested`：Attempt `cancelled`，Run `cancelled`；
- `retry_count < 1`：Attempt `lost`，Run `queued`，重试数加一；
- 否则 Attempt `lost`，Run `failed`。

所有分支释放逻辑容量并写持久 Event。

## 7. 原子分配与 claim

一次分配事务依次锁定并复查 Tenant 调度游标、Run、Worker，创建 Attempt/lease，将 Run 置为 assigned，写 Event 和 Assignment Outbox，更新公平游标与 Worker `last_assigned_at`。

Worker 收到 Redis 通知后调用 `claim_attempt()`。条件不匹配、通知重复、lease 过期、Worker 不匹配或 Run 已取消时均不执行模拟任务。成功 claim 生成 `claim_token`，Attempt/Run 进入 running，并确认 Assignment Outbox。

## 8. Redis 与 Dispatcher

每个 Worker 使用 `run:worker:{worker_id}:assignments` Stream 和独立 consumer group。Dispatcher 用 `FOR UPDATE SKIP LOCKED` 领取批次，XADD 后记录 delivered；崩溃导致重复发送由 claim 消解。未 acknowledged 的通知按退避时间重投。ScheduleWake 发布到共享 scheduler wake channel，只用于降低轮询延迟。

Redis 不可用时 Outbox 保留，Dispatcher 不改变 Run/Attempt 状态。

## 9. Cancel 与 Resume

POST Run 和 Resume 在现有状态事务内追加 ScheduleWake Outbox；即使通知丢失，Scheduler 轮询仍会发现 queued Run。对 assigned/running Run 的 cancel 在同一事务追加 Cancel Outbox。Worker 同时读取 Redis 快速信号和 PostgreSQL 状态；数据库是最终判断。Resume 由 Scheduler 按有限优先创建新 Attempt，不消耗 crash retry。

## 10. 测试与验收

- L0：eligibility、租户轮询、resume 有限优先、placement、retry budget；
- L1 真 PostgreSQL：双 Scheduler、容量不超卖、双 Worker claim、lease fencing、cancel/recovery 竞态、Outbox 幂等；
- L2.5 真 Redis/进程：Dispatcher crash 后重投、重复通知、Redis 重启、两个模拟 Worker 跨 Session 并行、同 Session 串行；
- 进程演练：杀死 running 模拟 Worker，验证第二 Attempt；再次杀死后 Run failed。

Phase 2 完成时，模拟执行链必须可从 POST Run 自动走到终态，但不得调用 Chat Loop 或模型 API。

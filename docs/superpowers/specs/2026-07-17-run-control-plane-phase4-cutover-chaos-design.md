# Run Control Plane Phase 4 Cutover and Chaos Design

## 1. 目标

完成 approval/input pause、resume、Prompt 修订链和故障收束；在新链路通过多进程验收后一次性切换并退役旧 `/api/v0/chat`、ChatTask 和旧 Chat 执行真相源。

## 2. 安全暂停与 continuation

只允许 approval tool、ask-user tool、非幂等副作用前 approval gate 三类暂停点。`PauseResult` 使用版本化、纯数据 continuation，保存恢复所需 messages、tool ledger、loop count 和 pending action；禁止保存连接、client、工具实例或进程内对象。

Worker 在单事务创建 RunPause、将 Attempt 置 paused、Run 置 waiting、写 Event 并释放 lease。Resume 原子解析 Pause 并把同一 Run 放回 queued；新 Attempt 可由任意 Worker 从 continuation 继续，不消耗 crash retry。

## 3. Prompt 修订链

修改 Prompt 永远创建新 RunMessage 和新 Run，`replaces_run_id` 指向直接前驱。旧 Run 不变，一个 Run 最多一个直接后继，形成线性链。前端默认展示最新版本，可展开历史；模型上下文只使用最新有效修订。

## 4. Cancel 与终态竞态

Cancel 在 Run 状态事务内写持久 Event 和 Cancel Outbox。Worker 在 token、工具边界和 loop 边界检查取消。Cancel 先提交时 completion 被拒绝；completion 先提交时 cancel 幂等返回终态。Pause/cancel 和 lease/cancel 使用同一 Run/Attempt 行锁顺序，避免死锁和非法混合状态。

## 5. 进程与 Redis 故障

Docker Compose/本机多进程拓扑包含 FastAPI、PostgreSQL、Redis、两个 Scheduler、Dispatcher 和两个 Chat Worker。验收脚本可重复执行以下故障：杀 Worker、杀 Scheduler、杀 Dispatcher、重启 Redis、重复 assignment、延迟 cancel、并发 resume。

每个场景必须以 PostgreSQL 查询证明最终状态，而不是只看进程日志或 Redis key。

## 6. 可观测性

暴露并测试 Run 状态数、Tenant 队列深度/最老等待、调度周期、无 slot 次数、公平分配计数、Worker 心跳/容量/负载、lease 过期、Attempt 结果、Outbox 积压/延迟/重投、Run 排队/执行/总耗时、token/cost 和 waiting 数量。

日志统一携带可获得的 `tenant_id/session_id/run_id/attempt_id/worker_id`，并清理 Prompt、token、密钥和敏感工具结果。

## 7. 切换门

删除旧链路前必须满足：Phase 2/3/4 目标测试通过；真 PG/Redis 多进程验收通过；至少一次真实 Chat Run 完成；前端只调用新 Run 执行 API；代码搜索确认没有新代码写 ChatTask；迁移 dry-run 数量和归属一致。

## 8. 数据迁移与清理

提供可重复、带 dry-run 的迁移命令，将需要保留的旧 ChatSession/ChatMessage 映射为 RunSession/RunMessage，并输出源/目标数量、失败记录和归属校验。切换前保留数据库备份。迁移通过后停止旧写入，再归档或清理旧数据。

物理表清理由显式迁移/清理命令执行，不依靠 `create_all()` 自动删除。命令必须拒绝在未指定确认参数时执行破坏性步骤。

## 9. 代码退役

删除 singular `/api/v0/chat` enqueue/stream/cancel/steer/retry、ChatTask ORM/repository、旧 Celery chat wrapper、旧 Chat Event/Cancel/Steer Bus、前端 task/steer/retry 状态和测试。旧 `/api/v0/chats` session router 由新的 v1 Session 资源面替代。

保留裸 Chat Loop、工具、MCP、Skill、Memory、通用 Redis、Trace、模型客户端及其他业务的 Celery。

## 10. 验收场景

1. 浏览器关闭后 Worker 完成，重开可读最终结果；
2. 两 Worker 跨 Session 并行，同 Session 串行；
3. A 积压时 B/C 不饿死；
4. 双 Scheduler 不重复分配；
5. 重复通知只有一个 claim；
6. Worker crash 后第二 Attempt，第二次 crash 后 failed；
7. cancel 后 crash 不重试；
8. waiting 不占 slot，resume 在新 Attempt 继续；
9. 多次修改 Prompt 形成不可变线性链；
10. Redis 重启不丢最终结果，未确认 Outbox 继续投递；
11. Dispatcher/Scheduler 重启后接管；
12. 旧执行入口和 ChatTask 写路径为零。

## 11. 完成定义

最终系统只有 Run/Attempt 是聊天执行事实源；FastAPI 不内联模型；增加 Worker 实例能提高跨 Session 吞吐；PostgreSQL 可重建状态；Redis 丢失不丢最终结果；人工等待可跨进程恢复；旧 ChatTask 不再被读写。

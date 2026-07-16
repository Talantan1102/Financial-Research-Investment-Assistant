# 企业级 Run Control Plane 设计

> 日期：2026-07-16
> 状态：设计已完成，等待用户审阅
> 目标：把现有 ChatTask + Celery 单任务执行路径升级为数据库驱动、可调度、可恢复、可横向扩展 Worker 的 Run 平台。

## 1. 决策摘要

本次采用自研 Run Control Plane，不引入 LangGraph Agent Server 或 Temporal。部署目标是一台电脑上的 Docker Compose 多进程环境；调度、租约、幂等和故障恢复必须真实实现，但不声称已经验证多机部署。

核心决策如下：

- PostgreSQL 是唯一事实源；Redis 只承担通知和短期流式事件。
- 一个用户请求对应一个不可变 Run；一次实际执行对应一个 Attempt。
- 只有一种 `run_type=chat` 和一种 `worker_type=chat`，但可以启动多个同构 Worker 实例。
- 同一 Session 同时最多一个非终态 Run；不同 Session 可以并行。
- Worker 崩溃时，同一 Run 新建 Attempt 并从本次请求起点重跑；最多自动重试一次。
- 运行中不能插话修改方向。用户取消、修改 Prompt、重新发送时创建新 Run，并以可空 `replaces_run_id` 记录修订关系。
- 人工审批和等待补充信息使用同一个 Run 的等待/恢复流程；恢复后创建新 Attempt，从明确安全暂停点继续。
- 调度算法采用方案 B：租户轮询、租户内 FIFO、resume 有限优先、最低负载 Worker。
- 新 Run 路径完整替换旧 `/api/v0/chat`、`ChatTask` 和旧 ChatTask 数据；保留用户数据和现有裸 Python Chat Loop。

## 2. 目标与非目标

### 2.1 目标

1. HTTP 请求只负责接收意图和查询状态，不持有模型执行生命周期。
2. 增加 Worker 实例后，不同 Session 的 Run 可以获得更多并行吞吐。
3. 浏览器、FastAPI、Redis 或 Worker 短暂故障时，Run 不会丢失或被无依据地标记成功。
4. 每次状态变化、执行尝试、工具调用、费用和最终结果可追踪、可审计。
5. 建立 B1 租户基础：成员、固定角色、租户隔离、并发/排队配额和审计。
6. 让调度算法、并发控制和恢复语义能够被独立测试和讲清楚。

### 2.2 非目标

- 不在本阶段验证跨主机部署、Kubernetes 或跨地域容灾。
- 不支持多种 Run/Worker 类型、GPU 拓扑或复杂资源装箱。
- 不实现邀请、SSO、SCIM、自定义 RBAC、计费套餐和复杂会话共享。
- 不支持运行中任意 steering，也不尝试暂停任意 Python/LLM 指令位置。
- 不保留旧 ChatTask 兼容 API 或迁移旧聊天任务数据。
- 不把现有监控、标题生成等 Celery 任务迁入新调度器；它们继续使用 Celery。

## 3. 八模块架构

```text
React Frontend
      │ HTTP / SSE
      ▼
FastAPI Run API ─── Tenant / Membership / RBAC
      │                         │
      └────────── PostgreSQL ───┘
                       ▲
             Run Scheduler
                       │ transaction + outbox
             Outbox Dispatcher
                       │ notification / stream
                     Redis
                       │
                Chat Worker Pool
                       │
              existing Chat Loop
```

八个模块的边界：

1. **React Frontend**：提交 Run、订阅事件、显示状态、取消和恢复，不参与调度判断。
2. **FastAPI Run API**：鉴权、校验、事务写入和查询，不直接调用模型，也不直接把 Run 推给 Worker。
3. **Tenant / Membership / RBAC**：租户隔离、成员角色、配额和租户级查询授权。
4. **PostgreSQL**：保存所有持久事实，是状态判断和故障恢复依据。
5. **Run Scheduler**：判断可运行性、公平选择、Worker 放置、lease 和 Attempt 创建。
6. **Outbox Dispatcher**：把数据库中已提交的分配事实可靠通知到 Redis，允许重复投递。
7. **Redis**：承载短期 token/progress stream 和任务通知，不决定 Run 的真实状态。
8. **Chat Worker Pool**：从 PostgreSQL 原子领取 Attempt，执行现有 Chat Loop，写回持久结果。

数据库是架构核心，但不承担业务编排。Scheduler 负责“应该运行谁”，数据库约束负责“实际上只能分配一次”。

## 4. 领域模型与不变量

### 4.1 核心层级

```text
Tenant
  └─ Session
      └─ Run
          └─ Attempt
              ├─ Step / ToolCall
              └─ Event / Trace / Usage
```

- **Tenant**：安全和资源配额边界。
- **Session**：连续对话边界。
- **Run**：用户的一次不可变意图，也是 API 主资源。
- **Attempt**：Run 的一次连续 Worker 占用或执行尝试。
- **Event**：供用户和系统读取的持久业务事实。
- **Trace**：更细的内部执行诊断信息。

### 4.2 必须成立的不变量

1. Run 输入创建后不可原地修改。
2. 同一 Session 最多一个 Run 处于 `queued/assigned/running/waiting_approval/waiting_input/cancel_requested`。数据库以部分唯一索引守住该约束。
3. 同一 Attempt 最多被一个 Worker 成功 claim。
4. Worker 必须先 claim 数据库记录，才能开始模型或工具执行。
5. Run 进入终态后不能回到非终态。
6. Redis 消息重复或丢失不能改变 PostgreSQL 中的事实。
7. 最终回答必须写入 PostgreSQL；Redis token 不能作为最终结果来源。
8. 非幂等工具调用必须携带由 `run_id + tool_call_id` 派生的幂等键。
9. 创建 Run 必须携带客户端幂等键；相同 Tenant、用户和幂等键的重复 POST 返回同一个 Run。

### 4.3 持久对象

第一版包含以下逻辑对象，具体列和索引在实施计划中拆解：

- `tenants`、`tenant_memberships`：租户、固定角色和资源上限。
- `sessions`、`messages`：对话及不可变消息。
- `runs`：输入快照、状态、修订关系和最终结果引用。
- `run_attempts`：Worker、lease、起止时间、失败原因和重试序号。
- `run_pauses`：审批/补充信息请求、安全暂停点和恢复输入。
- `run_events`：状态、工具、错误和最终结果等持久事件。
- `workers`：类型、容量、心跳和当前占用。
- `outbox`：待投递的分配通知。
- `usage_records`、`audit_logs`：用量、安全与管理操作审计。

## 5. API 边界

对外只保留六个核心 Run 入口，完整路径带租户作用域：

```text
POST /api/v1/tenants/{tenant_id}/runs
GET  /api/v1/tenants/{tenant_id}/runs/{run_id}
GET  /api/v1/tenants/{tenant_id}/runs/{run_id}/events
GET  /api/v1/tenants/{tenant_id}/runs/{run_id}/trace
POST /api/v1/tenants/{tenant_id}/runs/{run_id}/cancel
POST /api/v1/tenants/{tenant_id}/runs/{run_id}/resume
```

- `POST /runs` 校验 Session 当前没有其他非终态 Run，并在一个事务中写入用户消息、`queued` Run 和首个持久事件；不调用模型，不直接发送 Redis 消息。请求必须携带 `Idempotency-Key`，网络重试和重复点击不会创建两份 Run。
- `GET /runs/{id}` 返回当前状态、最终结果摘要、Attempt 概览和等待动作。
- `GET /events` 通过 SSE 返回持久事件与 Redis 临时 token 的统一视图，支持断线后按 event id 重连。
- `GET /trace` 仅返回当前用户有权查看的执行诊断；普通成员只能看自己的 Run，owner/admin 可查看租户范围。
- `cancel` 是幂等命令。终态再次取消返回当前终态，不制造新状态。
- `resume` 只接受 `waiting_approval` 或 `waiting_input`；审批结果或补充内容先落库，再把同一 Run 重新置为 `queued`。

Prompt 修改不是 `resume`。前端重新调用 `POST /runs`，新 Run 的 `replaces_run_id` 指向被修改的上一个 Run。

## 6. 生命周期

### 6.1 Run 状态

```text
queued → assigned → running → completed
                     ├──────→ failed
                     ├──────→ cancel_requested → cancelled
                     ├──────→ waiting_approval → queued
                     └──────→ waiting_input    → queued
```

- `queued`：已持久化，等待调度。
- `assigned`：已创建 Attempt 和 lease，但 Worker 尚未成功 claim。
- `running`：Worker 已 claim 并开始执行。
- `waiting_*`：暂停事实已提交，Worker slot 和 lease 已释放。
- `cancel_requested`：取消意图已提交，禁止创建自动重试 Attempt。
- `completed/failed/cancelled`：终态。

### 6.2 Attempt 语义

- Scheduler 分配时创建 Attempt；Worker 只负责 claim 和执行。
- Worker crash 或 lease 过期：当前 Attempt 标记 `lost`，同一 Run 回到 `queued` 并创建下一 Attempt。
- 一个 Run 最多两个普通执行 Attempt，即首次执行加一次自动故障重试。
- 人工等待会结束当前连续占用；恢复后创建新 Attempt，但不消耗故障重试次数。
- 从人工暂停恢复使用已持久化的安全暂停点；从 Worker crash 恢复则从本次 Run 输入起点重跑。

### 6.3 Prompt 修订链

```text
Run A
  ↑ replaced by
Run B (replaces_run_id=A)
  ↑ replaced by
Run C (replaces_run_id=B)
```

- 每次修改都生成新 Run、新消息、新费用和新执行轨迹。
- `replaces_run_id` 只指向紧邻的上一版本，不承担调度或重试语义。
- 普通追问不填写该字段。
- 模型构建会话上下文时，只使用修订链上的最新有效版本；旧版本只用于审计和历史展开。
- 前端默认展示最新版本，并允许查看修订历史。

## 7. Scheduler 调度算法

Scheduler 是控制面的核心，不是 Redis consumer 的别名。它分成五个可独立测试的决策步骤：Eligibility、Fairness、Priority、Placement、Recovery。

### 7.1 Eligibility：哪些 Run 当前可运行

Run 必须同时满足：

- 状态为 `queued`；
- Tenant 未超过最大运行并发数；
- Session 没有其他非终态 Run；
- 存在心跳有效、类型兼容且有空闲 slot 的 Chat Worker；
- Run 未被取消，且没有未解决的审批/补充信息请求。

`POST /runs` 同时执行租户排队上限校验。超过上限时明确返回容量错误，不创建半成品 Run。

### 7.2 Fairness：租户轮询

在所有 eligible Tenant 中，选择 `last_dispatched_at` 最早的租户；每成功分配一个 slot 后更新该时间。这样 Tenant A 即使积压 100 个 Run，也不能在 Tenant B、C 有任务时独占全部空闲 slot。

调度顺序示例：

```text
A1 → B1 → C1 → A2
```

公平游标持久化在 PostgreSQL。多个 Scheduler 进程可以竞争调度，但必须通过行锁和条件更新串行化同一轮租户选择；重复选择最终由 Run 状态条件和唯一约束兜底。

### 7.3 Priority：租户内部 FIFO + resume 有限优先

普通 Run 以 `queued_at` FIFO。恢复的 Run 获得固定、可配置的虚拟时间提前量：

```text
effective_queued_at = queued_at - RESUME_PRIORITY_BOOST_SECONDS
```

第一版默认提前 30 秒。它让正在等待人工操作的用户更快恢复，同时只是有限领先；等待更久的普通 Run 最终一定排在前面，不会饿死。

### 7.4 Placement：最低负载 Worker

只有一种 Chat Worker，不需要复杂装箱。选择心跳有效且有空闲容量的 Worker，按以下顺序排序：

1. `active_slots / capacity` 最低；
2. 最久未分配；
3. `worker_id` 稳定排序。

Worker capacity 是配置值。单机第一版通常每个 Worker capacity 为 1，可通过增加 Worker 进程验证横向吞吐。

### 7.5 原子分配

一次成功分配必须在同一 PostgreSQL 事务内完成：

1. 锁定并再次确认 Run 仍为 `queued`；
2. 确认租户、Session 和 Worker slot 仍可用；
3. Run 变为 `assigned`；
4. 创建 Attempt 和 lease；
5. 占用 Worker slot；
6. 写入持久事件和 Outbox。

任何一步失败则整笔回滚。调度算法决定候选者，事务和约束决定唯一结果。

### 7.6 Recovery：lease 回收

Scheduler 同时扫描 `assigned/running` 且 lease 过期的 Attempt：

- Run 已 `cancel_requested`：结束 Attempt 并把 Run 置为 `cancelled`，不重试。
- 尚有自动重试额度：Attempt 置为 `lost`，Run 回到 `queued`。
- 重试额度耗尽：Attempt 置为 `lost`，Run 置为 `failed`。

## 8. 分配、执行与事件流

### 8.1 正常路径

1. API 事务提交用户消息、queued Run 和创建事件。
2. Scheduler 分配 Run，创建 Attempt、lease 和 Outbox。
3. Dispatcher 读取 Outbox，把 Attempt 通知写入 Redis，并在成功后标记已投递。
4. Worker 收到通知后，使用条件更新去 PostgreSQL claim Attempt。
5. claim 成功后 Run 进入 `running`；失败则丢弃这条重复/过期通知。
6. Worker 运行现有裸 Python Chat Loop。
7. token/progress 写 Redis Streams；状态、工具、错误、usage 和 trace 写 PostgreSQL。
8. 最终 assistant message、最终结果和 `completed` 事件在数据库事务中提交。

Outbox 和 Redis 通知采用 at-least-once；Worker claim 和工具幂等把“至少一次通知”收敛为“至多一个有效执行者”。

### 8.2 事件分层

PostgreSQL 持久保存：

- Run/Attempt 状态变化；
- 审批和补充信息请求；
- 工具调用摘要、成功/失败和幂等键；
- usage、错误、最终回答和终态事件。

Redis Streams 临时保存：

- token chunk；
- 高频进度和 UI 动画事件。

Redis Stream 使用可配置 TTL，第一版默认 24 小时。过期后仍可从 PostgreSQL 获得完整状态和最终回答，只是不再重放逐 token 过程。

## 9. 取消、等待和恢复

### 9.1 取消

- API 原子写入 `cancel_requested` 和事件。
- 同一事务写入 cancel Outbox；Dispatcher 发送 Redis 快速通知，Worker 同时以数据库状态作为最终判断。
- Worker 在 LLM 流片、工具边界和循环边界检查取消标记，协作式停止。
- Worker 正常停止后提交 `cancelled`；已生成的临时 token 不作为正式 assistant message。
- Worker 已丢失时由 Scheduler 在 lease 过期后完成取消。
- 取消后的 Run 不自动重试；用户修改后重新提交新 Run。

### 9.2 人工审批和补充信息

只允许三类明确安全暂停点：

1. approval tool；
2. ask-user tool；
3. 非幂等副作用执行前的 approval gate。

Worker 在一个事务中保存暂停类型、请求内容、Chat Loop 继续所需的最小状态和持久事件，然后把 Run 置为 `waiting_approval` 或 `waiting_input`，结束当前 Attempt 并释放 slot/lease。

等待状态不占运行并发数，也不占排队配额。第一版不自动过期；用户或 owner/admin 可以取消。

### 9.3 Resume

- `resume` 请求必须匹配尚未解决的 pause，并携带批准/拒绝或用户补充内容。
- 恢复输入和状态变化同事务提交，Run 回到 `queued`。
- Scheduler 按有限优先策略重新调度，创建新 Attempt。
- Worker 从显式暂停点继续；恢复不是失败，不消耗自动重试次数。
- 同一个 pause 只能成功恢复一次；重复 resume 返回当前 Run 状态。

## 10. Tenant B1 边界与安全

### 10.1 能力范围

- 固定角色：`owner`、`admin`、`member`。
- owner/admin 可以把已经注册的用户加入或移出租户。
- member 只管理自己的 Session/Run；owner/admin 可以查看租户范围的 Run、用量和审计。
- 每个 Tenant 配置最大 running 数和最大 queued 数。
- 所有 Session、Run、Attempt、Event、Usage 查询必须同时带 `tenant_id` 条件。
- 管理操作写安全审计；执行写用量审计。

### 10.2 用户迁移

保留现有用户。首次迁移时，每个现有用户获得一个私有默认 Tenant 和 owner membership，保证原账号可以立即使用且彼此隔离。之后 owner/admin 可以把已注册用户加入企业 Tenant。

不迁移旧 ChatTask、旧 chat session 或旧 chat message；相关表和 API 在切换完成后删除。

## 11. 故障语义

| 故障 | 系统行为 |
|---|---|
| 浏览器关闭 | Run 继续；重连后查 PostgreSQL 状态并订阅剩余事件 |
| FastAPI 重启 | 已提交 Run 不受影响；未提交事务不存在 |
| Redis 短暂不可用 | Outbox 保留分配事实并重试通知；最终结果仍写 PostgreSQL |
| 重复 Redis 通知 | 只有一个 Worker 能 claim；其余丢弃 |
| Worker 崩溃 | lease 过期后同 Run 新 Attempt，从 Run 起点重跑一次 |
| Scheduler 崩溃 | 数据库状态不变；新 Scheduler 接管未分配和过期 lease |
| Dispatcher 崩溃 | 未确认 Outbox 继续重投 |
| 工具调用后 Worker 崩溃 | 幂等键阻止非幂等副作用重复发生 |
| cancel 与完成竞态 | 数据库条件更新决定唯一终态；先提交者生效，后提交者读取现状 |

## 12. 可观测性

第一版至少暴露以下指标和结构化日志：

- 各状态 Run 数、各租户排队深度和最老等待时间；
- 调度周期耗时、无可用 slot 次数、公平分配计数；
- Worker 心跳、容量、占用率和 lease 过期数；
- Attempt 成功、失败、lost、自动重试数；
- Outbox 积压、投递延迟和重复投递；
- Run 总耗时、排队耗时、执行耗时、token 与费用；
- waiting_approval/waiting_input 数量和等待时长。

日志必须带 `tenant_id/session_id/run_id/attempt_id/worker_id` 中适用的关联字段。

## 13. 测试与验收

### 13.1 测试分层

- **L0 纯逻辑**：状态转换、eligible 判断、公平顺序、resume 虚拟时间、Worker placement、重试预算。
- **L1 真 PostgreSQL**：事务分配、Session 活跃唯一约束、双 Scheduler 竞争、双 Worker claim、cancel/complete 竞态、租户隔离。
- **L2.5 真进程与真 Redis**：FastAPI、Scheduler、Dispatcher、多个 Worker 和 Redis 联调；杀进程验证 lease/outbox 恢复。
- **前端测试**：创建、重连、取消、等待、恢复、Prompt 修订链和历史展开。

### 13.2 核心验收场景

1. API 返回 Run 后立即关闭浏览器，Worker 继续完成，重开可见最终结果。
2. 启动两个 Chat Worker，不同 Session 可并行，同一 Session 不可并行。
3. Tenant A 积压 100 个 Run，Tenant B/C 各有任务时，调度顺序体现租户轮询。
4. 两个 Scheduler 同时运行，同一 Run 只创建一个有效分配结果。
5. 重复投递同一 Redis 通知，只有一个 Worker 成功 claim。
6. running Worker 被杀死，lease 到期后自动创建第二 Attempt；再次失败后 Run 为 failed。
7. cancel 后即使 Worker 同时崩溃，也不会自动重试。
8. waiting 状态不占 Worker slot；resume 后同一 Run 新 Attempt 从安全暂停点继续。
9. 用户连续修改 Prompt，形成不可变 `replaces_run_id` 链，模型上下文只使用最新有效版本。
10. Redis 重启期间最终结果不丢；恢复后 Outbox 能继续通知未执行任务。

## 14. 实施分期

### 阶段一：Run 数据骨架

- Tenant、Session、Run、Attempt、Event 等持久模型；
- 六个 Run API；
- 状态机、权限和租户隔离；
- 使用假执行器验证创建、查询、取消。

### 阶段二：调度控制面

- Worker 注册、心跳、capacity、slot 和 lease；
- Scheduler 五段算法；
- Outbox Dispatcher 和原子 claim；
- 使用模拟任务验证公平、并发、重复通知和 Worker crash。

### 阶段三：接入真实 Chat

- Chat Worker 复用现有裸 Python Chat Loop；
- Redis Streams token/progress；
- PostgreSQL 最终回答、工具、usage 和 trace；
- React 切换新 Run API；
- 删除旧 `/api/v0/chat`、ChatTask 和旧聊天数据。

### 阶段四：人工交互与故障收束

- approval/input pause 与 resume；
- Prompt 修订链；
- cancel、Redis 重启、双 Scheduler、重复通知和进程崩溃测试；
- 指标、审计和 Docker Compose 多进程验收。

每个阶段应拆成独立实施计划和可验证提交；阶段一到阶段三形成主链，阶段四在主链稳定后补齐。

## 15. 成功标准

本设计完成的标志不是“画出了前后端分离图”，而是以下事实都能通过自动化测试或真实进程演练证明：

- API 与模型执行生命周期彻底分离；
- PostgreSQL 可以重建所有 Run 的真实状态；
- 增加 Worker 实例能提高跨 Session 并行吞吐；
- 租户公平、Session 串行和配额限制同时成立；
- 重复通知、并发调度和进程崩溃不会造成重复有效执行或 Run 丢失；
- 人工等待不占执行资源，恢复与 Prompt 重提具有不同且清晰的语义；
- 旧 ChatTask 路径被完整退役，没有新旧双事实源。

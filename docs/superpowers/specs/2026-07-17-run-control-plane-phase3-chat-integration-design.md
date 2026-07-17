# Run Control Plane Phase 3 Chat Integration Design

## 1. 目标

把现有裸 Python Chat Loop 接到 Phase 2 Run Worker，以 Run/Attempt 为唯一执行事实源；提供 Redis token/progress 流、PostgreSQL 最终消息、工具审计、usage 和 trace，并把 React 执行路径切到新 Run API。

## 2. 范围

本阶段交付 ChatRunExecutor、持久化工具执行账本、usage、Run SSE 混合事件流、真实 Chat Worker、React Run API 切换和至少一次真实模型 API 冒烟。

旧 `/api/v0/chat` 在本阶段开发期间保留作对照；正式删除在 Phase 4 验收门后执行。Steering 不进入新链路。

## 3. ChatRunExecutor

从旧 `chat_runner.py` 提取与 ChatTask/Celery/旧 Redis key 无关的执行适配器。它复用 `ChatLoopState`、`ToolLoop`、`build_turn_components`、MCP、Skill、Memory、模型客户端和 cancel event。

输入为 Run、Attempt、输入消息、Session 历史、可选 continuation 和执行依赖；输出严格为 `CompletedResult`、`PauseResult` 或 `FailedResult`。Executor 不打开事务，不直接更新 ORM，不知道 FastAPI、Scheduler 或 Celery。

## 4. 持久化执行结果

完成事务同时写入 assistant `RunMessage`、`final_message_id`、Run/Attempt completed、usage、最终 trace 和持久 Event。Assignment Outbox 已在 claim 事务确认，不在完成事务重复确认。任何一步失败全部回滚。

失败事务保存规范化错误码和安全错误消息；原始异常进入结构化日志，不向普通用户泄露凭据或内部路径。

## 5. 工具执行账本

新增 `run_tool_executions`：`run_id`、`attempt_id`、`tool_call_id`、唯一 `idempotency_key`、tool name、request 摘要、status、result 摘要、error 和时间戳。

幂等工具重试前复用已成功结果。非幂等副作用必须经过 approval gate；没有稳定幂等键或 approval 的工具不得在 crash 自动重试路径执行。

## 6. Usage 与 Trace

新增 `run_usage_records`，按 Run/Attempt/模型记录 input、output、cached token 和成本。Trace 复用 `TraceSpanRow`，`request_id = str(run_id)`，span 属性包含 attempt/worker/tenant 关联字段，不创建第二套 Trace 表。

## 7. Redis 临时事件

`run:stream:{run_id}` 保存 token、progress 和 UI 动画事件，记录 attempt、event type、payload 和 durable watermark，TTL 24 小时并限制最大长度。Redis 写失败只降级流式体验，不改变最终执行结果。

## 8. SSE 游标与重连

Events endpoint 保持原路径，扩展为不透明游标 `v1:<durable_seq>:<redis_id>`，兼容 Phase 1 整数游标。

连接时先读取 PostgreSQL durable event；Run 非终态时继续 XREAD Redis，并在阻塞超时后重新 drain durable event。终态时最终 drain 数据库后关闭。终态重连以最终 RunMessage 为准，不依赖 token 回放。

## 9. 前端切换

发送消息使用 POST Run；SSE 使用 Run events；刷新和断流后 GET Run 校准。停止使用 cancel，人工响应使用 resume，修改 Prompt 创建带 `replaces_run_id` 的新 Run。移除新路径中的 steer/retry/task_id 语义。

六个 Run endpoint 仍是唯一执行与控制入口。侧边栏需要单独的 Session 资源查询面：list、detail、rename、archive/delete；它们只读写 RunSession/RunMessage，不创建或执行 Run。

## 10. Session 读模型

Session API 使用 `/api/v1/tenants/{tenant_id}/sessions`，提供 list、detail、PATCH title 和 DELETE archive。RunSession 增加 `archived_at`；DELETE 只做软归档，不物理删除仍被 Run 引用的历史。复用 Phase 1 RBAC：member 只看自己的 Session，owner/admin 可看 Tenant 范围。首次 POST Run 可懒创建 Session；不再要求先创建空 ChatSession。

## 11. 测试与验收

- ChatRunExecutor 使用 scripted model/tool 测试 completed/pause/fail/cancel；
- 真 PostgreSQL 验证最终消息、Run/Attempt/Event/usage/trace 原子性；
- fakeredis 与真 Redis 验证 token、复合 cursor、断线续读和 Redis 降级；
- React 测试发送、重连、取消、最终校准、Prompt 修改；
- L2.5 启动两个真实 Chat Worker，使用受控模型客户端证明不同 Session 并行；
- 在配置可用时执行一次真实模型 API smoke，记录 Run、Attempt、最终消息和 Trace 证据，不把凭据写入报告。

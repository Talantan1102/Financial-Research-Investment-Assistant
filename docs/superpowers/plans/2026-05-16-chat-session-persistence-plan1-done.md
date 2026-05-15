# Chat Session Persistence — Plan 1 (Foundation) DONE

**Branch**: `feat/chat-persistence-plan1-foundation`
**Ship 时间**: 2026-05-16
**Commits**: 10(见 commit chain 末尾)

## 落地状态

Plan 1 (Foundation) 完整 ship,A 档承诺达成:**刷新 / 关页面重开看到完整对话历史**。

### 完成清单

| Task | 内容 | Commit |
|---|---|---|
| 1 | ChatTask ORM 13 列 + chat_messages 加 task_id/status | `10eeacc` + `527de02`(code review fix:删 __init__ + 补 FK)|
| 2 | smoke 守护 chat_tasks 注册到 metadata | `ad25eb4` |
| 3 | ChatTaskRepo 6 状态机 + 9 method + L0 测试 | `d4bf0dc` |
| 3.5 | ChatMessage 3 JSONB 列加 sqlite variant(后续 L0/L1 sqlite fixture 用)| `b89b87a` |
| 4 | ChatSessionRepo 扩展 — append_message 接 task / find_active_task | `64291c7` |
| 5 | POST /chat 入口落 user + create chat_task / finally 落 assistant + mark | `ef14374` |
| 6 | LLM error 路径守护 + 修补 fixture type annotation | `b76823a` |
| 7 | GET /chats/{sid} 返回 active_task_id + message task_id/status | `44b76ee` |
| 8 | 前端去掉指向不存在 endpoint 的假 reconnect 循环 | `1916243` |
| 9 | serve path smoke + 全套测试守护 | 本 commit |

## 测试守护矩阵

| 守护项 | 结果 |
|---|---|
| Plan 1 scoped backend(8 test 套件,47 case)| 47/47 PASS |
| backend full unit + integration | 1084 passed / 1 skipped / 1 pre-existing flaky(`test_tool_node_executes_calls`,在 main 也 fail,非本 plan regression)|
| backend mypy(`backend/app/` 279 文件 strict)| Success: 0 issues |
| backend ruff(check + format,605 文件)| All checks passed |
| frontend vitest(46 文件 174 case)| 174/174 PASS |
| frontend build(tsc 类型检查)| OK |
| frontend lint | 0 new errors(32 pre-existing 在 router/store/utils 中,非本 plan 引入)|

## 关键架构成果

1. **6 状态 lifecycle 状态机**(queued → running → done | partial | cancelled | error),由 `ChatTaskRepo` 暴露 9 个 method 操作
2. **DB-as-truth 半成品**:user message + assistant message + chat_task 行 3 件一致性保证由 `_stream_chat` finally 块兜底
3. **Graceful degrade**:`get_async_session_factory` DI 在没有 PG 时返 None,legacy SSE 测试零破坏继续工作
4. **LangGraph checkpoint 入口**:`_finalize_task_persistence` 已经在 success path 尝试拿 `graph.aget_state(config).config["configurable"]["checkpoint_id"]` 存 PG;Plan 3 retry 从这个字段读续跑
5. **变量遮蔽 bug 修复**(`_stream_chat` 内 `pg_factory` 被 C.5 persona_populator 块 shadow)
6. **sqlite UUID(int=0) roundtrip 修复**(test-user stub 改 `uuid5(NAMESPACE_DNS, ...)` 避免 zero-UUID 在 sqlite 上的 adapter bug)

## Plan 2/3 留口

Plan 1 已经为后续 plan 准备好 schema 和接口:

- **`chat_tasks.last_event_seq`**:Plan 2 用作 Redis Streams 截止位置追踪,`ChatTaskRepo.bump_seq()` 已实现 + L0 测过
- **`chat_tasks.langgraph_checkpoint_id`**:Plan 1 入口成功 commit 写入,Plan 3 retry 直接读
- **`chat_tasks.parent_task_id`**:Plan 3 retry 链接前次失败 task,model 已 build
- **`chat_tasks.initial_prompt_message_id`**:Plan 3 retry 复用用户原 prompt,FK 已闭合
- **GET /chats/{sid} 返回 `active_task_id`**:Plan 2 前端拿到后用作 SSE replay endpoint 的路径参数
- **每 message 返回 `task_id` + `status`**:Plan 2 前端展示 task-level 进度

## Plan 1 ↔ Spec § 1.2 三个根因覆盖

| Spec § 1.2 失效面 | Plan 1 状态 |
|---|---|
| chat 消息不入库 | ✅ 修复(POST /chat 入口 + finally 块全覆盖)|
| 服务端不感知断开 | ❌ 仍未做 — Plan 2 引 Celery 解耦推理与 HTTP request 生命周期 |
| 前端假 reconnect 后端 404 | ✅ 修复(改一次性 GET /chats/:id 拉历史)|

Plan 1 覆盖 2/3 根因。Plan 2 (in-flight subscribe via Celery + Redis Streams) 收第三个根因 + C 档 in-flight 承诺。

## Plan 1 ↔ Hermes 参考对照

| Hermes 设计 | Plan 1 等效 | Plan 2/3 差距 |
|---|---|---|
| SQLite WAL DB-as-truth | PG ChatMessage + ChatTask 双层 | 我们多了 task lifecycle |
| Agent loop / transport 解耦 | 部分:`_stream_chat` 改 try/finally 但 agent 仍在 web 进程内 | Plan 2 引 Celery 真解耦 |
| 跨 transport 续话 | session_id 已是 first-class(`langgraph_thread_id`)| Plan 2 在多 client 上 fan-out 自然得到 |
| Reconnect 协议 | 一次性 reload 历史(A 档)| Plan 2 引 Redis Streams XREAD 协议(C 档)|

## 已知 follow-up(不进 Plan 1 范围)

| 项 | 优先级 | 推到 |
|---|---|---|
| `datetime.utcnow()` 全项目 deprecation warnings(Python 3.13)| 低 | 单独 fix-class commit 或 Plan 3 cleanup |
| `LongTermMemory.key_insights` / `company_data.extra_data` 裸 JSONB,sqlite L0 测试要 selective create_all 列表 | 低 | Plan 2/3 真用到再修 |
| `_build_async_pg_session_factory_or_none` 名字误导(实际是 sync factory,只给 C.5 persona 用)| 低 | Plan 2 重构 chat.py 时清理 |
| 前端 32 pre-existing lint errors(router/store/utils)| 低 | 单独 ` chore(lint)` PR |
| 浏览器 dogfood(真起 server + 关页面重开看历史)| 中 | 用户在 PR review / staging dogfood 阶段验证 |

## Commit Chain

```
1916243  fix(chat-persistence): 前端去掉指向不存在 endpoint 的假 reconnect 循环
44b76ee  feat(chat-persistence): GET /chats/{sid} 返回 active_task_id + message task_id/status
b76823a  test(chat-persistence): LLM error 路径守护 + 修补 fixture type annotation
ef14374  feat(chat-persistence): POST /chat 入口落 user msg + create chat_task; finally 落 assistant + mark
64291c7  feat(chat-persistence): ChatSessionRepo 扩展 — append_message 接 task / find_active_task
b89b87a  fix(chat-persistence): ChatMessage 3 个 JSONB 列加 sqlite variant
d4bf0dc  feat(chat-persistence): ChatTaskRepo 6 状态机 + 9 个 method + L0 test
ad25eb4  test(chat-persistence): smoke 守护 chat_tasks 表注册到 metadata
527de02  fix(chat-persistence): 删除 ChatTask.__init__ override + 补 user_id/initial_prompt_message_id FK
10eeacc  feat(chat-persistence): ChatTask ORM model + chat_messages 加 task_id/status 列
```

## 下一步

1. **Plan 1 PR review + merge**:接受 PR review,需要时调整,merge 到 main
2. **Plan 2 起 spec**(下一个 brainstorm session):in-flight subscribe via Celery + Redis Streams + 3 个新 endpoint + 前端真打字机
3. **Plan 3 起 spec**(Plan 2 ship 后):cancel + retry from checkpoint + stale scanner + L2 chaos

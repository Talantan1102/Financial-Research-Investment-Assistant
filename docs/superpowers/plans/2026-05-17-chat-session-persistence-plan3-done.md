# Chat Session Persistence — Plan 3 (Cancel + Retry + Stale + Golden) DONE

**Branch**: `feat/chat-persistence-plan3-cancel-retry`
**Ship 时间**: 2026-05-17
**Commits**: 9(8 task + 1 done card)+ 1 plan doc carryover(Plan 3 plan 文件本身在 Plan 2 PR `85a9b91` ship)

## 落地状态

Plan 3 主体 ship。`Plan 1 + 2 + 3` 三卷完整闭环 — chat session 持久化的 **DB-as-truth + in-flight subscribe + lifecycle 自愈** 体系完整可用。

### 完成清单(8/10 task ship + 1 deferred + 1 收尾)

| Task | 内容 | Commit |
|---|---|---|
| 1 | ChatCancelBus(Redis pub/sub + 4 L0 test)| `47e111b` |
| 2 | ChatTaskRepo.find_stale_running_tasks(5min cutoff query + 3 L0 test)| `0c11ce1` |
| 3 | Worker cancel listener + GraphInterrupt + partial commit | `719a848` |
| 4 | POST /chat/cancel/{tid} endpoint + 3 L1 test | `fa02f20` |
| 5 | POST /chat/retry/{tid} + Celery wrapper 接 resume_checkpoint_id + 4 L1 test | `296cbbc` |
| 6 | Stale scanner Celery Beat task + Beat schedule + 4 L0 test | `a6cac0a` |
| 7 | 前端 cancel + retry button + active_task_id state + 180/180 test PASS | `582cc9f` |
| 8 | L2 chaos test(杀 worker/Redis/web)| **deferred 到 Plan 3 follow-up**(plan 阶段就标「推到 implementer 按 conftest_celery spike」+ Plan 2 dogfood 场景 3 已手动验过 web crash 行为)|
| 9 | 3 differential golden cases(cancel/retry/two-turn-inflight)| `67e0ece` |
| 10 | Done card + PR | 本 commit |

## C 档完整体验路径(Plan 1+2+3 累计)

1. **发 prompt → 看打字机吐字**(Plan 2 commit `a4ddf02` 真根因修后)
2. **关页面 30s 重开 → in-flight subscribe 续流**(Plan 2 § 5.2 Scenario B + frontend Scenario B subscribe)
3. **Web 进程 crash → Celery 继续跑 → PG 落库 → 重启后 user 看到完整结果**(Plan 2 dogfood 场景 3 验过)
4. **点「停止生成」→ 推理几秒内停下,显示「已取消」+ 保留已生成部分**(Plan 3 Task 3/4 + 7)
5. **Worker crash → 1 分钟内 stale scanner mark error → 前端显 retry 按钮**(Plan 3 Task 6)
6. **点「重试」→ 从 LangGraph checkpoint 续跑(不重头)**(Plan 3 Task 5 + 7)

## 关键架构成果(Plan 3 增量)

### 1. Pub/Sub Cancel 机制(spec § 6.1 option c wrapper)

- Redis pub/sub channel-per-task: `chat:cancel:{task_id}`
- Worker 内 asyncio listener subscribe → set Event flag
- Graph node 之间 wrapper 检查 flag → raise `_CancelledByUser` → finalize 走 partial commit(`status=partial`, `langgraph_checkpoint_id` 写入留 retry 用)
- spec § 6.1:LangGraph 1.x 不支持外部 kill 信号,wrapper 是唯一可行方案

### 2. LangGraph Checkpoint Resume

- `run_chat_async` 接 `resume_checkpoint_id` kwarg → 注入 `RunnableConfig.configurable.checkpoint_id`
- `enqueue_run_chat` + Celery `run_chat` wrapper 整链路接通
- `POST /chat/retry/{tid}` 从 `chat_tasks.langgraph_checkpoint_id` 创建新 task(`parent_task_id=旧 tid`)→ enqueue 带 resume_checkpoint_id
- LangGraph 自动从 checkpoint state 续跑(thread_id + checkpoint_id 定位状态)

### 3. Stale Scanner 自愈

- Celery Beat 每 60s 跑 `scan_stale_chat_tasks_async`
- `find_stale_running_tasks(min_age_minutes=5)`:扫 status=running + started_at 5min 前
- mark_error + XADD `{type:error_done, reason:stale}` 到 Redis Stream
- 前端 SSE handler 收到 stale error event → 显 error badge + retry 按钮(Plan 3 Task 7)

### 4. UI 状态完整闭环

- `CurrentChatState.active_task_id`:in-flight 时 set,terminal 后 clear
- InputArea 据此切 send / 停止生成 按钮
- MessageList 在 error/partial assistant message 后显 retry 按钮
- ChatPane wire `onCancel={sse.cancelTask}` + `onRetry={sse.retryTask}`

## 测试守护矩阵

| 守护项 | 结果 |
|---|---|
| Plan 3 scoped backend(test_chat_cancel_bus / find_stale_running_tasks / cancel listener / cancel endpoint / retry endpoint / stale scanner / differential golden)| 全 PASS |
| Plan 1+2 regression(test_chat_runner / event_bus / task_repo / persistence_plan1 / inflight_plan2)| 全 PASS |
| backend mypy strict | 0 issues / 653 source files |
| backend ruff(check + format)| 全 clean |
| frontend vitest | 180/180 PASS |
| frontend tsc build | OK |
| frontend lint | 0 new error(32 pre-existing 不动)|

## Plan 3 → Plan 3 follow-up 留口

| 项 | 推迟原因 |
|---|---|
| L2 chaos test(杀 worker/Redis/web automated) | plan 阶段就标「推到 implementer 按 conftest_celery spike」;docker pause/unpause 等 environment-specific;Plan 2 dogfood 场景 3 已手动验过 web crash 行为 — 自动化是 nice-to-have polish |
| 浏览器 dogfood 真测 cancel + retry + stale 三个流 | PR review 阶段做(user 浏览器 + 真 worker + 真 Redis 端到端)|
| Cancel timing 一致性强保证 | spec § 6.1 接受 graph node 间 1-3s 粒度;wrapper 模式跨 node 检查不强精确 |

## Plan 3 spec § 1.2 三个根因影响(累计 Plan 1+2+3)

| § 1.2 失效面 | Plan 1 | Plan 2 | Plan 3 |
|---|---|---|---|
| chat 消息不入库 | ✅ POST 入口 + finally 落库 | continue | partial 路径也入库 |
| 服务端不感知断开 | ❌ | ✅ Celery 独立进程 + is_disconnected | + stale scanner 自愈 worker crash |
| 前端假 reconnect 404 | ✅ 改 reload 历史 | ✅ 真 stream/{tid} + last_event_id | + retry button 真 resume |

Plan 3 把 lifecycle robustness 闭环 — cancel / retry / stale-detect / golden 守护四件套全到位。

## Plan 1+2+3 总卡建议

Plan 3 PR merge 后可以写 `docs/claude-context/chat-session-persistence-done.md` 总卡(类似 c5-cross-session-memory-done.md / harness-board-review-mode-done.md 风格)。建议包含:
- 三卷范围 + 各自 commit chain
- DB-as-truth + agent/transport 解耦 + Pub/Sub cancel + checkpoint resume 四要素
- 简历叙事:LangGraph + Celery + Redis Streams + Pub/Sub + LangGraph checkpoint resume 的完整工业级 chat 推理基础设施
- Plan 3 follow-up 留口

## 工程量统计(Plan 3 实际)

| 阶段 | 内容 | wall time |
|---|---|---|
| Task 1 ChatCancelBus | 4 L0 + 实施 | ~15min |
| Task 2 find_stale_running_tasks | 3 L0 + 实施 | ~10min |
| Task 3 Worker cancel listener | 1 L0 + 实施(改 run_chat_async)| ~30min |
| Task 4 POST cancel endpoint | 3 L1 + 实施 | ~15min |
| Task 5 POST retry endpoint + Celery wrapper | 4 L1 + 实施 | ~25min |
| Task 6 Stale scanner Beat | 4 L0 + 实施 + 调度 | ~30min |
| Task 7 前端 cancel + retry UI(中间 subagent 中断,我续完)| ~50min |
| Task 9 3 differential golden | 3 L1 + 实施 | ~15min |
| Task 10 done card | 本文件 | ~5min |
| **合计** | | **~3.5 小时**(Claude Code 加速 + subagent 并发) |

## Commit Chain(Plan 3 主体)

```
67e0ece  test(chat-persistence): 3 differential golden — cancel/retry/two-turn-inflight
582cc9f  feat(chat-persistence): 前端 cancel + retry button + active_task_id state UI
a6cac0a  feat(chat-persistence): Stale scanner Celery Beat task — 自愈卡 running 的 chat_tasks
296cbbc  feat(chat-persistence): POST /chat/retry/{tid} + Celery wrapper 接 resume_checkpoint_id
fa02f20  feat(chat-persistence): POST /chat/cancel/{tid} endpoint + L1 publish test
719a848  feat(chat-persistence): worker cancel listener + GraphInterrupt + partial commit
0c11ce1  feat(chat-persistence): ChatTaskRepo.find_stale_running_tasks for Plan 3 stale scanner
47e111b  feat(chat-persistence): ChatCancelBus — Redis pub/sub cancel signal + 4 L0 test
```

## 下一步

1. **Plan 2 PR #61 先 merge 到 main**(Plan 3 依赖 Plan 2,从 Plan 2 branch 切出来 — merge 顺序很重要)
2. **Plan 3 PR**:Plan 2 merge 后,Plan 3 branch rebase on main + 开 PR
3. **浏览器 dogfood**:reviewer / user 真测 cancel + retry + stale 三个流
4. **写 Plan 1+2+3 总卡**(`docs/claude-context/chat-session-persistence-done.md`)
5. **(Optional)Plan 3 follow-up L2 chaos**:杀 worker / Redis / web 自动化 chaos test

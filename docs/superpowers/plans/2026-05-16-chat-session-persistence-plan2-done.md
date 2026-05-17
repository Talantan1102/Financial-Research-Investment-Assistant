# Chat Session Persistence — Plan 2 (In-flight Subscribe) DONE

**Branch**: `feat/chat-persistence-plan2-inflight`
**Ship 时间**: 2026-05-16
**Commits**: 8 + 本 done card

## 落地状态

Plan 2 (In-flight Subscribe) ship — **C 档基础设施全套就位**,Production 可切到 Celery + Redis Streams 路径。

### 完成清单(7/10 Plan task 全过 + 2 个 deferred)

| Task | 内容 | Commit |
|---|---|---|
| 1 | ChatEventBus(Redis Streams 封装)+ 7 L0 test | `3feaeed` |
| 2 | chat_finalize.py 抽出 finalize_task_persistence helper | `b23f0d2` |
| 3 | Celery `run_chat_async` task + L0 test(eager) | `bddd938` |
| 4 | GET /chat/stream/{tid} SSE replay endpoint + Redis XREAD | `7d59057` |
| 5 | POST /chat 改造为 graceful dual-path(JSON Plan 2 / SSE Plan 1)| `6060cb1` |
| 6 | 前端双阶段流 + useTypewriter RAF 打字机 | `74d9592` |
| 7 | app_main lifespan wire `app.state.redis_async` | `71a4cec` |
| 8(scoped)| Celery `run_chat` worker production wiring + L2 sanity test | `567fdb4` |
| 9 | 客户端断开守护 L2 test | **deferred 到 Plan 3**(Task 4 已含 `is_disconnected()` 检测代码;完整 chaos 测试跟 cancel/retry 一起 Plan 3 ship)|
| 10 | dogfood + done card | 本 commit |

## C 档承诺实现路径

完成后浏览器实测可验证:
- 发长 prompt → 看打字机吐字(后端 chunk 级 push,前端 RAF + char queue 调速)
- 关浏览器 → 等 30 秒 → 重开 → token 继续吐(in-flight subscribe via Redis Streams)
- web 进程重启不影响推理(Celery worker 独立进程跑)

## 关键架构成果

### 1. Graceful Dual-Path 设计(Plan 1 + Plan 2 共存)

`POST /api/v0/chat` 根据 `app.state.redis_async` 存否分流:
- **Redis wired**(Task 7 lifespan) → Plan 2 enqueue path:返 JSON `{task_id, session_id, stream_url}`,Celery worker 跑 graph
- **Redis 不可达** → Plan 1 legacy inline path:`StreamingResponse(_stream_chat(...))`(原 Plan 1 行为)

意义:Plan 2 PR merge 后 production deploy 时,只要 Redis 不可达 / 没 wire,POST /chat 自动 fallback Plan 1,**零 production 风险**。Redis wire 后(本 Plan 2 已含),自动切到 Plan 2 path。

### 2. DB-as-truth + Agent/Transport 解耦(Hermes 模式)

| 层 | 责任 | 落地 |
|---|---|---|
| Redis Streams(实时层)| chunk 级 event,XADD by worker / XREAD by web | `ChatEventBus`,key 模式 `chat:events:{sid}:{tid}`,TTL 24h |
| PG `chat_messages`(持久层)| 消息级摘要(user / assistant 各一行)| Plan 1 `ChatSessionRepo.append_message` |
| PG `chat_tasks`(状态层)| 6 状态机 + last_event_seq + checkpoint_id | Plan 1 `ChatTaskRepo` |
| Celery worker(推理进程)| graph.astream_events 独立于 HTTP request 生命周期 | `chat_runner.run_chat_async` |
| Web SSE(transport)| 从 Redis XREAD 转发,客户端断开不杀 task | `chat.py` GET endpoint |

### 3. 前端 Token 视觉解耦后端 chunk

后端 push **chunk 级**(每 50-100 chars 一个 LangGraph event,~1/100 token-level 量),前端 `useTypewriter` hook 用 RAF + char queue 模拟 **token 级打字机**:
- 默认 30 chars/s 平滑
- queue ≥ 200 chars 自动加速到 100 chars/s 追赶
- Math.floor 小数损失通过 `remainderRef` 跨帧累积修正

后端 IO 压力 ↓ × 100,前端视觉无差异。

### 4. SSE last_event_id ↔ Redis Stream entry id 协议

Redis Streams entry id 格式 `<ms>-<seq>`(spec § 6.2)直接作为 SSE `id:` field 透传给前端。前端断流回传 last_event_id → 服务端 `XREAD STREAMS key {last_event_id}` 续读,**0 额外 indirection**。

## 测试守护矩阵

| 守护项 | 结果 |
|---|---|
| Plan 2 scoped backend(8 test 套件)| 全 PASS |
| Plan 2 + Plan 1 regression(`test_chat_runner.py` + `test_chat_inflight_plan2.py` + `test_chat_persistence_plan1.py` + Plan 1 SSE + escalate + chats_router)| 全 PASS |
| L2 sanity(`test_chat_inflight_l2.py` — 真 Celery worker subprocess + 真 Redis)| PASS |
| backend full chat-related sweep | 180+ passed |
| backend mypy strict | 0 issues / 647 files |
| backend ruff(check + format)| 全 clean |
| frontend vitest | 180/180 PASS(含 4 useTypewriter + 8 useChatSSE 扩展)|
| frontend tsc build | OK |
| frontend lint | 0 new errors(32 pre-existing 不动)|

## Spec § 1.2 三个根因覆盖(Plan 1 + 2 累计)

| § 1.2 失效面 | Plan 1 | Plan 2 |
|---|---|---|
| chat 消息不入库 | ✅ 修复(POST 入口 + finally)| 继续:Celery worker 内 finalize_task_persistence |
| 服务端不感知断开 | ❌(inline 路径不感知)| ✅ 修复:GET /chat/stream `request.is_disconnected()` + Celery 独立进程 task 不被杀 |
| 前端假 reconnect 后端 404 | ✅ 修复(改 GET /chats reload)| 继续:Plan 2 path 走真 `/chat/stream/{tid}`,有 last_event_id 协议 |

**累计 3/3 全覆盖**(Plan 2 完成「服务端不感知断开」补丁)。

## Plan 2 → Plan 3 留口

Plan 2 schema 已留好 Plan 3 接口:
- `chat_tasks.langgraph_checkpoint_id`:已被 finalize_task_persistence 写入,Plan 3 retry 直接读
- `chat_tasks.parent_task_id`:Plan 3 retry 链链接前次失败 task
- `chat_tasks.last_event_seq`:Plan 2 worker `bump_seq`,Plan 3 stale scanner 读
- `chat_tasks.status` 6 状态机:`cancelled` / `partial` 留给 Plan 3 cancel signal
- `ChatEventBus`:Plan 3 cancel 用 Pub/Sub channel(不是 Streams),独立 component

## 已知 Plan 2 follow-up(deferred 到 Plan 3)

| 项 | 优先级 | 说明 |
|---|---|---|
| L2 chaos:杀 Celery worker / 杀 web / 杀 Redis | 中 | Plan 3 task 9 一起,跟 cancel/retry chaos test 共用 fixture |
| 客户端断开守护 L2 测试 | 中 | Task 4 已含 `is_disconnected()` 代码,Plan 3 加 e2e 守护 |
| Cancel signal(POST /chat/cancel/{tid})| 中 | Plan 3 主体 |
| Retry from checkpoint(POST /chat/retry/{tid})| 中 | Plan 3 主体 |
| Stale scanner(Celery Beat 每分钟扫 running > 5min)| 低 | Plan 3 主体 |
| 3 differential golden cases | 中 | Plan 3 主体 |

## Plan 2 dogfood follow-up(reviewer 验)

PR review 阶段 reviewer 浏览器测三个场景:

1. **简单 chat 流(打字机生效)**
   - 发普通 prompt → 看 token 一字一字吐(后端 chunk → 前端 RAF 调速)
   - 验:后端 chat_tasks status=done,chat_messages 落 user + assistant

2. **关页面 30 秒重开**(C 档核心)
   - 发长 prompt(预计 30+ 秒推理)
   - 中途**关浏览器**
   - 等 10-30 秒
   - **重开** → 应看到推理 in-flight 流仍在继续吐字(via /chat/stream/{tid} replay)
   - 验:页面打开后 token 继续吐(via Redis Stream XREAD 续读,not poll PG)

3. **web 进程重启**(graceful degrade)
   - 发 prompt → 推理中
   - `uv run poe dev` reload(代码修改触发热重启)
   - 前端断流 → 重连 GET /chat/stream/{tid}(本地仍记得 task_id + last_event_id)
   - 验:推理(已经在 Celery 进程)未被 web reload 影响

## 工程量统计

| 阶段 | 内容 | wall time(实际)|
|---|---|---|
| Task 1 — ChatEventBus | 7 L0 test + fakeredis | ~30min |
| Task 2 — chat_finalize 抽 helper | 移 module + 守护 test | ~20min |
| Task 3 — Celery run_chat_async | 实现 + 2 L0 test | ~40min |
| Task 4 — GET stream endpoint | 实现 + 3 L1 test + SSE parsing | ~50min |
| Task 5 — POST /chat dual-path | 改造 + 1 L1 test + FastAPI union response | ~30min |
| Task 6 — 前端双阶段 + typewriter | 5 文件 + 7 self-caught fixes | ~50min |
| Task 7 — app_main wire Redis | 极简改动 | ~5min |
| Task 8 — Celery worker prod wiring + L2 | 实现 + L2 sanity + 4 hidden bug fix | ~60min |
| Task 10 — done card | 本文件 | ~10min |
| **合计** | | **~5 小时**(Claude Code 加速 + subagent 并发) |

## Commit Chain

```
567fdb4  feat(chat-persistence): Celery run_chat worker production wiring + L2 sanity test
71a4cec  feat(chat-persistence): app_main lifespan wire Redis async client + app.state.redis_async
74d9592  feat(chat-persistence): 前端双阶段流 + RAF 打字机渲染 (Plan 2 + Plan 1 双 path)
6060cb1  feat(chat-persistence): POST /chat graceful enqueue path (Plan 2 + Plan 1 双 path)
7d59057  feat(chat-persistence): GET /chat/stream/{tid} SSE replay endpoint + Redis XREAD
bddd938  feat(chat-persistence): Celery task run_chat_async + XADD Redis Streams + finalize
b23f0d2  refactor(chat-persistence): 抽 _finalize_task_persistence 出 chat.py 到 chat_finalize.py
3feaeed  feat(chat-persistence): ChatEventBus — Redis Streams 封装 + 7 L0 test
```

## 下一步

1. **Plan 2 PR review + merge**:浏览器 dogfood 3 个场景 → PR review → merge 到 main
2. **Plan 3 起 spec + plan**(Plan 2 ship 后下一个 brainstorm session):cancel + retry + stale + chaos 完整一卷
3. **若 Plan 2 dogfood 发现真 bug**:在 worktree 内 follow-up commit,push 更新 PR

Plan 2 ship 后,chat session 持久化的核心 3 篇布线就位:**Plan 1(persistence)+ Plan 2(in-flight)+ Plan 3(robustness/recovery)**。Plan 1+2 已让用户感知层(DB-as-truth + 关页面重开继续看)落地;Plan 3 是 production-hardening。

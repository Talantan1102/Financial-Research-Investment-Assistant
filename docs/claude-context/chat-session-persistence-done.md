---
title: Chat Session 持久化 + In-flight Subscribe + Cancel/Retry 完整 ship
type: project
date: 2026-05-17
---

# Chat Session 持久化体系 ship 完(2026-05-17)

**结论**:三卷 Plan 1 + 2 + 3 全部 squash merged 到 main,Spec § 1.2 三根因 3/3 全覆盖,**C 档完整体验闭环**就位:打字机吐字 → 关页面 SSE 续流 → web 进程 crash recovery → cancel partial commit → stale 自愈 → retry from LangGraph checkpoint。

## 3 Plan ship 范围

| Plan | ship 范围 | PR / 入 main |
|---|---|---|
| Plan 1 — Foundation(DB-as-truth)| `chat_tasks` 6 状态机表(queued/running/done/cancelled/partial/error)+ `chat_messages` 加 task_id/status 列 + ChatTaskRepo 9 method + POST /chat 入口落 user message + create chat_task + `_stream_chat` finally 块 commit assistant + GET /chats/{sid} 返 active_task_id + 前端去掉假 reconnect 改 reload 历史 + 10 commits | PR #59 → main `4252dba` |
| Plan 2 — In-flight Subscribe(C 档)| ChatEventBus(Redis Streams 封装)+ chat_finalize.py 抽 helper + Celery `run_chat_async` task + GET /chat/stream/{tid} SSE replay endpoint + POST /chat graceful dual-path(JSON enqueue / SSE legacy fallback)+ 前端 useChatSSE 双阶段 + useTypewriter RAF 打字机 + app_main wire Redis async client + Celery worker production wiring + L2 sanity test + Scenario B subscribe(切 session 回来续 stream)+ **8 dogfood bug fix**(详见末尾 systematic-debugging 沉淀)+ 17 commits | PR #61 → main `62ba00f` |
| Plan 3 — Cancel + Retry + Stale + Golden | ChatCancelBus(Redis pub/sub channel-per-task)+ ChatTaskRepo.find_stale_running_tasks + Worker cancel listener + GraphInterrupt + partial commit + POST /chat/cancel/{tid} + POST /chat/retry/{tid}(parent_task_id 链 + resume_checkpoint_id)+ Stale scanner Celery Beat(60s 间隔)+ 前端 cancel + retry button + active_task_id state + 3 differential golden cases + 9 commits | PR #63 → main `03c823a` |

## 4 要素架构

| 要素 | 落地 |
|---|---|
| **DB-as-truth(Hermes 思路)** | PG `chat_messages` + `chat_tasks` 是 source of truth;每轮 LLM call / tool call 不等于「飞」出去,worker finally 块 commit。client 断了不影响 task 完整性。 |
| **Agent ↔ Transport 解耦** | Celery worker 进程跑 graph(独立于 web HTTP request 生命周期);Web SSE handler 只做 Redis Streams XREAD → SSE 转发;`request.is_disconnected()` 检测断开但不杀 task。web crash 不影响推理。 |
| **Redis Pub/Sub Cancel** | spec § 6.1 option c wrapper 模式 — LangGraph 1.x 不支持外部 kill 信号,worker 内 async listener subscribe `chat:cancel:{tid}` → set Event flag → graph node 之间 wrapper 检查 flag → raise `_CancelledByUser` → finalize 走 partial commit(status=partial,checkpoint_id 写入留 retry 用)。 |
| **LangGraph Checkpoint Resume** | `chat_tasks.langgraph_checkpoint_id` 在 done/partial/cancelled 时写入;retry endpoint 从这个字段构造 `RunnableConfig.configurable.checkpoint_id` 让 LangGraph 从 thread state 续跑(不重头);parent_task_id 链链接 retry 历史。 |

## Spec § 1.2 三根因覆盖矩阵

| 根因 | Plan 1 | Plan 2 | Plan 3 |
|---|---|---|---|
| chat 消息不入库(刷新蒸发)| ✅ POST 入口落 user + finally 落 assistant | continue | partial 路径也入库 |
| 服务端不感知断开(任务白跑)| ❌(inline path 仍跑)| ✅ Celery 独立进程 + `is_disconnected` 检测 | + stale scanner 自愈 worker crash |
| 前端假 reconnect 404 | ✅ 改 reload 历史 | ✅ 真 `/chat/stream/{tid}` + last_event_id 协议 | + retry button 真 resume |

**累计 3/3 全覆盖**。

## 完整用户感知路径(三卷累计)

1. **发 prompt → 看打字机吐字**(后端 chunk 级 push,前端 RAF + char queue 调速 30 chars/s → 视觉等同 token 级 streaming)
2. **关页面 30 秒重开 → in-flight subscribe 续流**(spec § 5.2 Scenario B — 切 session 回来 ChatPane 自动调 subscribeToTask(active_task_id))
3. **Web 进程 crash → Celery 独立进程继续跑 → 重启后看到完整结果**(spec § 5.5 Scenario E — Plan 2 dogfood 场景 3 已手动 + curl 双 verify)
4. **点「停止生成」→ 推理几秒内停下,显示「partial」状态 + 保留已生成部分**(spec § 5.3 Scenario C — cancel signal → graph wrapper → partial commit)
5. **Worker crash → 1 分钟内 stale scanner mark error → 前端 error badge + retry 按钮**(spec § 6.6 — Celery Beat 每分钟扫 `status=running` + `started_at > 5min`)
6. **点「重试」→ 从 LangGraph checkpoint 续跑(不重头开始)→ token 接着吐字**(spec § 5.4 Scenario D — retry endpoint + `resume_checkpoint_id` 注入)

## 关键决策(实施期撞实,spec 已锚定)

| 决策 | 落地 |
|---|---|
| Plan 拆 3 卷(spec § 9.1)| 而不是一卷大 ship。每 plan 独立可 ship + 可 PR + 可 review,降低 review 负担 |
| Plan 2 graceful dual-path(POST /chat 改造)| Redis wired → JSON enqueue(Plan 2 新);Redis 不可达 → SSE legacy(Plan 1)。production deploy 0 风险(rollback 自然) |
| Cancel 信号 spec § 6.1 option c wrapper | LangGraph 1.x 没原生 cancel API,wrapper 模式接受 1-3s 粒度;不引重型 GraphInterrupt 重构 |
| Retry checkpoint 续跑而非重头 | 用户主动 retry → 节省 LLM token / 推理时间;静默自动 retry 显式不做(spec § 9.3,避免 LLM 报错 → 烧钱循环)|
| Stale 阈值 5 分钟 + Beat 每 60s 跑 | spec § 6.6 — 正常推理 30s-3min,超 5min 无 last_event_seq 更新 99% 是死锁/崩溃;Beat 比 worker 内 heartbeat 更可靠(worker 死了 heartbeat 也死)|
| `chat_tasks.user_id` nullable(实施期 fix)| dogfood 暴露:production user="anonymous" `uuid.UUID("anonymous")` crash;改 nullable + `_coerce_user_uuid` 返 None 对齐 ChatSession.user_id 模式 |
| 6-state lifecycle 三 path 闭环 | queued → running → {done / partial / cancelled / error};retry 创建新 task 不复用旧 task(parent_task_id 链) |
| L2 chaos automated test deferred | plan 阶段就标 「推到 implementer 按 conftest_celery spike」;docker pause/unpause environment-specific;Plan 2 dogfood 场景 3 已手动验过 web crash + Plan 2 L2 sanity test landed |

## Plan 1+2+3 follow-up 留口

| 项 | 推迟原因 | 触发条件 |
|---|---|---|
| L2 chaos test 自动化(杀 worker / Redis / web)| environment-specific + 已手动验过 | 上 CI / scale 阶段做 |
| 浏览器 dogfood 真测 Plan 3 cancel + retry + stale 三流 | PR review 阶段时间不足 | reviewer / user 在 staging 验 |
| Cancel timing 一致性强保证(< 1s 粒度)| spec § 6.1 接受 1-3s wrapper 粒度 | 用户体验调研后决定 |
| 前端 cancel/retry button UX polish(loading state / confirmation modal)| Plan 3 ship 基本能用版本 | 用户反馈触发 |
| 多 tab fan-out 强一致性(同 session 两 tab 同步进度条)| spec § 9.2 留 v1.x escape hatch | 多人协作场景出现 |
| 全局 task dashboard(查看哪些 task 在跑 / 历史平均时长)| 个人 portfolio 不需要 | scale up 阶段 |
| Redis AOF 持久化(Redis crash 不丢 in-flight gap)| portfolio 不上 | production 数据可靠性要求提升 |
| Token 级 streaming(替代 chunk 级)| 前端 typewriter 模拟视觉够好 | LLM provider 支持成本下降时 |

## Systematic-debugging 沉淀(Plan 2 dogfood 教训)

Plan 2 dogfood「流式不显示」连续 **6 round symptom fix** 才用 backward trace 找到真根因:**SSE token dedup `ev.seq` 字段在 Plan 2 backend payload 缺失** → `undefined > 0 = false` → token 永远 skip → typewriter 从未 enqueue。

修复路径(commit `a4ddf02`):前端 dedup logic 改为只在 seq 存在且 ≤ last_seq 时 skip。

教训沉淀到 `~/.claude/projects/.../memory/feedback_n_round_fix_means_phase1_redo.md`:**3+ round fix 没用立刻 Phase 1 重做 + instrument 整条数据流 backward trace,不要继续猜下一个 component 的 symptom fix**。

skill `superpowers:systematic-debugging` Phase 4.5 已经明确:3+ failures = architectural / 跨组件问题。早一轮 curl SSE 端到端 trace 省 6 round 试错。

## 简历叙事段

> **Chat Session 持久化 + In-flight Subscribe + Cancel/Retry(2026 Q2)**
>
> 把单进程 SSE 长连接改造为 **LangGraph + Celery worker + Redis Streams + Pub/Sub** 的解耦推理架构,让 agent 推理脱离 HTTP request 生命周期:
>
> - **DB-as-truth 双层存储**:Redis Streams 做实时事件层(TTL 24h,XREAD 协议直接对应 SSE replay),Postgres 做持久消息层 + 6 状态 task lifecycle(queued/running/done/cancelled/partial/error)
> - **Cancel via Pub/Sub**:Redis `chat:cancel:{tid}` channel + worker 内 async listener + graph node wrapper 检查 Event flag → raise `_CancelledByUser` → finalize 走 partial commit
> - **Retry from LangGraph Checkpoint**:`chat_tasks.langgraph_checkpoint_id` + `parent_task_id` 链 → retry endpoint 创建新 task 注入 `RunnableConfig.configurable.checkpoint_id` → LangGraph 自动从 checkpoint state 续跑(不重头)
> - **Stale 自愈**:Celery Beat 每 60s 扫 `status=running + started_at > 5min` → mark error + XADD error_done event → 前端 retry 闭环
> - **Production-ready 改造**:graceful dual-path 让 deploy 时 Redis 未 wire 自动 fallback Plan 1 inline SSE — 0 risk progressive rollout
> - **故障演练**:web 进程 crash(curl 验)+ L2 sanity test(真 Celery worker subprocess)守护进程解耦

参考 Hermes(Nous Research)的 「agent loop / transport 解耦」设计,在 Web SSE 场景下加 in-flight subscribe + cancel + retry from checkpoint 能力。spec § 1.2 三根因(消息不入库 / 服务端不感知断开 / 前端假 reconnect)累计 3/3 全覆盖。

## Commit Chain(三卷主体,按 PR 合入顺序)

```
03c823a  Plan 3: Cancel + Retry + Stale + Differential Golden (#63)
62ba00f  Plan 2: In-flight Subscribe — Celery + Redis Streams + 打字机 (#61)
4252dba  Plan 1: Foundation — chat session 持久化 (#59)
```

## Spec / Plan 文档

- Spec: `docs/superpowers/specs/2026-05-16-chat-session-persistence-design.md`(三卷统一 spec)
- Plan 1 plan: `docs/superpowers/plans/2026-05-16-chat-session-persistence-plan1-foundation.md`
- Plan 1 done card: `docs/superpowers/plans/2026-05-16-chat-session-persistence-plan1-done.md`
- Plan 2 plan: `docs/superpowers/plans/2026-05-16-chat-session-persistence-plan2-inflight-subscribe.md`
- Plan 2 done card: `docs/superpowers/plans/2026-05-16-chat-session-persistence-plan2-done.md`
- Plan 3 plan: `docs/superpowers/plans/2026-05-17-chat-session-persistence-plan3-cancel-retry-chaos.md`
- Plan 3 done card: `docs/superpowers/plans/2026-05-17-chat-session-persistence-plan3-done.md`

## 总工程量(实际 wall time)

约 1.5-2 天 wall time(含 dogfood 试错):
- Plan 1: 3-4 小时(schema + repo + endpoint + 前端 fix)
- Plan 2: 5-6 小时(Celery + Redis Streams + 前端 + 8 dogfood round)
- Plan 3: 3.5-4 小时(cancel + retry + stale + golden + UI)

Claude Code 加速明显的部分:Plan code(boilerplate)+ unit test 模板。人-bound 段:Plan 2 dogfood 6 round fix(systematic-debugging 教训核心)。

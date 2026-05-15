# Chat Session 持久化与 In-flight Subscribe 设计

**作者**:Talantan1102
**起草**:2026-05-16
**状态**:Spec(待 plan 拆分)
**类型**:Implementation spec(架构改造 + 新组件 + Schema 演进)

---

## § 0 元信息与范围

### 0.1 触发动机

2026-05-16 审视当前 chat 模式的 session 生命周期实现,发现三个互相耦合的根因:

1. **chat 中间状态完全不入库** — `backend/app/router/chat.py:358-550` 的 `_stream_chat()` 把 SSE 事件「飞」出去后不留底,只有 `escalate.py:180-187` 在升级研报时 append_message。结果:**chat 模式下用户消息 + assistant 回复都不入库,刷新 = 蒸发**
2. **客户端断开服务端不感知,但也没存盘** — `_stream_chat()` 无 `request.is_disconnected()` 检测,LangGraph `graph.astream_events()` 继续跑完;但因为不写库,跑出来的结果**没有任何接收者**
3. **前端假装能 reconnect,后端没接** — `frontend/src/hooks/useChatSSE.ts:143` 拼 `GET /api/v0/chat/stream/:id?last_event_id=N`,但后端 `chat.py` 只有 `POST /api/v0/chat`,生产环境必定 404。前端测试用 MSW mock 了这个路径(`useChatSSE.test.tsx:90`)所以绿,**生产骨折**

对照参考:同源 agent 项目 Hermes(`/Users/talantan/.openclaw/workspace-main/hermes-agent`)的核心设计是 **DB-as-truth + agent/transport 解耦**:每轮 LLM call / tool call 立刻 SQLite WAL 写盘(`hermes_state.py:172-222` + `run_agent.py:3449`),客户端断开 → 后台 thread 继续跑 → 重连读 DB 完整 replay。

### 0.2 范围边界

**做**:
- chat 模式的 SSE 流改造为「event-bus 驱动」:Celery worker 跑 graph,事件 push 到 Redis Streams,web SSE 只做 transport
- 新建 `chat_tasks` 表 + `chat_messages` 加 task 关联字段
- 新增 `GET /chat/stream/{task_id}` / `POST /chat/cancel/{task_id}` / `POST /chat/retry/{task_id}` 三个 endpoint
- LangGraph `AsyncPostgresSaver` checkpointer 复用为 resume 来源
- 前端 `useChatSSE` 改造为真正的 last_event_id 协议,接 cancel / retry 按钮
- 6 状态 task lifecycle 状态机(queued / running / done / cancelled / partial / error)
- L0/L1/L2/L2.5 四层测试 + 故障演练(杀 Celery / 杀 web / 杀 Redis)

**不做(真 YAGNI,留 v1.x escape hatch)**:
- 多 tab fan-out 一致性强保证(Redis Streams 自然 fan-out,但跨 tab 进度条强同步不做)
- 全局 task dashboard(几条在跑/平均时长 等运维视图)
- Celery 跨用户 quota / rate limit
- Redis AOF/RDB 持久化(接受 Redis crash → in-flight gap 永久丢)
- 前端 playwright e2e(deferred 到后续 polish)
- token 级流式(决策 chunk 级 push,前端模拟打字机渲染)

### 0.3 关键 memory 引用

- `feedback_no_portfolio_simplification` — 每个非平凡决策按「工业级落地困难 + 业界 alternatives + 我们取舍」三维评估
- `feedback_estimate_in_claude_code_walltime` — 工期估算用 wall time(天/周),区分 Claude Code 加速段 vs 人-bound 段
- `feedback_real_collision_not_simulated` — 故障演练必须真的杀 Celery / 杀 web / 杀 Redis,不接受 mock
- `feedback_subagent_default_sonnet` / `feedback_plan_writing_must_use_opus` — Plan 阶段 subagent 配置
- `feedback_serve_path_no_ci_coverage` — 改 `app_main.py` 顶层 import / lifespan / include_router 必须本地 import smoke
- `feedback_legacy_barrel_eager_import_rot` — 引重依赖时先 grep 死代码
- `c5-plan2a-write-pipeline-core-done` — 类似的双层存储(热 Redis + 冷 PG)模式已 ship,架构语言可复用
- `celery-redis-test-fixture-pattern` — L0/L1 eager + L2 worker subprocess 已有 pattern
- `v0_architecture_landed` — LangGraph 1.1 + SqliteSaver(已被 AsyncPostgresSaver 取代,`app_main.py:186-189`)

### 0.4 用户研究 / 验证

用户已选档位与执行环境(brainstorm 2026-05-16 session,见 § 2.1)。三个核心决策有明确表态:
- 目标档位:**C 档**(in-flight subscribe,关页面重开能继续订阅 in-flight 增量)
- 执行环境:**Y**(Celery worker)
- 存储模型:**P**(Redis Streams + PG 双层) + chunk 级 push / 前端打字机渲染
- 失败恢复:**S3**(Redis pub/sub cancel + LangGraph checkpointer resume)

---

## § 1 现状根因

### 1.1 当前调用链

```
POST /api/v0/chat
  → chat.py:557 _stream_chat() generator
    → chat.py:419 graph.astream_events()
    → chat.py:292-342 _adapt_event() 把 LangGraph 事件映射成 SSE
    → yield → client
  (generator 关掉后 LangGraph 继续跑,但 event 没人接,等于"飞"出去)
  (整个流程内无 append_message;只有 escalate.py:180-187 写 1 条研报链接)
```

### 1.2 检索到的失效面

| 失效 | 证据 | 影响 |
|---|---|---|
| chat 消息不入库 | `_stream_chat()` 内 grep `append_message` 0 命中;`chat_session_repo.list_messages()` 只能查到 escalation 路径写的 1 条 | 关页面 = 历史蒸发 |
| 服务端不感知断开 | `_stream_chat()` 无 `request.is_disconnected()` / cancel 逻辑 | 算力照烧,但产物丢失 |
| 前端假装 reconnect | `useChatSSE.ts:143` 调用 `buildChatStreamUrl()`(`chatApi.ts:62-69`)拼一个后端不存在的 URL;`useChatSSE.test.tsx:90` 用 MSW mock 该路径,测试通过假象 | 生产环境 404 持续重试到放弃 |
| LangGraph checkpointer 仅用于 cross-turn | `AsyncPostgresSaver` 注册在 `chat_graph.py:248`,thread_id 在 `chat.py:407`,但没有 endpoint 暴露 checkpoint state | resume 能力沉睡 |

### 1.3 Hermes 参考解法摘要

| 设计点 | Hermes 实现 | 锚 |
|---|---|---|
| DB 是 source of truth | SQLite WAL,每轮 LLM call/tool call 立刻 `_flush_messages_to_session_db()` | `run_agent.py:3449`,`hermes_state.py:172-222` |
| Agent / transport 解耦 | agent loop 在后台 thread,`stream_delta_callback` 写队列,async consumer 推到 client;client 断开只是 consumer 标 `_closed=true`,agent 不感知 | `gateway/stream_consumer.py:1-90` |
| 跨 transport 续话 | `(source, user_id)` 索引 session,所有 gateway 共享同一 session_id | `gateway/session.py:716`,`gateway/run.py:1016` |
| Reconnect 协议 | 无 — DB-as-truth 兜底,client 重连先拉历史 + 再订阅增量 | `tui_gateway/event_publisher.py` best-effort |

本 spec 在 Hermes 思路上加 **C 档增量**:in-flight subscribe(不只看快照,还能继续看后续推出的新事件),用 Redis Streams 替代 Hermes 的「队列 + DB 轮询」。

---

## § 2 设计骨架

### 2.1 三个核心决策溯源

**决策 1:目标档位 = C(in-flight subscribe)**

| 选项 | 描述 | 工业典型 | trade-off |
|---|---|---|---|
| A | 历史可见(刷新看到完整对话,但 in-flight 中关掉看不到流) | 大多数 ChatGPT-clone | 工程量最小,但 C 档承诺的"关电脑回家继续看"不支持 |
| B | Hermes-style 完整 replay(每事件落库 + 截止快照) | Hermes / Claude.ai | 比 A 多一档但仍需 polling 增量 |
| **C** ✓ | **真 in-flight subscribe(继续订阅增量流)** | **实时协作产品** | **要 pub/sub 层(Redis Streams),工程量大但简历叙事最完整** |

选 C 理由:
- 解决用户提的真痛点(关掉/重开看到的不是空白)
- C 档对架构的"破坏性"反而推动正确的解耦(agent ≠ request handler),长期可维护性高
- 简历叙事:「LangGraph + Celery + Redis Streams 的 in-flight subscribe」比「事后 replay」工业级别更高

**决策 2:执行环境 = Y(Celery worker)**

| 选项 | 描述 | trade-off |
|---|---|---|
| X | FastAPI asyncio background task,事件走 Redis Streams 或内存 | 延迟最低,但 web 进程重启就丢任务;`uv run poe dev` reload 一次就杀推理 |
| **Y** ✓ | **Celery worker 跑 graph,事件 push 到 Redis Streams,web SSE 只做 transport** | **基础设施零边际成本(B-3 监控、C.5 memory 已用 Celery+Redis);天然多实例;真 fire-and-forget** |
| Z | 混合(短任务 X / 长任务 Y) | 两套机制并存,维护成本翻倍 |

选 Y 理由:
- 项目已有 Celery + Redis 完整 ops layer(`celery-redis-test-fixture-pattern` memory)
- 「关电脑回家继续看」隐含任务可能跑 5-10 分钟,asyncio task 在 web 进程内太脆弱
- 架构语言和现有 `app/tasks/` 一致

**决策 3:存储模型 = P(Redis Streams + PG 双层) + chunk 粒度**

| 选项 | 描述 | trade-off |
|---|---|---|
| **P** ✓ | **Redis Streams 实时层(TTL 24h)+ PG ChatMessage 持久层(消息级摘要)** | **Redis Streams `XREAD STREAMS key $LAST_ID` 天生为 SSE replay 设计;粒度匹配(LangGraph 上千事件不进 PG)** |
| Q | 全事件持久化(只 PG),用 LISTEN/NOTIFY 增量推 | PG INSERT 频率高;LISTEN/NOTIFY payload 8KB 限制;非 PG 强项 |
| R | 只 Redis Streams,TTL 7 天 | 7 天后会话蒸发,违反 chat 产品最基本预期 |

事件粒度:**chunk 级**(LangGraph 自然 chunk 边界,大约每 50-100 token / 一次 model provider 的 chunk callback)。前端 `setInterval` + 字符队列模拟打字机视觉。

选 P 理由:
- Redis Streams 是为 in-flight subscribe 生的,XADD + XREAD + last-id 完美匹配 SSE replay 语义
- `c5-plan2a-write-pipeline-core-done` 已成功用过「热 Redis + 冷 PG」的双层模式,语言一致
- chunk 级解决 token 级的 IO 爆炸(token 级 ×100 写入压力)又保留打字机视觉

**决策 4:失败恢复 = S3(Cancel + Checkpoint Resume)**

| 选项 | 描述 | trade-off |
|---|---|---|
| S1 | 朴素(无 cancel,失败直接弃) | 跑半小时撤不下来,UX 不可接受 |
| S2 | Redis pub/sub cancel + try/finally + partial commit | 工业典型;Cancel + 失败 commit 完整闭环 |
| **S3** ✓ | **S2 + LangGraph checkpointer resume** | **用户点 retry 从最后稳定 state 续跑,不从头跑** |

选 S3 理由:
- 用户主动选择;
- LangGraph `AsyncPostgresSaver` 已经在跑(`app_main.py:186-189`),但 resume 流程未验证 —— 用 retry 把这条路撞实是简历叙事的核心增量
- portfolio 的"严肃"档:故障可恢复 vs 只能重发 prompt 是质的差异

### 2.2 架构图

```
┌──────────────────────┐
│   Browser/Frontend   │
└──────────┬───────────┘
           │ ① POST /chat                               (启动:enqueue + 返回 task_id + stream_url)
           │ ② GET /chats/{sid}                         (拿历史 ChatMessage + active_task_id)
           │ ③ GET /chat/stream/{tid}?last_event_id=X   (重连 / 续订)
           │ ④ POST /chat/cancel/{tid}                  (停止 → PUBLISH cancel)
           │ ⑤ POST /chat/retry/{tid}                   (从 LangGraph checkpoint resume)
┌──────────┴──────────┐
│   FastAPI Web       │  只做 enqueue + SSE 转发 + cancel/retry 信号 + auth
└──────────┬──────────┘
           │
   ┌───────┴─────────────────────────────────────────────────────┐
   │                                                              │
┌──┴──────────┐                                          ┌────────┴──────┐
│   Redis     │                                          │   Celery       │
│  ─────────  │ ◀─── XADD chunks/events ─────────────── │   Worker       │
│ Streams:    │ ──── XREAD by web ────────────────▶     │                │
│   chat:     │                                          │   跑 LangGraph │
│   events:   │ ◀─── XADD done/error/cancelled ──────── │   astream_events│
│   {sid}:    │                                          │                │
│   {tid}     │                                          │   监听         │
│ (TTL 24h)   │                                          │   chat:cancel: │
│             │                                          │   {tid}        │
│ Pub/Sub:    │ ◀─── PUBLISH cancel by web ──────────── │                │
│   chat:     │ ──── SUBSCRIBE by worker ────────────▶  │   try/finally  │
│   cancel:   │                                          │   commit PG    │
│   {tid}     │                                          │                │
└─────────────┘                                          └────────┬───────┘
                                                                  │
                                                         ┌────────┴───────┐
                                                         │  PostgreSQL    │
                                                         │ ─────────────  │
                                                         │ chat_messages  │ (+ task_id / status)
                                                         │ chat_tasks(新) │ (6-state lifecycle)
                                                         │ langgraph_     │
                                                         │   checkpoints  │ (复用 AsyncPostgresSaver)
                                                         └────────────────┘
```

---

## § 3 组件清单

| 组件 | 新/改 | 路径 | 职责 |
|---|---|---|---|
| `ChatTaskRunner`(Celery task) | **新** | `backend/app/tasks/chat_task.py` | enqueue 入口;跑 `graph.astream_events()`;每事件 XADD;asyncio task 监听 cancel channel;try/finally 写 PG |
| `ChatEventBus` | **新** | `backend/app/services/chat_event_bus.py` | Redis Streams 封装:`xadd_event(sid, tid, payload)` / `xread_blocking(sid, tid, last_id, count)` / TTL setup |
| `ChatCancelBus` | **新** | `backend/app/services/chat_cancel_bus.py` | Redis pub/sub 封装:`publish_cancel(tid)` / async listener factory |
| `ChatTaskRepo` | **新** | `backend/app/services/chat_task_repo.py` | `chat_tasks` 表 CRUD:`create_queued` / `mark_running` / `mark_done` / `mark_cancelled` / `mark_error` / `find_stale` |
| `chat_session_repo`(已有) | **改** | `backend/app/services/chat_session_repo.py` | 加 `append_message(task_id=..., status=...)` 支持,新方法 `find_active_task(sid)` |
| POST `/chat` | **改** | `backend/app/router/chat.py:557` | 不再 inline 跑 graph;改成 `ChatTaskRepo.create_queued()` + `run_chat.delay(task_id)` + 返回 `{task_id, stream_url}` |
| GET `/chat/stream/{tid}` | **新** | `backend/app/router/chat.py` | 鉴权 + `ChatEventBus.xread_blocking()` 转发 SSE;支持 `last_event_id` query param |
| POST `/chat/cancel/{tid}` | **新** | `backend/app/router/chat.py` | 鉴权 + `ChatCancelBus.publish_cancel(tid)` + 立刻返回 202(异步生效) |
| POST `/chat/retry/{tid}` | **新** | `backend/app/router/chat.py` | 鉴权 + 从 `chat_tasks` 查 `langgraph_checkpoint_id` + enqueue 新 resume task |
| `chats.py` GET `/chats/{sid}` | **改** | `backend/app/router/chats.py:58` | 返回 messages + `active_task_id`(若有 in_flight task) + `last_event_seq`(replay 起点) |
| Celery Beat task `scan_stale_chat_tasks` | **新** | `backend/app/tasks/chat_stale_scanner.py` | 每分钟扫 status=running 且 `last_event_seq` 5 分钟无更新 → 标 error |
| `useChatSSE`(改) | **改** | `frontend/src/hooks/useChatSSE.ts` | 真正用 last_event_id 协议;接 `GET /chat/stream/{tid}`(stream endpoint 改成 task_id-based,不是 session_id-based);开 stream 前先 POST /chat 拿 task_id |
| `ChatPane`(改) | **改** | `frontend/src/components/chat/ChatPane.tsx` | 显示 task status badge;cancel / retry 按钮;打字机渲染 |
| `chatApi.ts`(改) | **改** | `frontend/src/api/chatApi.ts:62` | 重写 `buildChatStreamUrl()` 为 task_id-based;新增 `cancelTask()` / `retryTask()` |

---

## § 4 数据模型

### 4.1 新表 `chat_tasks`

```sql
CREATE TABLE chat_tasks (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id               UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    user_id                  UUID NOT NULL,
    status                   TEXT NOT NULL,
        -- enum: queued / running / done / cancelled / partial / error
    langgraph_thread_id      TEXT NOT NULL,
        -- 复用 chat.py:407 的 "{user_id}:{session_id}" 形式
    langgraph_checkpoint_id  TEXT,
        -- 最后一次稳定 checkpoint;retry 时定位
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at               TIMESTAMPTZ,
    finished_at              TIMESTAMPTZ,
    error_message            TEXT,
    last_event_seq           BIGINT NOT NULL DEFAULT 0,
        -- Redis Stream 截止位置(对应 stream entry id 的逻辑映射);stale 探测用
    initial_prompt_message_id UUID,
        -- 关联本次 task 由哪条 user message 触发;retry 时复用 prompt
    parent_task_id           UUID REFERENCES chat_tasks(id) ON DELETE SET NULL,
        -- retry 链接:新 task 的 parent 是前次失败的 task;非 retry 为 NULL
    CONSTRAINT chat_tasks_status_check
        CHECK (status IN ('queued','running','done','cancelled','partial','error'))
);

CREATE INDEX idx_chat_tasks_session ON chat_tasks(session_id);
CREATE INDEX idx_chat_tasks_status_updated ON chat_tasks(status, last_event_seq) WHERE status = 'running';
    -- stale scanner 用
```

### 4.2 `chat_messages` 加列

```sql
ALTER TABLE chat_messages
    ADD COLUMN task_id UUID REFERENCES chat_tasks(id) ON DELETE SET NULL,
    ADD COLUMN status  TEXT NOT NULL DEFAULT 'done'
        CHECK (status IN ('done','partial','cancelled','error'));

CREATE INDEX idx_chat_messages_task ON chat_messages(task_id);
```

**字段语义**:
- `task_id` = NULL: 用户消息(user role),或 legacy escalation 路径写入的 assistant 消息
- `status = 'done'`: 任务正常完成,content 完整
- `status = 'partial'`: 任务被 cancel,content 是 cancel 那一刻已生成的部分
- `status = 'cancelled'`: 任务被 cancel,content 为空(cancel 触发太早,未产生有效输出)
- `status = 'error'`: 任务失败,error 详情见 `chat_tasks.error_message`

### 4.3 状态机

```
chat_tasks.status:
    queued ───→ running ───→ done
              │           │
              │           ├──→ cancelled  (user POST /cancel)
              │           ├──→ partial    (user POST /cancel, 但已有部分输出)
              │           └──→ error      (LLM error / worker crash / stale)
              │
              └──→ error  (enqueue 失败,极少见)

chat_messages.status(role=assistant):
    与 chat_tasks.status 终态对齐:done / partial / cancelled / error
```

### 4.4 LangGraph checkpoint 复用

- `AsyncPostgresSaver` 已经在 `app_main.py:186-189` 注册,thread_id = `"{user_id}:{session_id}"`(`chat.py:407`)
- 本 spec 不动 checkpointer 的存储 schema(`langgraph_checkpoints` 表由 LangGraph 自管理)
- **thread 与 task 的层级**:thread 是 **session 级**(让 LangGraph cross-turn memory 在 session 内自然累积),task 是 **每轮 user message 级**;一个 thread 上会有多个 task 顺序跑(包括 retry 产生的新 task,见 § 11 第 4 项)
- 新增:每次 task finally 落库时,把 `graph.aget_state(config).config["configurable"]["checkpoint_id"]` 拿出来存到 `chat_tasks.langgraph_checkpoint_id`
- retry 时:用 `langgraph_thread_id` + `langgraph_checkpoint_id` 构造 `RunnableConfig` 给新 task,prompt 内容从 `initial_prompt_message_id` 关联的 user message 拿(用户不用重新输入)

---

## § 5 数据流(典型场景)

### 5.1 Scenario A — 新消息正常路径

```
[1] 前端 POST /api/v0/chat { session_id, message }
        Web:
          - INSERT chat_messages (role=user, content=...)
          - chat_task_repo.create_queued(session_id, user_id) → task_id
          - run_chat.delay(task_id)
          - 返回 { task_id, stream_url: "/chat/stream/{task_id}" }

[2] 前端立刻 GET /api/v0/chat/stream/{tid}?last_event_id=0
        Web SSE handler:
          - chat_event_bus.xread_blocking(sid, tid, last_id=0, block=30s)
          - 边收边 yield 给 client(打字机渲染)

[3] Celery worker:run_chat(task_id):
        - chat_task_repo.mark_running(task_id)
        - 启动 async listener:subscribe chat:cancel:{tid} → set asyncio.Event flag
        - try:
            async for event in graph.astream_events(thread_id, ...):
                chunk = adapt_event(event)
                chat_event_bus.xadd_event(sid, tid, chunk)
                chat_task_repo.bump_seq(task_id)  # 每 N 个 chunk 一次,降低写压
                if cancel_flag.is_set(): raise GraphInterrupt
        - finally:
            # 三件必做
            (a) chat_event_bus.xadd_event(sid, tid, {type:done|cancelled|error})
            (b) chat_session_repo.append_message(task_id, role=assistant, content=..., status=...)
            (c) chat_task_repo.mark_done|cancelled|partial|error(task_id, checkpoint_id=...)

[4] 前端收到 done → 关 SSE 连接(或保持开放等 server-side close)
```

### 5.2 Scenario B — 关页面 30 分钟后重开

```
[T+0]   user POST /chat, task 启动
[T+5]   user 关浏览器
[T+5..30] Celery worker 继续跑,Redis Stream 持续 XADD;Web SSE 转发 client 断了但 worker 不感知
[T+30]  user 重开页面
        前端 GET /api/v0/chats/{sid}
            Web:
              - list_messages(sid) → 历史已完成的消息
              - find_active_task(sid) → 若有 status IN (running, queued) 的 task
                  返回 { messages, active_task_id, last_event_seq }
              - 否则只返回 { messages }
        前端立刻 GET /chat/stream/{active_task_id}?last_event_id=0
              - xread_blocking 从头 replay 截止"现在"全部事件
              - 继续订阅增量直到 done
        用户视觉:页面打开,看到打字机重新跑一遍(可加 "replaying..." indicator)
```

### 5.3 Scenario C — 用户点停止

```
[1] 前端 POST /api/v0/chat/cancel/{tid}
        Web:
          - chat_cancel_bus.publish_cancel(tid)
          - 返回 202 Accepted

[2] Celery worker 内 async listener 收到 cancel 信号 → asyncio.Event.set()
[3] 下一个 graph node 之间检查 flag → raise GraphInterrupt
[4] finally 块:
        - xadd_event(type=cancelled)
        - append_message(status=partial, content=已生成内容)
        - mark_cancelled(task_id, checkpoint_id=...)
[5] 前端 SSE 流收到 cancelled 事件 → 显示「已取消」+ retry 按钮
```

### 5.4 Scenario D — Celery worker 崩(stale 探测)

```
[T+0]   task running,正常 XADD
[T+2m]  Celery worker OOM 死掉,task 中断
[T+2m+1s..6m] 无新 XADD,chat_tasks.last_event_seq 不更新
[T+3m]  Celery Beat 扫:
          scan_stale_chat_tasks() 找 status=running 且 last_event_seq 5min 未变
          → 标 status=error, error_message="worker crashed (stale heartbeat)"
[T+任意]   前端打开页面:
          GET /chats/{sid}
          - find_active_task 返回 active_task_id(因为 status 已转 error)
          - 前端看到 error badge + retry 按钮
        前端 POST /chat/retry/{tid}
          - Web 查 chat_tasks 拿 langgraph_checkpoint_id + initial_prompt_message_id
          - 若有 checkpoint_id:
              * 新建 chat_tasks 行(parent_task_id=旧 tid,initial_prompt_message_id 沿用)
              * enqueue 新 Celery task,config 带 thread_id + checkpoint_id → graph 从该 state 续跑
              * 旧 task status 保持 error(历史记录),新 task status=queued
          - 若无 checkpoint_id(从未 commit 过 checkpoint):返回 422 提示用户重发 prompt
```

### 5.5 Scenario E — Web 进程崩

- Web 进程被 kill / reload(`uv run poe dev` 热重启)
- 前端 SSE 连接断 → useChatSSE 指数退避重试 GET /chat/stream/{tid}?last_event_id=<本地最后收到的 seq>
- Web 恢复后,前端重连成功,从 last_event_id 之后续 XREAD
- Celery worker 不受影响

---

## § 6 关键技术决策(带 alternatives 和 tradeoff)

### 6.1 Cancel 信号在 graph 内的传播方式

**问题**:LangGraph 1.x 不支持直接「外部 kill 信号 → 中断 astream_events」。必须 worker 内部做。

**Alternatives**:
- **a. `interrupt_after` / `interrupt_before` 静态配置** — 在 graph 编译时指定中断 node,但只能预设位置,不响应外部信号 → ❌
- **b. 在每个 node 内手动检查 flag(主动轮询)** — 需要改所有 agent 代码,侵入性强 → ❌
- **c. graph 节点间用 wrapper 检查 cancel flag,raise GraphInterrupt** ✓ —— wrapper 用 LangGraph 的 `set_entrypoint` / `add_conditional_edges` 在 supervisor 节点之间插一个 "cancel_guard" 检查点
- **d. 直接 `worker.terminate()`(Celery revoke + signal=SIGTERM)** — 暴力,丢中间状态,无法 partial commit → ❌

**取舍**:选 c。侵入性可控(只动 supervisor / agent 之间的 edge),保留 partial commit 能力。

**类比**:Hermes `stream_consumer._closed` flag 模式 — agent 不阻塞等待 client ACK,但在自然边界检查 flag。

### 6.2 Redis Streams 的 entry id ↔ HTTP last_event_id 协议

**问题**:Redis Streams 的 entry id 是 `<millisecond>-<sequence>`,长度 ~17 字符,前端用作 SSE `Last-Event-ID` header 时需要稳定可比较。

**Alternatives**:
- **a. 直接透传 Redis Streams id** ✓ — `XREAD STREAMS key <last_id>` 原生支持,服务端无需翻译
- b. 服务端自维护单调递增 seq → Redis Streams id 映射 — 多一层 indirection,无收益

**取舍**:选 a。前端 `last_event_id` query param 直接传 Redis entry id 字符串;服务端 `XREAD STREAMS key {last_event_id}`。**例外**:首次连接 last_event_id="0"(stream 起点)。

### 6.3 Redis Streams 的内存占用与 TTL

**问题**:LangGraph 一轮推理产 ~50-200 chunks(chunk 级),每个 chunk ~200-500 bytes(JSON 序列化后)。一个 task 的 Stream ~10-100KB。1000 task/天 → 10-100MB/天。Redis 默认无 TTL。

**Alternatives**:
- a. 不设 TTL,定期清理(`XTRIM MAXLEN`) — 需要额外 Celery Beat 任务,复杂度高
- **b. 每个 Stream 单独 PEXPIRE 24h** ✓ — Redis 7+ 支持 stream key TTL(本质上就是 EXPIRE key 24h)
- c. 用 stream-level `XADD ... MAXLEN ~ 1000` 限制条数 — 限制总长度但不限制总占用时间;in-flight 中可能丢老事件

**取舍**:选 b。每次 task 创建时 `EXPIRE chat:events:{sid}:{tid} 86400`;task 结束(done/cancelled/error)后续 SET 一次 EXPIRE 24h(从结束时刻算)。

### 6.4 多个 user message 一个 task 还是各自一个

**问题**:LangGraph supervisor 一轮可能调多个 sub-agent,每个产 ChatMessage(plan + tool_call + answer)。task 跟 message 是 1:N 还是 1:1?

**Alternatives**:
- a. 1:1(每个 user message 一个 task) ✓ — 自然语义边界,retry 时也是「重发这一条 user message」
- b. 1:N(一个 task 多次 turn,跨多条 user message) — 跟 LangGraph thread 等价,但 cancel/retry 边界模糊

**取舍**:选 a。一个 task = 一次 user 发送 → 一次 assistant 回复(可能跨多个 chunk / tool call)。chat_messages.task_id 关联:user message 的 task_id 是触发它的 task;assistant message 的 task_id 是产生它的 task。

### 6.5 前端打字机渲染速率

**问题**:chunk 级 push,但前端要呈现 token 级视觉。chunk 到达节奏不稳(LLM 输出快慢不均)。

**Alternatives**:
- a. 固定速率(如 30 chars/s)— 平滑但可能落后于实际推理速度
- **b. 字符队列 + 动态 RAF 调速**(buffer 一定字符 → 按字符总数 / 期望 duration 算出当帧 yield 数) ✓ — 平滑 + 跟得上速度
- c. 不做打字机,chunk 一到立刻全显 — 视觉劣化,且 chunk 50-100 chars 一跳会"跳行"

**取舍**:选 b。`useChatSSE` 内维护 char queue,`requestAnimationFrame` 每帧 yield 几个字符,目标:queue 长度小于 200 chars 时按 30 chars/s,大于时加速到 100 chars/s(避免落太远)。

### 6.6 stale 探测的实现

**问题**:Celery worker 崩了 task 卡 running,如何判定?

**Alternatives**:
- a. Celery 自带 `result_backend` — `AsyncResult.state` 是 SUCCESS/FAILURE/PENDING,但 worker 崩可能停在 STARTED 永不更新
- b. Celery Beat 定时扫 `chat_tasks` 表,`status='running'` AND `last_event_seq` 5 分钟未变 → 标 error ✓
- c. 每个 task 后台 heartbeat 每 30s 写 PG — 写压更大,且 worker 死了 heartbeat 也死

**取舍**:选 b。每分钟 Beat 跑一次 `scan_stale_chat_tasks`,标 error 顺带 XADD `{type:error, reason:stale}` 让在线 client SSE 立刻收到。

**stale 阈值**:5 分钟。理由:正常一轮推理 30s-3min,超 5min 无 chunk 更新 99% 是死锁/崩溃。

---

## § 7 错误处理矩阵

| 失败 | 触发条件 | 服务端行为 | 用户感知 |
|---|---|---|---|
| LLM API 报错 | provider 429/500/timeout | try 内 catch → XADD `{type:error, reason:llm_error}` → task status=error → error_message 落库 | SSE 收 error 事件 → 红色 banner + retry 按钮 |
| Cancel 用户主动 | POST /chat/cancel | PUBLISH → worker raise GraphInterrupt → partial commit | SSE 收 cancelled 事件 → 灰色 badge,内容保留 |
| Celery worker crash | OOM / SIGKILL / 主机重启 | task 卡 running → Beat 探测 stale → 标 error | 重开页面看到 error badge + retry 按钮 |
| Web 进程 crash | uvicorn reload / OOM | task 不受影响;前端 SSE 中断 → 自动重连 GET /stream | 短暂卡顿,自动恢复继续看 |
| Redis crash | Redis OOM / 重启 | Stream 内存数据全丢;worker 继续跑但 XADD 失败(retry 3 次后 task 标 error) | 重开页面只能看到崩溃前已 commit 的 ChatMessage;in-flight gap 永久丢 |
| Postgres crash | PG 重启 | Celery task 在 commit 时阻塞;Web `/chats` query 失败返 503 | 短暂 503;PG 恢复后所有功能复原 |
| Checkpoint 找不到 | retry 时 `chat_tasks.langgraph_checkpoint_id IS NULL` | 返回 422 "无法恢复" | 提示用户重发 prompt(从 user message 重新提交) |
| 多次快速 cancel | user 重复点 cancel | publish_cancel 幂等;worker 收到一次就 raise | 仅一次 cancel 事件 |
| 多次快速 retry | user 重复点 retry | chat_tasks 加唯一约束 `(session_id, status='running') unique`;第二次 retry 报 409 | "已在重试中" 提示 |

---

## § 8 测试策略

| 层 | 内容 | 工具 |
|---|---|---|
| L0 unit | `ChatEventBus.xadd/xread` / `ChatCancelBus.publish/subscribe` / `ChatTaskRepo` 状态迁移 / try/finally commit 三件套覆盖 | pytest + fakeredis + pg fixture |
| L1 集成(eager + fakeredis + 真 PG fixture) | 4 条主路径:正常完成 / cancel / LLM error / resume from checkpoint | Celery `task_always_eager=True` + `celery-redis-test-fixture-pattern` memory |
| L2 集成(真 Celery worker subprocess + 真 Redis + 真 PG) | 故障演练:杀 Celery worker / 杀 web / 杀 Redis 三类 chaos,验证 task/message 终态 + stale 探测 | `pg-test-container-pattern` memory + Celery worker subprocess fixture |
| L2.5 serve path 守护 | 真 uvicorn + 真 Celery worker + e2e curl SSE,验证 reconnect 一致性 | `feedback_serve_path_no_ci_coverage` memory 要求 |
| 前端 unit | `useChatSSE` last_event_id 协议 / chunk → 打字机 / cancel / retry button | vitest + MSW(注意:MSW mock 路径要和真后端一致,避免 `useChatSSE.test.tsx:90` 的伪绿) |
| 前端 e2e | "关页面 30s 重开"场景 | **deferred**(留 v1.x,先把后端测全) |

**Differential golden cases**(借鉴 `v0.8.4-architecture-landed` 的差分测试):
- Case 1:同 session 同 prompt,有/无 cancel 中断 → 终态消息不同(complete vs partial)
- Case 2:同 session 同 prompt,worker crash 后 retry vs 不 retry → retry 后续 message 与 crash 前 stream 拼接一致
- Case 3:同 session 两轮 prompt,第二轮 in-flight 时关页面再开 → 第一轮 done + 第二轮 active stream replay

---

## § 9 范围边界与 v1.x 留口

### 9.1 v1.0 ship(本 spec)

✅ in-flight subscribe(C 档)
✅ Celery worker 跑 graph(Y)
✅ Redis Streams + PG 双层存储(P + chunk 级)
✅ Cancel + Checkpoint Resume(S3)
✅ 6-state task lifecycle
✅ stale 探测 + 自愈
✅ 故障演练 L2 测试

### 9.2 v1.x 留口(不堵不做)

| Feature | 留口方式 |
|---|---|
| 多 tab fan-out 强一致 | Redis Streams 已支持 multi-consumer,加 consumer group 即可;前端需要的 vector clock / op transform 留 v1.x |
| 全局 task dashboard | `chat_tasks` 表已经够 query,需要时加个 admin route |
| Celery 跨用户 quota | 单用户限并发 task 数,在 POST /chat 处加约束 |
| Redis 持久化 | AOF 模式 toggle,基础设施层,无代码改动 |
| token 级 streaming | `chat_event_bus.xadd_event` 接受任意粒度,改 chunker 即可 |
| 前端 playwright e2e | 写测试,不动产品代码 |

### 9.3 显式不做(架构原则)

❌ checkpoint resume 静默重投 — user 必须主动 retry,不做后台自动重试(避免 LLM 报错 → 烧钱循环)
❌ 跨 session 状态迁移(把 task 从一个 session 拖到另一个)— 产品语义不清,无需求
❌ 前端持久化 SSE buffer(IndexedDB)— DB-as-truth 哲学下不需要前端缓存

---

## § 10 工程量与简历叙事

### 10.1 工期估算(wall time,按 `feedback_estimate_in_claude_code_walltime`)

| 阶段 | 内容 | wall time |
|---|---|---|
| Schema migration | `chat_tasks` 新表 + `chat_messages` 加列 + sqlalchemy model + repo | 0.5 天 |
| ChatEventBus + ChatCancelBus | Redis Streams + pub/sub 封装 + L0 test | 1 天 |
| ChatTaskRunner(Celery task) | 完整 try/finally + cancel listener + checkpoint commit | 2 天 |
| Router 改造 | POST /chat 改 enqueue + 新 3 endpoint + chats.py 改造 | 1 天 |
| stale scanner(Beat) | 简单逻辑 | 0.5 天 |
| 前端 useChatSSE 改造 | last_event_id 协议 + cancel/retry button + 打字机渲染 | 1.5 天 |
| L0/L1 测试 | 4 条主路径 + ChatEventBus / Repo 单测 | 1.5 天 |
| L2 故障演练 | Celery worker subprocess fixture + 杀 Celery/web/Redis 三套 | 2 天 |
| L2.5 serve path 守护 | 真 uvicorn e2e | 0.5 天 |
| Resume from checkpoint | LangGraph 配置 + 验证从中断 state 续跑 + edge cases | 2 天 |
| Differential golden(3 case) | 写 + 跑 + 调 | 1 天 |
| README + dogfood | 文档刷新 + 自己用 1 天看 bug | 1 天 |
| **合计** | | **~15 天 wall time ≈ 3-4 周** |

加速点:ChatEventBus / Repo / Router 这种 boilerplate 类 Claude Code 加速明显(~2-3x)
人-bound 点:Resume 验证 + 故障演练 + dogfood 是 review-heavy,Claude Code 不加速

### 10.2 简历叙事

> **Chat session 持久化与 in-flight subscribe(2026-Q2)**
>
> 把单进程 SSE 长连接改造为 **LangGraph + Celery worker + Redis Streams** 的解耦架构,让 agent 推理脱离 HTTP request 生命周期:
>
> - **DB-as-truth 双层存储**:Redis Streams 做实时事件层(TTL 24h,XREAD 协议直接对应 SSE replay),Postgres 做持久消息层
> - **6 状态 task lifecycle**(queued/running/done/cancelled/partial/error)+ Celery Beat stale 探测自愈
> - **Cancel + Resume**:Redis pub/sub 信号 + LangGraph `AsyncPostgresSaver` checkpoint,用户主动重试可从最后稳定 state 续跑
> - **故障演练 L2 测试**:杀 Celery worker / 杀 web / 杀 Redis 三类 chaos,验证 task 终态收敛 + partial commit 一致性
>
> 参考 Hermes (Nous Research) 的「agent loop / transport 解耦」设计,在 Web SSE 场景下加 in-flight subscribe 能力。

---

## § 11 开放问题 / 未决项

| # | 问题 | 倾向 | 决策推到 |
|---|---|---|---|
| 1 | LangGraph "cancel_guard" wrapper 的具体插入点(每个 supervisor / 每个 agent / 每条 edge?) | 每条 edge 之间 + supervisor 节点入口 | plan 实现阶段 spike |
| 2 | chunk 大小阈值(50 / 100 / 200 chars?自适应?) | 100 chars,后期看真实推理日志调 | dogfood 阶段调 |
| 3 | Redis Streams `XADD` 失败重试策略(3 次 vs 指数退避 vs 立刻 task error) | 3 次同步 retry → fail → task error,避免对 Redis 抖动过度敏感 | plan 实现阶段 |
| 4 | retry 是否允许多次链式(第 N 次 retry 从第 N-1 次的 checkpoint?) | 允许;每次 retry 都创建新 task,`parent_task_id` 链接前一次(已加字段) | ✓ 已定 |
| 5 | escalation 流程(POST /escalate)和新 task 架构的整合 | escalate 现在是单独 endpoint,改 plan 时再决定:复用 task 系统还是保持独立 | plan 拆分时定 |
| 6 | 多 worker 部署时 cancel signal 路由(PUBLISH 是广播,所有 worker 都收到 → 哪个真在跑就响应?) | Pub/Sub channel 名带 task_id,worker 启动时 SUBSCRIBE `chat:cancel:{tid}` only when own task → 自然路由 | plan 实现阶段 |

---

**End of spec.**

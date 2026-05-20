# Chat Session Title — LLM 异步生成 + 手动重命名 设计文档

**日期**: 2026-05-17
**作者**: Talantan + Claude (brainstorming session)
**状态**: spec drafted, 待 user review

---

## 1. 背景与动机

Chat session 持久化总卡(Plan 1+2+3)ship 后, sidebar 已经能列出所有历史 session, 但 **每个 session 的 title 仍然丑得没法看**:

- DB schema 已有 `chat_sessions.title` 字段(`backend/app/models/chat.py:58`), default `"新对话"`
- 当前唯一的"自动生成"路径在 `backend/app/router/session_router.py:277-281` — 第一条 user message 落库时直接取前 20 字 + `"..."` 作为 title
- 后端虽然有 `PUT /sessions/{id}` 重命名 endpoint(`session_router.py:140` + `repo.rename_session()`), 但前端 sidebar **完全没有暴露 rename UI** — 用户没办法手动改

对照 ChatGPT / Claude.ai 的标准做法:
- 首轮对话完成后, 用 cheap LLM 根据 user 提问 + assistant 回复生成 ~10-15 字标题
- sidebar hover 出现 `...` 菜单, 可手动 rename / delete
- 用户手动改过的 title 不再被 LLM 覆盖

当前实现的痛点:
1. **截断标题没信息量** — "帮我分析一下贵州茅..." vs "贵州茅台估值分析"
2. **session 列表难以扫描** — 用户回头找历史对话只能靠时间戳猜
3. **后端 endpoint 已就绪但前端 dead-end** — `rename_session` 写了没人用, 浪费

---

## 2. Scope(明确做 / 不做)

### 做(本 spec 范围)

- 后端: `chat_sessions` 表加 `title_source` 字段(三态枚举)
- 后端: 新增 `generate_session_title` Celery task, 首轮 assistant 完成后异步触发
- 后端: 删除 `session_router.py:277-281` 的 20 字截断逻辑, 移到 Celery task fallback 分支
- 后端: `PUT /sessions/{id}` 写 title 时同时设 `title_source = "user_renamed"`
- 前端: sidebar session 行 hover 出 `...` icon → dropdown(Rename only, Delete 留 TODO)
- 前端: Rename → title 文本变 inline input(Enter 提交 / Esc 取消 / blur 提交)
- 前端: chatSessions store 加 `renameSession(id, title)` action(乐观更新 + 失败回滚)
- 前端: SSE close 后追加一次 ~3s 后的 sidebar refetch, 拿到 LLM 写入的 title
- 测试: L0 task 单测 + L1 真 Celery eager + cassette + L2 e2e serve path + 前端 vitest

### 不做(明确排除)

- ❌ Sidebar Delete session(留 dropdown 位置 + TODO 注释, 物理删除/软删除策略下次 brainstorm)
- ❌ Title 多语言(prompt 中文模板, 用户首条消息是英文则 LLM 自然出英文 title, 不强制)
- ❌ Title 实时 SSE 推送 — 用 SSE close 后延时 refetch 这种 best-effort 方案
- ❌ 历史 session(已存在的)批量回填 LLM title — 只对 new session 生效, 老 session 沿用现在的 title 不动
- ❌ Title 长度严格校验 — DB 是 `String(255)`, LLM prompt 要求 ≤15 字, 截断兜底即可
- ❌ Right-click context menu / 双击 inline edit(Q5 已选 A: hover `...` 菜单)

---

## 3. 核心架构

```
┌─────────────────────────────────────────────────────────────────┐
│ User 首轮对话流程                                                 │
│                                                                  │
│  1. POST /api/v0/chats/  → 创建 session, title="新对话",          │
│                            title_source="pending"                │
│  2. User 提问 → SSE 流开始                                       │
│  3. Celery worker 跑 chat_runner → finalize_task_persistence      │
│     落 assistant message + mark_done                            │
│     ─ 之后 check: 若 title_source=="pending"                    │
│       → enqueue generate_session_title(countdown=1s)              │
│  4. SSE close → 前端 refetch sidebar(title 还是"新对话")           │
│  5. generate_session_title task(独立 Celery 进程):                │
│     ─ 读 session 首轮 user.content + assistant.content[:500]      │
│     ─ 调 LLMService(tier="fast", schema=None)                    │
│     ─ prompt: "为以下对话生成 10-15 字中文标题, 仅返回标题文本"     │
│     ─ 写回 session.title + title_source="llm_generated"          │
│     ─ 失败 retry 2 次(Celery autoretry, 指数退避)                 │
│     ─ 全部失败 → fallback: title=user.content[:20]+"...",         │
│                            title_source="llm_generated"          │
│  6. 前端 SSE close 后 ~3s 再 refetch sidebar → 新 title 显示       │
│                                                                  │
│ User 手动 rename(任意时刻):                                       │
│  ─ Hover session 行 → 点 `...` → Rename                          │
│  ─ Inline input → Enter/blur 提交 → PUT /sessions/{id}            │
│  ─ 后端写 title + title_source="user_renamed"                     │
│  ─ 此后 generate_session_title task 启动时 skip(若还没跑)          │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. 数据模型

### 4.1 Schema 改动

`backend/app/models/chat.py` 的 `ChatSession` 加一个字段:

```python
class ChatSession(Base):
    __tablename__ = "chat_sessions"
    # ... 现有字段 ...
    title_source = Column(
        String(16),
        nullable=False,
        default="pending",
        server_default="pending",
    )  # pending | llm_generated | user_renamed
```

三态语义:
- `pending` — session 刚创建, 还没有自动/手动 title; LLM task 看到此状态会跑
- `llm_generated` — LLM task 写入(成功或 fallback 截断都算); 后续不再触发 LLM
- `user_renamed` — 用户手动改名; 拥有最高优先级, LLM task 启动时 skip

> **状态机不可逆**: `pending` → `llm_generated` 或 `user_renamed`; `llm_generated` → `user_renamed`(用户改名覆盖 LLM); `user_renamed` 终态。

### 4.2 迁移策略

项目 v0.9.x #2.5 后用 PG, 但 **目前不引 alembic**(per claude-context `v0.9.x-no-alembic-until-db-unify.md`), 用 `create_all()` 幂等。

对老数据:
- PG 现有 row 没有 `title_source` 字段 → server_default="pending" 自动填
- 但老 row 已经有 截断式 title (非 "新对话"), 我们 **不希望** 跑 LLM 覆盖
- 解决: app 启动时一次性 migration script `backend/scripts/backfill_title_source.py`:
  - `UPDATE chat_sessions SET title_source='llm_generated' WHERE title_source='pending' AND title != '新对话'`
  - 即"已经有非默认 title 的"老 session 一律视为 llm_generated, 不再重跑
  - 仍是 `"新对话"` 的老 session 也保留 pending → 等用户下次跟它聊会触发 LLM(可接受)

---

## 5. Celery Task 设计

### 5.1 新文件 `backend/app/tasks/title_generation.py`

```python
@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 2, "countdown": 5},
    retry_backoff=True,
)
def generate_session_title(self, session_id: str) -> None:
    """异步生成 session title 的 Celery task.

    入口: chat_task worker 落完首轮 assistant message 后 enqueue.
    幂等: 启动时检查 title_source 不为 pending 则 skip.
    失败兜底: 全部 retry 失败 → fallback 到 user.content[:20] 截断.
    """
    with get_db_session() as db:
        session = db.query(ChatSession).filter_by(id=session_id).one_or_none()
        if session is None:
            return  # session 被删了
        if session.title_source != "pending":
            return  # 已经被 user rename 或 LLM 跑过

        msgs = (
            db.query(ChatMessage)
            .filter_by(session_id=session_id)
            .order_by(ChatMessage.created_at.asc())
            .limit(2)
            .all()
        )
        if len(msgs) < 2:
            return  # 还没出现首轮 assistant, 不该被触发
        user_msg, assistant_msg = msgs[0], msgs[1]

        try:
            title = _llm_generate_title(
                user_text=user_msg.content,
                assistant_text=assistant_msg.content[:500],
            )
        except Exception:
            if self.request.retries >= 2:
                # 全部 retry 失败, fallback
                title = user_msg.content[:20] + ("..." if len(user_msg.content) > 20 else "")
            else:
                raise  # 继续 retry

        session.title = title
        session.title_source = "llm_generated"
        db.commit()


def _llm_generate_title(user_text: str, assistant_text: str) -> str:
    """调 LLMService cheap tier 生成 10-15 字 title.

    返回纯文本 title(已 strip + 截断到 255 字以内防御性).
    """
    llm = get_llm_service()
    prompt = (
        "请为以下对话生成一个 10-15 个汉字的简洁标题, 直接返回标题文本, "
        "不要任何前后缀 / 引号 / 编号:\n\n"
        f"用户: {user_text}\n"
        f"助手: {assistant_text}"
    )
    resp = llm.chat(prompt=prompt, tier="fast", schema=None)
    raw = resp.content.strip().strip('"').strip("'").strip("「").strip("」")
    return raw[:255]
```

### 5.2 Trigger 接入

接入点: `backend/app/router/chat_finalize.py` 的 `finalize_task_persistence` success 分支(在 `task_repo.mark_done(...)` 之后):

```python
# === NEW: 首轮 assistant 完成后, 异步生成 session title ===
session = await session_repo.get_session(str(session_id))
if session and session.title_source == "pending":
    from app.tasks.title_generation import generate_session_title
    generate_session_title.apply_async(args=[str(session_id)], countdown=1)
```

> **为什么 trigger 条件只看 `title_source == "pending"`**: 项目里 `chat_sessions.message_count` 字段虽然 schema 存在(`models/chat.py:64`), 但 worker 路径(`append_message`)**实际不更新**, 只在 view 层 `func.count()` 实时算。用 `title_source == "pending"` 作为唯一触发条件简单可靠 — 第二轮对话时 source 已为 `llm_generated`, 自然不再触发。
>
> **为什么 `countdown=1`**: 保证 task 启动时 assistant message 在 PG 已经可见(防 read-after-write 边缘 case)。
>
> **task 内部 robustness 校验**: generate_session_title 启动后再做 `len(messages) < 2` skip(防御性, 极小概率被外部错误触发)。

### 5.3 LLM tier 选择

走 `tier="fast"`(项目 `Tier = Literal["fast", "balanced", "deep"]`, fast 对应 cheap 模型):
- title 生成是低复杂度任务, 不需要 balanced/deep
- 失败重试 2 次 + 兜底截断, 不会因 cheap 模型偶发抽风影响主流程
- per-call 成本估算: ~500 tokens 输入 + ~30 tokens 输出 ≈ ¥0.001 / session
- `schema=None` 表示自由文本输出(不走 constrained JSON), title 是单行短文本足够

---

## 6. 后端 API 改动

### 6.1 删除 `session_router.py:277-281` 同步截断

```python
# OLD(删):
if message_data.role == "user" and session.title == "新对话":
    session.title = message_data.content[:20] + (
        "..." if len(message_data.content) > 20 else ""
    )

# NEW: 不再在消息落库时同步生成 title, 留给 Celery task
```

### 6.2 `PUT /sessions/{id}` 加 title_source 写入

```python
session.title = session_data.title
session.title_source = "user_renamed"  # NEW
db.commit()
```

### 6.3 `chat_session_repo.rename_session()` 同步改

```python
async def rename_session(self, session_id: str, new_title: str) -> None:
    async with self._session_factory() as s:
        await s.execute(
            update(ChatSession)
            .where(ChatSession.id == sid)
            .values(title=new_title, title_source="user_renamed")  # NEW
        )
```

### 6.4 `title_source` 暴露策略

`title_source` 仅服务端使用, **不暴露到前端 view**(`ChatSessionView` / `SessionResponse` 都不加该字段)。理由:
- 前端 rename UI 对所有 session 都开, 不依赖 source 状态
- 减小 API surface, 降低 v1.x 重构成本
- dogfood 若发现需要(例如想给"LLM 生成 vs 用户改"加视觉区分), v1.x follow-up 再加

---

## 7. 前端 UI 设计

### 7.1 Sidebar `...` 菜单

`frontend/src/components/sidebar/chat-session-list.tsx` 改造:

```tsx
<div className="group flex items-center justify-between hover:bg-...">
  <span className="truncate">{s.title}</span>
  <Dropdown opener={<MoreIcon className="opacity-0 group-hover:opacity-100" />}>
    <DropdownItem onClick={() => startRename(s.id, s.title)}>
      重命名
    </DropdownItem>
    {/* TODO: Delete session — 留待下次 brainstorm 决定软/硬删除 */}
  </Dropdown>
</div>
```

设计点:
- `opacity-0 group-hover:opacity-100`: 非 hover 状态隐藏 icon, 视觉干净
- Dropdown 简单 1-2 项, 用项目里已有的 ui primitive(若无则 light 写一个)
- 移动端 fallback: tap-and-hold 触发(可选, v1 暂不做)

### 7.2 Inline Rename UX

state machine:
- `display` (default): 显示 title 文本
- `editing` (点 Rename 后): title 变 `<input>` autofocus + 选中全文
- 提交触发:
  - **Enter**: submit
  - **blur**: submit(保存当前值)
  - **Esc**: cancel(恢复原值)

```tsx
{editingId === s.id ? (
  <input
    autoFocus
    defaultValue={s.title}
    onKeyDown={(e) => {
      if (e.key === "Enter") commit(e.currentTarget.value);
      if (e.key === "Escape") cancel();
    }}
    onBlur={(e) => commit(e.currentTarget.value)}
  />
) : (
  <span>{s.title}</span>
)}
```

### 7.3 store action

`frontend/src/store/chat-sessions.ts`:

```ts
async renameSession(id: string, newTitle: string) {
  const prev = this.sessions.find(s => s.id === id)?.title
  // 乐观更新
  this.sessions = this.sessions.map(s =>
    s.id === id ? { ...s, title: newTitle } : s
  )
  try {
    await chatApi.renameChat(id, newTitle)
  } catch (e) {
    // 失败回滚
    this.sessions = this.sessions.map(s =>
      s.id === id ? { ...s, title: prev ?? s.title } : s
    )
    throw e
  }
}
```

`frontend/src/api/chatApi.ts` 加:

```ts
export async function renameChat(id: string, title: string): Promise<void> {
  await fetch(`/api/sessions/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  })
}
```

> ⚠️ 注意 endpoint: 后端 `session_router.py` 用 `/api/sessions/...` prefix, 而 `chats.py` 用 `/api/v0/chats/...`。Rename 走 `session_router` 的 PUT, 与现有 `/sessions` 路由一致。

### 7.4 SSE close 后追加 refetch

`frontend/src/hooks/useChatSSE.ts`(已存在)在 `onclose` 现有 refetch 后 + 一次延迟:

```ts
onclose: () => {
  refetchSidebar()
  // NEW: 等 LLM title task 大概率完成后再刷一次
  setTimeout(() => refetchSidebar(), 3000)
}
```

**为什么 3s**:
- LLM cheap tier 生成 ~10-15 字 title 实测 0.8-1.5s
- Celery enqueue + worker pickup ~100-500ms
- 3s 给一个保守上限; 仍未完成的边缘 case 用户切走再回来时刷, 可接受

---

## 8. 测试策略

### 8.1 L0 unit(backend)

`backend/tests/tasks/test_title_generation.py`:
- prompt 拼装正确(含 assistant truncation 到 500 字)
- `title_source != "pending"` 时 skip
- `len(messages) < 2` 时 skip
- LLM 返回带引号 / 「」 时 strip 干净
- 超 255 字截断兜底
- LLM 全失败 → fallback 到 `user_msg.content[:20] + "..."`

### 8.2 L1 integration(backend)

`backend/tests/tasks/test_title_generation_integration.py`:
- Celery `task_always_eager=True`(项目已有 fixture)
- 真 LLMService + VCR cassette 录一次 LLM call
- 验证 session.title + title_source 落库正确

### 8.3 L2 e2e(backend serve path)

`backend/tests/integration/test_chat_title_e2e.py`:
- 起 serve fixture(项目已有)
- POST 创建 session → POST 用户消息 → 等 SSE 完成
- 显式 `result.get()` 等 generate_session_title task 完成
- GET `/sessions/{id}` 读到非 "新对话" title + title_source="llm_generated"

### 8.4 user_renamed 跳过 LLM

- 创建 session → 立刻 PUT rename → 再发消息 → 验证 LLM task 启动时 skip(title 保持 user_renamed)

### 8.5 前端 vitest

`frontend/src/components/sidebar/__tests__/chat-session-list-rename.test.tsx`:
- hover 显示 `...` icon
- 点 Rename → input 出现 + autofocus
- Enter / blur 调 `chatApi.renameChat`
- Esc 不调 API + 恢复原 title
- 失败回滚乐观更新

### 8.6 cassette + dogfood

- 录一份 cassette: 用户问 "贵州茅台最近怎么样" → assistant 答估值分析 → title 应该类似 "贵州茅台估值分析"
- dogfood 标准: 至少 3 个真实首轮对话, 人眼看 title 都"有信息量" + 不超 15 字

---

## 9. Migration / Rollout

1. PR 内顺序:
   1. PG schema 改 `models/chat.py` 加 `title_source`(create_all 幂等覆盖)
   2. 写 `scripts/backfill_title_source.py` + app_main lifespan 启动时跑一次(idempotent UPDATE)
   3. 新建 `tasks/title_generation.py` + 在 `router/chat_finalize.py` success 分支接入 enqueue
   4. 改 `session_router.py` PUT + 删 277-281 截断
   5. 改 `chat_session_repo.rename_session()` 同步设 title_source
   6. 前端: chatApi.renameChat + store.renameSession + sidebar `...` 菜单 + inline input
   7. 前端: useChatSSE 加 3s 延时 refetch
   8. 写测试
2. 灰度:
   - 个人 portfolio 项目无需灰度, 直接 ship
   - 但 PR 自验证清单含: 老 session(已有截断 title)backfill 后 title_source=llm_generated, 不被重跑

---

## 10. 工期估算

按 claude-context `feedback_estimate_in_claude_code_walltime.md` 用 wall time 估:

| 阶段 | 时间 | 说明 |
|------|------|------|
| schema + backfill script | 0.5h | 单表加字段 + 一次性 SQL |
| Celery task + trigger 接入 | 1h | 新文件 + chat_task 一行 enqueue |
| 后端 API 改 / 删 277-281 | 0.5h | 直接编辑 |
| 前端 sidebar `...` + inline rename | 1.5h | UI + store + api + 乐观更新 |
| 前端 SSE 延时 refetch | 0.2h | useChatSSE 一行 setTimeout |
| 测试 L0/L1/L2 + 前端 vitest | 1.5h | 含 cassette 录一次 |
| dogfood + spec close | 0.3h | 跑 3 个真实首轮看 title |
| **合计** | **~5.5h wall time** | Claude Code 加速段 |

---

## 11. 风险与已知坑

1. **LLM 输出格式不稳定**: cheap 模型可能返回 "标题: xxx" 这种带前缀。**对策**: `_llm_generate_title` 里 strip 引号 / 「」 / 常见前缀; 实在崩了 fallback 兜底。
2. **Celery task 跑早于 message commit**: 极小概率 chat_task worker commit assistant message **后**立刻 enqueue, 但 generate_title task 在 read replica / 慢 commit 场景下读不到。**对策**: enqueue 用 `delay(countdown=1)` 给 1s 延迟; 或 task 内 retry on `len(messages) < 2`。 v1 选 countdown=1 简单方案。
3. **Old session 的 title_source backfill 时机**: app_main lifespan 跑一次 UPDATE 是开发期 OK 的, prod 应该走 alembic migration。本项目 v0.9.x 还没 alembic, 接受这个权宜。
4. **前端 endpoint 路径混淆**: `/api/v0/chats/*` vs `/api/sessions/*` 是两套 router 并存, rename 必须走后者。PR 验证清单要含 manual curl 一次。
5. **3s setTimeout 太脆弱**: 若 LLM cheap tier 偶尔 ~5s, 用户切走再回来才看到 title。可接受但记录为 v1.x follow-up(SSE 推送 title-updated event)。

---

## 12. v1.x Follow-up(明确不在本 spec 范围)

- Sidebar Delete session(软删 / 硬删 / 归档?)
- SSE 推送 `title-updated` event, 替代 3s setTimeout
- 多轮对话内重新生成 title(对话主题变化时)
- 用户手动触发 "重新生成 title" 按钮
- 历史 session 全量回填 LLM title(目前只对 new session 生效)

---

## 13. 决策摘要(brainstorming Q1-Q5)

| Q | 决策 | 理由 |
|---|------|------|
| Q1 触发时机 | 首条 assistant 完成后异步 | 不阻塞 user 看回复; 信息够 |
| Q2 异步实现 | Celery 独立 task | 与项目 chat_task 异步基础设施一致 |
| Q3 LLM 输入 | user 首条 + assistant 首条(500 字截断) | ChatGPT 标准做法, 主题准 |
| Q4 失败 / 覆盖 | 2 次 retry + 20 字截断 fallback; `title_source` 三态 | 用户体验兜底 + 手动改名不被覆盖 |
| Q5 前端 UI | hover `...` 菜单 → Rename(Delete 留 TODO) | 主流产品风格 + 后续扩展位 |

---

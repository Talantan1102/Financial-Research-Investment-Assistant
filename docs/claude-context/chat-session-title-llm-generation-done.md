---
name: chat-session-title-llm-generation-done
description: chat session title 从 20 字截断升级到 LLM 异步生成 + 手动 rename + title_source 三态防覆盖 ship
type: project
---

Chat Session Title LLM 异步生成 ship — 2026-05-17。

**结论:** Session title 从前 20 字截断升级为 "首轮 assistant 完成后 enqueue
Celery generate_session_title task,LLM fast tier 生成 10-15 字中文标题" 的异步
副产品模式;`ChatSession.title_source` 三态枚举(pending / llm_generated /
user_renamed)管覆盖优先级,user_renamed 终态永不被 LLM 覆盖;前端 sidebar
双阶段 refetch(SSE done 即时 + 3s 延时)等异步 title 落库,hover `...` →
inline rename input。

**Why:**
- 旧的 `session_router.py:277-281` 同步 20 字截断没语义价值,sidebar 全是
  "为什么AAPL最近跌得这..." 这种无信息标题
- 同步 LLM 调用会阻塞首轮回复 ~1-2s; 项目已有 Celery + Redis 基础设施
  (v1.0 monitoring + chat persistence 都跑过),用异步 task 零成本接入
- LLM 写一次后用户可能想改名;反之用户改完后 LLM task 跑回来覆盖更糟糕。
  三态 title_source 比布尔 is_user_renamed 更明确(显式跟踪 "谁写的"),
  也给 v1.x "重新生成 title 按钮" 留扩展位

**How to apply:**
- 异步副产品模式可复用:`chat_finalize` success branch 是天然 enqueue 点
  (assistant message 已 commit,首轮信息完整);countdown=1s 给 DB commit
  缓冲;task 内 `if title_source != "pending": return` 幂等防覆盖
- 类似可加 task:自动 summary / 自动 tag / emoji autopick / 推荐 follow-up
  question — 都是 "首轮完成后,基于完整对话上下文,异步算一个副产品字段"
- 三态枚举写覆盖优先级是通用模式: pending → 系统生成 → 用户手动,user 写永远
  最高优先级,系统 task 启动先 check state 再决定 skip / overwrite
- 前端 SSE close 后用 `setTimeout(3000)` 延时 refetch 简单但脆弱(LLM
  >3s 时用户看不到 title) — v1.x 升级 SSE 推送 `title-updated` event

**Anchor:**
- spec: `docs/superpowers/specs/2026-05-17-chat-session-title-llm-generation-design.md`
- plan: `docs/superpowers/plans/2026-05-17-chat-session-title-llm-generation-plan.md`

**ship 范围 (15 task / ~5.5h wall time):**

| 范围 | 关键改动 |
|---|---|
| Schema | `ChatSession.title_source` String(16) + server_default="pending" |
| Backfill | `scripts/backfill_title_source.py`(老非默认 title → llm_generated)+ app_main lifespan 接入 |
| Celery task | `tasks/title_generation.py` — LLM fast tier + 2 retry + 20 字截断 fallback + 幂等 state check |
| Trigger | `chat_finalize` success branch enqueue countdown=1 |
| 后端 API | 删 277-281 同步截断 + `PUT /sessions/{id}` 写 title_source=user_renamed |
| 前端 | `chatApi.renameChat` + store `renameSession`(乐观+回滚)+ Sidebar hover `...` 菜单 + inline rename + `useChatSSE` close 后 3s 延时 refetch |
| 测试 | L0 unit 6 branch + L1 integration scaffold(cassette deferred)+ L2 e2e scaffold(docker_available 守护)+ frontend vitest 29 chat-title 测试 |

**关键决策:**
- title_source 三态而非 is_user_renamed 布尔 → 显式 "谁写的" + 留扩展位
- Celery task 而非 inline await → 不阻塞首轮回复 + 复用已有基础设施
- LLM input 是 user 首条 + assistant 首条 [:500] → ChatGPT 标准做法,主题准
- 失败兜底走 user.content[:20] + "..." → 比一直留 "新对话" 更有信息
- 前端 3s setTimeout 而非 SSE event → v1 简单,v1.x 升级为推送

**留 hook (v1.x P2/P3):**
1. SSE 推送 `title-updated` event 替代 3s setTimeout(脆弱性已记录)
2. 多轮对话主题变化时重新生成 title
3. 用户手动 "重新生成 title" 按钮
4. 历史 session 全量回填 LLM title(目前只对 new session 生效)
5. Sidebar Delete session(软删 / 硬删 / 归档?)

**Task 15 dogfood prep 沉淀:**
- e2e fixture chain 需要 docker 时,`pytestmark.skipif(not _docker_available())`
  必须显式加,否则 collection-time error(`celery_worker_subprocess` 在
  fixture 实例化时抛 DockerException);跟 `feedback_third_party_plugin_defaults.md`
  同源 — plan 阶段建模 e2e 环境必须含 docker / Redis / serve URL 三件套
- mypy `ignore_missing_imports = true` 全局只压 `import-not-found`,**不**压
  `import-untyped`;dogfood-only 文件如果用 `requests`(transitive dep 已装但
  无 stub),加 `[[tool.mypy.overrides]] module="requests"` 局部 skip
  优于引入 types-requests dev dep
- `ReturnType<typeof window.setTimeout>` 在 @types/node 叠加 overload 下会解析
  成 NodeJS Timeout(不是预期的 DOM number),production / mock 必须统一不带
  `window.` 前缀,让 NodeJS overload 一致命中

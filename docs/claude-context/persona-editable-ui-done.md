---
name: persona-editable-ui-done
description: Tier 1 persona block ChatGPT 风列表式可编辑 UI ship — 双轨 / atomic / 升级动画 / agent 双层保护
type: project
---

Persona Editable UI ship — 2026-05-17。

**结论:** /memory 页加 "画像" 默认 tab, 以 ChatGPT 风列表式 UI 暴露 Tier 1
persona block, 物理分 "你声明的" / "agent 观察到的" 双 section, agent 不可改
user 区 (服务层 + prompt 双层 enforce); 用户改 agent 区条自动升级 user 区 +
高亮动画提示。

**Why:**
- c5 cross-session memory ship 后 Tier 1 working blocks 缺用户交互入口
- dogfood 无法验 self-managed memory 写入质量

**How to apply:**
- persona 写入路径: 用户 UI → /api/v0/persona/* → PersonaService → ChatMemoryPersonaItem
- agent 写入路径: chat → core_memory_append/replace → PersonaService.apply_agent_*
  → 同 PG 表
- prompt cache 兼容: PersonaService._sync_to_working_block 把 items 渲染回
  working_blocks.persona.content; ChatPlanner Phase 1 render_persona_markdown
  路径不变

**Anchor:**
- spec: `docs/superpowers/specs/2026-05-17-persona-editable-ui-design.md`
- plan: `docs/superpowers/plans/2026-05-17-persona-editable-ui-plan.md`

**ship 范围 (21 task):**

| Phase | 范围 |
|---|---|
| 1 | schema + persona_items_md + PersonaService(CRUD + agent_*) + render/sync + migration |
| 2 | persona_router 4 endpoint + L1 e2e + chat_planner 端到端 |
| 3 | personaApi client + MemoryPersona 组件 (read/edit/add/delete/upgrade-anim) + chat 顶角入口 + /memory tab 默认 + Playwright e2e |
| 4 | HierarchicalMemory.core_memory_* persona 分支 + prompt 双轨保护段 + L1 保护 e2e |
| 5 | dogfood + 沉淀 |

**关键决策:**
- 持久化形态: markdown blob → row-per-item with stable UUID (新表 chat_memory_persona_items)
- agent 写入双轨保护: prompt + service 层双层 enforce
- user 改 agent 区条 → 自动升级 user 区 + 200ms 高亮动画
- 删除 = 物理删 (audit 留 P2 hook)
- agent 写入实时刷新 v1 不做 (SSE 留 P2 hook)

**留 hook (v1.x P2/P3):**
1. agent 写入实时 SSE 刷新
2. 编辑 audit log + 软删
3. items 拖拽排序 UI
4. 多语言 (section heading 走 i18n)
5. scratchpad UI (Phase 4)

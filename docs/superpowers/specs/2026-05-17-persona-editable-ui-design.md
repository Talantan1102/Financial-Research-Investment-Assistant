# Persona Editable UI — 设计文档

**日期**: 2026-05-17
**作者**: Talantan + Claude (brainstorming session)
**状态**: spec drafted, 待 user review

---

## 1. 背景与动机

C.5 cross-session memory ship 之后（Plan 7A/7B），项目已经有 `/memory` 页面展示
**Tier 2 archival graph**（Cytoscape 图 / Timeline / Audit 三 tab）。但 **Tier 1
working blocks**（persona / scratchpad markdown）虽然 Phase 1 已经接到
chat_planner prompt，**用户没有任何 UI 入口看到 / 修改自己的画像**。

用户原话："我们的记忆模块，在前端应该要有一个板块给用户看到 md，需要用用户友
好的方式展示，并且用户可以自己修改并且同步。"

类比 ChatGPT 的 Memory：用户期待能在 settings 类页面看到 agent "记住了我什么"，
并随时修改 / 删除。当前缺失这一层会导致：
1. 用户不知道自己被记住了什么 → 信任问题
2. agent 记错 / 过期信息无法纠正 → 体验问题
3. dogfood 阶段无法 verify self-managed memory 写入质量 → 评测盲区

---

## 2. Scope（明确做 / 不做）

### 做（v1 范围）

- `/memory` 页加 `画像` sub-tab，作为**默认 tab**
- 画像 tab 以 ChatGPT 风**列表式 UI** 展示 Tier 1 persona block
- 物理分两 section：**「你声明的」**（user 区，agent 只读）+
  **「agent 观察到的」**（agent 区，用户可改可删；改了自动升级为 user 区）
- 用户操作：增、删、改单条 item；编辑用 inline textarea
- chat 顶角加快捷入口 `📋 我的画像`，跳 `/memory#persona`
- persona 持久化层 schema 升级：从单段 markdown blob → `persona_items` 表
  （每行 stable UUID + source enum + text + position）
- agent 的 `core_memory_append/replace` 加转译层 + 用户区写入保护

### 不做（明确排除）

- ❌ scratchpad block 暴露 UI（Phase 4 才物理独立成 PG 表，先不动）
- ❌ Tier 2 archival graph 改造（保持现状不动；图谱 / 时间线 / 历史降为非默认
  tab，不重写）
- ❌ Tier 3 semantic recall UI（全自动，不暴露）
- ❌ 用户编辑历史 audit log（v1 物理删除；P2 留 hook 等 dogfood 撞实需求再加）
- ❌ agent 写入实时 SSE 刷新（v1 用户切到 tab 时拉一次；P2 hook）
- ❌ 多语言（section heading 中文写死）
- ❌ items 拖拽排序（position 字段已留但 v1 不开 UI）

---

## 3. 核心架构

```
┌─────────────────────────────────────────────────────────────┐
│ Frontend                                                    │
│  /memory page                                               │
│  ├── tabs: [画像*]  [图谱]  [时间线]  [历史]                │
│  └── MemoryPersona.tsx                                      │
│      ├── UserDeclaredSection (list + 加按钮)                │
│      └── AgentInferredSection (list, 改/删 → API)           │
│  chat landing 顶角 → 快捷入口                                │
└─────────────────────────────────────────────────────────────┘
         │  REST (lib/persona-api.ts, msw L0)
         ▼
┌─────────────────────────────────────────────────────────────┐
│ Backend                                                     │
│  /api/persona  router                                       │
│   GET    /api/persona              → {user_declared, agent_inferred}│
│   POST   /api/persona/items        → 新增 item              │
│   PATCH  /api/persona/items/{id}   → 改 text (agent 区改→升级)│
│   DELETE /api/persona/items/{id}   → 删除                   │
│                                                             │
│  PersonaService                                             │
│   - list_items(user_id) → group by source                   │
│   - add_item / update_item / delete_item                    │
│   - render_to_markdown(user_id) → 给 ChatPlanner 用         │
│   - apply_agent_append(user_id, text) ← 给 MCP 转译          │
│   - apply_agent_replace(user_id, old, new) ← 给 MCP 转译     │
│                                                             │
│  ChatMemoryPersonaItem (新表)                               │
│   id uuid PK / user_id / source enum / text / position /    │
│   created_at / updated_at                                   │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│ Migration: ChatMemoryWorkingBlock 'persona' 单段 md         │
│  → 一次性 parse + 写入 persona_items                         │
│  → working_blocks.persona 保留作 prompt cache key            │
│    （每次 render 同步刷新 content = render_to_markdown）     │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. 数据模型

### 4.1 新表：`chat_memory_persona_items`

| 字段          | 类型              | 约束                          | 说明                              |
| ------------- | ----------------- | ----------------------------- | --------------------------------- |
| id            | UUID              | PK, default uuid4             | 稳定 item id                      |
| user_id       | UUID              | NOT NULL, FK users.id, index  | 跨用户隔离                        |
| source        | ENUM('user', 'agent') | NOT NULL                  | 物理双 section                    |
| text          | TEXT              | NOT NULL, len ≤ 500           | bullet 内容                       |
| position      | INTEGER           | NOT NULL, default 0           | section 内排序（v1 不开 UI）      |
| created_at    | TIMESTAMP         | NOT NULL, default now()       | 用于展示 "你于 YYYY-MM-DD 加"     |
| updated_at    | TIMESTAMP         | NOT NULL, default now()       | source upgrade 时也刷新           |
| __indexes__   |                   | (user_id, source, position)   | list_items 查询主路径             |

### 4.2 关系到现有 `ChatMemoryWorkingBlock`

`working_blocks` 表保留，`block_name='persona'` 的行 `content` 字段从"agent 直
写的 markdown" 改为 "**由 persona_items 渲染出的 markdown**"。

ChatPlanner 仍读 `working_blocks.persona.content` 走原 `render_persona_markdown`
路径 → **prefix cache 完全兼容**（spec § 4 Phase 1）。

PersonaService 在任何写操作后调 `_sync_to_working_block(user_id)`，把 items
列表渲染成 markdown 并 upsert 到 `working_blocks.persona.content`。

### 4.3 渲染契约（items → markdown）

```markdown
## 你声明的
- {user_item_1.text}
- {user_item_2.text}

## agent 观察到的
- {agent_item_1.text}
- {agent_item_2.text}
```

- section heading 中文写死（v1 不做 i18n）
- 空 section 仍渲染 heading（让 agent 看到结构）+ 一行 `_（暂无）_`
- items 按 position ASC 排序

---

## 5. 关键决策评估

### 决策 1：persona 持久化形态（决定 atomic 操作的可靠性）

**问题**: 列表式 UI 要求增/删/改**单条** item 可靠，需要 stable id。后端 persona
当前是单段 markdown blob，没有天然 id。

**业界 alternatives**:

| 方案 | 形态 | id 生成 | 易碎点 |
|------|------|---------|--------|
| A · markdown blob 不变 | 单段 text | (section, line index) | 加 / 删一条 → 后面所有 id 漂移 → 编辑失败 |
| B · markdown blob 不变 | 单段 text | content hash(text) | 编辑同 item 一字 → id 变 → API 找不到 |
| C · 新表 persona_items | row per item | UUID | 无漂移；多一次 join（可忽略） |

类似工业实例：
- **Notion** 每个 block 都是独立 row（UUID），不是把整页存成 md blob
- **Letta (MemGPT)** archival memory 也是 row per memory（含 timestamp 和 metadata）
- **ChatGPT Memory** 看请求格式应该也是 list of items（每条独立 delete）

**Tradeoff**:
- A/B 看似 minimal change（只改 UI），但 id 不稳定导致编辑失败属于致命 bug
- C 需要 1 张新表 + migration，但 atomic 操作 / source 标识 / position / audit
  扩展性都更好

**量化评估方案**:
- 不需要 benchmark — 决策依据是 id 稳定性的功能正确性，不是性能
- migration 一次性 parse 既有 persona blob，按 H2 section + bullet 拆分，全部
  写入 persona_items 表；新用户无 migration 成本

**选 C**。理由：UI atomic 操作可靠性 > minimal change。

---

### 决策 2：agent 写入双轨保护机制

**问题**: 用户选了 "双轨" 冲突策略（用户声明区 agent 只读），需要在
`core_memory_append/replace` 层 enforce — 不能让 agent 改用户区。

**业界 alternatives**:

| 方案 | enforce 层 | 漏写风险 |
|------|------------|----------|
| A · 只靠 prompt 约束 | LLM 自律 | 高 — prompt 没看到也会写错 |
| B · 服务层硬 enforce | PersonaService.apply_agent_replace 只在 source='agent' 的 items 里 match | 低 — 即使 prompt 漏说也兜底 |
| C · DB row-level 权限 | sqlalchemy event listener 拦截 source='user' 的 UPDATE | 最强，但 sqlalchemy event 跨 session 难调试 |

类似工业实例：
- **OpenAI Memory API** 应该有 source 区分（手动 vs 自动），具体 enforce 层不可见
- **Letta core_memory_replace** 自身有 old_content match 失败的 fallback（变 append），
  我们可以复用这个模式

**Tradeoff**:
- A 仅 prompt → 不可靠
- B 服务层 → 防 agent 写入意外 / agent prompt 漏看；fallback 行为可控
  （match 失败 → 降级为 append 到 agent 区）
- C DB 层 → 最强但调试 / 测试复杂；ROI 低

**量化评估方案**:
- L1 integration test：跑 100 轮 chat session，统计 agent 试图改用户区的次数
  → 期望 0；如有，service 层应拦截 + log warn，不进 DB
- prompt 在 `memory_tool_usage.md` 加约束 + L0 test 断言文案存在

**选 B + prompt 约束（A + B 组合）**。理由：双层防护，cost 低。

---

### 决策 3：user 改 agent 区条 → 升级为 user 区（vs 保留 agent 区）

**问题**: 用户在 agent 区改了某条 text，这条该不该自动迁到 user 区？

**Alternatives**:

| 方案 | 行为 | 用户心智 |
|------|------|----------|
| A · 改了就升级到 user 区 | source 改成 'user'，移动到 user section | "我改过的就是我说的算" — 符合直觉 |
| B · 留在 agent 区，标 "user-edited" | 加额外字段 user_edited=True | 增加 schema 复杂度，UI 多一种状态 |
| C · 弹 dialog 让用户选 | "迁到你声明区 / 留在 agent 区" | 多余 click，烦人 |

**选 A**。理由：用户既然选了"双轨"语义（user 区是"我说的"），改过的条目自然属于 user 区；
B/C 都增加复杂度但无明显收益。

实现：`PATCH /api/persona/items/{id}` 在原 source='agent' 时自动改 source='user'，
position 改成 user 区 max(position)+1。前端 UI 改完后会发现条目"消失"在 agent
区，"出现"在 user 区 —— 加一个 200ms 的高亮动画提示 "已迁到你的声明区"。

---

### 决策 4：删除是物理删还是软删（audit trail）

**Alternatives**:

| 方案 | 优点 | 缺点 |
|------|------|------|
| A · 物理 DELETE | schema 简单 | 误删无法恢复 |
| B · 软删（deleted_at 时间戳） | 可恢复 / audit | 多一个 WHERE，schema 多一列 |

**选 A（物理删）**。理由：v1 demo 阶段，撞实"误删想恢复"的真实需求再加 B。
P2 hook 已在 "不做" 范围列出。如果 dogfood 撞实需求，schema migration
加 deleted_at 列 + 改 GET 加 WHERE 即可，迁移成本低。

---

### 决策 5：agent 写入实时刷新策略

**问题**: 用户在 /memory 页停着，agent 在 chat 那边写了一条新 memory，UI 该
不该自动出现新条目？

**Alternatives**:

| 方案 | 实现 | 用户体验 |
|------|------|----------|
| A · 不刷新（v1） | 用户切 tab / 刷新页 才看到 | 简单；用户可能困惑 "刚才聊的怎么没更新" |
| B · 定时轮询 5s | setInterval + GET | 简单但浪费请求 |
| C · SSE push | 后端 emit `persona-updates` event | 体验最好，需新建 SSE channel |

**选 A（v1 不刷新，P2 hook 留 C）**。理由：
- 作品集 demo 阶段，用户主动来 /memory 看一次居多，不会长停页面
- C 实现成本不低（SSE channel + 跨 process 通信 + 前端 EventSource），ROI 在
  scale 阶段才显著
- 如果 dogfood 撞实"我刚才让 agent 记的为什么这没出现"，再上 C

---

### 决策 6：list item 排序

**问题**: section 内 items 按什么顺序展示？

**Alternatives**:

| 方案 | 顺序 | 适用 |
|------|------|------|
| A · created_at ASC | 老的在上 | 阅读自然，但用户加完新条找不到 |
| B · created_at DESC | 新的在上 | 用户加完立刻看到，但老的（更稳定的画像）沉底 |
| C · position 字段（v1 = 加入顺序） | 跟 A 等价但留扩展 | v1 等价于 A，但留 UI 拖拽空间 |

**选 C**。`position` 字段写入时 = 当前 section max(position)+1，等价于 created_at ASC
顺序但留有"拖拽排序"的 P3 hook（不开 UI）。

---

## 6. 前端 UI 设计

### 6.1 tab 结构（`/memory/index.tsx` 改造）

```
┌─ /memory ─────────────────────────────────────────────────┐
│ [画像*]  [图谱]  [时间线]  [历史]                          │
├──────────────────────────────────────────────────────────┤
│  ❯ 你声明的                                                │
│  ┌─────────────────────────────────────────────┐  ✏️ 🗑️   │
│  │ 金融研究员，做个人投资 + 客户报告              │           │
│  └─────────────────────────────────────────────┘           │
│  ┌─────────────────────────────────────────────┐  ✏️ 🗑️   │
│  │ 风险偏好：保守稳健                            │           │
│  └─────────────────────────────────────────────┘           │
│  ┌─ + 手动添加一条 ──────────────────────────────┐         │
│  └─────────────────────────────────────────────┘           │
│                                                             │
│  🤖 agent 观察到的                                          │
│  ┌─────────────────────────────────────────────┐  ✏️ 🗑️   │
│  │ 长期关注新能源 + 高股息消费板块               │           │
│  └─────────────────────────────────────────────┘           │
│  ┌─────────────────────────────────────────────┐  ✏️ 🗑️   │
│  │ 持有茅台 2000 股（2026-03 起）                │           │
│  └─────────────────────────────────────────────┘           │
└──────────────────────────────────────────────────────────┘
```

- 默认 tab 'persona'，URL hash `#persona`（chat 顶角链接锚到这）
- section heading 用 emoji + 文字加权重视觉区分
- inline edit：点 ✏️ → 切 textarea + ✓ 保存 / ✗ 取消
- 删除：点 🗑️ → antd Popconfirm "确认删除?"
- 加：点 "+ 手动添加一条" → 弹 modal 输入 textarea + 保存按钮
  - 加的条目默认进 user 区（无论从哪个 section 的加按钮点）

### 6.2 状态机（前端 state）

```
list_loaded → idle
            → editing(id)  → patching → idle (or error toast)
            → deleting(id) → confirmed → deleting → idle
            → adding       → modal_open → posting → idle
```

state 用 valtio store（沿用现有 frontend pattern），不引 redux / zustand。

### 6.3 chat 顶角快捷入口

`pages/chat` 顶部右侧加 `<Button icon={📋}>我的画像</Button>` → 跳 `/memory#persona`。

### 6.4 空状态

- 两 section 都空：center 一个温柔提示 "还没有任何记忆 — 跟 agent 多聊几句，
  它会自己开始记；你也可以点 + 自己加" + 一个 "+ 添加我的第一条" 大按钮
- 单 section 空：section 标题下显 "_（暂无）_" 灰字，不显加按钮
  （加按钮只在 user 区始终显）

### 6.5 source 升级动画

`PATCH` 响应 `{source: 'user', position: N}`（原是 'agent'）→ 前端：
1. 在 agent 区原位置淡出（200ms opacity → 0）
2. 在 user 区 list 底部淡入 + 短暂背景高亮（amber，200ms）
3. toast 提示 "已迁到你的声明区"

---

## 7. 后端 API 详细 schema

### 7.1 GET /api/persona

```json
{
  "user_declared": [
    {
      "id": "uuid",
      "text": "string",
      "source": "user",
      "created_at": "iso8601",
      "updated_at": "iso8601",
      "position": 0
    }
  ],
  "agent_inferred": [...]
}
```

### 7.2 POST /api/persona/items

Request:
```json
{ "text": "string ≤ 500", "target_section": "user" | "agent" }
```

Response: created Item（含 id + position）

约束：
- `text` 非空，去首尾空白，长度 ≤ 500
- `target_section` 默认 'user'（UI 加按钮始终传 'user'）
- agent 调用的内部 API 走 `PersonaService.apply_agent_append`，不经此 endpoint

### 7.3 PATCH /api/persona/items/{id}

Request: `{ "text": "string ≤ 500" }`

Response: updated Item（含 source —— 若 agent→user 升级，前端据此触发动画）

行为：
- 找到 item → 改 text + updated_at
- 若原 source='agent'：改 source='user'，position 改为 user 区 max(position)+1
- 跨 user 隔离：404 if item.user_id != current_user_id

### 7.4 DELETE /api/persona/items/{id}

Response: `204 No Content`
跨 user 隔离同上。

---

## 8. agent self-managed 写入转译层

### 8.1 `PersonaService.apply_agent_append(user_id, content)`

旧 `core_memory_append(user_id, 'persona', content)` 路径改：
1. 按 `\n` 切 content 成 lines，过滤空行
2. 每行去掉 leading `- ` / `* ` prefix（agent 可能输出 bullet 也可能不）
3. 每个 line 作为一个新 item 插入 persona_items，source='agent'，
   position = max(agent 区 position) + 1, +2, ...
4. 调 `_sync_to_working_block(user_id)` 刷新 markdown

### 8.2 `PersonaService.apply_agent_replace(user_id, old_content, new_content)`

旧 `core_memory_replace` 路径改：
1. 在 source='agent' 的 items 里找 text == old_content 的 item
2. 找到 → 改 text=new_content + updated_at
3. 未找到 → fallback 为 apply_agent_append(new_content)，log warn
   （跟 Letta MemGPT 的现有 fallback 模式一致）
4. **never** match source='user' 的 items（即使 text 一致）
5. `_sync_to_working_block(user_id)` 刷新 markdown

### 8.3 `memory_tool_usage.md` 加约束段

加一段 "❌ Don't" 反例：
```
- ❌ 不要试图修改 [你声明的] 区的任何 bullet — 这些是用户手动加的，
   agent 不可改写。若有冲突，向用户提议而不是直接 replace。
```

L0 test 断言文案存在 + L1 test 跑场景：user 加 "保守"，agent 试图 replace
"保守" → "激进"，verify service 层拦截 + 落到 agent 区 append。

---

## 9. Migration 策略

`alembic` 当前不在项目（spec § v0.9.x-no-alembic 决策）— 走 `create_all()` 幂等。

新增 model + 一次性 backfill 脚本：

```python
# backend/scripts/migrate_persona_blob_to_items.py
async def migrate_all():
    for user_id, persona_block in iter_existing_persona_blocks():
        items = parse_markdown_to_items(persona_block.content)
        # 老 blob 没有 source 区分 → 全部标 source='agent'
        # （因为之前都是 agent 写的，没有 user 编辑入口）
        upsert_persona_items(user_id, items, default_source='agent')
```

边界：
- 老 blob 无 H2 section → 全部为 agent 区 items
- 老 blob 已有 `## 你声明的` H2（不存在这种情况，安全断言）→ skip warn
- 空 blob → 不写 items（用户空状态）

**调用时机**: `backend/app/main.py` lifespan startup 时检测一次（
`get_setting('persona_migration_v1_done') is False` → 跑 → 标 True），
跑过一次后跳过。

---

## 10. 错误处理

### 后端

| 场景 | 行为 |
|------|------|
| GET 时 PersonaService 报错 | 500，前端显示"加载失败，请重试" |
| POST text 超 500 / 空 | 400 + error msg |
| PATCH/DELETE id 不存在 / 跨 user | 404 |
| apply_agent_replace 找不到 + fallback append | log warn，正常 200 |
| migration 解析失败 | log error，保留老 blob 不删；下次 startup 再试 |

### 前端

| 场景 | 行为 |
|------|------|
| GET 失败 | 显示"加载失败" + "重试"按钮 |
| POST/PATCH/DELETE 失败 | toast error + 不更新本地 state（GET 兜底） |
| inline edit 时网络断 | 保留 textarea 不丢用户输入，错误 toast，点 ✓ 重试 |

---

## 11. 测试设计

### L0 backend unit (`backend/tests/unit/memory/`)

1. `test_persona_service.py`
   - list_items: 跨 user 隔离
   - add_item: source / position / text validation
   - update_item: source 升级 user → agent ✗ / agent → user ✓
   - delete_item: 物理删
   - render_to_markdown: 空 section / 非空 / 顺序
   - apply_agent_append: 多行切分 / prefix 去除
   - apply_agent_replace: match / no-match fallback / never match user 区

2. `test_persona_router.py`
   - GET schema
   - POST validation (text 空 / 超 500 / target_section invalid)
   - PATCH source 升级
   - DELETE
   - 跨 user 404

3. `test_persona_markdown_roundtrip.py`
   - markdown ↔ items 双向转换
   - 边界：空 / 只有 user 区 / 只有 agent 区 / 含特殊字符

4. `test_migrate_persona_blob.py`
   - 老 blob → items（全标 agent）
   - 空 blob → no-op
   - 解析失败时 graceful fallback

5. `test_memory_tool_usage_template.py`（既有文件追加 1 assertion）
   - 断言模板含 "❌ 不要试图修改 [你声明的] 区" 文案（决策 2 / §8.3）

### L1 backend integration (`backend/tests/integration/memory/`)

1. `test_persona_e2e.py` (真 PG fixture)
   - user 加 → agent 加 → user 改 agent 区条 → 升级 → 查 GET 返回正确
   - render_to_markdown 跟 PersonaService 状态一致

2. `test_persona_chat_planner_e2e.py`
   - user 改 persona → ChatPlanner 下轮 prompt 含新内容（端到端 wire 验证）

3. `test_agent_double_track_protection.py`
   - 模拟 agent 调 apply_agent_replace 试图改 user 区条
   - verify service 层拒绝 + log warn + 落到 agent 区 append

### L0 frontend vitest (`frontend/src/components/memory/__tests__/`)

1. `MemoryPersona.test.tsx`
   - 渲染两 section / 空状态
   - inline edit 流程（点 ✏️ → textarea → ✓ → PATCH）
   - 删除流程（Popconfirm → DELETE）
   - 添加 modal
   - source 升级动画 trigger

2. `persona-api.test.ts` (msw)
   - 5 endpoint mock + typed response

### E2E Playwright (`frontend/tests/e2e/`)

1. `memory-persona.spec.ts`
   - 打开 /memory → 默认在画像 tab
   - 添加一条 → 出现在 user 区
   - 编辑 agent 区一条 → 看到迁移动画 + 出现在 user 区
   - 删除一条 → 消失
   - chat 顶角点击 "我的画像" → 跳转到 /memory#persona

---

## 12. 留 hook（v1.x P2/P3）

1. **agent 写入实时刷新 SSE**（决策 5）
   - 触发：dogfood 撞实"刚刚跟 agent 说的为什么 UI 不显"
   - 文件：`backend/app/sse/persona_channel.py` + 前端 `EventSource`

2. **编辑 audit log**（决策 4）
   - 触发：dogfood 撞实"我误删了想恢复"
   - schema：persona_items 加 `deleted_at` 列 + 新建 `persona_items_history` 表

3. **items 拖拽排序**（决策 6）
   - 触发：用户多到 10+ 条想自定义优先级
   - 前端：react-dnd + position 字段更新

4. **多语言**: section heading 走 i18n
   - 触发：上线英文界面

5. **scratchpad UI**: Phase 4 才物理独立成 PG 表后再做

---

## 13. 项目集成 / 跟现有架构对齐

- **chat_planner Phase 1**: `render_persona_markdown` 路径完全兼容 —
  PersonaService 在写入后调 `_sync_to_working_block` 把 markdown 同步到
  `working_blocks.persona.content`，ChatPlanner 不感知 schema 变化
- **prefix cache**: persona markdown 仍是 frozen snapshot（每 session 起手装
  一次），用户编辑后下一 session 才生效；UI 加一行小字 "改动会在下次新对话
  生效" 提示用户
- **Tier 2 graph 不动**: /memory 现有 3 tab 仅降级为非默认 tab，组件代码不改
- **Onboarding modal**: 现有 `MemoryOnboardingModal.tsx` 加一句关于"画像 tab
  可以编辑" 的引导
- **测试基础设施**: 复用现有 PG fixture / vitest+msw / Playwright

---

## 14. 实施估算（Claude Code wall time）

| Phase | 内容 | wall time |
|-------|------|-----------|
| 1 | schema + migration + PersonaService | 1 day |
| 2 | REST endpoint + L0/L1 backend test | 1 day |
| 3 | MemoryPersona.tsx + persona-api.ts + L0 vitest | 1.5 day |
| 4 | /memory tab 重排 + chat 顶角入口 + Playwright e2e | 0.5 day |
| 5 | agent 写入转译 + prompt 改造 + 双轨保护 e2e | 1 day |
| 6 | dogfood 跑 1 真 session + 调整 | 0.5 day |
| **总计** | | **~5.5 day** |

---

## 15. 简历叙事 hook

> "继 c5 cross-session memory ship 后，Tier 1 working blocks 缺用户交互入口，
> dogfood 验不到 self-managed memory 写入质量。Persona Editable UI 把
> 'agent 自管理 memory' 暴露为 ChatGPT 风的列表式 UI，并加'双轨'语义 —
> user-declared 区 agent 只读 / agent-inferred 区用户可改可删（改了自动升级
> 为 user 区）。schema 升级 markdown blob → row-per-item with stable UUID
> 解决 atomic 操作的 id 漂移问题（对照 Notion / Letta 工业实例）；agent 的
> core_memory_append/replace 加服务层转译 + 双层（prompt + service）写入保
> 护，防止 agent 覆盖 user 区。"

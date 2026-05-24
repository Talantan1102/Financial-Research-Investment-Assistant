# Harness Board 框架重做(landing → 7 模块图 + 模块页 6 字段 DeepCard + 故事页 skill 接口)— 设计文档

**作者**:Talantan1102
**起草**:2026-05-24
**状态**:Spec — Plan 1 ship 2026-05-24 + Plan 2 ship 2026-05-24(DeepCard v2 schema + 模块页 /m/{dim} + 三色 chip + 右键 + 就地展开 + 图上传;首页 Topology 留 Plan 3,/story 改造留 Plan 4)
**类型**:Refactor / IA 全洗 + 数据 schema 改 + UI 全新
**参考论文**:Li et al., *Agent Harness Engineering: A Survey*, 2026
**关联前序**:`docs/superpowers/specs/2026-05-20-harness-board-etclovg-migration-design.md`(7 维迁移已 ship,本 spec 在其上 reframe IA + 数据 model)

---

## § 0 元信息与范围

### 0.1 触发动机

ETCLOVG 7 维迁移(2026-05-20)和 V2 polish(2026-05-14)ship 后,看板已经把"自定义 8 维"换成论文权威 ETCLOVG 7 维,并刷了 iOS Calm Minimal 视觉。但 IA 与产品形态依然是「项目自查工具」 — 首页是 D-view(7 维 grid + 60+ capability chip)+ B-view(Kanban),信息密度高,讲不出故事。

本次重做把看板从「项目自查工具」reframe 为「**论文 ETCLOVG 框架的项目实例化展示工具**」,核心三页:

1. **首页 `/`** — ETCLOVG 7 模块 Topology 关系图(论文 §2.3 锚定的语义,而非平铺 grid),点击模块 → 跳模块页
2. **模块页 `/m/{dim_id}`** — 单维度内全部 capability,三色状态、右键改状态、单击就地展开 6 字段 DeepCard
3. **故事页 `/story`** — 占位 skill 接口(粘 markdown + mermaid 渲染),故事内容由现有 skill 生成,本次不做生成器

闪卡 / 鸟瞰 / 调查 等 6 个子页全退役;decisions 作为 DeepCard 字段 5 集成进特性详情。

### 0.2 为什么不能继续用现有 IA

| 维度 | 现有问题 | 本次目标 |
|---|---|---|
| **首页讲不出故事** | D-view 7 维 grid + Kanban + App Shell 三段 ≈ 项目管理软件,看不出 ETCLOVG 是什么、模块间什么关系 | 首页 = 论文 §2.3 的 Topology 关系图本身(可点击),一图懂 |
| **DeepCard 字段自由 JSON** | 没有强制结构,内容随心填,简历讲故事时每个 capability 要从头梳理 | 6 字段固化(需求场景 / 设计方案 / Tradeoff / 方案点评 / 决策记录 / 实现效果),填的过程 = 整理面试材料 |
| **决策(/decisions)与特性割裂** | 决策是从 spec/plan 抽的,但与 capability 没绑定关系 | 决策吸进 DeepCard 字段 5,讲特性时决策天然在身边 |
| **图文断档** | 当前 DeepCard 是纯文本,设计方案 / 实现效果无图,简历价值低 | 上传按钮 + screenshots/ 进 git + mermaid 渲染,图文混排 |
| **三色含义弱** | lit `#34C759`(绿)/ wip `#FF9F0A`(橙)/ todo `#C7C7CC`(浅灰)— 灰 todo 视觉权重过低,「未开发」反而隐身 | 颜色保持(用户决议),但提升 todo 视觉权重(更强对比) |
| **6 个子页过载** | overview / story / decisions / survey / flashcards/today / flashcards/stats 各自半成品,没有完整闭环 | 退役 4 个(survey / overview /2 flashcards),decisions 字段化,只留 / + /m/{dim} + /story 三页 |
| **闪卡偏离主航向** | SM-2 复习卡 35 张 hand-curated seed,但用户不复习 = 无用功 | 整条退役 |

### 0.3 范围边界

**做**(框架层 — 内容留后续协作填):

- 首页 `/` 重写为 ETCLOVG Topology 关系图(SVG 可交互, click → /m/{dim_id})
- 新增模块页 `/m/{dim_id}` × 7
- DeepCard 字段 schema 改造 — 6 字段(需求场景 / 设计方案 / Tradeoff / 方案点评 / 决策记录 / 实现效果)
- DeepCard 单击就地展开(替代 modal)
- chip 右键菜单(三色切换 + 复制锚点)
- 图上传 endpoint + 文件存 `dashboard/screenshots/{cap_id}/` 进 git
- 字段渲染支持 markdown + mermaid(mermaid.js CDN 引入)
- 故事页 `/story` 改造为 textarea(粘 skill 输出) + 渲染区
- 数据迁移:flashcards / prefill_log 表删除;`deep_cards.payload` schema rev(自由 JSON → 6 字段固定 + screenshots 列表)
- 退役 4 子页 + 11 个 partial 模板;清 CSS 旧 dot class
- iOS Calm Minimal 视觉延续(SF Pro / Newsreader / Geist Mono / amber × teal / numerale)
- 60+ DeepCard 占位内容(每张 6 字段都给 "(待填)" placeholder),后续轮人工填实
- /decisions 派生保留(decision_extractor 不动),按 cap_id 路由进 DeepCard 字段 5

**不做**(YAGNI):

- 故事 skill 本体(已有 skill,本次只接口占位)
- DeepCard 内容(60+ capability × 5 字段 ≈ 300 项,工作量太大,后续轮协作填)
- 截图 / GIF(用户提供,本次不预填)
- 富文本编辑器(WYSIWYG)— 仅 markdown textarea
- DeepCard 字段 LLM 草拟功能(原 `/cap/{id}/ai_draft/{field}` 退役,先 manual)
- 评论 / 多人协作(单用户工具)
- 历史版本(deep_cards 表 single-row per cap,无版本)
- 移动端响应式(简历演示场景以桌面 demo 为主;基本 viewport 适应即可,不做触屏右键)
- alembic 迁移(memory `v0.9.x-no-alembic-until-db-unify`,继续手写 schema rev SQL)
- 国际化(全中文)

### 0.4 关键 memory 引用

- `feedback_no_portfolio_simplification` — 个人项目也要工业级三维评估
- `feedback_design_doc_format` — 每个非平凡决策必须四件套
- `feedback_yagni` — 抽象/Protocol/config 必须有当前真实需求驱动
- `feedback_architecture_first` — 改前对齐架构层次和契约,不绕开
- `project_etclovg_migration_2026-05-20` — 7 维迁移已完成,本次在其上 reframe
- `project_harness_board_v2_polish_done` — V2 polish 视觉系统是本次重做的视觉底座(fingerprint / 配色 / 字体不动)
- `feedback_legacy_barrel_eager_import_rot` — 退役 import 链要 grep 验证
- `feedback_unguarded_imports_after_delete` — 删模块前 grep 引用面

---

## § 1 现状盘点

### 1.1 当前 routes(28 条 Route + 1 Mount)

```
GET  /                             index            main.html         保留 → 全新重写
GET  /healthz                      healthz          json              保留
GET  /decisions                    decisions_view   decisions.html    退役页面;derive 留
POST /decisions/{id}/note          post_decision_note                 退役(吸进 cap.field5)
DELETE /decisions/{id}/note        delete_decision_note               退役
GET  /capability/{id}/edit         edit_capability  _edit_select.html 退役(被右键替代)
POST /capability/{id}/override     post_override                      改 rename → POST /cap/{id}/status
GET  /refresh                      post_refresh     SSE               保留(刷新流水线)
GET  /overview                     overview_view    overview.html     退役
GET  /overview/fallback            overview_fallback                  退役
GET  /api/overview/graph.json      overview_graph_json                退役
GET  /story                        story_view       story.html        改造
GET  /survey                       survey_view      survey.html       退役
GET  /cap/{id}                     deep_card_modal  _deep_card_modal  改造 → _deep_card_inline.html(就地展开)
GET  /cap/{id}/related             related_capabilities               保留(就地展开内复用)
POST /cap/{id}/field/{f}           post_field_update                  保留(6 字段编辑)
POST /cap/{id}/ai_draft/{f}        post_ai_draft                      退役(YAGNI)
GET  /flashcards/today             flashcards_today                   退役
GET  /flashcards/stats             flashcards_stats                   退役
GET  /api/flashcards/stats.json    flashcards_stats_json              退役
POST /flashcards/{id}/review       post_flashcard_review              退役
POST /admin/milvus/reindex         post_admin_milvus_reindex          保留(refresh pipeline 一部分)
Mount /static                      StaticFiles                        保留 + 增 /static/uploads(N/A — 改进 git)
```

### 1.2 当前 sqlite 表(6 张)

```
derived_snapshot    保留     — 派生快照
capability_override 保留     — 三色 override(从 GET 改 POST /cap/{id}/status)
decision_note       保留     — 决策 note (DeepCard 字段 5 引用)
deep_cards          改 schema — payload JSON 内固化 6 字段 + screenshots[]
flashcards          删       — 闪卡退役
prefill_log         删       — ai_draft 退役
```

### 1.3 当前 yaml SoT

```
dimensions.yaml     不动 — 7 维 + 5 catch_all(catch_all 保留作 path_router fallback)
capabilities.yaml   不动 — 69 项(本次不增减,但 manual derive_rule 项保持 manual)
```

### 1.4 当前模板(28 个)

| 模板 | 动作 |
|---|---|
| `base.html` | 保留 + 引 mermaid.js CDN |
| `main.html` | 重写为 Topology 关系图首页 |
| `decisions.html` `overview.html` `overview_fallback.html` `story.html` `survey.html` `flashcards.html` `flashcards_stats.html` | story.html 改造;其余 6 个**删** |
| `_board_nav.html` | 简化(4 项:首页 / 故事 / refresh / GitHub 锚) |
| `_hero.html` | 删(Topology 图直接画在 main.html) |
| `_view_toggle.html` `_d_view.html` `_b_view.html` `_app_shell.html` `_d_b_toggle.html` | **删**(IA 全洗) |
| `_capability_chip.html` | 重写(三色 + 右键 hook) |
| `_deep_card_modal.html` | 改造为 `_deep_card_inline.html`(就地展开) |
| `_deep_card_field.html` | 保留 + 接 mermaid 渲染 |
| `_edit_select.html` | 删(被右键替代) |
| `_refresh_panel.html` | 保留(SSE 流水线不动) |
| `_decision_card.html` `_decision_filter.html` `_decision_note_form.html` | **删**(decisions 页退役) |
| `_story_card.html` `_flashcard_review.html` | **删** |
| **新增** `_topology_diagram.html` | 首页 ETCLOVG Topology SVG + 模块跳转 |
| **新增** `_module_page.html` | 模块页主结构(chip 列表 + 就地展开区) |
| **新增** `_context_menu.html` | 右键菜单(三色 + 复制锚点) |
| **新增** `_screenshot_uploader.html` | 字段编辑里的上传按钮组件 |

### 1.5 当前 derive 模块(15 个)

```
保留 不动:
  capability_resolver / path_router / snapshot_builder / refresh_pipeline
  decision_extractor / seed_ingest / provenance / commit_time_extractor
  completion / types / deep_card_types / llm_prefill_prompt / app_shell_stat
退役 删:
  flashcard_generator(闪卡)
  srs(闪卡 SM-2 调度)
  story_builder(/story 自由故事生成器)
  survey_loader(survey 退役)
  graph_builder(/overview cytoscape 数据)
新增:
  topology_layout(首页 SVG 7 模块布局参数)
  screenshot_repo(上传文件管理)
```

---

## § 2 目标 IA

### 2.1 最终 URL 拓扑

```
/                       — 首页:ETCLOVG Topology 关系图 (全新)
/m/{dim_id}             — 模块页:dim_id ∈ {execution,tool,context,lifecycle,observability,verification,governance}
/story                  — 故事页:粘 skill 输出 markdown + mermaid 渲染
/healthz                — 健康检查
/refresh                — SSE 全量刷新流(保留)
/cap/{cap_id}/expand    — htmx 触发:就地展开 6 字段 DeepCard(返回 fragment)
/cap/{cap_id}/field/{f} POST — 字段编辑保存
/cap/{cap_id}/status    POST — 三色状态切换(从右键菜单触发)
/cap/{cap_id}/screenshot POST — 截图上传 endpoint
/cap/{cap_id}/related   GET — 字段渲染时附带相关 capability 推荐(保留)
/admin/milvus/reindex   POST — Milvus 重建(refresh pipeline)
/static/...             — 静态资源 Mount
```

**退役**(11 条):`/overview` `/overview/fallback` `/api/overview/graph.json` `/survey` `/decisions` `/decisions/{id}/note` × 2 `/flashcards/today` `/flashcards/stats` `/api/flashcards/stats.json` `/flashcards/{id}/review` `/capability/{id}/edit` `/capability/{id}/override`(后者 rename 为 `/cap/{id}/status`)`/cap/{id}/ai_draft/{f}`(YAGNI)

退役处理:**直接 404,不做 301 redirect**(单用户工具,无外部链接需要兼容)。

### 2.2 nav-rail 简化

```
旧:[首页] [决策] [鸟瞰] [故事] [调查] [复习]      6 项
新:[首页] [故事] [refresh] [GitHub]              4 项(GitHub 链外部 repo)
```

### 2.3 首页 `/` 结构(全新)

```
┌──────────────────────────────────────────────────────────┐
│ nav-rail (80px, fixed left)                              │
├──────────────────────────────────────────────────────────┤
│ <main>                                                    │
│   <section.hero>                                          │
│     <h1>Harness, 不是模型。</h1>                          │
│     <p>(沿用现有 hero 文案 — Prompt→Context→Harness)</p> │
│   </section>                                              │
│                                                           │
│   <section.topology>                                      │
│     {{ Topology SVG }} ← 见 § 4.2                         │
│   </section>                                              │
│                                                           │
│   <section.summary>                                       │
│     7 模块概要带状条 — 每模块名 + 状态条 lit/wip/todo 比例 │
│     mobile fallback:topology 图隐藏,只剩这条             │
│   </section>                                              │
│ </main>                                                   │
└──────────────────────────────────────────────────────────┘
```

**首页不再有**:D-view 7 维 grid · B-view Kanban · App Shell 行 · view-toggle · capability chip 平铺

### 2.4 模块页 `/m/{dim_id}` 结构(新)

```
┌──────────────────────────────────────────────────────────┐
│ nav-rail                                                  │
├──────────────────────────────────────────────────────────┤
│ <header.module-head>                                      │
│   <breadcrumb>首页 / E 执行环境</breadcrumb>               │
│   <h1>{{ dim.number }} {{ dim.name_cn }}                  │
│       <span class="en">{{ dim.name_en }}</span></h1>     │
│   <p class="paper-anchor">论文 § 3</p>                   │
│   <div class="module-stats">                              │
│     5 lit / 2 wip / 4 todo · 进度 50%                     │
│   </div>                                                  │
│ </header>                                                 │
│                                                           │
│ <section.capabilities>                                    │
│   <ol>                                                    │
│     {% for c in caps %}                                   │
│       <li class="cap-item" id="cap-{{ c.id }}">          │
│         <div class="cap-chip dot-{{c.status}}">          │
│           {{ c.name_cn }} <span>·</span>                  │
│           {{ c.name_en }}                                 │
│           <span class="status-badge">{{c.status}}</span> │
│         </div>                                            │
│         <!-- 默认 collapsed -->                           │
│         <div class="cap-detail" hidden></div>            │
│       </li>                                               │
│     {% endfor %}                                          │
│   </ol>                                                   │
│ </section>                                                │
└──────────────────────────────────────────────────────────┘
```

**交互**:
- chip 单击 = htmx GET `/cap/{id}/expand` → 填充 `.cap-detail` + slide-down 展开;再点 = 收起(纯 JS toggle)
- chip 右键 = 阻止默认菜单 + 显示 `_context_menu.html`(三色切换 + 复制锚点链接)
- 锚点链接格式:`/m/{dim_id}#cap-{cap_id}`(URL hash 自动滚动 + auto-expand)

### 2.5 故事页 `/story` 结构(改造)

```
┌──────────────────────────────────────────────────────────┐
│ nav-rail                                                  │
├──────────────────────────────────────────────────────────┤
│ <header><h1>故事</h1>                                     │
│   <p>从 skill 拿到面试故事 markdown,粘到下方渲染。</p>  │
│ </header>                                                 │
│                                                           │
│ <div class="story-editor">                                │
│   <textarea placeholder="粘 skill 输出..."                │
│             oninput="renderStory(this.value)"></textarea> │
│ </div>                                                    │
│                                                           │
│ <div class="story-render markdown-body" id="story-out">  │
│   <!-- 客户端 marked.js + mermaid.js 渲染 -->            │
│ </div>                                                    │
│                                                           │
│ <aside class="story-help">                                │
│   <h4>skill 调用提示</h4>                                  │
│   <p>本看板不调用 skill,粘 markdown 即可。                │
│      支持 mermaid sequenceDiagram(用户视角时序图)。</p>│
│ </aside>                                                  │
└──────────────────────────────────────────────────────────┘
```

**零自动化**,纯 client-side render。后续要接 skill 调用时,在 `<aside>` 加 "调用" 按钮即可。

---

## § 3 DeepCard 6 字段模板

### 3.1 字段定义

| # | id | 中文名 | 类型 | 必填 | 说明 |
|---|---|---|---|---|---|
| 1 | `scenario` | 需求场景 | markdown | 必填 | 这个 capability 解决什么问题 / 在什么场景被触发 |
| 2 | `design` | 设计方案 | markdown + 图 + mermaid | 必填 | 架构图 / 数据流 / 关键组件 |
| 3 | `tradeoff` | Tradeoff | markdown 表格 | 必填 | 业界 alternatives + 我们选哪个 + 为什么 |
| 4 | `review` | 方案点评 | markdown | 必填 | 优点 / 不足 / 已知坑 / 如果重做会改什么 |
| 5 | `decisions` | 决策记录 | 派生 + 用户 note | 自动填(可空) | 从 spec/plan 抽 + 可手动加 note |
| 6 | `evidence` | 实现效果 | markdown + 截图 / GIF | 仅 `lit` 必填,其他状态禁用 | 跑通的样子(截图 / 调用链 / 输出 sample) |

### 3.2 payload JSON schema

```json
{
  "schema_version": 2,
  "scenario": "markdown 文本",
  "design": "markdown 文本(可含 ![](screenshots/...) 和 mermaid 代码块)",
  "tradeoff": "markdown 文本",
  "review": "markdown 文本",
  "decisions": {
    "auto_extracted_ids": ["dec_001", "dec_042"],
    "user_notes": [
      {"id": "n_1", "text": "...", "created_at": "..."}
    ]
  },
  "evidence": "markdown 文本 (lit 必填,wip/todo 为 null)",
  "screenshots": [
    "screenshots/{cap_id}/design-arch.png",
    "screenshots/{cap_id}/effect-demo.gif"
  ]
}
```

### 3.3 schema migration(v1 → v2)

```sql
-- 当前 deep_cards.payload 是自由 JSON,迁移规则:
--   v1 字段全保留,但放进 v2 的 "legacy_payload" key
--   v2 6 字段全设 "(待填)" placeholder
--   schema_version: 2
ALTER TABLE deep_cards ADD COLUMN _migrated_at TEXT;
-- 迁移用 Python 脚本(dashboard/scripts/migrate_deepcard_v2.py)读 v1,写 v2
```

**迁移脚本逻辑**:

```python
# 伪代码 — 实际见 plan
for row in cursor.execute("SELECT cap_id, payload FROM deep_cards"):
    old = json.loads(row.payload)
    new = {
        "schema_version": 2,
        "scenario": old.get("scenario") or "(待填 — 这个 capability 解决什么问题)",
        "design": old.get("design") or old.get("how") or "(待填)",
        "tradeoff": old.get("tradeoff") or "(待填)",
        "review": old.get("review") or "(待填)",
        "decisions": {"auto_extracted_ids": [], "user_notes": []},
        "evidence": old.get("effect") if cap.status == "lit" else None,
        "screenshots": []
    }
    cursor.execute("UPDATE deep_cards SET payload = ?, _migrated_at = ? WHERE cap_id = ?",
                   (json.dumps(new), now(), row.cap_id))
```

### 3.4 字段编辑界面(就地展开内)

```
┌──── ▼ multi_tier_signature (lit) ────────────────────┐
│ § 1 需求场景                                  ✎ 编辑  │
│   不同 agent 步骤精度需求不同,planner / writer /     │
│   data_collector 各自配套不同 tier 模型...            │
│                                                       │
│ § 2 设计方案                                  ✎ 编辑  │
│   [架构图]                                            │
│   tier_router 节点 + signature schema...              │
│                                                       │
│ § 3 Tradeoff                                  ✎ 编辑  │
│   方案 A vs B vs C ...                                 │
│                                                       │
│ § 4 方案点评                                  ✎ 编辑  │
│   优点:... 不足:... 已知坑:...                     │
│                                                       │
│ § 5 决策记录                                  + note │
│   ◇ 2026-05-03 选 tier_router 而不是 model_caching   │
│     ↳ note: ...                                      │
│   ◇ 2026-05-10 ...                                    │
│                                                       │
│ § 6 实现效果                                  ✎ 编辑  │
│   [截图: tier 切换日志]                               │
│   prompt_id=xxx tier=tier_2 → response in 2.3s...    │
└───────────────────────────────────────────────────────┘
```

**编辑流**:点 ✎ → 字段变 textarea + 上传按钮(`_screenshot_uploader.html`)+ 保存/取消按钮 → POST `/cap/{id}/field/{f}` → 服务端 markdown render(原 `provenance.py` 不动)→ swap fragment 回原位。

---

## § 4 视觉与交互

### 4.1 三色 token(保持现 ship)

```css
:root {
  --status-lit:  #34C759;  /* iOS 绿 — 已实现 */
  --status-wip:  #FF9F0A;  /* iOS 橙 — 开发中 */
  --status-todo: #C7C7CC;  /* 浅灰 — 未开发 */
}
```

**视觉权重提升**(todo 不再隐身):
- lit chip:`background: var(--status-lit); color: white;`
- wip chip:`background: rgba(255,159,10,0.18); border: 1px dashed var(--status-wip); color: #B25800;`
- todo chip:`background: white; border: 1.5px solid var(--status-todo); color: #6E6E73;` (实线边而非虚线,避免太弱)

### 4.2 首页 Topology SVG 布局(论文 §2.3 锚定)

```
viewBox="0 0 960 540"

  ┌──────────────── 顶部横切带 (y=20-80) ────────────────┐
  │                                                       │
  │   ╭─────────────────╮         ╭─────────────────╮   │
  │   │ G · Governance  │         │ O · Observ.     │   │
  │   ╰─────────────────╯         ╰─────────────────╯   │
  └───────────────────────────────────────────────────────┘
            ↓ cross-cut 横切 ↓     ↓ cross-cut 横切 ↓
  ┌──────────────── 中段三件套 (y=180-340) ──────────────┐
  │                                                       │
  │  ╭─────────╮   ╭─────────╮   ╭─────────╮             │
  │  │T · Tool │↔ │C · Ctx  │↔ │L · Lifec.│             │
  │  ╰─────────╯   ╰─────────╯   ╰─────────╯             │
  └───────────────────────────────────────────────────────┘
            ↓ run-on 运行其上 ↓                  → V 旁路
  ┌──────────────── 底盘 (y=420-500) ────────────────────┐
  │   ╭────────────────────────────────╮  ╭──────╮      │
  │   │ E · Execution & Sandbox        │  │V·Veri│      │
  │   ╰────────────────────────────────╯  ╰──────╯      │
  └───────────────────────────────────────────────────────┘

每个模块矩形含:
  - 模块代号 (大字 SF Pro 36px semibold)
  - 中文名 (16px regular)
  - lit/wip/todo 计数 (Geist Mono 12px)
  - 进度条 (4px 高,跟现有 .l-stat 同款)
  - 论文 § 锚 (10px 灰)

矩形 hover:阴影抬升 + indigo border (#5E5CE6) + cursor: pointer
矩形 click:window.location = `/m/${dim_id}`
矩形之间连线:
  - G/O → T/C/L: 虚线箭头(横切语义)
  - T/C/L → E: 实线箭头(运行其上)
  - V → L: 虚线(旁路)
```

### 4.3 chip 三色 + 右键菜单

```html
<!-- _capability_chip.html -->
<button class="cap-chip cap-chip--{{ c.status }}"
        data-cap-id="{{ c.id }}"
        oncontextmenu="showContextMenu(event, '{{ c.id }}'); return false;"
        hx-get="/cap/{{ c.id }}/expand"
        hx-target="#detail-{{ c.id }}"
        hx-swap="innerHTML"
        onclick="toggleExpand('{{ c.id }}')">
  <span class="cap-name">{{ c.name_cn }}</span>
  <span class="cap-status">{{ c.status_label }}</span>
</button>
```

```html
<!-- _context_menu.html (固定 hidden, JS show + position) -->
<div id="context-menu" class="ctx-menu" hidden role="menu">
  <button hx-post="/cap/{cap_id}/status" hx-vals='{"status":"lit"}'>● 标为已实现</button>
  <button hx-post="/cap/{cap_id}/status" hx-vals='{"status":"wip"}'>● 标为开发中</button>
  <button hx-post="/cap/{cap_id}/status" hx-vals='{"status":"todo"}'>● 标为未开发</button>
  <hr>
  <button onclick="copyAnchor('{cap_id}')">复制锚点链接</button>
</div>
```

### 4.4 单击就地展开

```javascript
// dashboard/static/inline-expand.js (新)
function toggleExpand(capId) {
  const detail = document.getElementById(`detail-${capId}`);
  if (detail.hidden) {
    // htmx 已经触发 GET /cap/{id}/expand,这里只管 reveal
    detail.hidden = false;
    detail.style.maxHeight = '0';
    requestAnimationFrame(() => {
      detail.style.transition = 'max-height 240ms ease-out';
      detail.style.maxHeight = detail.scrollHeight + 'px';
    });
  } else {
    detail.style.maxHeight = '0';
    setTimeout(() => { detail.hidden = true; }, 240);
  }
}
```

### 4.5 图上传

```python
# dashboard/server.py 新 endpoint
async def post_screenshot(request: Request) -> JSONResponse:
    cap_id = request.path_params["cap_id"]
    form = await request.form()
    upload: UploadFile = form["file"]

    # 校验
    if upload.content_type not in {"image/png", "image/jpeg", "image/gif", "image/webp"}:
        return JSONResponse({"error": "类型不允许"}, status_code=400)
    content = await upload.read()
    if len(content) > 500_000:
        return JSONResponse({"error": "≤ 500KB"}, status_code=400)

    # 落 dashboard/screenshots/{cap_id}/{timestamp}-{filename}
    out_dir = DASHBOARD_ROOT / "screenshots" / cap_id
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", upload.filename)
    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out_path = out_dir / f"{ts}-{safe_name}"
    out_path.write_bytes(content)

    rel_path = f"screenshots/{cap_id}/{out_path.name}"
    return JSONResponse({
        "path": rel_path,
        "markdown": f"![{safe_name}]({rel_path})",
        "git_hint": f"git add dashboard/{rel_path}"
    })
```

**前端**:`_screenshot_uploader.html` 内 input[type=file] + JS post → 返回插 textarea 当前光标位置 + toast `提醒 git add ...`。

### 4.6 渲染层(markdown + mermaid)

```html
<!-- base.html 加载 -->
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<script>
  mermaid.initialize({ startOnLoad: false, theme: 'neutral' });
</script>
```

```javascript
// dashboard/static/render-field.js (新)
function renderField(rawMarkdown) {
  // marked render 出 HTML, 但 mermaid 代码块保留为 <pre><code class="language-mermaid">
  const html = marked.parse(rawMarkdown, {
    breaks: true,
    highlight: (code, lang) => lang === 'mermaid' ? code : code
  });
  // 后处理:把 mermaid code 块包成 <div class="mermaid">
  return html.replace(
    /<pre><code class="language-mermaid">([\s\S]*?)<\/code><\/pre>/g,
    '<div class="mermaid">$1</div>'
  );
}
function postRender(container) {
  mermaid.run({ nodes: container.querySelectorAll('.mermaid') });
}
```

**故事页**:textarea oninput → renderField → 替换 #story-out innerHTML → postRender 渲染 mermaid。
**字段就地展开**:服务端 markdown render(`provenance.py` 现有 markdown 模块)+ 客户端 mermaid postRender(只对 .mermaid 节点)。

---

## § 5 关键决策(四件套)

### D1:首页形态 — Topology 关系图

**问题陈述**:首页要让读者一眼懂 ETCLOVG 是什么 + 我们项目落在哪 + 模块间什么关系。现有 D-view 7 维 grid + Kanban 是项目管理风,讲不出语义。

**业界 Alternatives**:

| 方案 | 描述 | 例子 |
|---|---|---|
| A. 论文 Figure 风 | 7 个等大 box 2 行(4+3),纯静态分组 | 多数论文 Figure 1 |
| B. 轮辐 fingerprint 升级 | 现有 fingerprint 演进为可点击 7 扇形 | Apple Watch activity rings / NVD3 polar |
| **C. Topology 关系图(选)** | 不平均布局,E 底盘 / TCL 中 / OG 顶横切 / V 旁,模块间方向线 | C4 model / k8s architecture diagram |
| D. Cytoscape 自由图 | 任意 layout 自动 spread | 现 `/overview` |

**Tradeoff**:

| 维度 | A | B | C(选) | D |
|---|---|---|---|---|
| 论文忠实度 | 高(平铺) | 中 | **最高**(§2.3 语义) | 低 |
| 视觉张力 | 弱(像 grid) | 强 | 中 | 中(乱) |
| 简历独特性 | 低(常见) | 高 | **中-高**(架构感) | 低 |
| 实施成本 | 低 | 中 | 中-高 | 已存在 |
| 移动端 | 易 | 易 | 难(需 fallback) | 已支持 |

**取舍**:选 C。理由:
1. **论文锚定 §2.3 是本项目的差异化** — 别人做 LLM 看板很多,但能讲出"为什么 OG 是横切、E 是底盘"的几乎没有,这是面试 hook
2. **视觉张力够** — 不平均布局自然把 OG 顶 / E 底视觉化,比 A 等分网格有信息密度
3. **mobile fallback** 走 § 2.3 的 7 模块概要带状条,降级方案明确

**量化评估**:
- 首页一屏不滚动塞下 7 模块图(viewBox 960×540,@1440 屏 ≈ 67% 宽度)
- 模块间连线 ≤ 6 条(G→TCL × 3, O→TCL × 3, TCL→E × 3, V→L × 1,实际 8 条但 G/O 合并视觉)
- 点击 → 跳模块页响应 < 200ms(纯 GET /m/{id},数据来自 sqlite snapshot)

---

### D2:DeepCard 6 字段固化

**问题陈述**:当前 DeepCard 是自由 JSON,内容随心填,简历讲故事时每张 cap 都要现编 "为什么做 / 怎么做 / 效果如何"。需要固化字段引导填入,且字段对应面试讲故事的结构。

**业界 Alternatives**:

| 方案 | 字段集 | 出处 |
|---|---|---|
| A. STAR | Situation / Task / Action / Result | 面试经典 |
| B. 5W1H | What / Why / Where / When / Who / How | 调查记者 |
| **C. 6 字段(选)** | 需求场景 / 设计方案 / Tradeoff / 方案点评 / 决策记录 / 实现效果 | 自定 — 工程师视角 |
| D. ADR | Title / Status / Context / Decision / Consequences | Architectural Decision Record |
| E. 自由 JSON(现) | 无固定 | 现有 |

**Tradeoff**:

| 方案 | 面试可讲 | 工程师友好 | 决策可吸纳 | 必填合理性 |
|---|---|---|---|---|
| A STAR | 强(面试) | 中(action 太泛) | 弱 | 4 项都必填 OK |
| B 5W1H | 强 | 弱(why/when 重复) | 弱 | 6 项太多 |
| **C 6 字段** | 中-强 | **强** | **强**(字段 5 = decisions) | 5 项+1 条件必填合理 |
| D ADR | 中 | 强 | 强(本来就是决策) | 多个 cap 共享决策,模型反 |
| E 自由(现) | 弱 | 中 | 弱 | 无约束 |

**取舍**:选 C。理由:
1. **工程师母语** — 需求/设计/Tradeoff/点评是项目自审框架,跟 spec 文档结构同源
2. **决策记录字段**自然吸纳 `/decisions`(其他方案没有这个位置)
3. **STAR 的 S+T+A+R 可以由 1+2+6 派生**(场景 = S,设计 = T+A,效果 = R),面试讲故事时由故事 skill 重组,而看板存的是更原子的视角

**量化评估**:
- 6 字段单字段平均 200-500 字(markdown),全 cap × 6 字段 ≈ 60 × 6 × 300 = 108,000 字符,sqlite TEXT 列足够
- 必填规则:1/2/3/4 全状态必填,5 自动派生(可空),6 仅 `lit` 必填 — UI 用浅灰 + "状态切到 lit 时显示" disable 状态控制

---

### D3:图载体 — 上传 + screenshots/ 进 git

**问题陈述**:每个 capability 详情要"图文结合"。图存哪、怎么上传、是否进 git 直接决定开发流和多机同步体验。

**业界 Alternatives**:

| 方案 | 存哪 | 进 git | 编辑流 |
|---|---|---|---|
| A. 仓库手放 | `dashboard/screenshots/{cap}/` | ✓ | cp + markdown 引用 + commit |
| B. 上传按钮 + uploads/ | `dashboard/static/uploads/` | ✗(.gitignore) | 点上传 → 自动插入 |
| **C. 上传按钮 + screenshots/(选)** | `dashboard/screenshots/{cap}/` | ✓ | 点上传 → 自动插入 + toast 提示 git add |
| D. 外链图床 | imgur / s3 | ✗ | 拷贝外链 |
| E. mermaid 纯文本 | 字段内 ``` 代码块 | ✓ | 写代码 |

**Tradeoff**:

| 维度 | A | B | **C** | D | E |
|---|---|---|---|---|---|
| 多机同步 | ✓ | ✗ | **✓** | ✓ | ✓ |
| 操作便利 | 弱 | 强 | **强** | 中 | 弱(限流程图) |
| 仓库 size | 涨 | 不涨 | **涨**(可控) | 不涨 | 不涨 |
| 截图 / GIF 支持 | ✓ | ✓ | ✓ | ✓ | **✗** |
| 备份 | git | 单独 | **git** | 外站 | git |
| 实施成本 | 0 | endpoint + UI | endpoint + UI + git toast | 0 | 0(纯 client mermaid) |

**取舍**:选 C(主)+ E(辅,设计方案字段支持 mermaid 代码块)。理由:
1. **多机同步**对本项目必要(memory 有"git pull 同步"偏好)— B/D 直接否
2. **截图 / GIF 不可放弃**(实现效果靠这些)— E 单独否
3. **仓库 size** 用 ≤500KB 限制 + 60 cap × 平均 3 图 = 180 图 × 500KB = 90MB 上限,可接受;远期可加 git-lfs(不在 spec)
4. **上传按钮** + git toast 是最小化用户摩擦同时不破坏多机同步

**量化评估**:
- 单图 ≤ 500KB(后端 enforce)
- 类型白名单:png / jpg / jpeg / gif / webp(svg 暂不允许,潜在 XSS)
- 上传响应 < 300ms(本地 sqlite + fs,无外网)
- 仓库 size 增长上限:< 100MB(60 cap × 3 image × 500KB)

---

### D4:capability 单击展开 — 就地展开

**问题陈述**:点 chip 后看详情,展开方式决定模块页的信息密度与浏览节奏。

**业界 Alternatives**:

| 方案 | 描述 | 例子 |
|---|---|---|
| **A. 就地展开(选)** | 同页内插入 6 字段卡,slide-down 动画 | macOS Finder list view |
| B. Modal 弹层 | 浮层覆盖,htmx swap modal-overlay(现有) | 多数管理后台 |
| C. 分屏 | 左 chip 列表 右 detail panel | Gmail / Mac Mail |

**Tradeoff**:

| 维度 | **A** | B | C |
|---|---|---|---|
| 上下文保留 | **强**(看到前后 chip) | 弱(modal 遮盖) | 强 |
| 多 cap 对比 | **可**(同时展开多个) | 不可(一次一个) | 不可(只 1 个 right pane) |
| 实施成本 | 中(slide JS) | **低**(沿用现有) | 高(布局重做) |
| 移动端 | 易(就是滚动) | 易 | 难(分屏挤) |
| 锚点导航 | **天然**(/m/x#cap-y 滚动 + auto-expand) | 不天然(锚点要打开 modal) | 不天然 |

**取舍**:选 A。理由:
1. **锚点链接**是核心需求(决策记录 / 复制锚点功能依赖),A 天然支持
2. **多 cap 对比**是模块页的隐式需求(看完 capability X 想跟旁边的 Y 比),A 允许同时展开
3. **实施成本**(slide JS)增量可控,且现有 modal 系统不删除(deep_card_modal 改造为 inline,核心 markdown render 复用)

**量化评估**:
- 展开动画 240ms ease-out(标准 iOS)
- 同时展开 cap 数:无上限(用户决定)
- 锚点自动展开:URL hash `#cap-{id}` → 滚动 + 模拟 click

---

### D5:三色 token — 保持现 ship

**问题陈述**:用户原需求字面是"绿 / 黄 / 蓝",但现 ship 是"绿 / 橙 / 灰"。换色 vs 保留?

**业界 Alternatives**:

| 方案 | lit | wip | todo |
|---|---|---|---|
| A. 信号灯 红黄绿 | green | yellow | gray | — 红绿色盲反义 |
| **B. 现 ship(选)** | `#34C759` | `#FF9F0A` | `#C7C7CC` | iOS 系 |
| C. 用户字面绿黄蓝 | `#34C759` | `#FFCC00` | `#007AFF` | iOS 系新组合 |
| D. 单色明度梯 | dark / mid / light 一种色 | 极简但信息弱 |

**Tradeoff**:

| 维度 | A | **B** | C | D |
|---|---|---|---|---|
| 色盲友好 | ✗ | **中**(绿橙可分) | 中-差(绿蓝 + 橙近色) | 中 |
| 现 ship 一致 | ✗ | **✓** | ✗ | ✗ |
| iOS Calm Minimal 风 | ✗ | **✓** | ✓ | ✓ |
| todo 视觉权重 | 弱(灰) | **弱**(灰)| 强(蓝) | 视配置 |
| 切换成本 | 高 | **0** | 中(改 css var) | 中 |

**取舍**:选 B(用户最终决议)。但**提升 todo 视觉权重** — 边框 1.5px 实线(替代当前 dashed),避免 "未开发=隐身" 的反语义。

**量化评估**:CSS var 仅 3 个,所有 chip / Topology 模块 / status badge 统一引用;切换成本(改 CSS 文件)< 50 行修改。

---

### D6:故事页 skill 接口 — A 渲染区

**问题陈述**:故事 skill 已存在(用户已有),看板这边只需要前端接口"占位",方便后续接 skill。占位形态决定后续接入工作量。

**业界 Alternatives**:

| 方案 | 描述 |
|---|---|
| **A. textarea + 渲染区(选)** | 粘 markdown → 客户端 render |
| B. 调用按钮 + 占位 | 顶部按钮(暂禁) + 渲染区 |
| C. 选 capability + 模板下拉 | 选 cap list + STAR/5W → 生成 prompt 给用户去 skill 跑 → 粘回来 |

**Tradeoff**:

| 维度 | **A** | B | C |
|---|---|---|---|
| 当下可用 | **是**(纯渲染) | 否(按钮禁用) | 是(给 prompt) |
| 自动化度 | 0 | 中(等接 skill) | 中-高 |
| 实施成本 | **低**(textarea + marked + mermaid) | 低 | 中 |
| 后续接 skill 难度 | 低(加按钮调 endpoint) | 0(已是占位) | 中(要把"选 cap"逻辑外移) |
| 用户需求时序对齐 | **是**(用户视角 → 时序图,mermaid 原生支持) | 是 | 是 |

**取舍**:选 A。理由:
1. **零等待**:不依赖 skill 接入即可用(粘 markdown 就能 demo)
2. **时序图天然**:mermaid sequenceDiagram 是用户视角讲故事的标准载体
3. **接 skill 是 1 个按钮的事**:未来在 textarea 旁加"调 skill"按钮触发 POST `/story/generate` → 返回 markdown 填 textarea

**量化评估**:textarea 200 字符以上即可形成 demo;mermaid sequenceDiagram 平均 8-12 行;渲染 < 100ms(client-side)。

---

### D7:scope — 单 spec(框架)+ 后续轮(内容)

**问题陈述**:重做工作量大(IA 全洗 + 数据 schema 改 + 视觉重做 + 60+ DeepCard 内容填),一个 spec 装得下吗?

**业界 Alternatives**:

| 方案 | 描述 |
|---|---|
| A. 单 Mega spec | 全部塞一个 |
| **B. 单 spec(框架) + 后续轮(内容)(选)** | 本 spec 只定框架,内容留协作填 |
| C. 3 sub-spec | B 数据 + A 首页 + C 故事 各一 |

**Tradeoff**:

| 维度 | A | **B** | C |
|---|---|---|---|
| spec 长度 | 极长 | **中**(本文 ~1200 行) | 短(各 ~600 行) |
| 起步速度 | 慢(spec 写不完) | **快**(框架 1 周内) | 中(3 spec 串行) |
| 内容填充 | 在 spec 内反复 | **在 spec 外协作** | 各 sub-spec 自定 |
| 重做风险 | 高(改 schema 牵动一切) | **中**(框架定后再填) | 低(各部分独立) |

**取舍**:选 B。理由:
1. **框架与内容是不同性质工作**:框架 = 工程,内容 = 知识沉淀,混在一个 spec 里两头都做不好
2. **60 cap × 6 字段 = 360 项填空**,spec 阶段穷举不现实
3. **C 3 sub-spec 的拆法** A 首页和 B 数据强耦合(模块页要先有三色 schema 才能渲染),拆开反而要造 mock,不如合一

**量化评估**:本 spec 行数控制在 1500 行内(已 ≈ 1200);后续内容填充由 plan + 协作轮处理,每 5-10 个 cap 一轮。

---

### D8:退役清单 — 直接 404 不做 redirect

**问题陈述**:11 条 route 退役,如何处理?

**业界 Alternatives**:
- A. 直接 404
- B. 301 redirect 到 / 或 /m/相关
- C. 保留 stub 页"已退役,请去 X"

**取舍**:A。理由:**单用户工具,无外部链接需要兼容**;internal navigation 由 nav-rail 控制,nav-rail 同步删除入口;搜索引擎不索引(无 sitemap)。

**量化评估**:0 外部链接 + 0 SEO 影响 + nav-rail 简化 6 项→4 项。

---

### D9:右键菜单内容 — 4 项精简

**问题陈述**:右键能放多少功能?

**Alternatives**:
- A. 极简(3 状态切换)
- **B. 4 项(3 状态 + 复制锚点)(选)**
- C. 富(3 状态 + 锚点 + 跳模块页 + 删 DeepCard + AI 草拟)

**取舍**:B。3 状态切换是核心需求,复制锚点支持决策记录引用 / 简历贴链;删除 DeepCard 不存在(deep_cards 是 cap_id 主键,只能编辑不能删);AI 草拟 YAGNI(D7 已退役)。

---

### D10:模块页 URL — `/m/{dim_id}`

**问题陈述**:模块页路径选什么?

**Alternatives**:
- A. `/arch/{dim}`
- **B. `/m/{dim}`(选)**
- C. 单字母 `/e` `/t` `/c`
- D. 全名 `/module/{dim}`

**取舍**:B。理由:简短(2 字符) + 语义清晰("m" = module) + 不与 ETCLOVG 字母混淆(C 方案 `/c` 既是模块又是 URL,歧义);A `/arch` 太抽象;D 太长。

---

## § 6 实施清单

### 6.1 routes 操作

```
保留:    GET / · GET /healthz · GET /refresh · POST /admin/milvus/reindex
重写:    GET / (首页 Topology)
改造:    GET /story (新 textarea + 渲染)
新增 4:  GET /m/{dim_id} × 1(动态,1 handler 处理 7 个 dim)
         GET /cap/{id}/expand × 1
         POST /cap/{id}/status × 1(原 /capability/{id}/override rename)
         POST /cap/{id}/screenshot × 1
保留不动 2: /cap/{id}/field/{f} POST(支持 6 字段)
            /cap/{id}/related GET
退役 11: /overview · /overview/fallback · /api/overview/graph.json
         /survey · /decisions × 3 · /capability/{id}/edit
         /flashcards/today · /flashcards/stats · /api/flashcards/stats.json
         /flashcards/{id}/review · /cap/{id}/ai_draft/{f}
```

### 6.2 模板操作

```
保留 4:  base.html · _refresh_panel.html · _deep_card_field.html · _board_nav.html(简化)
重写 1:  main.html
改造 1:  story.html
新增 4:  _topology_diagram.html · _module_page.html · _context_menu.html · _screenshot_uploader.html
重写 2:  _capability_chip.html(三色 + 右键 hook) · _deep_card_modal.html → _deep_card_inline.html
退役 11: _hero.html · _view_toggle.html · _d_view.html · _b_view.html
         _app_shell.html · _d_b_toggle.html · _story_card.html
         _flashcard_review.html · _decision_card.html · _decision_filter.html · _decision_note_form.html · _edit_select.html
退役页 6: decisions.html · overview.html · overview_fallback.html · survey.html
         flashcards.html · flashcards_stats.html
```

### 6.3 sqlite 操作

```sql
-- 删表
DROP TABLE IF EXISTS flashcards;
DROP TABLE IF EXISTS prefill_log;
DROP INDEX IF EXISTS idx_flashcards_cap_id;
DROP INDEX IF EXISTS idx_flashcards_next_review;

-- 改 schema(deep_cards.payload)
-- 通过 migrate_deepcard_v2.py 脚本 in-place 改 JSON 结构

-- 加列(可选,记录迁移时间)
ALTER TABLE deep_cards ADD COLUMN _migrated_at TEXT;

-- override 表保留(三色 = lit/wip/todo,enum 不变)
-- decision_note 表保留(吸进 DeepCard 字段 5 用)
-- derived_snapshot 表保留(snapshot 不动)
```

### 6.4 derive 模块操作

```
保留 13: capability_resolver · path_router · snapshot_builder · refresh_pipeline
         decision_extractor · seed_ingest · provenance · commit_time_extractor
         completion · types · deep_card_types · llm_prefill_prompt · app_shell_stat
退役 5:  flashcard_generator · srs · story_builder · survey_loader · graph_builder
新增 2:  topology_layout.py(首页 SVG 7 模块定位)
         screenshot_repo.py(上传文件管理)
```

### 6.5 静态资源操作

```
保留:    htmx.min.js · modal.js · toast.js · refresh-panel.js · style.css(改造)
新引入:  marked.min.js · mermaid.min.js (CDN)
新增本地: render-field.js · inline-expand.js · context-menu.js · screenshot-upload.js
退役:    overview.js · flashcards.js · decisions-filter.js · cytoscape.min.js · cytoscape-cose-bilkent.min.js · mockup-v2.html
```

### 6.6 CSS 操作

```
保留(改造):
  - :root vars(增 mermaid theme override)
  - .nav-rail(删 2 个 nav 项的 active 状态)
  - .hero-block · .stage(继续用)
  - .refresh-panel · .modal-overlay · .toast-container

重写:
  - 删:.layer-stack · .layer · .chip(三色规则)· .kanban · .app-shell-row
       .view-toggle · .view-tab · .section-marker(仅在 IA 不使用时删)
       .overview-frame · .overview-toolbar · .overview-canvas · .overview-legend · .overview-tooltip
       .fingerprint(原 8 spoke)+ .fingerprint-caption
       .dot-prompt · .dot-tools · .dot-orch · .dot-memory · .dot-rag · .dot-guard · .dot-eval · .dot-cost(ETCLOVG 旧色 cruft)

新增:
  - .topology-diagram + .module-box × 7 + 连线 path
  - .cap-chip + .cap-chip--lit/wip/todo
  - .cap-detail(就地展开容器)
  - .ctx-menu(右键菜单)
  - .module-page · .module-head · .breadcrumb
  - .screenshot-uploader
  - .story-editor · .story-render · .mermaid theme
  - .markdown-body(KaTeX-style typography for rendered markdown)
```

### 6.7 文件迁移规则

```
ADD:
  - dashboard/screenshots/.gitkeep(确保目录存在,首次 cap 上传前)
  - dashboard/scripts/migrate_deepcard_v2.py(一次性迁移)

UPDATE:
  - .gitignore 不变(dashboard/screenshots/ 进 git;dashboard/static/uploads/ 既然不用,不创建)
```

---

## § 7 测试策略

### 7.1 现有测试影响

```
保留(无影响):
  - dashboard/tests/derive/test_capability_resolver.py
  - dashboard/tests/derive/test_path_router.py
  - dashboard/tests/derive/test_snapshot_builder.py
  - dashboard/tests/derive/test_decision_extractor.py
  - dashboard/tests/state/test_repositories.py(deep_cards repo 测试改 schema)
  - dashboard/tests/integration/test_seed_deep_cards.py(seed 改 v2 格式)

退役:
  - dashboard/tests/derive/test_app_shell_stat.py(如果 _app_shell.html 退役)
    → 保留 app_shell_stat.py 测试本身,但不再被 main.html 使用
  - dashboard/tests/unit/test_flashcard_generator.py
  - dashboard/tests/unit/test_srs.py
  - dashboard/tests/unit/test_story_builder.py
  - dashboard/tests/integration/test_flashcard_*.py × 3
  - dashboard/tests/integration/test_overview_*.py × 2
  - dashboard/tests/integration/test_story_endpoint.py(改造,见下)

改造:
  - dashboard/tests/server/test_main_endpoint.py(/ 重写,断言改 Topology SVG 关键元素)
  - dashboard/tests/integration/test_story_endpoint.py(/story 改 textarea + 渲染)
  - dashboard/tests/integration/test_v2_modal_endpoint.py → test_inline_expand_endpoint.py

新增:
  - dashboard/tests/integration/test_module_page.py(/m/{dim} × 7,断言 chip 数 + 状态)
  - dashboard/tests/integration/test_status_post.py(POST /cap/{id}/status 改三色)
  - dashboard/tests/integration/test_screenshot_upload.py(图上传 + 类型 / 大小验证)
  - dashboard/tests/integration/test_deepcard_v2_migration.py(v1 → v2 迁移幂等)
  - dashboard/tests/unit/test_topology_layout.py(SVG 布局参数)
  - dashboard/tests/unit/test_screenshot_repo.py
```

### 7.2 验收准则

| # | 准则 | 验证方式 |
|---|---|---|
| 1 | 首页 `/` 显示 7 模块 Topology + click → /m/{id} | E2E click 测试 + 7 个 module-box 元素存在 |
| 2 | 模块页 `/m/{dim}` 显示该维度全部 cap chip,三色正确 | 对 7 维度各跑一次,断言 chip 数 = capabilities.yaml 该维度 capability 数 |
| 3 | chip 单击就地展开 6 字段 | DOM 检查 cap-detail 出现 + 6 section 存在 |
| 4 | chip 右键弹菜单 + 三色切换 + 锚点复制 | DOM 检查 ctx-menu 显示 + POST /cap/{id}/status 状态变更 |
| 5 | 截图上传 → 文件落 `dashboard/screenshots/{cap}/` + markdown 返回 | 文件系统检查 + 返回 JSON.path 校验 |
| 6 | 截图非 png/jpg/gif/webp 或 > 500KB 拒绝 | POST 错误样本 → 400 |
| 7 | 故事页 textarea 输入 markdown + mermaid → 渲染正常 | Playwright e2e 验证 mermaid SVG 存在 |
| 8 | 退役 11 条 route 全 404 | 一次性 11 个 GET 断言 404 |
| 9 | DeepCard v1→v2 迁移幂等(跑两遍结果一致)| Migration script 跑两遍后 hash 对比 |
| 10 | /healthz 仍 200 | 烟雾 |

### 7.3 e2e dogfood

迁移完成后,作者本人:
- 浏览 7 个 /m/{dim_id} 页(目视检查 chip 状态)
- 右键改 1 个 cap 的状态(目视检查色变)
- 单击展开 1 个 cap,编辑 1 个字段(粘 markdown + 上传 1 张图)
- /story 粘一段 STAR markdown 含 mermaid sequenceDiagram,看渲染

---

## § 8 风险与回滚

### 8.1 风险清单

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| Migration 错误把 DeepCard 内容搞丢 | 低 | 高 | (1) 迁移前自动 backup `harness_board.db` → `.bak`(2) 迁移脚本 in-place 改 payload JSON,不覆盖整行(3) 跑两遍幂等测试 |
| mermaid CDN 失联 | 低 | 中(渲染坏) | base.html fallback 提示;CDN 切 jsdelivr → unpkg 自动切换 |
| Topology SVG 在小屏(< 800px)不好看 | 高 | 中(简历用桌面 demo) | mobile fallback 走 § 2.3 7 模块概要带状条,Topology 图隐藏 |
| screenshots/ 仓库 size 快速膨胀 | 中 | 中 | (1) 单图 ≤ 500KB enforce(2) plan 阶段加 lint 检查总 size(3) 远期 git-lfs |
| chip 右键在 Safari / 触屏不工作 | 中 | 中 | 长按(touch + 500ms)触发同 menu;Safari 测过的 contextmenu 事件支持 |
| /decisions 退役后,decision_extractor 输出无处可看 | 低 | 低 | DeepCard 字段 5 接管;独立测试 derive 仍跑 |

### 8.2 回滚策略

**完全回滚**(出现 P0 bug):
- `git revert` spec 实施 PR
- `cp harness_board.db.bak harness_board.db`
- 重启服务

**分段回滚**(某一 sub-feature 坏):
- migration / 视觉 / Topology / 模块页 / 故事页 五个区块各自独立 PR(plan 阶段拆分)
- 单 PR 出问题只 revert 该 PR

---

## § 9 不做(YAGNI)

- 故事 skill 本体(已有 skill,本次只接口)
- DeepCard 60+ × 6 字段内容(后续协作填)
- 截图 / GIF 内容(用户手动准备)
- WYSIWYG 富文本编辑器(只 markdown textarea)
- ai_draft 字段(原 POST `/cap/{id}/ai_draft/{f}` 退役)
- DeepCard 历史版本
- 多人协作 / 评论
- alembic 迁移
- 移动端响应式(只保留 viewport meta,Topology 在小屏 fallback)
- 国际化(中文)
- 暗色模式(决议沿用 ETCLOVG 迁移 § 10.Q1 — 只 Light Mode)
- /overview cytoscape 替代品(Topology 图就是替代)
- 右键菜单的"删除"功能(deep_cards 不支持删,只编辑)
- 浏览器 push notification / 提醒功能(YAGNI)

---

## § 10 后续 hook(spec 之外)

| 后续工作 | 触发 | 描述 |
|---|---|---|
| **内容填充轮**(× N) | 框架 ship 后立即 | 每轮 5-10 个 capability,人工 + Claude 协作填 6 字段 |
| **故事 skill 接入** | story 模块的 skill 优化完 | 故事页加 "调 skill" 按钮 → POST `/story/generate` |
| **截图 / GIF 录制** | 内容填充时 | 实现效果字段对应每个 lit cap 准备 1-2 张图 |
| **决策记录 backfill** | 内容填充时 | decision_extractor 已自动派生,但用户 note 需手动加 |
| **简历演示页**(可选) | 内容填充 80% 后 | 可能起 `/portfolio` 独立页,提取 lit cap 做简历贴图(本 spec 不含) |
| **git-lfs**(可选) | 仓库 size > 100MB | 截图迁 git-lfs |
| **fingerprint SVG 二次设计**(可选) | Topology 图 ship 后 | 把现有 fingerprint 保留为 footer 小图标(品牌延续) |

---

## § 11 附录:文件清单(实施时的全量增删表)

### 11.1 新增

```
dashboard/templates/_topology_diagram.html
dashboard/templates/_module_page.html
dashboard/templates/_context_menu.html
dashboard/templates/_screenshot_uploader.html
dashboard/templates/_deep_card_inline.html     (从 _deep_card_modal.html 改名)
dashboard/derive/topology_layout.py
dashboard/derive/screenshot_repo.py
dashboard/static/render-field.js
dashboard/static/inline-expand.js
dashboard/static/context-menu.js
dashboard/static/screenshot-upload.js
dashboard/scripts/migrate_deepcard_v2.py
dashboard/screenshots/.gitkeep
docs/superpowers/specs/2026-05-24-harness-board-framework-rebuild-design.md  (本文件)
```

### 11.2 重写

```
dashboard/templates/main.html
dashboard/templates/_capability_chip.html
dashboard/static/style.css(大幅改写)
```

### 11.3 改造

```
dashboard/templates/story.html
dashboard/templates/_board_nav.html(简化为 4 项)
dashboard/templates/base.html(引入 marked + mermaid CDN)
dashboard/state/db.py(SCHEMA 删 flashcards / prefill_log)
dashboard/state/repositories.py(FlashcardRepo / PrefillRepo 删)
dashboard/server.py(routes + handlers 大幅变动)
```

### 11.4 删除

```
dashboard/templates/decisions.html
dashboard/templates/overview.html
dashboard/templates/overview_fallback.html
dashboard/templates/survey.html
dashboard/templates/flashcards.html
dashboard/templates/flashcards_stats.html
dashboard/templates/_hero.html
dashboard/templates/_view_toggle.html
dashboard/templates/_d_view.html
dashboard/templates/_b_view.html
dashboard/templates/_app_shell.html
dashboard/templates/_d_b_toggle.html
dashboard/templates/_story_card.html
dashboard/templates/_flashcard_review.html
dashboard/templates/_decision_card.html
dashboard/templates/_decision_filter.html
dashboard/templates/_decision_note_form.html
dashboard/templates/_edit_select.html
dashboard/derive/flashcard_generator.py
dashboard/derive/srs.py
dashboard/derive/story_builder.py
dashboard/derive/survey_loader.py
dashboard/derive/graph_builder.py
dashboard/static/overview.js
dashboard/static/flashcards.js
dashboard/static/decisions-filter.js
dashboard/static/cytoscape.min.js
dashboard/static/cytoscape-cose-bilkent.min.js
dashboard/static/mockup-v2.html
dashboard/tests/unit/test_flashcard_generator.py
dashboard/tests/unit/test_srs.py
dashboard/tests/unit/test_story_builder.py
dashboard/tests/integration/test_flashcard_repo.py
dashboard/tests/integration/test_flashcards_endpoint.py
dashboard/tests/integration/test_flashcards_stats_endpoint.py
dashboard/tests/integration/test_flashcard_regenerate_hook.py
dashboard/tests/integration/test_overview_endpoint.py
dashboard/tests/integration/test_overview_after_seed.py
```

### 11.5 保留(不动)

```
dashboard/config/dimensions.yaml
dashboard/config/capabilities.yaml
dashboard/derive/capability_resolver.py
dashboard/derive/path_router.py
dashboard/derive/snapshot_builder.py
dashboard/derive/refresh_pipeline.py
dashboard/derive/decision_extractor.py
dashboard/derive/seed_ingest.py
dashboard/derive/provenance.py
dashboard/derive/commit_time_extractor.py
dashboard/derive/completion.py
dashboard/derive/types.py
dashboard/derive/deep_card_types.py
dashboard/derive/llm_prefill_prompt.py(暂留 — ai_draft 退役但 prompt 模块可能 import 链)
dashboard/derive/app_shell_stat.py(留 — 后续可能复用)
dashboard/state/milvus_collection.py
dashboard/state/keyword_recommender.py
dashboard/templates/_deep_card_field.html
dashboard/templates/_refresh_panel.html
dashboard/static/htmx.min.js
dashboard/static/modal.js
dashboard/static/toast.js
dashboard/static/refresh-panel.js
```

---

**完。**

---

**Plan 拆分提示**(spec 之外):

实施建议拆 4 个 plan(平行/串行混合):

```
Plan 1 — 数据 schema + migration              [先,无 UI 依赖]
   migrate_deepcard_v2.py · sqlite schema · repositories 改 · derive 退役 6 个 · 测试改
Plan 2 — 模块页 /m/{dim} + chip + 就地展开    [Plan 1 后]
   _capability_chip.html 三色 · _deep_card_inline.html · /cap/{id}/expand · _module_page.html · /m/{dim}
   inline-expand.js · context-menu.js · 上传 endpoint + screenshot_repo · _screenshot_uploader.html
Plan 3 — 首页 Topology + nav 简化              [Plan 2 后,可与 Plan 4 并行]
   _topology_diagram.html · topology_layout.py · main.html 重写
   _board_nav.html 简化 · CSS 重写 · 删退役 partial / route
Plan 4 — /story 改造                           [Plan 2 后,可与 Plan 3 并行]
   story.html 改造 · render-field.js · base.html 引 mermaid CDN
```

# Harness Board v2 Polish — UI 美化 + 鸟瞰修复 + 一键全量更新

**作者**:Talantan1102
**起草**:2026-05-14
**状态**:Spec(待 plan 拆分)
**类型**:Implementation spec(改进 + 修复 + 视觉重做)

---

## § 0 元信息与范围

### 0.1 触发动机

2026-05-14 用户提出 Harness Board 三项不完善:

1. **界面不够精美** — 当前 879 行 CSS dark slate 主题视觉单薄,像 admin 工具不像 portfolio 作品
2. **鸟瞰界面空的** — `/overview` cytoscape 渲染 62 节点几乎全是孤立小灰点
3. **看板缺一键更新功能** — 当前 `/refresh` 只 invalidate snapshot,不刷其他派生数据;且前端无入口按钮

经调研定位三个根因 + 一次 mockup v3 视觉方向对齐,本 spec 把三件事 + 整套 UI 表面美化作为一个 v2 polish 整包交付。

### 0.2 根因总结(写入 spec 作为长期记忆)

| 问题 | 根因 | 影响面 |
|---|---|---|
| 鸟瞰空 | `dashboard/data/deep_cards_seed.jsonl` 35 张 seed 是手动 CLI(`backend/app/scripts/seed_deep_cards.py`),没在 startup / refresh 流程自动跑;`board.db` 当前只有 3 张,其他 59 个节点 confidence=0 + 无 edge + 虚线 border + 透明度 0.4,视觉上"空" | `/overview` 完全失去价值 |
| 一键更新缺位 | `/refresh` 只 `SnapshotRepo.invalidate()` 然后 302,不刷 decision / seed / Milvus;且前端无任何按钮入口,需 curl POST | refresh 语义不完整,用户每次要手动跑多个 CLI |
| 视觉单薄 | dark slate `#020617` + 系统 sans + emoji nav + 4 列均匀栅格 + 无层次 | 不像 portfolio 级作品 |

### 0.3 范围边界

**做**:
- 后端:`/refresh` 升级为 SSE 流式 5-step pipeline(C 重档),seed ingest 接入 lifespan + refresh
- 前端:整套 UI 表面按 Quiet Workshop 设计语言重写(13 个模板 + style.css 重写)
- 鸟瞰:数据修复 + 节点视觉增强(hover tooltip / edge confidence 加权)
- 全 UI 表面:含 inline edit / filter / 空状态 / loading / error / modal / toast / 微动画

**不做(真 YAGNI)**:
- Milvus / OPENAI 配置 UI(env var 配)
- 进度面板取消/暂停
- 多用户 / 历史 refresh 记录
- 后端 API schema 改造(只动 UI 层 + `/refresh` 实现,接口契约稳定)
- mockup-v2.html 保留作 design reference,不删除

### 0.4 关键 memory 引用

- `feedback_no_portfolio_simplification` — 每个非平凡决策按"工业级 + 业界 alternatives + 取舍"评估
- `feedback_plain_language_for_industry_terms` — brainstorm 阶段大白话,spec 严谨
- `harness-board-review-mode-done` — V1 已 ship 总卡,本 spec 是 V2 polish 增量
- `harness-board-review-plan3-done` — 35 张 hand-curated seed 已存在但未自动加载

---

## § 1 设计语言:Quiet Workshop

### 1.1 整体定位

"暖黑作坊" — 私人工艺作坊感而非仪表盘感。让 portfolio 看起来"作者认真对待自己作品"。

参考:Stripe Press 书页 × Linear changelog × Are.na knowledge collection × Source Han 中文古典排版。

### 1.2 颜色 token(双强调互补)

| Token | Hex | 用途 |
|---|---|---|
| `--ink` | `#0c0908` | 主底色(暖黑,偏红不偏蓝) |
| `--ink-2` | `#14100c` | 次底色(nav rail / dc-right) |
| `--paper` | `#1a1410` | 卡片底色 |
| `--paper-2` | `#221b15` | 卡片高光区 / numeral 水印 |
| `--hair` | `rgba(235,227,212,0.08)` | 主分割线 |
| `--hair-2` | `rgba(235,227,212,0.04)` | 次分割线(dashed) |
| `--fg` | `#ebe3d4` | 主文本(羊皮纸色) |
| `--fg-dim` | `#b9ad94` | body 正文 |
| `--fg-mute` | `#7d6e58` | 辅助 / 说明 |
| `--fg-faint` | `#4a3f33` | 极弱(time stamp / placeholder) |
| **`--amber` `#c89456`** | 主强调 | **行动 / 高光 / 当前 active / 主 CTA** |
| `--amber-glow` `#e5b079` | — | hover glow |
| `--amber-deep` `#8a5f30` | — | border |
| `--amber-soft` `rgba(200,148,86,0.12)` | — | 填充 |
| **`--teal` `#6f9494`** | 次强调(古铜青) | **路径 / 数据 / 链接 / 次级标签 / 次 CTA** |
| `--teal-glow` `#8db1b1` | — | hover |
| `--teal-deep` `#3f5e5e` | — | border |
| `--teal-soft` `rgba(111,148,148,0.13)` | — | 填充 |
| `--lit` `#94b87a` | — | 状态:已实现(sage 沙绿) |
| `--wip` `#d4824a` | — | 状态:在做(terracotta 赤陶,带心跳脉冲) |
| `--todo` `#6b5d49` | — | 状态:未做(灰土,dashed border) |
| `--danger` `#a64545` | — | error(暗砖) |

### 1.3 字体栈

| 用途 | 字体 | 备注 |
|---|---|---|
| Display(标题 / 大字 / italic 强调) | **Newsreader**(可变 opsz 6-72,wght 300-700) | Google Fonts;比 Fraunces 温和、长文友好 |
| Display 中文 | **Source Han Serif SC**(思源宋体)优先 + Noto Serif SC 回退 | |
| Body sans | **Manrope**(wght 300-700) | 圆润、不工程感 |
| Body sans 中文 | Noto Sans SC | |
| Mono(chip / 数字 / 等宽数据) | **Geist Mono** | 现代温和,vs JetBrains Mono 更轻 |

字号 / 行高节奏:

| 元素 | 字号 | 行高 |
|---|---|---|
| body | 15.5px | 1.68 |
| 长文 serif(story body / DeepCard val) | 16px | 1.85-1.9 |
| 闪卡 body | 15.5px | 1.85 |
| 大标题 hero | clamp(52px, 7.6vw, 100px) | 0.98 |
| section title | 26px | 1.2 |
| layer card title | 24px | 1.22 |
| decision card title | 19px | 1.4 |
| mono / chip | 11.5-12px | — |

### 1.4 视觉 signature moments

| # | 元素 | 实现要点 |
|---|---|---|
| 1 | **Fingerprint**(hero 右侧 320×320 SVG) | 8 维放射 + 每维点数对应该维 lit/wip/todo 数量;数据从 snapshot 派生(每个 board 状态独一无二) |
| 2 | **非均匀栅格**(网格 8 层 layer-card) | `grid-template-columns: repeat(12, 1fr)` + 各 layer span 不同(7/5/4/4/4/6/6/12) |
| 3 | **大编号水印**(layer-card 右上) | Fraunces 86px,色 `--paper-2`(只比底色亮一点) |
| 4 | **Chip 上 confidence dots** | 4-5 颗 mono 小圆点直接画在 chip 里,无需 hover |
| 5 | **WIP 心跳** | `.chip.wip::after` 1.6s 脉冲圆点 |
| 6 | **左侧 nav rail** | 80px 竖排 5 视图入口,底部琥珀圆形 refresh 按钮(hover 旋转 180°) |
| 7 | **Story drop cap** | 56px italic Newsreader + amber,只第一段第一字符 |
| 8 | **Decision changelog** | 左 sticky 维度计数 + 右 timeline,dim tag amber / layer tag teal |
| 9 | **节点 radial glow**(鸟瞰) | `drop-shadow(0 0 6-8px {dim-color})`,只 lit 节点发光 |
| 10 | **Flashcard 3D flip** | `transform-style: preserve-3d` + 600ms cubic-bezier 翻牌;评分按钮像唱片机 |

mockup 已在 `dashboard/static/mockup-v2.html`(v3 版本)作 design source-of-truth。

---

## § 2 后端:`/refresh` 升级为 SSE 5-step pipeline(C 重档)

### 2.1 端点契约

```
POST /refresh
Accept: text/event-stream
```

响应 `text/event-stream`,每个 step 发 1-2 个 `step` event + 最终 1 个 `done` event。

```
event: step
data: {"step": "chip_resolve", "status": "running", "label": "扫代码判断 chip 状态"}

event: step
data: {"step": "chip_resolve", "status": "done", "label": "扫代码判断 chip 状态", "detail": "62 chip · 4 lit + 1 wip changed", "duration_ms": 412}

event: step
data: {"step": "seed_ingest", "status": "running", "label": "加载 DeepCard seed"}

event: step
data: {"step": "seed_ingest", "status": "done", "label": "加载 DeepCard seed", "detail": "35 cards · 32 insert / 3 skip(existing)", "duration_ms": 184}

event: step
data: {"step": "decision_extract", "status": "running", "label": "重抽 spec/plan/memory 决策"}

event: step
data: {"step": "decision_extract", "status": "done", "label": "重抽 spec/plan/memory 决策", "detail": "128 entries · +6 since last", "duration_ms": 1820}

event: step
data: {"step": "milvus_reindex", "status": "running", "label": "向量重建"}

event: step
data: {"step": "milvus_reindex", "status": "skip", "label": "向量重建", "detail": "OPENAI_API_KEY missing", "duration_ms": 8}

event: step
data: {"step": "snapshot_finalize", "status": "running", "label": "整合 snapshot"}

event: step
data: {"step": "snapshot_finalize", "status": "done", "label": "整合 snapshot", "detail": "refreshed_at 2026-05-14T18:42:11", "duration_ms": 56}

event: done
data: {"total_ms": 2480, "snapshot_refreshed_at": "2026-05-14T18:42:11", "steps_summary": {"done": 4, "skip": 1, "error": 0}}
```

### 2.2 5 个 step

| Step | 实现 | 依赖 | 可降级 |
|---|---|---|---|
| `chip_resolve` | `capability_resolver.resolve_status` 全量重跑 | 文件系统 | 否(失败则整体 fail) |
| `seed_ingest` | 提取 `seed_deep_cards.py` 核心逻辑为 `SeedIngestService`,读 `dashboard/data/deep_cards_seed.jsonl` **insert-if-missing**(已存在 cap_id 跳过,保护用户手动编辑)进 deep_cards 表;不动 flashcards 已 SRS 进度 | 文件系统 + sqlite | 否 |
| `decision_extract` | `decision_extractor.extract_all` 全量重跑 | 文件系统(spec/plan + memory 目录) | 否 |
| `milvus_reindex` | 调 `_build_embedder()` + `DeepCardMilvusClient.upsert`(等价当前 `post_admin_milvus_reindex`) | OPENAI_API_KEY + Milvus 服务 + 网络 | **是**(任一缺失 skip,不阻断) |
| `snapshot_finalize` | `SnapshotRepo.invalidate()` + 立即 `build_snapshot` 写新 row | sqlite | 否 |

### 2.3 降级矩阵(`milvus_reindex` 专属)

| 前置条件 | 表现 |
|---|---|
| `HARNESS_BOARD_MILVUS_HOST` 未设 | `status: skip, detail: "milvus disabled"` |
| `DASHSCOPE_API_KEY` / 对应 embedding key 缺失 | `status: skip, detail: "embedding key missing"` |
| `await client.ensure_collection()` 抛 `ConnectionError` | `status: skip, detail: "milvus unreachable"` |
| `embedder.embed()` 抛任何 exception | `status: skip, detail: "embedding error: {msg[:80]}"` |
| 正常 | `status: done, detail: "{n} cards upserted"` |

任何 skip 不阻断后续 step。`snapshot_finalize` 总是跑最后。

### 2.4 错误处理

- chip_resolve / seed_ingest / decision_extract / snapshot_finalize 任一抛异常:发 `event: step status=error detail={msg}` 然后发 `event: done steps_summary.error > 0`,前端面板 step 标红,不自动 reload
- 客户端断连(EventSource close):pipeline 继续跑完(不取消),只是无人监听

### 2.5 Lifespan idempotent seed ingest

新增 `dashboard/server.py` lifespan context manager(项目其他模块统一用 lifespan,不用 deprecated 的 `@app.on_event`):

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(_app: Starlette) -> AsyncIterator[None]:
    SeedIngestService(
        seed_path=PROJECT_ROOT / "dashboard" / "data" / "deep_cards_seed.jsonl",
        db_path=DB_PATH,
        config_dir=CONFIG_DIR,
    ).run_once_if_underfilled()
    yield

app = Starlette(routes=[...], lifespan=lifespan)
```

策略:

1. **触发条件**:db 中 DeepCards 数 < seed jsonl 总数(36 > 35 也跳过,只看是否"underfilled")
2. **写入语义** = **insert-if-missing**(不是 upsert):只对 db 不存在的 `cap_id` 插入;**已存在的 cap_id 一律跳过**,保护用户手动编辑
3. **副作用**:seed 文件 jsonl 内容更新后,db 已存在的 row 不会自动同步。若想同步:用户手动在 db 删除该 row 后再 refresh(简单可控,符合 portfolio 单用户场景)
4. **不删除**:任何情况下不 DELETE db row(避免 SRS flashcard 进度被波及)

### 2.6 服务抽取

新增 `dashboard/derive/refresh_pipeline.py`:

```python
@dataclass
class StepEvent:
    step: str
    status: Literal["running", "done", "skip", "error"]
    label: str
    detail: str = ""
    duration_ms: int = 0

class RefreshPipeline:
    def __init__(self, project_root: Path, config_dir: Path, db_path: Path): ...

    async def stream(self) -> AsyncIterator[StepEvent]:
        """yield 5 个 step × (running, done|skip|error) + 1 个 done event"""
```

抽 `seed_deep_cards.py` 的核心成 `dashboard/derive/seed_ingest.py:SeedIngestService`。CLI(`backend/app/scripts/seed_deep_cards.py`)退化为薄包装,默认走 insert-if-missing;新增 `--force` flag 走 upsert(向后兼容旧"强制重填"用途)。

`SeedIngestService` API:

```python
class SeedIngestService:
    def __init__(self, seed_path: Path, db_path: Path, config_dir: Path): ...

    def run_once_if_underfilled(self) -> SeedIngestResult:
        """db 中 card 数 < seed 总数时跑 insert-if-missing,否则 no-op。"""

    def run(self, *, force: bool = False) -> SeedIngestResult:
        """显式跑(refresh step 用)。force=True 时 upsert 覆盖现存 row。"""

@dataclass
class SeedIngestResult:
    total_seed: int       # jsonl 行数
    inserted: int         # 新插入
    skipped_existing: int # cap_id 已存在跳过
    skipped_invalid: int  # cap_id 不在 capabilities.yaml 跳过
    overwritten: int      # 仅 force=True 时 > 0
```

---

## § 3 前端:一键更新面板

### 3.1 入口位置

nav-rail 底部一个 38×38 琥珀圆形 refresh 按钮(mockup v3 已有位置)。常态:`color: var(--amber); border: 1px solid var(--amber-deep); background: transparent`;hover:背景变 `--amber` + `transform: rotate(180deg)` 200ms;active(面板展开中):无 hover transform,加 pulsing border。

### 3.2 面板形态

点击按钮 → 在按钮右侧 anchor 一个 **240×360px 浮层面板**,绝对定位,无 overlay backdrop(不阻断主页操作)。`role="dialog"`,ESC 关闭。

```
┌──────────────────────────┐
│  ⟳ 全量刷新                │ ← amber italic Newsreader 16px
│  ────────────             │
│                          │
│  ✓ 扫代码判断 chip 状态     │ ← amber √ + fg 字
│    62 chip · +4 lit       │ ← teal mono detail
│                          │
│  ✓ 加载 DeepCard seed     │
│    35 cards · 32 upsert    │
│                          │
│  ⟳ 重抽 spec/plan 决策   │ ← teal spinner + teal italic 字
│                          │
│  ○ 向量重建              │ ← fg-faint 字
│                          │
│  ○ 整合 snapshot         │
│                          │
│  ─────────────────       │
│  ⏱ 2.4s · 4 done · 1 skip│ ← mono 总览
└──────────────────────────┘
```

### 3.3 状态映射

| step.status | 图标 | 图标色 | 字色 | 说明 |
|---|---|---|---|---|
| (未开始) | `○` | `--fg-faint` | `--fg-faint` | 灰圈 |
| `running` | `⟳`(旋转) | `--teal` | `--teal` italic | 古铜青斜体 |
| `done` | `✓` | `--amber` | `--fg` | 琥珀√ + 主色字 |
| `skip` | `⊘` | `--wip` | `--wip` | 橙警示 |
| `error` | `✗` | `--danger` | `--danger` | 暗砖红 |

### 3.4 完成行为

- `event: done` 收到后:
  - 若 `steps_summary.error === 0`:面板 5 秒 fade-out → 自动 `location.reload()` 让主页拉新 snapshot
  - 若 `steps_summary.error > 0`:面板保留,顶部加一个 "✗ 部分失败 · 详情" 折叠 + retry 按钮(POST `/refresh` 再来一次)
- 客户端关闭面板(ESC / 点空白):面板隐藏但 EventSource 继续(不取消请求);下次打开按钮还能看到中途状态(从内存 buffer 恢复)

### 3.5 SSE 客户端实现

`dashboard/static/refresh-panel.js`(~150 行):
- 监听 nav-rail refresh 按钮 click
- 创建 `EventSource('/refresh')`
- 监听 `step` / `done` event → 更新面板 DOM
- 错误处理 / EventSource close 自动 cleanup
- 面板 HTML 由 `refresh-panel-template.html`(Jinja partial)渲染一个空骨架,JS 填内容

---

## § 4 鸟瞰修复 + 视觉增强

### 4.1 数据修复

§ 2.5 lifespan + § 2.2 seed_ingest step 双触发,保证 db ≥ 35 张 DeepCard。

### 4.2 视觉增强(在 mockup v3 基础上)

在 `dashboard/derive/graph_builder.py` + `dashboard/static/overview.js` 应用:

| 增强 | 实现 |
|---|---|
| 节点 hover tooltip | cytoscape `qtip` extension(已含)或自建小 div;内容:`{cap.name_cn} · conf {n}/5`(无 DeepCard 时:`{cap.name_cn} · 待填 DeepCard`)|
| 维度 cluster halo | 鸟瞰 SVG 不动(cytoscape 渲染),但 `node` style 加 `outline-color` 按维度色 + 半透;todo 节点(无 DeepCard)`background-opacity: 0.4` + `border-style: dashed`(已有) |
| 边按 confidence 加权 | `edge` style:两端 confidence 都 ≥ 4 时 `width: 1.2`,否则 `width: 0.6` + `opacity: 0.5` |
| 节点 glow(只 lit) | cytoscape 不原生支持 box-shadow,改用 `overlay-opacity` + `overlay-color` 模拟 |
| 维度过滤切换动画 | `cy.elements().style({display: 'none'})` 改为渐隐 200ms |

### 4.3 空状态兜底

`/api/overview/graph.json` 返回 nodes 数 < 5 时,前端 `overview.js` 仍渲染,但顶部加一个浮条:`💡 看上去 DeepCard 还很少 — [跑一次全量刷新?]`(按钮直接触发 § 3 面板)。

---

## § 5 全 UI 表面重写

### 5.1 模板改动清单

| 模板 | 改动 | 依据 |
|---|---|---|
| `base.html` | 加 Google Fonts link / nav-rail container / refresh-panel container / SVG grain overlay | mockup § hero |
| `_board_nav.html` | 顶部 nav → 左侧 nav-rail 竖排,5 视图 + 底部 refresh 按钮 | mockup nav-rail |
| `_hero.html` | 加 fingerprint SVG(数据从 snapshot 派生 — 8 维 lit/wip/todo 比例)+ Newsreader 大标题 + WIPs 区 | mockup hero |
| `_view_toggle.html` | D/B 切换 → underline tab(border-bottom amber) | mockup view toggle |
| `_d_view.html` / `_b_view.html` | layer-stack 12-col 非均匀栅格 + numeral 水印 | mockup grid |
| `_capability_chip.html` | chip + confidence dots + wip 心跳 + hover 浮起 | mockup chip |
| `_app_shell.html` | 底部 mini stat + Geist Mono | 保留逻辑,改样式 |
| `overview.html` | toolbar 改 pill + cytoscape style 升级 + 空状态浮条 | mockup overview |
| `overview_fallback.html` | 维度卡片墙改 nav-rail 风格 | 一致性 |
| `story.html` | filter 与 decision filter 形态统一 + serif body | mockup story |
| `_story_card.html` | drop cap + serial + three-cuts | mockup story-card |
| `flashcards.html` | deck + 进度 + 评分面板 | mockup flashcard |
| `_flashcard_review.html` | 3D flip 卡 + 唱片机评分 | mockup flashcard |
| `flashcards_stats.html` | 圆环进度 + 时间线 + 维度散点(新增视觉) | spec § 5.3 |
| `decisions.html` | 左 sticky filter + 右 timeline | mockup decisions |
| `_decision_card.html` | commit hash + 三段 + tag 双色(dim amber / layer teal) | mockup |
| `_decision_filter.html` | filter list + count | mockup decisions-side |
| `_decision_note_form.html` | 抽屉式 + textarea Source Han Serif + submit toast | new |
| `_deep_card_modal.html` | dc-head + dc-body 2-col + 双强调 + ESC 关闭 + fade-scale 进入 | mockup deep-card |
| `_deep_card_field.html` | inline edit field + AI draft 按钮 loading + textarea Source Han Serif | new |
| `_edit_select.html` | custom dropdown(替代原生 select) | new |

### 5.2 全局组件(新增 / 统一)

| 组件 | 文件 | 用途 |
|---|---|---|
| Toast 系统 | `dashboard/static/toast.js` + 含 in base.html | 全局右下,3 类(success amber / info teal / warn wip / error danger);API:`Toast.show({type, msg, ttl})` |
| Loading skeleton | CSS class `.skeleton` | teal 半透 placeholder,replace 转圈 |
| Empty state | CSS class `.empty-state` | 暖琥珀图标 + 引导文案 + CTA |
| Error state | CSS class `.error-state` | wip 橙警示 + retry + 详情折叠 |
| Modal overlay | `modal.js` + CSS | fade backdrop + scale entry + ESC 关闭 + click-outside 关 |
| 微动画 | CSS-only `transition / animation` | hover 浮起 / page transition / 数字滚动 |

### 5.3 `flashcards_stats.html` 视觉规范(新增页面)

| 区块 | 视觉 |
|---|---|
| 顶部圆环进度 | SVG circle,周长 = 总卡数,filled 弧 = lit 数;中心 Newsreader 大数字 + "/ 35" |
| 时间线 | 横向时间轴,每个 review 一个小圆点(色 = grade 0-5 渐变 wip→lit) |
| 维度散点图 | 8 维 × confidence 0-5 散点,dim 颜色编码 |
| 数字总览 | Geist Mono 大字:总卡 / 今日 / 平均 conf / 连续天数 |

### 5.4 CSS 文件结构

`dashboard/static/style.css` 重写为:

```
:root         { 全部 token (颜色/字体/字号节奏) }
@font-face    { 不引(走 Google Fonts CDN) }
html, body    { 全局 baseline + 噪点 overlay }

/* Sections */
.nav-rail     { ... }
.hero         { ... }
.fingerprint  { ... }
.section-marker { ... }
.layer-stack  { ... }
.layer        { ... }
.chip         { ... }
.overview-*   { ... }
.story-*      { ... }
.flashcard*   { ... }
.decision*    { ... }
.deep-card    { ... }
.refresh-panel{ ... }
.toast        { ... }
.skeleton     { ... }
.empty-state  { ... }
.error-state  { ... }

/* Reveal animations */
@keyframes rise   {}
@keyframes blink  {}
@keyframes spin   {}
.reveal       { 类似 mockup,d1-d4 分级 stagger }
```

预计 1200-1500 行,从当前 879 行扩(新增组件 / 状态)。

---

## § 6 测试矩阵

| Layer | 测什么 | 文件 |
|---|---|---|
| L0 单元 | `RefreshPipeline._chip_resolve_step` / `_seed_ingest_step` 等 5 个独立函数:正常 / 异常 / skip 各路径 | `dashboard/tests/unit/test_refresh_pipeline.py` |
| L0 单元 | `SeedIngestService.run_once_if_underfilled()`:db 中 DeepCards 数 < seed 总数时跑 / ≥ 总数时跳过 / 跑后增量 upsert 不覆盖已编辑 row | `dashboard/tests/unit/test_seed_ingest.py` |
| L0 单元 | `graph_builder.build_graph_payload` confidence 加权 edge | 已有 + 新 case |
| L1 集成 | SSE endpoint:返回 ≥ 11 个 event(5×(running+done) + 1 done);Milvus 不可达时第 4 个 step 是 skip 且后续 step 仍 done | `dashboard/tests/integration/test_refresh_sse.py` |
| L1 集成 | Lifespan startup:db underfilled(card 数 < seed 数) → ingest;db 已满 → 跳过;增量场景 — 手动编辑过的 row 不被覆盖 | `dashboard/tests/integration/test_lifespan_seed.py` |
| L2 e2e | seed 加载后 `GET /api/overview/graph.json` 返回 ≥ 35 nodes + ≥ 10 edges | `dashboard/tests/integration/test_overview_after_seed.py` |
| L2 e2e(可选) | Playwright:打开 `/`,点 refresh 按钮,看到 5 个 step 完成,自动 reload,鸟瞰 ≥ 35 节点 | `dashboard/tests/e2e/test_refresh_flow.py`(标 `@pytest.mark.e2e`,默认 skip,CI nightly 跑) |
| 视觉 | mockup-v2.html 作 design reference,不做 pixel diff(过度) | — |

### 6.1 ChatGPT-only failure mode 守护

- `OPENAI_API_KEY` env 在 test 中 unset,SSE 必须 skip milvus_reindex 而不挂
- `HARNESS_BOARD_MILVUS_HOST` 在 test 中 unset,同上
- 测试用 fixture monkeypatch 这两个 env

---

## § 7 实施顺序与版本号

### 7.1 版本号 / 分支

- 分支:`feat/harness-board-v2-polish`
- 版本归位:**v0.9.6 harness-board polish**
- PR 题:`feat(harness-board): V2 polish — UI 重写 + 鸟瞰修复 + 一键 SSE 全量更新`

### 7.2 实施分 Plan(预计 3 plan)

| Plan | 范围 | 工期(Claude Code wall time) |
|---|---|---|
| **Plan 1 · 后端 pipeline + 数据修复** | RefreshPipeline / SeedIngestService / lifespan / SSE endpoint / 降级矩阵 + L0/L1 测试 | ~1 天 |
| **Plan 2 · 前端样式重写** | style.css 重写 + 13 模板 + Quiet Workshop 设计语言 + fingerprint SVG + 全组件(toast/skeleton/empty/error/modal) | ~2-3 天 |
| **Plan 3 · 鸟瞰增强 + flashcards stats + refresh 面板 + 收尾** | overview.js cytoscape style 升级 + tooltip + edge 加权 + flashcards_stats 新页 + refresh-panel.js + L2 e2e + dogfood | ~1-1.5 天 |

总:~4-5 天 wall time。

### 7.3 Plan 间 dep

- Plan 1 必须先 ship(Plan 2 / 3 测试 refresh 流要依赖 SSE endpoint)
- Plan 2 / 3 可并行起 worktree,Plan 3 的 refresh-panel.js 复用 Plan 2 的 Quiet Workshop token

---

## § 8 验收标准(ship gate)

1. **鸟瞰**:打开 `/overview`,渲染 ≥ 35 节点 + ≥ 10 edges,memory 维度成簇发光,有 hover tooltip,无 `console.error`
2. **一键更新**:
   - 主页 nav-rail 底部有琥珀 refresh 按钮
   - 点击展开 240×360 面板,5 个 step 逐行更新,无 milvus 时第 4 个 skip 后第 5 个仍 done
   - 完成后面板 fade + 自动 reload,主页数据反映新 snapshot
3. **视觉**:
   - 全 5 视图(网格 / 鸟瞰 / 故事 / 闪卡 / 决策)+ DeepCard modal + flashcards_stats + 所有 form / filter 都跟 mockup v3 视觉一致
   - Newsreader / Source Han Serif / Manrope / Geist Mono 字体加载成功
   - 双强调(琥珀主 / 古铜青次)正确应用,确认 mockup 列出的 12 处用色位点
   - 空状态 / loading / error / toast / modal fade 都至少各被用到 1 次(dogfood verify)
4. **测试**:L0 + L1 全绿,L2 鸟瞰 e2e 绿;Playwright e2e 可选 skip
5. **降级**:本地 unset 两个 env 跑 `/refresh`,5 step 全部跑完(4 done + 1 skip),前端面板不挂

---

## § 9 Spec Self-Review

### 9.1 Placeholder scan
- [x] 无 TBD / TODO
- [x] 所有 step / 模板 / 测试都列出具体文件名

### 9.2 Internal consistency
- [x] § 2.3 降级 vs § 3.3 状态映射 vs § 6 测试 三方对齐(skip 路径)
- [x] § 1 设计 token vs § 5 CSS 文件结构 一致
- [x] § 0 范围 vs § 8 验收标准 一致

### 9.3 Scope check
- 3 个 plan,各 ~1-3 天;总 ~4-5 天 wall time,符合一个 spec 的合理 scope

### 9.4 Ambiguity check
- "全量"在 § 2 上下文中明确 = 5 step,不是字面"清空 db";已显式写出
- "降级"在 § 2.3 列出 5 种 milvus skip 触发条件,无歧义
- "rebuild snapshot" vs "invalidate snapshot":§ 2.2 snapshot_finalize 步骤明确两步(invalidate + 立即 build),不是只 invalidate

---

## § 10 Out of scope(YAGNI 显式)

- Milvus 配置 UI(env var 配)
- 进度面板支持取消/暂停
- 多用户 / 历史 refresh 记录
- 后端 API schema 改造(只动 UI 层 + `/refresh` 实现,接口契约稳定)
- mockup-v2.html 删除(留作 design reference)
- DeepCard 内容 LLM auto-fill 流程(已有 ai_draft endpoint,样式美化即可,逻辑不动)
- Cytoscape 替换为其他图库(继续用 cytoscape + cose-bilkent)

---

## § 11 Memory cross-references

实施 ship 后落:

- `harness-board-v2-polish-done` — 总卡,记录 3 plan ship + 关键决策 anchor
- 若 SSE 流式 pattern 抽出可复用 service:留 reference 给 future use case(monitoring engine 已有 Celery 异步,本 SSE 走 in-process)

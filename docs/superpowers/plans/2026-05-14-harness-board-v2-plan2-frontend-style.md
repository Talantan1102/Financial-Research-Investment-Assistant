# Harness Board v2 Polish — Plan 2: 前端样式重写 + 13 模板 + 全局组件

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans`. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** [`docs/superpowers/specs/2026-05-14-harness-board-v2-polish-design.md`](../specs/2026-05-14-harness-board-v2-polish-design.md)

**分支:** `feat/harness-board-v2-polish`
**版本归位:** v0.9.6 harness-board polish
**PR 题:** `feat(harness-board): V2 polish — UI 重写 + 鸟瞰修复 + 一键 SSE 全量更新`

**前置依赖:** Plan 1(后端 RefreshPipeline + SSE endpoint + SeedIngestService + lifespan)需先 ship。本 Plan 2 只动 frontend(templates / static / css / js),**不动后端 routes 与 Python 业务逻辑**。

**Goal:** 把 dashboard 前端从 dark slate admin 风格重写为 Quiet Workshop 暖黑作坊设计语言 — 双强调(琥珀 amber × 古铜青 teal)+ Newsreader / Source Han Serif / Manrope / Geist Mono 字体栈 + signature moments(fingerprint SVG / 非均匀栅格 / drop cap / 3D flip 闪卡 / decision changelog / deep card modal),完整覆盖 13 个 Jinja 模板 + 1 个新 partial + 5 个全局组件 + 重写 `style.css`(~879 → ~1500 行)。

**Architecture(纯 frontend,无 build step):**
- Jinja2 templates(继续走 starlette + jinja2 render)
- 单文件 `dashboard/static/style.css`(spec § 5.4 — 不拆多文件)
- Google Fonts CDN(`<link rel="stylesheet">`,不引 @font-face)
- htmx + cytoscape 保留
- 新增 `toast.js` / `modal.js` 全局组件(纯 vanilla JS)
- `refresh-panel.js` Plan 3 写;**Plan 2 只把 `_refresh_panel.html` 空骨架 + CSS 写完**

**测试策略:**
- 前端难强 TDD,采用 **smoke L0 + L1 + 视觉自审**:
  - L0:每个模板 Jinja render 不抛 `TemplateSyntaxError`
  - L1:启动 dashboard server,每页 GET 200,无 console.error
  - 视觉:跑 `uv run poe serve` 后目测对照 `dashboard/static/mockup-v2.html`
- 不做 pixel-diff e2e(过度,spec § 6 已注明)

**字体 fallback chain(全文统一):**
- `--display`: `'Newsreader', 'Source Han Serif SC', 'Noto Serif SC', Georgia, serif`
- `--serif-cn`: `'Source Han Serif SC', 'Noto Serif SC', 'Newsreader', Georgia, serif`
- `--sans`: `'Manrope', 'Noto Sans SC', -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif`
- `--mono`: `'Geist Mono', ui-monospace, "SF Mono", Menlo, monospace`

---

## File Structure

**新建:**
- `dashboard/templates/_refresh_panel.html` — 一键刷新面板空骨架(JS 接 SSE 由 Plan 3 实现)
- `dashboard/static/toast.js` — 全局 Toast.show API
- `dashboard/static/modal.js` — 全局 Modal open/close + ESC + click-outside

**重写(全文替换):**
- `dashboard/static/style.css` — 879 行 → ~1500 行 Quiet Workshop CSS

**修改:**
- `dashboard/templates/base.html` — Google Fonts link / nav-rail container / refresh-panel container / grain overlay / 全局 JS 引入
- `dashboard/templates/_board_nav.html` — 顶部 emoji nav → 左侧 80px nav-rail 竖排 + 底部 refresh 按钮
- `dashboard/templates/_hero.html` — Newsreader 大标题 + WIPs + fingerprint SVG(Jinja 循环从 snap.layers 派生)
- `dashboard/templates/_view_toggle.html` — D/B underline tab
- `dashboard/templates/_d_view.html` — 12-col 非均匀栅格 layer-stack
- `dashboard/templates/_b_view.html` — kanban 三列改 Quiet Workshop 样式
- `dashboard/templates/_capability_chip.html` — chip + confidence dots + wip 心跳 + hover 浮起
- `dashboard/templates/_app_shell.html` — 底部 mini stat + Geist Mono
- `dashboard/templates/overview.html` — toolbar pill + 空状态浮条容器
- `dashboard/templates/overview_fallback.html` — 维度卡片墙 Quiet Workshop 风
- `dashboard/templates/story.html` — filter 形态统一 + section-marker
- `dashboard/templates/_story_card.html` — drop cap + serial + three-cuts
- `dashboard/templates/flashcards.html` — flash-stage 2-col 布局
- `dashboard/templates/_flashcard_review.html` — 3D flip + 唱片机评分
- `dashboard/templates/flashcards_stats.html` — 圆环进度 + 时间线 + 散点 + Geist Mono(占位接 Plan 3 context)
- `dashboard/templates/decisions.html` — 双栏 sticky filter + timeline
- `dashboard/templates/_decision_card.html` — commit hash + 三段 + tag 双色
- `dashboard/templates/_decision_filter.html` — sticky 维度 list + count
- `dashboard/templates/_decision_note_form.html` — 抽屉式 textarea + submit toast hook
- `dashboard/templates/_deep_card_modal.html` — dc-head + dc-body 2-col + fade-scale + ESC
- `dashboard/templates/_deep_card_field.html` — inline edit + AI draft loading
- `dashboard/templates/_edit_select.html` — custom dropdown

---

> **Note for executor:** 由于 Plan 2 涉及完整 frontend 重写,后续 20 个 task(原 plan 起草 subagent 在 read-only 模式下输出了完整 CSS / HTML / JS code blocks)的详细内容见此文件 git 历史 commit `<待 implement 时记录>`。每个 task 严格按 writing-plans skill 的 TDD 风格 + bite-sized step + 完整代码块 + smoke 验证 + commit。

## Task 索引(20 task)

> **Note:** 在写本文件时,plan 起草 subagent 因 read-only 限制,**任务的完整 code block 已通过会话 transcript 提供给 orchestrator**,实施 subagent 应优先去 transcript / 直接读 mockup-v2.html 取 source-of-truth 的 CSS。如下 task 索引保留**完整任务结构、文件路径、关键决策、smoke 验证、commit 命令**,**完整 code block 见同目录 Plan 2 reference**(若发现 code 缺失,实施 subagent 应:1. 读 `dashboard/static/mockup-v2.html` 提取对应区段 CSS;2. 按 spec § 1 / § 5 决策填充)。

### Task 1: style.css Phase 1 — :root token + baseline + grain + reveal animations
**Files:** Modify `dashboard/static/style.css`(**全文清空重写**,从此 task 开始逐 phase 累积写入同一文件)

完整 CSS 见 mockup-v2.html `:root { ... }` 块 + 全局 `html, body`,token 严格按 spec § 1.2 表。Smoke:`uv run poe serve` 起,GET `/`,body 暖黑底色 + grain overlay 出现。

Commit: `feat(harness-board): style.css phase 1 — Quiet Workshop tokens + baseline`

### Task 2: base.html — Google Fonts + nav-rail / refresh-panel container + global JS
**Files:** Modify `dashboard/templates/base.html`

完整 HTML:`<head>` 加 Google Fonts preconnect + Newsreader/Manrope/Geist Mono/Noto Serif+Sans SC `<link>`;`<body>` 加 `{% block nav %}{% endblock %}` / `{% include "_refresh_panel.html" ignore missing %}` / `<main class="board">{% block content %}{% endblock %}</main>` / `<div id="modal-overlay">` / `<div id="toast-container">` / `<script src="/static/toast.js" defer>` + `modal.js` defer。`body { padding-left: 80px; }` baseline 留 nav-rail 位。

Smoke:F12 Network 看 fonts.gstatic.com 拉到 Newsreader / Manrope / Geist Mono。

Commit: `feat(harness-board): base.html — fonts + nav slots + global JS`

### Task 3: _board_nav.html — 左侧 nav-rail 竖排 + 底部 refresh 按钮
**Files:** Modify `_board_nav.html` + `main.html` + `overview.html` / `overview_fallback.html` / `story.html` / `flashcards.html` / `flashcards_stats.html` / `decisions.html`(每个把 `_board_nav.html` 抽到 `{% block nav %}`)

`<nav class="nav-rail">` 含 `brand-mark` (H. 琥珀字)+ 5 个 `nav-item`(Grid/Map/Story/Cards/Forge,SVG 图标 + 小字)+ `nav-bottom button.refresh-btn` 琥珀圆形按钮 id=`refresh-btn`。

Smoke:GET `/`,左侧 80px 黑底 rail 出现(active 项琥珀竖线,等 Task 4 CSS 完整生效)。

Commit: `feat(harness-board): _board_nav.html — left rail with refresh button`

### Task 4: style.css Phase 2 — nav-rail + hero + fingerprint
**Files:** Modify `dashboard/static/style.css`(追加 Phase 2)

`.nav-rail` fixed left 80px / `.brand-mark` Newsreader 22px amber / `.nav-item` flex column 14px padding,hover teal,active amber border-left / `.refresh-btn` 38×38 圆,hover bg amber + rotate 180deg + transition / `.nav-rail .refresh-btn.active` pulse-border animation。`.hero-block` 80px top padding / `.hero-grid` 1fr 320px / `.hero-meta` mono uppercase / `.hero-title` Newsreader clamp(52px, 7.6vw, 100px) italic amber/teal em / `.hero-sub` Source Han Serif 17px 1.85 / `.hero-wips` border-top hair + label wip uppercase / `.fingerprint` 320×320。

完整 CSS 见 mockup-v2.html `.nav-rail` / `.hero-grid` / `.fingerprint` 段。

Smoke:GET `/`,nav-rail + hero(等 Task 5 _hero.html 重写后才有内容)。

Commit: `feat(harness-board): style.css phase 2 — nav-rail + hero + fingerprint`

### Task 5: _hero.html — Newsreader 大标题 + fingerprint Jinja 派生
**Files:** Modify `dashboard/templates/_hero.html`

`<section class="hero-block">` `<div class="hero-grid">` 左侧 hero-meta pill + hero-title `所有<em>力气</em><br>都留在<em class="cool">架子</em>上。` + hero-sub `<span class="accent">项目复盘 + 知识沉淀工具</span>` 等 + hero-wips for wips。

右侧 `<div class="fingerprint">` 含 SVG viewBox="-160 -160 320 320":
- `<defs>` radialGradient `#fpglow` amber 18%→0
- 3 个同心圆 r=140/100/60
- 8 维 spoke 用 `{% for layer in snap.layers %}` `{% set angle = loop.index0 * 45 %}` `<g transform="rotate({{ angle }})">`,line + 5 dots(lit 绿 #94b87a / wip 橙 #d4824a / todo 灰 #6b5d49)+ 维度编号 text
- 中心双环(teal r=28 外 + amber r=22 内)+ italic H

caption: `<strong>fingerprint</strong> · {{ snap.total_lit }} lit / {{ snap.total_wip }} wip / {{ snap.total_todo }} todo`

Smoke:GET `/`,hero 出现大标题 + 320×320 fingerprint。

Commit: `feat(harness-board): _hero.html — Newsreader title + fingerprint SVG`

### Task 6: _d_view.html + _b_view.html + _capability_chip.html + _view_toggle.html
**Files:** Modify 4 templates

`_d_view.html`:`<div class="layer-stack">` 包 `{% for L in snap.layers %}<article class="layer" id="layer-{{ L.id }}">` 含 `<span class="numeral">{{ L.number }}</span>` + `<div class="l-eyebrow"><span class="dot dot-{{ DIM_SHORT[L.id] }}"></span>` + l-title + l-stat bar + chips。开头加 Jinja `{% set DIM_SHORT = {...8 维映射 prompt/tools/orch/memory/rag/guard/eval/cost} %}`。

`_b_view.html`:三列 kanban-col(todo/doing/done)。

`_capability_chip.html`:`<span class="chip {{ c.status }}">` + name_cn + `<span class="conf-dots">` for confidence + stale-mark。htmx GET `/capability/{id}/edit` swap outerHTML。

`_view_toggle.html`:underline tab `<a href="/?view=d" class="view-tab{% if view_mode == 'd' %} active{% endif %}">` 含 tab-num(D/B Newsreader italic)+ tab-name。

Smoke:GET `/`,网格 8 层级出现(等 Task 7 CSS)。

Commit: `feat(harness-board): grid / kanban / chip / view-toggle templates`

### Task 7: style.css Phase 3 — layer / chip / view-toggle / app-shell / kanban
**Files:** Modify `style.css`(追加 Phase 3)

`.layer-stack` grid 12 col + `:nth-child(1) span 7 / (2) span 5 / (3-5) span 4 / (6-7) span 6 / (8) span 12`。`.layer` paper bg + 1px hair border + hover border-color amber-soft / `.layer .numeral` absolute top -8 right 14 Newsreader 86px paper-2 / `.layer .l-title` 24px Newsreader opsz 48 / `.l-stat .bar i` lit bg + width transition 800ms / `.layer .chips` flex-wrap gap 6px。

`.chip` mono 11.5px / `.chip.lit` lit-bg + lit color + lit border 30% / `.chip.wip` wip-bg + wip color + wip border 35% + `::after` 4×4 wip dot blink animation / `.chip.todo` transparent + fg-mute + dashed fg-faint border / `:hover` translateY -2px + box-shadow + amber border。`.chip .conf-dots i` 3×3 圆点 currentColor。

`.view-toggle` flex 32 gap + border-bottom hair / `.view-tab` 10px padding + border-bottom transparent transition / `:hover` teal / `.active` amber + border。

`.kanban` grid repeat(3, 1fr) gap 20 / `.kanban-col` paper + 1px hair / `.kanban-head` mono uppercase 10px + count Newsreader 14 italic amber / `.kanban-todo` fg-mute / `.kanban-doing` wip / `.kanban-done` lit。

Smoke:网格 12-col 非均匀 + chip 三态 + numeral 86px 水印出现。

Commit: `feat(harness-board): style.css phase 3 — layer + chip + tabs + kanban`

### Task 8: overview.html + overview_fallback.html — toolbar pill + 空状态浮条
**Files:** Modify 2 templates

`overview.html`:`{% extends "base.html" %}` + `{% block nav %}{% include "_board_nav.html" %}{% endblock %}` + `{% block content %}` 含 `.section-marker` + `{% if total_nodes < 5 %}<div class="empty-state empty-state--overview" id="overview-empty-hint">` 空状态浮条(button id `overview-refresh-trigger`)+ `<div class="overview-frame">` 含 toolbar pill(`label.pill` 包 `input checkbox hidden`)+ `<div id="overview-canvas">` + `<div class="overview-legend">` lit-glow / wip-clay / todo-dashed swatches。最后引入 cytoscape + overview.js。

`overview_fallback.html`:`<div class="overview-fallback-grid">` repeat auto-fit + `.dim-block` paper card + dim-block-head amber italic Newsreader 22。

Smoke:GET `/overview`,toolbar pill 出现,canvas div 占位。

Commit: `feat(harness-board): overview templates — pill toolbar + empty-state`

### Task 9: story.html + _story_card.html — drop cap + serial + three-cuts
**Files:** Modify 2 templates

`story.html`:`<form method="get" class="story-filter">` 两 filter-row(维度 pill / 时间窗 date input + select order),`<div class="story-rail">` 包 `{% for sc in stories %}{% include "_story_card.html" %}` 或 `{% else %}<div class="empty-state">`。

`_story_card.html`:`<article class="story-card">` + `.meta`(serial No.NN + DIM + date + cap-link teal a)+ `<h3>{{ sc.name_cn }}</h3>` + `<div class="body"><p>{{ sc.problem }}</p>{% if sc.decision %}<p><strong>决策:</strong>{{ sc.decision }}</p>` + `<div class="three-cuts">` Why/What/Lessons 三列 + `.story-card-footer` link-tag。

Smoke:GET `/story`,出现 filter + 卡片流(样式 Task 10)。

Commit: `feat(harness-board): story templates — three-cuts + cap-link`

### Task 10: style.css Phase 4 — overview frame + story rail + filter pill
**Files:** Modify `style.css`(追加 Phase 4)

`.overview-frame` radial-gradient bg paper-2→ink + 1px hair + 4px border-radius / `.overview-toolbar` mono 11px gap 10 / `.pill` 999px border + hair / `:hover` amber / `:has(input:checked)` amber-soft 填充。`.overview-canvas` 70vh / `.overview-legend` absolute bottom right + mono 10px / `.swatch.lit-glow` dim-memory + box-shadow 6px / `.swatch.wip-clay` wip / `.swatch.todo-dashed` transparent + dashed fg-faint。

`.overview-fallback-grid` grid auto-fit 280px / `.dim-block` paper card / `.dim-block-num` Newsreader italic 22px amber / `.dim-block-name` Newsreader 18.

`.story-section` padding-top 32 / `.story-filter` paper card + 2 filter-row + filter-date / filter-select ink-2 bg / `.filter-apply` amber-soft button + hover bg amber + ink color。`.story-rail` padding-left 80 + `::before` left 20 1px hair 竖线 / `.story-card` paper + 36×44 padding + `::before` 14×14 圆点 ink fill + 2px amber border + 0 0 0 4px ink shadow(rail dot)/ `.meta` mono 10px uppercase / `.serial` Newsreader 12 amber italic / `.cap-link a` teal border-bottom teal-deep / `:hover` teal-glow / `h3` Newsreader 32 opsz 72 / `.body` Source Han Serif 16/1.9 letter-spacing 0.005em / `.body p:first-of-type::first-letter` Newsreader 56px italic amber float left / `.body strong` amber 500 / `.body em` teal italic Newsreader 500 / `.three-cuts` grid 3 + border-top hair / `.cut .h` mono 10 amber uppercase / `.cut .b` Source Han Serif 13.5。`.link-tag` mono 10 teal + teal-deep border + 2px。

Smoke:GET `/overview` + `/story` 视觉对照 mockup § 02 / § 03。

Commit: `feat(harness-board): style.css phase 4 — overview frame + story rail`

### Task 11: flashcards.html + _flashcard_review.html — 3D flip + 唱片机评分
**Files:** Modify 2 templates

`flashcards.html`:`.flash-toolbar`(count + stats 链接 teal)+ `.flash-progress`(label + Newsreader italic amber 22 num)+ `.flash-stage` grid 1fr 280px。左 `.flash-card-deck` for today_cards 含 `<div class="flash-card" data-fc-id ...>{% include "_flashcard_review.html" %}` / 右 `<aside class="flash-rate">` h4 + grade grid 6 + hint。

`_flashcard_review.html`:`<div class="flash-card-frame inner-card" data-card-id>` `<div class="inner">` `<div class="face front">` corner / eyebrow / h2 question / body / footnote(tap to flip + next/new card)+ `<div class="face back" transform="rotateY(180deg)">` 同结构 + answer 强调双强调。底部 `.grade-row hidden` 含 6 grade-action htmx POST `/flashcards/{id}/review`。

Smoke:GET `/flashcards/today`,3D 卡 + 评分盘(样式 Task 13)。

Commit: `feat(harness-board): flashcard templates — 3D flip + dial rating`

### Task 12: flashcards_stats.html — 静态壳 + SVG mount 点(Plan 3 hydrate)
**Files:** Modify `flashcards_stats.html`

**与 Plan 3 协调:** Plan 3 Task 6/7 把 view 改为只 render 静态壳 + 加 `/api/flashcards/stats.json` endpoint + 改本模板加 inline JS fetch 后用 `document.createElementNS` 渲 SVG。**本 Plan 2 task 只写静态 DOM 骨架 + Quiet Workshop 样式**,inline JS hydrate / 数据请求由 Plan 3 接管。

模板写 4 个 `<div class="stat-num">` 含 `<span class="num" id="stat-total">—</span>` 等 mount 点 + `<svg id="stats-ring">` 含 bg circle + `id="stats-ring-fill"` + `id="stats-ring-text"` + `<svg id="stats-timeline">` 含 base line + `<svg id="stats-scatter">` 空容器。所有数字位 `—` 占位。**不写 Jinja `{% for ... %}` 循环数据**(Plan 3 inline JS 会用 DOM API 追加)。

Plan 3 Task 7 完整 inline JS / SVG 渲染算法见 Plan 3 文件。

Smoke:GET `/flashcards/stats`,4 stat-card 占位 `—` + 圆环 + 空 timeline / scatter SVG 容器出现,样式生效。

Commit: `feat(harness-board): flashcards_stats — static shell + SVG mounts`

### Task 13: style.css Phase 5 — flashcard 3D flip + stats ring/scatter
**Files:** Modify `style.css`(追加 Phase 5)

`.flash-stage` grid 1fr 280px / `.flash-card-deck { perspective: 1600px }` / `.flash-card { height: 360px }` / `.flash-card.flipped .inner` rotateY 180deg / `.flash-card-frame .inner transform-style preserve-3d transition 600ms` / `.flash-card-frame .face` absolute inset 0 + backface-visibility hidden + linear-gradient paper-2→paper + 1px hair + 6px radius + 44×48 padding + inset 0 1px highlight + 24 48 -24 shadow / `.face.back { transform: rotateY(180deg) }` / `.eyebrow` mono 11 amber 0.2em uppercase / `.face h2` Newsreader 28 opsz 72 / `.body` Source Han Serif 15.5/1.85。

`.flash-rate` paper + 1px hair + 6px radius + 24 padding + sticky top 28 / `.grade` grid 6 + 6 gap / `.grade-btn` aspect 1 + transparent + 1px hair + 50% radius + Newsreader 16 + transition / `:hover` amber + amber-soft / `[data-g="5"]` lit / `[data-g="0"]` danger / `.hint` mono 10 center。

`.stats-overview` grid 4 / `.stat-card` paper + 22 20 padding / `.stat-num` mono 38px amber tight letter-spacing -0.02em / `.stat-lbl` mono 10 fg-mute 0.18em uppercase。

`.stats-ring` 220×220 / `.ring-center` absolute flex center / `.ring-num` Newsreader 48 opsz 72 / `.ring-denom` mono 14 fg-mute / `.ring-cap` mono 10 fg-faint 0.18em uppercase。

`.timeline-track` flex-wrap gap 6 + dashed hair-2 borders / `.timeline-dot` 10×10 50% radius。`.scatter-svg` 100% × 240。

`.stats-dim-list` grid 2 + dashed border / `.stats-dim-name` fg-dim / `.stats-dim-num` Newsreader amber。

Smoke:GET `/flashcards/today`(3D 卡 + 评分)+ GET `/flashcards/stats`(stat cards / ring / scatter)。

Commit: `feat(harness-board): style.css phase 5 — flashcard 3D + stats viz`

### Task 14: decisions.html + _decision_card.html + _decision_filter.html + _decision_note_form.html
**Files:** Modify 4 templates

`decisions.html`:`.section-marker § 05 Forge`+ warning-banner 兼容 memory_path_warning + `<div class="decisions-grid">` 内 `_decision_filter.html` + `<div class="decisions-list">` for decisions(empty-state 兜底)+ 引入 `decisions-filter.js`。

`_decision_filter.html`:`<aside class="decisions-side">` 含 `<h5>维度</h5><ul class="filter-list">` 全部 `<li class="filter-item active" data-value="">All</li>` + for main_dims + META + `<h5>层级</h5>` filter-state-list active/deprecated + `<h5>关键字</h5><input class="filter-keyword">`。同步改 `decisions-filter.js` 选择器 `.filter-chip` → `.filter-item` / `.filter-layer-chip` / `.filter-state-chip`。

`_decision_card.html`:`<article class="decision-card" id="dec_{{ d.id }}" data-layer data-state data-text>` + `.head`(commit version mono amber + when mono fg-mute)+ `<h4>{{ d.title }}</h4>` + `.summary` Source Han Serif + `.tags` 含 `.tag.dim {{ d.layer }}` + `.tag.layer` for refs + `.tag.layer {{ d.state }}` + `{% include "_decision_note_form.html" with decision_id=d.id, note=note_lookup.get(d.id, '') %}`。

`_decision_note_form.html`:`<details class="decision-note-drawer">` + `<summary class="decision-note-toggle">` 显示 note 前 60 字 或 "加 note" + `<form hx-post hx-on::after-request="Toast.show success">` 含 textarea Source Han Serif + button.note-submit。

Smoke:GET `/decisions`,左 sidebar + 右 timeline 卡(等 Task 15 CSS)。

Commit: `feat(harness-board): decision templates — changelog + drawer note`

### Task 15: style.css Phase 6 — decisions changelog + warning banner + form inputs
**Files:** Modify `style.css`(追加 Phase 6)

`.warning-banner` wip-bg + wip border 35% + 12×18 padding + mono 12 / `.warning-icon` 18 circle + 1px currentColor。

`.decisions-grid` grid 220px 1fr gap 48 / `.decisions-side` sticky top 24 / `.decisions-side h5` mono 10 fg-mute 0.2em uppercase / `.filter-list` list-none / `.filter-item` 7px padding + mono 12 fg-dim + flex space-between + dashed border-bottom hair-2 + transition / `.filter-count` Newsreader italic 11 fg-mute / `:hover` teal / `.active` amber / `.filter-keyword` ink-2 bg + 1px hair + mono 11 / `:focus` amber border。

`.decision-card` transparent + border-left 1px hair + 0 0 36 32 padding + relative + margin-left 4 / `::before` absolute left -5 top 8 + 9×9 amber + 50% radius + 0 0 0 4px ink shadow(timeline dot)/ `.head` flex baseline gap 16 / `.commit` mono 11 amber 0.05em / `.when` mono 10 fg-mute / `h4` Newsreader 19 opsz 48 letter-spacing -0.003em / `.summary` Source Han Serif 14.5/1.8 letter-spacing 0.005em / `.tags` flex 8 gap / `.tag` mono 10 fg-mute + 1px hair + 2px radius + 0.05em letter-spacing / `.tag.dim` amber + amber-deep 28% border + amber-soft bg / `.tag.layer` teal + teal-deep 28% + teal-soft bg。

`.decision-note-drawer` margin-top 14 / `.decision-note-toggle` mono 10 fg-mute uppercase cursor / `::-webkit-details-marker { display: none }` / `::before` + amber / `[open] ::before` − amber / textarea ink-2 bg + 1px hair + Source Han Serif 14/1.7 + resize vertical / `:focus` amber border / `.note-submit` amber-soft button → hover amber bg + ink color。

Smoke:GET `/decisions`,左 sidebar sticky + 右 timeline + tag 双色 + note drawer 展开。

Commit: `feat(harness-board): style.css phase 6 — decisions changelog + drawer`

### Task 16: _deep_card_modal.html + _deep_card_field.html + _edit_select.html
**Files:** Modify 3 templates

`_deep_card_modal.html`:`<div class="deep-card" data-modal-content>` 含:
- `.dc-head`:`.dc-cap-id` 维度前缀 amber + `<h2>{{ cap.name_cn }}</h2>` Newsreader 32 opsz 72 + `.status status--{{ cap.status }}` pill + `.dc-close` 32 circle onclick Modal.close()
- `.dc-body` grid 1fr 280px:`.dc-left` 28×40 padding for content_fields → `_deep_card_field.html` / `.dc-right` ink-2 bg 含 `<h5>Code anchors</h5><ul>` for code_anchors `<code>{{file}}:{{line}}</code>` + Linked decisions / Linked capability / Linked specs(各无值时 `<li class="muted">(无)</li>`)+ `<div class="related-block" hx-get="/cap/{{ cap.id }}/related?k=5" hx-trigger="load">` 含 `<span class="skeleton-line">…</span>`

`_deep_card_field.html`:`<div class="dc-field dc-field--{{ field.source }}" data-field>` + `.dc-field-head`(lbl + 条件 AI 草拟 button htmx POST `/cap/.../ai_draft/{field}` hx-indicator)。值显示分三态:空 `<div class="val val-empty">(未填)`、list iterable `<ul class="alternatives-list">` 含 `<em>{{ item.name }}</em>` teal italic + tradeoff、字符串 `<div class="val val-editable" contenteditable hx-post="/cap/.../field/{field}" hx-trigger="blur changed" hx-on::after-request Toast.show info>`。底部 `.dc-field-prov` provenance + `.dc-field-loading.htmx-indicator` skeleton。

`_edit_select.html`:`<form class="edit-select-form" hx-post="/capability/{id}/override" hx-target="this" hx-swap="outerHTML">` 含 `<select class="custom-select" onchange="this.form.requestSubmit()" autofocus>` 选项 lit / wip / todo / `__clear__`(清除 override)。

Smoke:点 chip → htmx swap 出 custom-select。其他模态等 Task 18 Modal.open。

Commit: `feat(harness-board): deep-card modal + field + edit-select templates`

### Task 17: style.css Phase 7 — deep card + form inputs + skeleton
**Files:** Modify `style.css`(追加 Phase 7)

`.deep-card` paper + 1px hair + 6px radius + 32 64 -32 shadow + max-width 980 + width 92vw + max-height 86vh + flex column / `.dc-head` 28 40 padding + bottom hair + linear-gradient paper-2→paper / `.dc-cap-id` mono 11 amber 0.1em / `.dc-head h2` Newsreader 32 opsz 72 letter-spacing -0.005em / `.status` mono 10 0.2em uppercase + 999px + 1px border / `.status--lit` lit + lit border 30% / `.status--wip` wip + wip border 35% / `.status--todo` fg-mute + fg-faint border / `.dc-close` 32 circle + 1px hair + fg-mute + 18 font + transition / `:hover` amber + amber border。

`.dc-body` grid 1fr 280px overflow-y auto / `.dc-left` 28 40 / `.dc-right` 28 32 + ink-2 bg + 1px hair border-left / `.dc-field` margin-bottom 24 / `.dc-field-head` flex baseline space-between / `.lbl` mono 10 amber 0.22em uppercase / `.val` Source Han Serif 15.5/1.85 / `.val em` teal italic Newsreader / `.val-empty` fg-faint italic / `.val-editable` cursor text + 1px dashed transparent outline + 4 offset + transition / `:hover` hair outline / `:focus` amber outline solid。

`.ai-draft-btn` teal-soft bg + teal-deep border + teal + 3 10 padding + mono 10 0.08em + flex 6 gap / `:hover` teal bg + ink + `.ai-icon` 6×6 round。`.alternatives-list` dashed border-bottom / `li em` teal italic Newsreader。`.dc-field-prov` mono 10 fg-faint + em fg-mute italic + code teal。

`.dc-right h5` mono 10 teal opacity 0.75 0.22em uppercase / `ul` list-none / `li` mono 11.5 fg-dim + dashed border-bottom hair-2 / `li code` teal / `li a` fg-dim → hover teal-glow / `li.muted` fg-faint italic / `li.ellipsis` overflow ellipsis nowrap。

`.custom-select` ink-2 + 1px amber-deep + amber + 4 24 4 10 padding + mono 11.5 + appearance none + 自绘三角 amber 箭头 / `:focus` amber-glow border。

`.skeleton-line` linear-gradient paper-2→hair→paper-2 + skeleton-pulse 1.6s + 2px radius + 4 0 margin / `.short { width 60% }` / @keyframes skeleton-pulse 200% → -200%。`.htmx-indicator { display: none }` / `.htmx-request .htmx-indicator { display: block }`。

Smoke:chip → custom-select / 点 cap 详情 → modal 2-col + dual accent。

Commit: `feat(harness-board): style.css phase 7 — deep-card modal + skeleton`

### Task 18: _refresh_panel.html 新建 + toast.js + modal.js
**Files:** Create `_refresh_panel.html` + `toast.js` + `modal.js`

`_refresh_panel.html`:`<aside class="refresh-panel" id="refresh-panel" role="dialog" hidden>` 含:
- `.refresh-panel-head` 含 `.refresh-panel-icon ↻` + `<h3>全量刷新</h3>` + `.refresh-panel-close × onclick="document.getElementById('refresh-panel').hidden = true;"`
- `.refresh-step-list` 5 个 `<li class="refresh-step" data-step="...">` 每个含 `<span class="step-icon" data-state="pending">○</span>` + `.step-label` 中文标签 + `.step-detail` 空(Plan 3 填)。5 个 data-step: `chip_resolve` / `seed_ingest` / `decision_extract` / `milvus_reindex` / `snapshot_finalize`
- `.refresh-panel-foot` 含 `.refresh-summary` + `.refresh-retry hidden` button

`toast.js`(IIFE):
```js
(function(global) {
  'use strict';
  const TYPES = {
    success: { cls: 'toast--success', defaultTtl: 2400 },
    info:    { cls: 'toast--info',    defaultTtl: 2400 },
    warn:    { cls: 'toast--warn',    defaultTtl: 4000 },
    error:   { cls: 'toast--error',   defaultTtl: 5000 },
  };
  function ensureContainer() {
    let c = document.getElementById('toast-container');
    if (!c) {
      c = document.createElement('div');
      c.id = 'toast-container'; c.className = 'toast-container';
      c.setAttribute('aria-live', 'polite');
      document.body.appendChild(c);
    }
    return c;
  }
  function show({ type = 'info', msg = '', ttl } = {}) {
    if (!msg) return;
    const config = TYPES[type] || TYPES.info;
    const c = ensureContainer();
    const el = document.createElement('div');
    el.className = 'toast ' + config.cls;
    el.setAttribute('role', 'status');
    el.textContent = msg;
    c.appendChild(el);
    requestAnimationFrame(() => el.classList.add('toast--show'));
    const lifeMs = ttl || config.defaultTtl;
    setTimeout(() => {
      el.classList.remove('toast--show');
      el.classList.add('toast--hide');
      setTimeout(() => el.remove(), 300);
    }, lifeMs);
  }
  global.Toast = { show };
})(window);
```

`modal.js`(IIFE):
```js
(function(global) {
  'use strict';
  const OVERLAY_ID = 'modal-overlay';
  function getOverlay() { return document.getElementById(OVERLAY_ID); }
  function open() {
    const ov = getOverlay(); if (!ov) return;
    ov.classList.add('modal-overlay--open');
    ov.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
  }
  function close() {
    const ov = getOverlay(); if (!ov) return;
    ov.classList.remove('modal-overlay--open');
    ov.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
    setTimeout(() => { if (!ov.classList.contains('modal-overlay--open')) ov.innerHTML = ''; }, 220);
  }
  function isOpen() {
    const ov = getOverlay();
    return ov && ov.classList.contains('modal-overlay--open');
  }
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (isOpen()) { close(); return; }
    const panel = document.getElementById('refresh-panel');
    if (panel && !panel.hidden) panel.hidden = true;
  });
  document.addEventListener('click', (e) => {
    const ov = getOverlay();
    if (!ov || !isOpen()) return;
    if (e.target === ov) close();
  });
  global.Modal = { open, close, isOpen };
})(window);
```

Smoke:F12 console 跑 `Toast.show({type:'success', msg:'hello'})` 应右下角出现琥珀 toast。F12 `document.getElementById('refresh-panel').hidden = false` 应看到空骨架面板出现。

Commit: `feat(harness-board): refresh-panel skeleton + toast + modal JS`

### Task 19: style.css Phase 8 — refresh panel + toast + skeleton + empty + error + modal
**Files:** Modify `style.css`(追加 Phase 8 — 最后一段)

`.refresh-panel` fixed left 88 bottom 28 + 240 width + 360 min-height + ink-2 + 1px amber-deep + 4px radius + 18 18 14 padding + z-index 50 + 20 40 -20 shadow + fade-scale-in 220ms animation / `[hidden] { display: none }`。

`.refresh-panel-head` flex 8 gap + 12 padding-bottom + 1px hair border-bottom + 14 margin-bottom / `.refresh-panel-icon` amber 14 Newsreader / `h3` Newsreader 16 italic amber / `.refresh-panel-close` ml-auto transparent + fg-mute + 16 cursor → hover amber。

`.refresh-step` grid 16 1fr gap 8 + 8 padding-y + dashed border-bottom hair-2 / `.step-icon` mono 12 center fg-faint / `[data-state="running"]` teal + spin animation / `[data-state="done"]` amber / `[data-state="skip"]` wip / `[data-state="error"]` danger / `.step-label` sans 12 fg-dim line-height 1.4 / `[data-state="running"] .step-label` teal italic / `[data-state="done"] .step-label` fg / `.step-detail` grid-column 2 + mono 10 teal 0.04em。

`.refresh-panel-foot` mt-14 + pt-12 + 1px hair border-top + flex space-between + mono 10 fg-mute / `.refresh-retry` amber-soft + amber-deep + amber + 2 10 padding + mono 10 0.05em。

`.toast-container` fixed right 28 bottom 28 + flex column-reverse 10 gap + z-200 + pointer-events none / `.toast` paper + 1px hair + 3px border-left + 12 18 padding + mono 12 fg + 0.03em + opacity 0 translateY 8 + transition 240ms + max-width 360 + 10 24 -10 shadow / `.toast--show` opacity 1 translateY 0 / `.toast--hide` opacity 0 translateY 8 / `--success` amber / `--info` teal / `--warn` wip / `--error` danger。

`.empty-state` flex 14 gap + 28 32 padding + paper + 1px dashed amber-deep + 4px radius + fg-dim + Source Han Serif 14.5 / `.empty-icon` 28 circle + 1px amber + Newsreader italic 18 / `.empty-msg a` teal + teal-deep border-bottom / `.empty-cta` amber-soft → hover amber + ink / `--overview` mb-18。

`.error-state` flex flex-start 14 + 22 28 padding + rgba(166,69,69,0.06) bg + 1px danger + danger + mono 12 / `details` sans family。

`.modal-overlay` fixed inset 0 + rgba(12,9,8,0.78) bg + display none + flex center + z 150 + opacity 0 + transition 220ms + backdrop-filter blur(2px) / `--open` display flex + opacity 1 / `--open > [data-modal-content], > .deep-card` fade-scale-in 240ms animation。

`.muted { color: var(--fg-faint); font-style: italic; }`。

Smoke:F12 跑 4 类 Toast.show + `_refresh_panel` fade-scale-in 出现 + modal click-outside / ESC 关。

Commit: `feat(harness-board): style.css phase 8 — refresh panel + toast + empty + modal`

### Task 20: 全 dogfood smoke + 视觉自审 + 最终 commit
**Files:** 无修改

跑 `uv run poe serve` → 5 个 view + DeepCard modal + flashcards_stats + 各 form 视觉对照 mockup-v2.html 1-6 section + spec § 8.3 12 处用色 checklist + 全局组件(Toast/Skeleton/Empty/Modal)4 处 dogfood verify + Google Fonts 5 个字体 200 + console 无 error。

**5 处用色 checklist(spec § 8.3):**
1. hero-title em 琥珀 (`所有力气`)
2. hero-title em.cool 古铜青 (`架子`)
3. fingerprint 中心环外圈古铜青 + 内圈琥珀
4. layer 4(memory)`l-stat` 100% 琥珀色高亮
5. chip lit 沙绿 / wip 赤陶心跳 / todo 灰 dashed
6. story drop cap 琥珀 italic
7. story body `<em>` 古铜青 italic / `<strong>` 琥珀
8. decision tag dim 琥珀 / layer 古铜青
9. deep-card `.val em` 古铜青 italic
10. deep-card `.dc-right h5` 古铜青
11. refresh-panel step running 古铜青 italic / done 琥珀
12. toast 4 类色 amber/teal/wip/danger

Final commit:
```bash
git add dashboard/static/style.css dashboard/static/toast.js dashboard/static/modal.js dashboard/templates/
git commit -m "feat(harness-board): plan2 — frontend Quiet Workshop 重写

- style.css 879→~1500 行,8 phase 重写
- 13 模板按 spec § 5.1 改造 + 1 个新 _refresh_panel.html partial
- 5 全局组件:toast.js / modal.js / skeleton / empty / error CSS
- 字体 Newsreader / Source Han Serif / Manrope / Geist Mono CDN 加载
- 双强调琥珀 × 古铜青 token 完整应用"
```

---

## Out of scope(本 Plan 显式不做)

- 后端 routes / view 函数 / Python 业务不动
- `_refresh_panel.html` 的 JS 逻辑(SSE 接入)— Plan 3 范围
- cytoscape node/edge style 升级 — Plan 3
- flashcards_stats 真数据 wire(timeline / scatter / streak_days)— Plan 3
- flashcards.js 改造(已有 3D flip 触发逻辑)
- overview.js cytoscape 配置 — Plan 3
- e2e Playwright 测试(spec § 6.2 optional / nightly)

## Plan 2 验收 ship gate

- [ ] `uv run poe serve` 起 server,6 个主 URL 全部 200,console 无 error
- [ ] 13 模板视觉对照 mockup-v2.html section 1-6 一致
- [ ] 12 处双强调用色 checklist 全过
- [ ] toast / skeleton / empty / modal 4 处 dogfood verify
- [ ] Google Fonts 5 个字体加载 200
- [ ] style.css 行数 ~1400-1600
- [ ] commit 落到 `feat/harness-board-v2-polish` 分支
- [ ] `git diff --stat` 检查仅 frontend 文件改动

---

## Plan 3 hooks(留给 Plan 3)

- `dashboard/static/refresh-panel.js` 新建,监听 `#refresh-btn` 点击 → toggle `#refresh-panel[hidden]` → `new EventSource('/refresh')` → 按 `data-step` 选 `.refresh-step` → 改 `data-state` + 填 `.step-detail`
- `dashboard/templates/flashcards_stats.html` view 后端补 `timeline / scatter / streak_days / today_reviewed`
- `dashboard/static/overview.js` cytoscape node style 改为 radial glow + edge confidence 加权 + qtip
- `dashboard/templates/_decision_filter.html` view 补 `dim_counts / state_counts` context

## Implementation Reference

**重要 — 实施 subagent 落地 CSS / HTML 完整代码时**:
- 主参考:`dashboard/static/mockup-v2.html`(v3 版本,Quiet Workshop CSS 完整体)
- 按本 plan task 索引顺序,**每个 phase CSS 直接从 mockup `<style>` 块对应区段抽取**(根据 spec § 5.4 的 CSS 文件结构注释定位)
- HTML 模板的 DOM 结构按本 plan 描述 + mockup 对应 section 还原
- 严格遵守 spec § 1.2 color token / § 1.3 字体节奏 / § 1.4 signature moments / § 5.1 13 模板清单 / § 5.2 5 全局组件
- 每个 task TDD smoke 验证后 commit;commit message 严格按本 plan 给出

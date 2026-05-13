# Harness Board v2 Polish — Plan 3:鸟瞰增强 + Flashcards Stats Endpoint + Refresh 面板 JS + L2 e2e + Dogfood

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans`. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** [`docs/superpowers/specs/2026-05-14-harness-board-v2-polish-design.md`](../specs/2026-05-14-harness-board-v2-polish-design.md)

**分支:** `feat/harness-board-v2-polish`
**版本归位:** v0.9.6 harness-board polish
**PR 题:** `feat(harness-board): V2 polish — UI 重写 + 鸟瞰修复 + 一键 SSE 全量更新`

**前置依赖:**
- Plan 1 已 ship:`POST /refresh` 走 SSE 5 step pipeline(`chip_resolve` / `seed_ingest` / `decision_extract` / `milvus_reindex` / `snapshot_finalize`);SSE event 格式见 spec § 2.1;Lifespan idempotent seed ingest 已接;`SeedIngestService` / `RefreshPipeline` 已抽取
- Plan 2 已 ship:Quiet Workshop 颜色 token 已在 `style.css` 落地;`_refresh_panel.html`(空骨架,仅 `<div class="refresh-panel" id="refresh-panel" hidden>...</div>` + 5 个 `.step-row` placeholder)已加入 `base.html` mount 点;CSS class `.refresh-panel / .step-row / .step-icon / .step-detail / .step-summary` 已定义;`flashcards_stats.html` 已重写为新视觉骨架(留 4 个待 hydrate 的 SVG / 数字 placeholder);`Toast.show({type, msg, ttl})` / `Modal.open(html)` 全局 API 可用

**Goal:** 收口 V2 polish 的鸟瞰视觉增强 + refresh 一键更新前端 JS + flashcards_stats 数据接口与可视化 hydration + L2 e2e 守护 + 全面 dogfood 通过 ship gate。

**Architecture:** 后端单一新增 data endpoint `GET /api/flashcards/stats.json`(starlette + JSONResponse,跟 `overview_graph_json` 同模式),从 `FlashcardRepo` 派生 5 字段(总卡 / 今日复习 / 平均 conf / 连续天数 / timeline + scatter)。前端三件事并行:`graph_builder` payload 加 `weight` 字段(两端 conf min,≥4→1.2 / 否则 0.6);`overview.js` cytoscape style 升级(节点 glow 用 `overlay-color`+`overlay-opacity` 模拟、edge 数据驱动宽度、自建 tooltip div 跟 mouse、空状态浮条);`refresh-panel.js` 新建挂 nav-rail 按钮 → `new EventSource('/refresh')` → 监听 `event:step`/`event:done` 更新 DOM + 完成行为分支;`flashcards_stats.html` 加 inline JS fetch `/api/flashcards/stats.json` 后用纯 SVG 渲染圆环 + 时间线 + 散点。

**Tech Stack:** 纯 JS / SVG / EventSource / cytoscape 3.30 + cose-bilkent 4.x / starlette + JSONResponse / httpx.AsyncClient + TestClient(L1/L2);**无 build step**。

**Plan 3 ship checklist:**
- `graph_builder.build_graph_payload` edge payload 加 `weight` 字段 + L0 测试覆盖
- `overview.js` cytoscape style 升级(节点 glow / edge weight / 透明度策略 / 维度过滤渐隐 200ms)
- `overview.js` 节点 hover 自建 div tooltip(conf / 待填两种文案)
- `overview.html` 空状态浮条(nodes < 5 时显示,按钮触发 `window.HarnessRefresh.open()`)
- `refresh-panel.js` 新建(~150 行):监听按钮 → EventSource → 5 step DOM 渲染 → 完成行为分支 → ESC 关面板不取消请求 → 全局 API
- `GET /api/flashcards/stats.json` data endpoint(starlette JSONResponse)+ FlashcardRepo 派生
- `flashcards_stats.html` 模板 hydrate JS(SVG 圆环 + 时间线 + 散点 + 数字总览)
- L1 集成测试:`/api/flashcards/stats.json` 结构 + 边界(0 卡 / 35 卡)
- L2 e2e:seed ingest 后 graph endpoint 返回 ≥ 35 nodes / ≥ 10 edges
- L2 e2e(可选,Playwright,`@pytest.mark.e2e` skip by default)
- dogfood 5 项验收 + 落 memory `harness-board-v2-polish-done` 总卡

预计 ~8-10 task / ~1-1.5 天 Claude Code wall time。

---

## File Structure(Plan 3 范围)

**新建:**
- `dashboard/static/refresh-panel.js` — SSE 客户端 + 面板 DOM 渲染 + 全局 API(~150 行)
- `dashboard/tests/integration/test_flashcards_stats_endpoint.py` — L1 集成
- `dashboard/tests/integration/test_overview_after_seed.py` — L2 e2e(graph 数据守护)
- `dashboard/tests/e2e/__init__.py` — 新目录
- `dashboard/tests/e2e/test_refresh_flow.py` — L2 Playwright(可选,`@pytest.mark.e2e` skip by default)

**修改:**
- `dashboard/derive/graph_builder.py` — edge payload 加 `weight` 字段(两端 conf 加权)
- `dashboard/tests/unit/test_graph_builder.py` — 加 4 case 覆盖 weight 逻辑
- `dashboard/static/overview.js` — cytoscape style 重做 + tooltip div + 空状态浮条 + 过滤渐隐
- `dashboard/templates/overview.html` — 加 `#overview-tooltip` div + `#overview-empty-hint` 浮条 mount 点
- `dashboard/templates/flashcards_stats.html` — 加 4 个 SVG mount 点 + inline JS hydrate(或抽 `flashcards-stats.js`)
- `dashboard/server.py` — 加 `Route("/api/flashcards/stats.json", flashcards_stats_json)`;`flashcards_stats` view 只 render 静态壳
- `dashboard/templates/base.html` — 引入 `refresh-panel.js`(放 body 尾)
- `pyproject.toml` 或 `pytest.ini` — 注册 `e2e` marker(若 Plan 2 未注册)
- `README.md` — V2 polish 章节加 dogfood checklist 总览(最后 Task)
- `CLAUDE.md` — Harness Board V2 章节加 ship 完成索引

---

## Task 1:graph_builder edge confidence 加权

**Files:**
- Modify: `dashboard/derive/graph_builder.py`
- Test: `dashboard/tests/unit/test_graph_builder.py`

**目标:** 让 edge payload 携带 `weight` 字段,前端 cytoscape style 用 `'width': 'data(weight)'` 数据驱动 — 两端 DeepCard `srs_state.confidence` 都 ≥ 4 时 `weight=1.2`(实线高亮),否则 `weight=0.6`(半透次要)。

- [ ] **Step 1: Write tests**

```python
# 追加到 dashboard/tests/unit/test_graph_builder.py 末尾

def test_edge_weight_both_endpoints_high_conf() -> None:
    """两端 conf ≥ 4 → weight 1.2(实线主线)"""
    caps = [
        Capability(id="01.a", dimension="prompt_context", name_cn="A", name_en="A",
                   status="lit", derived_status="lit"),
        Capability(id="02.b", dimension="tools_function", name_cn="B", name_en="B",
                   status="lit", derived_status="lit"),
    ]
    cards = [
        DeepCard(cap_id="01.a", linked_capabilities=["02.b"],
                 srs_state=SrsState(confidence=4)),
        DeepCard(cap_id="02.b", linked_capabilities=["01.a"],
                 srs_state=SrsState(confidence=5)),
    ]
    payload = build_graph_payload(caps, cards)
    assert payload["edges"][0]["data"]["weight"] == 1.2


def test_edge_weight_one_endpoint_low_conf() -> None:
    """一端 conf < 4 → weight 0.6(半透次要)"""
    caps = [
        Capability(id="01.a", dimension="prompt_context", name_cn="A", name_en="A",
                   status="lit", derived_status="lit"),
        Capability(id="02.b", dimension="tools_function", name_cn="B", name_en="B",
                   status="lit", derived_status="lit"),
    ]
    cards = [
        DeepCard(cap_id="01.a", linked_capabilities=["02.b"],
                 srs_state=SrsState(confidence=2)),
        DeepCard(cap_id="02.b", linked_capabilities=["01.a"],
                 srs_state=SrsState(confidence=5)),
    ]
    payload = build_graph_payload(caps, cards)
    assert payload["edges"][0]["data"]["weight"] == 0.6


def test_edge_weight_both_low_conf() -> None:
    """两端都低 conf → weight 0.6"""
    caps = [
        Capability(id="01.a", dimension="prompt_context", name_cn="A", name_en="A",
                   status="lit", derived_status="lit"),
        Capability(id="02.b", dimension="tools_function", name_cn="B", name_en="B",
                   status="lit", derived_status="lit"),
    ]
    cards = [
        DeepCard(cap_id="01.a", linked_capabilities=["02.b"],
                 srs_state=SrsState(confidence=1)),
        DeepCard(cap_id="02.b", linked_capabilities=["01.a"],
                 srs_state=SrsState(confidence=3)),
    ]
    payload = build_graph_payload(caps, cards)
    assert payload["edges"][0]["data"]["weight"] == 0.6


def test_edge_weight_one_endpoint_no_deep_card() -> None:
    """一端无 DeepCard → conf=0 → weight 0.6"""
    caps = [
        Capability(id="01.a", dimension="prompt_context", name_cn="A", name_en="A",
                   status="lit", derived_status="lit"),
        Capability(id="02.b", dimension="tools_function", name_cn="B", name_en="B",
                   status="todo", derived_status="todo"),
    ]
    cards = [
        DeepCard(cap_id="01.a", linked_capabilities=["02.b"],
                 srs_state=SrsState(confidence=5)),
    ]
    payload = build_graph_payload(caps, cards)
    # edge 应仍存在(02.b 在 visible_ids)— weight 走低分支
    assert len(payload["edges"]) == 1
    assert payload["edges"][0]["data"]["weight"] == 0.6
```

跑 `uv run pytest dashboard/tests/unit/test_graph_builder.py -k weight` → 应全失败(无 weight key)。

- [ ] **Step 2: Implementation**

修改 `dashboard/derive/graph_builder.py` 的 edges 构造段(line 64-77 区域):

```python
    # edges — 无向 dedupe + self-loop 去 + confidence 加权
    edge_pairs: set[tuple[str, str]] = set()
    for dc in deep_cards:
        if dc.cap_id not in visible_ids:
            continue
        for other in dc.linked_capabilities:
            if other == dc.cap_id:  # self-loop
                continue
            if other not in visible_ids:
                continue
            pair = (dc.cap_id, other) if dc.cap_id <= other else (other, dc.cap_id)
            edge_pairs.add(pair)

    def _edge_weight(a: str, b: str) -> float:
        """两端 confidence 取 min;≥ 4 → 1.2 实线主线,否则 0.6 半透。"""
        ca = cards_by_id.get(a)
        cb = cards_by_id.get(b)
        conf_a = ca.srs_state.confidence if ca else 0
        conf_b = cb.srs_state.confidence if cb else 0
        return 1.2 if min(conf_a, conf_b) >= 4 else 0.6

    edges: list[dict[str, Any]] = [
        {"data": {"source": s, "target": t, "id": f"{s}__{t}", "weight": _edge_weight(s, t)}}
        for s, t in sorted(edge_pairs)
    ]
```

- [ ] **Step 3: Verify**

```bash
uv run pytest dashboard/tests/unit/test_graph_builder.py -v
uv run mypy dashboard/derive/graph_builder.py
uv run ruff check dashboard/derive/graph_builder.py
```

全绿 → commit `feat(harness-board): graph edge confidence weighting`

---

## Task 2:overview.js cytoscape style 升级(节点 glow + edge weight + 过滤渐隐)

**Files:**
- Modify: `dashboard/static/overview.js`

**目标:** style block 重做应用 4 项视觉增强 — (a) lit 节点用 cytoscape `overlay-color` + `overlay-opacity` 模拟外发光 box-shadow(cytoscape 不原生支持);(b) edge `width` 用 `data(weight)` 数据驱动,低 weight 加 `opacity: 0.5`;(c) `has_deep_card=false` 节点 `background-opacity: 0.4` + `border-style: dashed`(保留);(d) 维度过滤切换时 `cy.elements().style({display: 'none'})` 改为 `cy.elements().animate({style: {opacity: 0}}, {duration: 200})` 渐隐。

- [ ] **Step 1: 用 Quiet Workshop token 改 DIM_COLORS**

把 line 3-12 的 DIM_COLORS 替换为 Quiet Workshop palette(Plan 2 已落地的 amber/teal 双强调延续,改 8 维色板更暖且互补):

```javascript
  const DIM_COLORS = {
    prompt_context:    '#c89456',  // amber 主
    tools_function:    '#6f9494',  // teal 次
    orchestration:     '#94b87a',  // lit sage
    memory:            '#d4824a',  // wip terracotta
    rag_knowledge:     '#8db1b1',  // teal-glow
    guardrails:        '#a64545',  // danger 暗砖
    eval_observability:'#b9ad94',  // fg-dim
    cost_routing:      '#e5b079',  // amber-glow
  };
```

- [ ] **Step 2: 升级 cytoscape style block**

整段替换 line 50-84 的 `style: [...]` 为:

```javascript
      style: [
        {
          selector: 'node',
          style: {
            label: 'data(label)',
            'font-family': 'Manrope, sans-serif',
            'font-size': 11,
            color: '#b9ad94',  // fg-dim
            width: 'mapData(size, 1, 10, 24, 56)',
            height: 'mapData(size, 1, 10, 24, 56)',
            'background-color': function (ele) { return DIM_COLORS[ele.data('dimension')] || '#7d6e58'; },
            'background-opacity': function (ele) {
              // todo (无 DeepCard) 用 0.4 半透;lit 1.0;wip 0.7
              if (!ele.data('has_deep_card')) return 0.4;
              const st = ele.data('status');
              return st === 'lit' ? 1.0 : st === 'wip' ? 0.7 : 0.5;
            },
            'border-width': 2,
            'border-color': function (ele) { return confidenceBorder(ele.data('confidence')); },
            'border-style': function (ele) { return ele.data('has_deep_card') ? 'solid' : 'dashed'; },
            'text-valign': 'bottom',
            'text-margin-y': 6,
            'text-outline-color': '#0c0908',  // ink
            'text-outline-width': 2,
          },
        },
        {
          // 只 lit 节点发光 — 用 overlay-color + overlay-opacity 模拟 box-shadow
          selector: 'node[status = "lit"]',
          style: {
            'overlay-color': function (ele) { return DIM_COLORS[ele.data('dimension')] || '#c89456'; },
            'overlay-opacity': 0.28,
            'overlay-padding': 5,
          },
        },
        {
          // wip 心跳:用 underlay-opacity 周期变化(cytoscape 不支持 keyframes,
          // 退化为静态 underlay)
          selector: 'node[status = "wip"]',
          style: {
            'underlay-color': '#d4824a',
            'underlay-opacity': 0.2,
            'underlay-padding': 4,
          },
        },
        {
          selector: 'edge',
          style: {
            'width': 'data(weight)',
            'line-color': '#7d6e58',  // fg-mute
            'curve-style': 'bezier',
            opacity: function (ele) { return ele.data('weight') >= 1.0 ? 0.85 : 0.45; },
            'line-style': function (ele) { return ele.data('weight') >= 1.0 ? 'solid' : 'dashed'; },
          },
        },
        {
          selector: '.cy-flash-highlight',
          style: {
            'overlay-color': '#e5b079',
            'overlay-opacity': 0.5,
            'border-color': '#c89456',
            'border-width': 4,
          },
        },
      ],
```

- [ ] **Step 3: confidenceBorder 改 Quiet Workshop 色阶**

替换 line 20-24:

```javascript
  function confidenceBorder(c) {
    // todo → wip → lit 渐变,跟 chip dots 一致
    const stops = ['#4a3f33', '#6b5d49', '#7d6e58', '#b9ad94', '#94b87a', '#c89456'];
    return stops[Math.max(0, Math.min(5, c || 0))];
  }
```

- [ ] **Step 4: 维度过滤改渐隐**

`reload()` 函数末尾不变(继续 `loadAndRender(qs)` 重 fetch),但在 `loadAndRender` 内 cytoscape 创建前若 `cy` 已存在,先 fade out:

```javascript
  async function loadAndRender(query) {
    query = query || '';
    if (cy) {
      // 维度过滤切换:旧 cy 元素渐隐 200ms 后销毁
      cy.elements().animate({ style: { opacity: 0 } }, { duration: 200 });
      await new Promise(r => setTimeout(r, 210));
      cy.destroy();
      cy = null;
    }
    // ...保留原 fetch + 渲染逻辑
  }
```

- [ ] **Step 5: 手动验证**

```bash
uv run uvicorn dashboard.server:app --port 8910
# 浏览器打开 http://localhost:8910/overview
# 期望:lit 节点周围有 amber 外发光;low-conf edge 是 dashed 半透;
# 过滤维度切换看到 200ms 渐隐
```

无 `console.error` → commit `feat(harness-board): overview cytoscape glow + edge weighting + fade`

---

## Task 3:overview.js 节点 hover tooltip(自建 div)

**Files:**
- Modify: `dashboard/static/overview.js`
- Modify: `dashboard/templates/overview.html`(加 mount 点)

**目标:** cytoscape `qtip` extension 需额外 CDN + jQuery,过重;改为自建一个 `position: fixed` div 跟 mouseover/mouseout 节点显示 tooltip。文案规则(spec § 4.2):有 DeepCard → `{name_cn} · conf {n}/5`,无 → `{name_cn} · 待填 DeepCard`。

- [ ] **Step 1: overview.html 加 tooltip mount 点**

在 line 20(`<div id="overview-canvas">`)之后,`<script>` 之前插入:

```html
<div id="overview-tooltip" class="overview-tooltip" hidden></div>
<div id="overview-empty-hint" class="overview-empty-hint" hidden>
  💡 看上去 DeepCard 还很少 —
  <button type="button" id="overview-empty-refresh">跑一次全量刷新?</button>
</div>
```

CSS class `.overview-tooltip` / `.overview-empty-hint` 由 Plan 2 已落地 style.css(若未,本 task 末尾顺带加 minimal style 到 style.css)。Minimal fallback CSS(若 Plan 2 没含):

```css
.overview-tooltip {
  position: fixed;
  pointer-events: none;
  background: var(--paper);
  border: 1px solid var(--hair);
  color: var(--fg);
  font-family: var(--mono);
  font-size: 12px;
  padding: 6px 10px;
  border-radius: 4px;
  z-index: 200;
  box-shadow: 0 4px 12px rgba(0,0,0,0.4);
}
.overview-empty-hint {
  position: absolute;
  top: 16px; left: 50%; transform: translateX(-50%);
  background: var(--amber-soft);
  border: 1px solid var(--amber-deep);
  color: var(--fg);
  font-family: var(--display); font-style: italic;
  padding: 8px 16px;
  border-radius: 999px;
  z-index: 150;
}
.overview-empty-hint button {
  background: transparent; border: none; color: var(--amber);
  text-decoration: underline; cursor: pointer; font: inherit;
}
```

- [ ] **Step 2: overview.js hover 逻辑**

在 `cy = cytoscape({...})` 之后、`cy.on('tap', 'node', ...)` 之前插入:

```javascript
    const tooltip = document.getElementById('overview-tooltip');
    cy.on('mouseover', 'node', function (evt) {
      if (!tooltip) return;
      const d = evt.target.data();
      const text = d.has_deep_card
        ? `${d.label} · conf ${d.confidence}/5`
        : `${d.label} · 待填 DeepCard`;
      tooltip.textContent = text;
      tooltip.hidden = false;
    });
    cy.on('mouseout', 'node', function () {
      if (tooltip) tooltip.hidden = true;
    });
    // 跟随鼠标
    document.getElementById('overview-canvas').addEventListener('mousemove', function (e) {
      if (!tooltip || tooltip.hidden) return;
      tooltip.style.left = (e.clientX + 12) + 'px';
      tooltip.style.top  = (e.clientY + 12) + 'px';
    });
```

- [ ] **Step 3: Verify**

手动:hover 任一节点 → 看到 tooltip;mouseout → 消失;mousemove → tooltip 跟随。

commit `feat(harness-board): overview hover tooltip`

---

## Task 4:overview 空状态浮条 + 联动 refresh 面板

**Files:**
- Modify: `dashboard/static/overview.js`

**目标:** `loadAndRender` 完成后,若 `payload.nodes.length < 5`,显示 `#overview-empty-hint` 浮条;按钮 click 触发 `window.HarnessRefresh.open()`(Task 5 提供)。

- [ ] **Step 1: 加空状态判断**

在 `loadAndRender` 内,`cy = cytoscape({...})` 之后(渲染完毕)加:

```javascript
    const emptyHint = document.getElementById('overview-empty-hint');
    if (emptyHint) {
      emptyHint.hidden = payload.nodes.length >= 5;
    }

    const emptyBtn = document.getElementById('overview-empty-refresh');
    if (emptyBtn && !emptyBtn.dataset.bound) {
      emptyBtn.dataset.bound = '1';
      emptyBtn.addEventListener('click', function () {
        if (window.HarnessRefresh && typeof window.HarnessRefresh.open === 'function') {
          window.HarnessRefresh.open();
        } else {
          // refresh-panel.js 未加载,fallback toast
          if (window.Toast) window.Toast.show({ type: 'warn', msg: '刷新模块未就绪' });
        }
      });
    }
```

- [ ] **Step 2: Verify(暂时手测,Task 5 之后回归)**

清空 board.db(`rm backend/data/board.db`)后启动 → `/overview` 看到浮条;点 button → console 不报错(此时 Task 5 未 ship,看到 toast warn)。

commit `feat(harness-board): overview empty-state hint with refresh wiring`

---

## Task 5:refresh-panel.js 新建(SSE 客户端 + 全局 API)

**Files:**
- Create: `dashboard/static/refresh-panel.js`
- Modify: `dashboard/templates/base.html`

**目标:** Plan 2 已落地的空骨架 `_refresh_panel.html`(挂在 base.html 末尾)由本 JS 接管 — 监听 nav-rail 底部 `.btn-refresh` 按钮 click → `new EventSource('/refresh')` → 监听 `event:step` / `event:done` 更新 DOM → 完成行为按 spec § 3.4 分支(error > 0 留 + retry / 无 error 5s fade + `location.reload()`)。ESC 关面板但不取消 EventSource。导出 `window.HarnessRefresh.open()`。

**Plan 2 假设 DOM(必须与 Plan 2 Task 18 一致):**

Plan 2 写的 `_refresh_panel.html` 关键 hook:
- `<aside class="refresh-panel" id="refresh-panel" role="dialog" hidden>`
- 5 个 `<li class="refresh-step" data-step="...">` 含 `.step-icon[data-state="pending"]` / `.step-label` / `.step-detail`
- 5 个 data-step 值:`chip_resolve` / `seed_ingest` / `decision_extract` / `milvus_reindex` / `snapshot_finalize`
- `<span class="refresh-summary" id="refresh-summary">`(在 `.refresh-panel-foot` 内)
- `<button class="refresh-retry" type="button" id="refresh-retry" hidden>`

**JS 选择器约定**:row 用 `querySelector('.refresh-step[data-step="..."]')` 不是 `.step-row`。icon state 用 `[data-state]` 属性(Plan 2 CSS 用 attribute selector 切色)。

- [ ] **Step 1: base.html 引入脚本**

在 `</body>` 之前加(确保在 toast/modal JS 之后):

```html
<script src="/static/refresh-panel.js" defer></script>
```

- [ ] **Step 2: 创建 refresh-panel.js**

```javascript
// dashboard/static/refresh-panel.js
// Plan 3 — SSE 客户端 + refresh 面板渲染。spec § 3。
(function () {
  'use strict';

  const ICONS = {
    pending: '○',
    running: '⟳',
    done:    '✓',
    skip:    '⊘',
    error:   '✗',
  };

  let eventSource = null;        // 持续到 done event,不随面板关闭取消
  let lastSummary = null;        // 缓存最新 done payload,面板再打开恢复显示
  let stepStates  = {};          // {chip_resolve: 'done', ...} 缓存
  let stepDetails = {};          // {chip_resolve: '62 chip · 4 lit', ...}
  let panelEl     = null;
  let isFading    = false;

  function $(id) { return document.getElementById(id); }

  function setStepDOM(stepName, status, detail) {
    const row = panelEl.querySelector('.refresh-step[data-step="' + stepName + '"]');
    if (!row) return;
    const icon   = row.querySelector('.step-icon');
    const detEl  = row.querySelector('.step-detail');
    // 同时改 row.dataset.state(供 .refresh-step[data-state] CSS) +
    // icon.dataset.state(供 .step-icon[data-state] CSS) + textContent
    icon.textContent = ICONS[status] || ICONS.pending;
    icon.dataset.state = status;
    row.dataset.state = status;
    if (detail) detEl.textContent = detail;
  }

  function restoreCachedState() {
    Object.keys(stepStates).forEach(function (step) {
      setStepDOM(step, stepStates[step], stepDetails[step] || '');
    });
    if (lastSummary) renderSummary(lastSummary);
  }

  function resetPanel() {
    stepStates = {}; stepDetails = {}; lastSummary = null;
    panelEl.querySelectorAll('.refresh-step').forEach(function (row) {
      row.dataset.state = 'pending';
      const icon = row.querySelector('.step-icon');
      icon.dataset.state = 'pending';
      icon.textContent = ICONS.pending;
      row.querySelector('.step-detail').textContent = '';
    });
    const sum = $('refresh-summary');
    sum.hidden = true; sum.textContent = '';
    $('refresh-retry').hidden = true;
    panelEl.style.opacity = '';
    isFading = false;
  }

  function renderSummary(data) {
    const sum = $('refresh-summary');
    const s = data.steps_summary || {};
    const total = ((data.total_ms || 0) / 1000).toFixed(1);
    const parts = ['⏱ ' + total + 's'];
    if (s.done)  parts.push(s.done + ' done');
    if (s.skip)  parts.push(s.skip + ' skip');
    if (s.error) parts.push(s.error + ' error');
    sum.textContent = parts.join(' · ');
    sum.hidden = false;
  }

  function startStream() {
    if (eventSource) { eventSource.close(); eventSource = null; }
    resetPanel();

    eventSource = new EventSource('/refresh');

    eventSource.addEventListener('step', function (evt) {
      let data;
      try { data = JSON.parse(evt.data); } catch (e) { return; }
      stepStates[data.step]  = data.status;
      stepDetails[data.step] = data.detail || '';
      setStepDOM(data.step, data.status, data.detail);
    });

    eventSource.addEventListener('done', function (evt) {
      let data;
      try { data = JSON.parse(evt.data); } catch (e) { return; }
      lastSummary = data;
      renderSummary(data);
      eventSource.close(); eventSource = null;

      const hasError = (data.steps_summary && data.steps_summary.error) > 0;
      if (hasError) {
        $('refresh-retry').hidden = false;
        if (window.Toast) window.Toast.show({ type: 'error', msg: '刷新部分失败,可重试', ttl: 6000 });
      } else {
        // 5s fade + reload
        isFading = true;
        setTimeout(function () {
          if (!isFading) return;  // 期间被点 refresh 重跑则取消 fade
          panelEl.style.transition = 'opacity 800ms';
          panelEl.style.opacity = '0';
          setTimeout(function () { location.reload(); }, 850);
        }, 5000);
      }
    });

    eventSource.addEventListener('error', function () {
      // 网络/服务端断连
      if (window.Toast) window.Toast.show({ type: 'error', msg: 'SSE 断连,可重试' });
      $('refresh-retry').hidden = false;
      if (eventSource) { eventSource.close(); eventSource = null; }
    });
  }

  function openPanel() {
    panelEl.hidden = false;
    panelEl.focus();
    if (eventSource) {
      // 流仍在跑,恢复显示当前状态(从内存 buffer)
      restoreCachedState();
    } else if (lastSummary && (lastSummary.steps_summary || {}).error > 0) {
      // 错误态保留,允许 retry,不重跑
      restoreCachedState();
    } else {
      // 全新开跑(包括 done 已 reload 错过 / 第一次打开)
      startStream();
    }
  }

  function closePanel() {
    panelEl.hidden = true;
    isFading = false;  // 取消任何 fade-pending
    // EventSource 不关 — 流继续跑;再次 open 恢复状态
  }

  function init() {
    panelEl = $('refresh-panel');
    if (!panelEl) return;  // 页面无面板挂载(测试场景)

    // nav-rail 主按钮(Plan 2 写的 id="refresh-btn" class="refresh-btn")
    const navBtn = document.getElementById('refresh-btn');
    if (navBtn) {
      navBtn.addEventListener('click', function (e) {
        e.preventDefault();
        if (panelEl.hidden) openPanel();
        else closePanel();
      });
    }
    // 兼容兜底
    document.querySelectorAll('.refresh-btn, [data-action="refresh"]').forEach(function (btn) {
      if (btn === navBtn) return;
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        if (panelEl.hidden) openPanel();
        else closePanel();
      });
    });

    // ESC 关
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !panelEl.hidden) closePanel();
    });

    // Retry
    const retry = $('refresh-retry');
    if (retry) {
      retry.addEventListener('click', function () { startStream(); });
    }
  }

  // 全局 API(供 overview.js 空状态浮条调用)
  window.HarnessRefresh = {
    open: function () {
      if (!panelEl) return;
      if (panelEl.hidden) openPanel();
    },
    close: closePanel,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
```

- [ ] **Step 3: 手动验证**

```bash
uv run uvicorn dashboard.server:app --port 8910
# 浏览器:点 nav-rail 底部琥珀 refresh 按钮 → 看到 240×360 面板展开
# → 5 行依次:○ → ⟳ → ✓/⊘,无 milvus env 时第 4 行 ⊘
# → 5s 后 fade + reload,主页 snapshot refreshed_at 是新时间
# → ESC 中途关面板,再点按钮看到当前进度(继续跑)
# → unset OPENAI_API_KEY + HARNESS_BOARD_MILVUS_HOST 跑 — 5 step 全完成 4 done + 1 skip
```

无 `console.error` → commit `feat(harness-board): refresh panel SSE client JS`

---

## Task 6:`/api/flashcards/stats.json` data endpoint

**Files:**
- Modify: `dashboard/server.py`

**目标:** 新增 `GET /api/flashcards/stats.json`,返回 6 字段 JSON,供前端 hydrate。原 `flashcards_stats` view 简化为只 render 静态壳(数据 JS 拉)。

**Schema:**

```json
{
  "total": 35,
  "today": 8,
  "avg_confidence": 3.4,
  "streak_days": 5,
  "timeline": [
    {"date": "2026-04-15", "grade": 4},
    {"date": "2026-04-15", "grade": 5}
  ],
  "scatter": [
    {"dim": "prompt_context", "conf": 4},
    {"dim": "memory",         "conf": 2}
  ]
}
```

- [ ] **Step 1: Write test**

```python
# dashboard/tests/integration/test_flashcards_stats_endpoint.py
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from dashboard.derive.deep_card_types import Flashcard, SrsState


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    from dashboard import server
    from dashboard.state.db import open_db, ensure_schema

    db_path = tmp_path / "board.db"
    monkeypatch.setattr(server, "DB_PATH", db_path)
    # 建空 schema
    conn = open_db(db_path); ensure_schema(conn); conn.close()
    return TestClient(server.app)


def test_stats_json_empty_db(client: TestClient) -> None:
    resp = client.get("/api/flashcards/stats.json")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["today"] == 0
    assert body["avg_confidence"] == 0.0
    assert body["streak_days"] == 0
    assert body["timeline"] == []
    assert body["scatter"] == []


def test_stats_json_with_seed_flashcards(client: TestClient, tmp_path: Path) -> None:
    """种 5 flashcards (3 reviewed) → 校验各 metric。"""
    from dashboard.state.db import open_db
    from dashboard.state.repositories import FlashcardRepo

    now = datetime.now(UTC)
    conn = open_db(tmp_path / "board.db")
    try:
        repo = FlashcardRepo(conn)
        # 3 张今天复习过 (grade 4,5,3) + 2 张未复习
        for i, grade in enumerate([4, 5, 3]):
            repo.upsert(Flashcard(
                id=f"01.a::tradeoff::{i}", cap_id="01.a",
                template_kind="tradeoff", question="Q", answer="A",
                srs_state=SrsState(confidence=grade, repetition=1, interval=1,
                                   last_reviewed_at=now,
                                   next_review_at=now + timedelta(days=1)),
            ))
        for i in range(2):
            repo.upsert(Flashcard(
                id=f"04.b::lessons::{i}", cap_id="04.b",
                template_kind="lessons", question="Q", answer="A",
                srs_state=SrsState(),  # repetition=0,新卡
            ))
    finally:
        conn.close()

    resp = client.get("/api/flashcards/stats.json")
    body = resp.json()
    assert body["total"] == 5
    assert body["today"] == 3              # 今天复习的 3 张
    assert 3.0 <= body["avg_confidence"] <= 4.5  # (4+5+3)/3 = 4.0
    dims = [s["dim"] for s in body["scatter"]]
    assert "prompt_context" in dims or "memory" in dims
    # timeline 含 3 个 reviewed 点
    assert len(body["timeline"]) == 3
    for t in body["timeline"]:
        assert "date" in t and "grade" in t


def test_stats_html_hydrates_via_js(client: TestClient) -> None:
    """flashcards_stats.html 应只返静态壳 + 引用 /api/flashcards/stats.json。"""
    resp = client.get("/flashcards/stats")
    assert resp.status_code == 200
    assert "/api/flashcards/stats.json" in resp.text
    assert 'id="stats-ring"' in resp.text  # SVG mount 点
```

跑测试 → 全失败(endpoint 未注册)。

- [ ] **Step 2: 实现 endpoint**

在 `dashboard/server.py` 替换原 `flashcards_stats` 函数,并新增 `flashcards_stats_json`:

```python
from collections import Counter
from datetime import UTC, date, datetime, timedelta


def _compute_streak_days(review_dates: list[date]) -> int:
    """连续复习天数 — 从今天往前数,直到第一个 gap。"""
    if not review_dates:
        return 0
    unique = sorted(set(review_dates), reverse=True)
    today = datetime.now(UTC).date()
    streak = 0
    expected = today
    for d in unique:
        if d == expected:
            streak += 1
            expected = expected - timedelta(days=1)
        elif d == expected + timedelta(days=1):
            # 今天没复习但昨天复习了 — streak 从昨天起算
            if streak == 0:
                expected = d
                streak = 1
                expected = expected - timedelta(days=1)
            else:
                break
        else:
            break
    return streak


async def flashcards_stats_json(_request: Request) -> JSONResponse:
    """Plan 3 — flashcards_stats.html 的数据 endpoint。"""
    conn = open_db(DB_PATH)
    try:
        fcs = FlashcardRepo(conn).get_all()
    finally:
        conn.close()

    total = len(fcs)
    if total == 0:
        return JSONResponse({
            "total": 0, "today": 0, "avg_confidence": 0.0, "streak_days": 0,
            "timeline": [], "scatter": [],
        })

    today_utc = datetime.now(UTC).date()
    reviewed = [f for f in fcs if f.srs_state.last_reviewed_at is not None]
    today_count = sum(
        1 for f in reviewed
        if f.srs_state.last_reviewed_at and f.srs_state.last_reviewed_at.date() == today_utc
    )

    # 平均 confidence(只算已复习过的;空则 0)
    if reviewed:
        avg_conf = round(sum(f.srs_state.confidence for f in reviewed) / len(reviewed), 2)
    else:
        avg_conf = 0.0

    # 连续天数
    streak = _compute_streak_days([
        f.srs_state.last_reviewed_at.date()
        for f in reviewed if f.srs_state.last_reviewed_at
    ])

    # 时间线:过去 30 天,每个 reviewed flashcard 一个点
    cutoff = today_utc - timedelta(days=30)
    timeline = []
    for f in reviewed:
        if f.srs_state.last_reviewed_at is None:
            continue
        d = f.srs_state.last_reviewed_at.date()
        if d < cutoff:
            continue
        timeline.append({"date": d.isoformat(), "grade": f.srs_state.confidence})
    timeline.sort(key=lambda x: x["date"])

    # 散点:每卡 (dim, conf);dim 由 cap_id 前缀派生 — 跟 capabilities.yaml 维度一致
    caps_cfg = load_capabilities(CONFIG_DIR / "capabilities.yaml")
    cap_to_dim = {c.id: c.dimension for c in caps_cfg}
    scatter = []
    for f in fcs:
        dim = cap_to_dim.get(f.cap_id, "unknown")
        scatter.append({"dim": dim, "conf": f.srs_state.confidence})

    return JSONResponse({
        "total": total,
        "today": today_count,
        "avg_confidence": avg_conf,
        "streak_days": streak,
        "timeline": timeline,
        "scatter": scatter,
    })


async def flashcards_stats(_request: Request) -> HTMLResponse:
    """V5 学习统计页 — 只 render 静态壳,数据 JS 拉 /api/flashcards/stats.json。"""
    template = templates.get_template("flashcards_stats.html")
    return HTMLResponse(template.render(active_nav="flashcards"))
```

routes 列表加:

```python
Route("/api/flashcards/stats.json", flashcards_stats_json),
```

- [ ] **Step 3: Verify**

```bash
uv run pytest dashboard/tests/integration/test_flashcards_stats_endpoint.py -v
uv run mypy dashboard/server.py
```

全绿 → commit `feat(harness-board): flashcards stats JSON endpoint`

---

## Task 7:flashcards_stats.html 接 endpoint 渲染 SVG 圆环 / 时间线 / 散点

**Files:**
- Modify: `dashboard/templates/flashcards_stats.html`

**目标:** Plan 2 已落地的模板壳里加 4 个 SVG mount 点 + inline `<script>` 拉 `/api/flashcards/stats.json` 后用纯 DOM API 渲染。

**SVG 计算细节:**

- **圆环进度:** 一个 200×200 SVG,中心 100,100,半径 80;两个 `<circle>` — 背景灰圈 + 前景 amber 弧。`circumference = 2π × 80 ≈ 502.65`;`stroke-dasharray = "{circumference}"`;`stroke-dashoffset = circumference × (1 - progress)`,progress = `mastered / total`(mastered = scatter 里 conf≥4 数)。中心数字 Newsreader italic 36px。
- **时间线:** 800×80 SVG;x = `((date - cutoff) / 30) × 760 + 20`;y = `70 - (grade / 5) × 60`;每点 `<circle r=4>`,fill 按 grade 渐变 wip(`#d4824a` grade 0)→ lit(`#94b87a` grade 5)。
- **散点:** 600×240 SVG,8 维水平分列(每列宽 `600/8=75`,中心 `x = col*75 + 37.5`);conf 0-5 垂直分行(每行高 `240/6=40`,中心 `y = 240 - (conf+0.5)*40`)。每个点 `<circle r=3.5>` fill 用维度色(跟 overview.js DIM_COLORS 一致)。

- [ ] **Step 1: 重写 flashcards_stats.html**

```html
{# Plan 3 — flashcards_stats 视觉重做。spec § 5.3。 #}
{% extends "base.html" %}
{% block content %}
{% include "_board_nav.html" %}

<div class="stats-page">
  <header class="stats-head">
    <h2 class="stats-title">📊 学习统计</h2>
    <a href="/flashcards/today" class="btn-back">← 回到今日复习</a>
  </header>

  <section class="stats-numbers" id="stats-numbers">
    <div class="stat-num"><span class="num" id="stat-total">—</span><span class="label">总卡</span></div>
    <div class="stat-num"><span class="num" id="stat-today">—</span><span class="label">今日</span></div>
    <div class="stat-num"><span class="num" id="stat-avg">—</span><span class="label">平均 conf</span></div>
    <div class="stat-num"><span class="num" id="stat-streak">—</span><span class="label">连续天</span></div>
  </section>

  <section class="stats-ring-wrap">
    <svg id="stats-ring" width="200" height="200" viewBox="0 0 200 200">
      <circle cx="100" cy="100" r="80" fill="none" stroke="var(--hair)" stroke-width="6"/>
      <circle id="stats-ring-fill" cx="100" cy="100" r="80" fill="none"
              stroke="var(--amber)" stroke-width="6" stroke-linecap="round"
              stroke-dasharray="502.65" stroke-dashoffset="502.65"
              transform="rotate(-90 100 100)"/>
      <text id="stats-ring-text" x="100" y="106" text-anchor="middle"
            font-family="Newsreader" font-style="italic" font-size="36"
            fill="var(--fg)">0</text>
      <text x="100" y="130" text-anchor="middle"
            font-family="Geist Mono" font-size="11" fill="var(--fg-mute)">/ 35</text>
    </svg>
  </section>

  <section class="stats-timeline-wrap">
    <h3 class="stats-sub">过去 30 天</h3>
    <svg id="stats-timeline" width="800" height="80" viewBox="0 0 800 80">
      <line x1="20" y1="70" x2="780" y2="70" stroke="var(--hair)" stroke-width="1"/>
    </svg>
  </section>

  <section class="stats-scatter-wrap">
    <h3 class="stats-sub">8 维 × confidence 散点</h3>
    <svg id="stats-scatter" width="600" height="240" viewBox="0 0 600 240"></svg>
  </section>
</div>

<script>
(function () {
  const DIM_COLORS = {
    prompt_context:    '#c89456',
    tools_function:    '#6f9494',
    orchestration:     '#94b87a',
    memory:            '#d4824a',
    rag_knowledge:     '#8db1b1',
    guardrails:        '#a64545',
    eval_observability:'#b9ad94',
    cost_routing:      '#e5b079',
    unknown:           '#7d6e58',
  };
  const DIM_ORDER = [
    'prompt_context','tools_function','orchestration','memory',
    'rag_knowledge','guardrails','eval_observability','cost_routing',
  ];

  function gradeColor(grade) {
    // grade 0→wip 颜色,5→lit;中间线性
    const wip = [212, 130, 74];  // d4824a
    const lit = [148, 184, 122]; // 94b87a
    const t = Math.max(0, Math.min(5, grade)) / 5;
    const c = wip.map((v, i) => Math.round(v + (lit[i] - v) * t));
    return 'rgb(' + c.join(',') + ')';
  }

  function renderRing(total, mastered) {
    const C = 2 * Math.PI * 80;  // 502.65
    const ratio = total > 0 ? Math.min(1, mastered / total) : 0;
    document.getElementById('stats-ring-fill').setAttribute(
      'stroke-dashoffset', String(C * (1 - ratio))
    );
    document.getElementById('stats-ring-text').textContent = String(mastered);
  }

  function renderTimeline(timeline) {
    const svg = document.getElementById('stats-timeline');
    const today = new Date();
    const cutoffMs = today.getTime() - 30 * 86400000;
    timeline.forEach(function (pt) {
      const dt = new Date(pt.date + 'T00:00:00Z').getTime();
      const x = ((dt - cutoffMs) / (30 * 86400000)) * 760 + 20;
      const y = 70 - (pt.grade / 5) * 60;
      const c = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      c.setAttribute('cx', String(x.toFixed(1)));
      c.setAttribute('cy', String(y.toFixed(1)));
      c.setAttribute('r', '4');
      c.setAttribute('fill', gradeColor(pt.grade));
      c.setAttribute('opacity', '0.85');
      svg.appendChild(c);
    });
  }

  function renderScatter(scatter) {
    const svg = document.getElementById('stats-scatter');
    // 维度 label
    DIM_ORDER.forEach(function (dim, col) {
      const cx = col * 75 + 37.5;
      const t = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      t.setAttribute('x', String(cx));
      t.setAttribute('y', '232');
      t.setAttribute('text-anchor', 'middle');
      t.setAttribute('font-family', 'Geist Mono');
      t.setAttribute('font-size', '9');
      t.setAttribute('fill', 'var(--fg-mute)');
      t.textContent = dim.slice(0, 6);
      svg.appendChild(t);
    });
    // confidence row label
    for (let conf = 0; conf <= 5; conf++) {
      const cy = 220 - (conf + 0.5) * 35;
      const t = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      t.setAttribute('x', '4'); t.setAttribute('y', String(cy + 3));
      t.setAttribute('font-family', 'Geist Mono'); t.setAttribute('font-size', '9');
      t.setAttribute('fill', 'var(--fg-faint)');
      t.textContent = String(conf);
      svg.appendChild(t);
    }
    // 点(jitter 避免重叠)
    scatter.forEach(function (pt) {
      const col = DIM_ORDER.indexOf(pt.dim);
      const cx = (col >= 0 ? col : 0) * 75 + 37.5 + (Math.random() - 0.5) * 14;
      const cy = 220 - (pt.conf + 0.5) * 35 + (Math.random() - 0.5) * 8;
      const c = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      c.setAttribute('cx', String(cx.toFixed(1)));
      c.setAttribute('cy', String(cy.toFixed(1)));
      c.setAttribute('r', '3.5');
      c.setAttribute('fill', DIM_COLORS[pt.dim] || DIM_COLORS.unknown);
      c.setAttribute('opacity', '0.75');
      svg.appendChild(c);
    });
  }

  async function hydrate() {
    try {
      const resp = await fetch('/api/flashcards/stats.json');
      if (!resp.ok) throw new Error('http ' + resp.status);
      const d = await resp.json();
      document.getElementById('stat-total').textContent  = d.total;
      document.getElementById('stat-today').textContent  = d.today;
      document.getElementById('stat-avg').textContent    = d.avg_confidence.toFixed(2);
      document.getElementById('stat-streak').textContent = d.streak_days;
      // mastered = scatter 里 conf≥4 数
      const mastered = d.scatter.filter(s => s.conf >= 4).length;
      renderRing(d.total, mastered);
      renderTimeline(d.timeline);
      renderScatter(d.scatter);
    } catch (e) {
      console.error('stats hydrate failed', e);
      if (window.Toast) window.Toast.show({ type: 'error', msg: '统计数据加载失败' });
    }
  }
  hydrate();
})();
</script>
{% endblock %}
```

- [ ] **Step 2: Verify**

```bash
uv run pytest dashboard/tests/integration/test_flashcards_stats_endpoint.py -v
uv run uvicorn dashboard.server:app --port 8910
# 浏览器 → /flashcards/stats → 看到圆环 + 时间线点 + 散点 + 4 个数字
```

commit `feat(harness-board): flashcards stats SVG hydration`

---

## Task 8:L2 e2e — graph endpoint after seed ingest

**Files:**
- Create: `dashboard/tests/integration/test_overview_after_seed.py`

**目标:** spec § 6 + § 8.1 验收 — seed ingest 跑过后,`/api/overview/graph.json` 返回 ≥ 35 nodes + ≥ 10 edges。用 Plan 1 已有的 `SeedIngestService` 跑一遍 fixture,然后请求 endpoint 校验。

- [ ] **Step 1: Write test**

```python
# dashboard/tests/integration/test_overview_after_seed.py
"""Plan 3 L2 e2e — seed 加载后鸟瞰节点 / 边量级守护。spec § 6 + § 8。"""
from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient


@pytest.fixture()
def client_with_seed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    """跑一次 SeedIngestService.run() 把 35 张 seed 写进 tmp db。"""
    from dashboard import server
    from dashboard.derive.seed_ingest import SeedIngestService
    from dashboard.state.db import ensure_schema, open_db

    db_path = tmp_path / "board.db"
    conn = open_db(db_path)
    ensure_schema(conn)
    conn.close()

    monkeypatch.setattr(server, "DB_PATH", db_path)

    seed_path = server.PROJECT_ROOT / "dashboard" / "data" / "deep_cards_seed.jsonl"
    SeedIngestService(seed_path=seed_path, db_path=db_path,
                       config_dir=server.CONFIG_DIR).run()
    return TestClient(server.app)


def test_graph_has_35_plus_nodes_after_seed(client_with_seed: TestClient) -> None:
    """spec § 8.1 — seed ingest 后 graph 节点 ≥ 35。"""
    resp = client_with_seed.get("/api/overview/graph.json")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["nodes"]) >= 35, f"got {len(body['nodes'])} nodes, need ≥ 35"


def test_graph_has_10_plus_edges_after_seed(client_with_seed: TestClient) -> None:
    """spec § 8.1 — seed ingest 后 graph 边 ≥ 10(linked_capabilities 派生)。"""
    resp = client_with_seed.get("/api/overview/graph.json")
    body = resp.json()
    assert len(body["edges"]) >= 10, f"got {len(body['edges'])} edges, need ≥ 10"


def test_graph_edges_carry_weight_field(client_with_seed: TestClient) -> None:
    """Plan 3 Task 1 — 每个 edge 有 weight 字段(0.6 或 1.2)。"""
    resp = client_with_seed.get("/api/overview/graph.json")
    body = resp.json()
    for e in body["edges"]:
        assert "weight" in e["data"]
        assert e["data"]["weight"] in (0.6, 1.2)
```

- [ ] **Step 2: Verify**

```bash
uv run pytest dashboard/tests/integration/test_overview_after_seed.py -v
```

期望全绿(Plan 1 + Plan 3 串起来 ship gate 守护)。

commit `test(harness-board): L2 e2e graph after seed ingest`

---

## Task 9:L2 Playwright e2e(可选,skip by default)

**Files:**
- Create: `dashboard/tests/e2e/__init__.py`
- Create: `dashboard/tests/e2e/test_refresh_flow.py`
- Modify: `pyproject.toml` 或 `pytest.ini`(注册 `e2e` marker,Plan 2 若已注册可跳过)

**目标:** spec § 6 第 7 行 + § 8.4 — 提供 Playwright 完整 flow 但默认 skip(`@pytest.mark.e2e`),nightly CI 用 `pytest -m e2e` 跑。本 task 仅落代码,**不阻断 plan ship**(Playwright 依赖未安装的 CI 不跑)。

- [ ] **Step 1: 注册 marker(若 Plan 2 未做)**

`pyproject.toml`(检查 `[tool.pytest.ini_options]` 节):

```toml
[tool.pytest.ini_options]
markers = [
    "e2e: Playwright end-to-end tests (skip by default, nightly only)",
]
addopts = "-m 'not e2e'"
```

- [ ] **Step 2: 写 e2e 测试**

```python
# dashboard/tests/e2e/test_refresh_flow.py
"""Plan 3 L2 e2e (Playwright) — refresh flow + overview render。

默认 skip;nightly 跑 `pytest -m e2e`。需:
    uv pip install playwright pytest-playwright
    uv run playwright install chromium
"""
from __future__ import annotations

import pytest

pytest.importorskip("playwright")

pytestmark = pytest.mark.e2e


def test_refresh_flow_completes_and_reloads(page) -> None:
    """打开 /,点 refresh 按钮,5 step 完成,自动 reload。"""
    page.goto("http://127.0.0.1:8910/")
    page.click(".btn-refresh")
    # 等 5 行都不再 pending
    page.wait_for_selector('.refresh-step[data-step="snapshot_finalize"][data-state="done"]',
                           timeout=20_000)
    # done 后 5s + 800ms fade,~6s 内会 reload
    page.wait_for_url("**/", timeout=10_000)


def test_overview_renders_35_plus_nodes(page) -> None:
    page.goto("http://127.0.0.1:8910/overview")
    page.wait_for_function(
        "() => document.querySelectorAll('#overview-canvas canvas').length > 0",
        timeout=10_000,
    )
    # cytoscape 内部节点数无法直接读,改用 console eval
    node_count = page.evaluate("() => window.cy ? window.cy.nodes().length : 0")
    assert node_count >= 35  # 注:本检查需 overview.js 暴露 window.cy
```

> 注:`overview.js` 当前 `cy` 是 closure 局部变量;若 e2e 要 evaluate,Task 2 可顺便加 `window.cy = cy;`(便于调试)。**非阻断**。

- [ ] **Step 3: Verify**

```bash
uv run pytest dashboard/tests/e2e/ -v   # 默认 skip(addopts -m 'not e2e')
uv run pytest dashboard/tests/e2e/ -v -m e2e  # 需 Playwright 安装才跑
```

commit `test(harness-board): optional Playwright e2e refresh flow (skip by default)`

---

## Task 10:Dogfood + ship gate + memory 总卡

**Files:**
- Modify: `README.md`(V2 polish 章节)
- Modify: `CLAUDE.md`(Harness Board 段索引)
- Memory: `harness-board-v2-polish-done`(落 memory 总卡)

**目标:** spec § 8 ship gate 5 项验收逐条 dogfood + 记录;落 memory 总卡;Plan 3 final commit。

- [ ] **Step 1: Dogfood checklist 逐项跑**

按 spec § 8:

1. **鸟瞰 (§ 8.1):**
   - [ ] 浏览器打开 `/overview` → 节点数 ≥ 35,edges ≥ 10
   - [ ] memory 维度成簇(`#d4824a` 一簇),lit 节点周围有 amber 外发光
   - [ ] hover 任一节点 → tooltip 显示 `{name} · conf X/5` 或 `· 待填 DeepCard`
   - [ ] DevTools console:无 error

2. **一键更新 (§ 8.2):**
   - [ ] nav-rail 底部琥珀 refresh 按钮可见,hover 旋转 180°
   - [ ] 点击展开 240×360 面板
   - [ ] 5 个 step 依次 ○ → ⟳ → ✓,无 milvus env 时第 4 行 ⊘(skip),第 5 仍 done
   - [ ] 完成后 5 秒 fade,自动 `location.reload()`
   - [ ] reload 后主页 snapshot refreshed_at 是新时间

3. **视觉 (§ 8.3):**
   - [ ] 5 视图(网格 / 鸟瞰 / 故事 / 闪卡 / 决策)+ DeepCard modal + flashcards_stats 全跟 mockup-v2.html 视觉一致
   - [ ] Newsreader / Source Han Serif / Manrope / Geist Mono 加载成功(DevTools Network 校验)
   - [ ] 双强调(amber 主 / teal 次)用色正确
   - [ ] **本 plan 必证:** 空状态(< 5 nodes 浮条)/ loading(SSE running 状态)/ error(refresh error 行)/ toast(SSE 断连)/ modal fade(refresh 完成 800ms fade)**各被用到至少 1 次**

4. **测试 (§ 8.4):**
   - [ ] `uv run pytest dashboard/tests/unit dashboard/tests/integration -v` 全绿
   - [ ] `uv run mypy dashboard` strict 全绿
   - [ ] `uv run ruff check dashboard` clean

5. **降级 (§ 8.5):**
   - [ ] `unset OPENAI_API_KEY HARNESS_BOARD_MILVUS_HOST && uv run uvicorn ...`
   - [ ] 点 refresh → 5 step 全跑完,milvus 行 ⊘ skip "milvus disabled" / "embedding key missing"
   - [ ] 主页继续可用,无 500

每条打 ✓ 才能 ship。

- [ ] **Step 2: README V2 polish 段加 dogfood 总览**

`README.md` 加(或更新)章节:

```markdown
### v0.9.6 Harness Board V2 Polish

- UI 全面重写为 Quiet Workshop 设计语言(暖黑作坊感)
- `/refresh` 升级 SSE 5-step pipeline:chip_resolve / seed_ingest / decision_extract / milvus_reindex(可降级)/ snapshot_finalize
- nav-rail 底部琥珀 refresh 按钮 → 240×360 SSE 进度面板
- 鸟瞰修复:lifespan + refresh 双触发 seed ingest 保证 ≥ 35 张 DeepCard
- 鸟瞰增强:节点 amber glow / edge confidence 加权 / hover tooltip / 空状态浮条
- flashcards_stats 新视觉:圆环进度 + 时间线 + 8 维 × conf 散点
- L0 + L1 + L2 e2e 守护;Playwright e2e 可选(`pytest -m e2e`)

Ship gate(§ 8):节点 ≥ 35 / SSE 全跑通 / 视觉对齐 mockup / 测试全绿 / 降级不挂。
```

- [ ] **Step 3: CLAUDE.md Harness Board 段索引更新**

加 v2 polish 完成索引(Plan 1/2/3 文件路径)。

- [ ] **Step 4: 落 memory 总卡**

新增 memory `harness-board-v2-polish-done`,内容:

```
Harness Board v2 Polish ship 完成(2026-05-14)

3 plan 全 ship:
- Plan 1: 后端 SSE pipeline + SeedIngestService + lifespan
- Plan 2: 前端 Quiet Workshop 重写 + 13 模板 + fingerprint SVG
- Plan 3: 鸟瞰增强 + flashcards stats + refresh JS + L2 e2e

关键决策 anchor:
- /refresh 改 SSE in-process(非 Celery),5 step;milvus 单点可降级(skip 不阻断)
- seed ingest insert-if-missing(保护用户编辑);CLI 退化为薄包装 + --force
- 设计语言 Quiet Workshop:暖黑 + amber/teal 双强调 + Newsreader/Manrope/Geist Mono
- 节点 glow 用 cytoscape overlay-color(不原生 box-shadow)
- edge confidence 加权:两端 min(conf) ≥ 4 → width 1.2 实线;否则 0.6 半透 dashed
- refresh-panel.js ESC 关面板不取消 EventSource(可恢复中途状态)
- flashcards_stats 数据走 /api/flashcards/stats.json,前端纯 SVG 渲染无 build step

下次相关改动看:
- spec: docs/superpowers/specs/2026-05-14-harness-board-v2-polish-design.md
- mockup: dashboard/static/mockup-v2.html(design source-of-truth,保留)
```

- [ ] **Step 5: Final commit**

```bash
git add README.md CLAUDE.md
git commit -m "feat(harness-board): v2 polish ship — Plan 3 dogfood done"
```

确保 PR 题:`feat(harness-board): V2 polish — UI 重写 + 鸟瞰修复 + 一键 SSE 全量更新`

---

## Plan 3 完成判定

所有 Task 1-10 checkbox 打 ✓ + spec § 8 五条验收全绿 + memory 总卡落 ✓ → Plan 3 ship。

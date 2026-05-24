# Harness Board 框架重做 — Plan 3:首页 Topology 关系图 + 退役 overview/decisions/survey 子页 + 清理暂留类型

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把看板首页从 D-view 7 维 grid + B-view Kanban + App Shell 三段重写为单一 **ETCLOVG Topology 关系图**(论文 §2.3 锚定:E 底盘 / TCL 中段三件套 / OG 顶横切 / V 旁路),点击模块跳 `/m/{dim_id}`。同时退役 `/overview`(cytoscape)/ `/decisions` / `/survey` 3 个子页 + 对应 partials + derive + 11 个测试文件;清掉 Plan 1 暂留的 SrsState/Flashcard/TemplateKind 类型 + graph_builder 模块。Plan 3 ship 后,看板剩 4 页:`/` / `/m/{dim}` / `/story`(Plan 4 改造) / `/healthz`。

**Architecture:** 自上而下 — 先建 Topology(`_topology_diagram.html` SVG + topology_layout.py + main.html 重写)→ 退役 4 子页(每页一个 task,删 route + handler + template + derive 模块 + 测试)→ 清类型 + graph_builder(grep 验证无引用 → 删)→ nav-rail 重写 + CSS 大瘦身 → smoke + ship 标记。

**Tech Stack:** Starlette · Jinja2 · 内嵌 SVG(无外部 lib) · Python 3.11 · pytest · uv · pre-commit(ruff + mypy + commit-msg validator)。

---

## File Structure

```
新增:
  dashboard/derive/topology_layout.py            (7 模块坐标 + 连线 + 进度计算)
  dashboard/templates/_topology_diagram.html     (SVG 首页主图,可点击)
  dashboard/tests/unit/test_topology_layout.py
  dashboard/tests/integration/test_topology_homepage.py

重写:
  dashboard/templates/main.html                  (hero 简文 + Topology + 进度带状条;删 view-toggle / d-view / b-view / app-shell-row)
  dashboard/templates/_board_nav.html            (去 letter shortcuts + 子页入口;留 首页 / 故事 / refresh)
  dashboard/static/style.css                     (大瘦身 — 删 layer-stack / kanban / view-toggle / hero / app-shell / overview-frame / 旧 .dot-* class)

修改:
  dashboard/server.py                            (删 overview / decisions / survey routes + handlers + import)
  dashboard/derive/deep_card_types.py            (删 SrsState / Flashcard / TemplateKind 类)

删除文件:
  dashboard/templates/overview.html
  dashboard/templates/overview_fallback.html
  dashboard/templates/survey.html
  dashboard/templates/decisions.html
  dashboard/templates/_hero.html
  dashboard/templates/_view_toggle.html
  dashboard/templates/_d_view.html
  dashboard/templates/_b_view.html
  dashboard/templates/_app_shell.html
  dashboard/templates/_d_b_toggle.html
  dashboard/templates/_decision_card.html
  dashboard/templates/_decision_filter.html
  dashboard/templates/_decision_note_form.html
  dashboard/templates/_edit_select.html
  dashboard/templates/_story_card.html           (Plan 4 重做 /story 时一并清,Plan 3 不动 — 见 § Plan boundary)
  dashboard/derive/graph_builder.py
  dashboard/derive/survey_loader.py
  dashboard/derive/app_shell_stat.py
  dashboard/static/overview.js
  dashboard/static/cytoscape.min.js
  dashboard/static/cytoscape-cose-bilkent.min.js
  dashboard/static/mockup-v2.html
  dashboard/tests/unit/test_graph_builder.py
  dashboard/tests/derive/test_app_shell_stat.py
  dashboard/tests/integration/test_overview_endpoint.py
  dashboard/tests/integration/test_overview_after_seed.py
  dashboard/tests/integration/test_related_endpoint.py        (其实可能保留 — verify 时决定)
  dashboard/tests/server/test_decisions_endpoint.py
  dashboard/state/__init__.py (若需调整)
```

---

## Plan boundary

**本 plan 做:**
- 首页 Topology 关系图
- 退役 /overview, /decisions, /survey + 对应模板 + derive + 测试
- 清 SrsState / Flashcard / TemplateKind 类型(deep_card_types.py)+ graph_builder
- nav-rail 重写(去 Plan 2 临时 letter shortcuts 和退役的子页入口)
- CSS 大瘦身

**本 plan 不动**(留 Plan 4):
- `/story` 改造(textarea + skill 接口占位,base.html 的 marked / mermaid CDN Plan 2 已引)
- `_story_card.html`(/story 还在用,Plan 4 重写)
- `story_builder.py`(/story 用,Plan 4 退役)
- DeepCard 60+ × 6 字段内容填充(后续协作轮)
- 实现效果截图(用户提供)

---

## Task 0:准备 — baseline grep + verify clean

**Files:** None modified

- [ ] **Step 0.1:Verify clean + baseline**

```bash
git status --short
uv run pytest dashboard/tests/ -q 2>&1 | tail -3
uv run mypy dashboard/ 2>&1 | tail -3
```
Expected: clean / all pass / 0 mypy issue / 3 skip。记录 baseline pytest pass 数(214 expected after Plan 2)。

- [ ] **Step 0.2:grep — 退役模块的所有引用面**

```bash
grep -rnE "graph_builder|survey_loader|app_shell_stat|story_builder|SrsState|Flashcard|TemplateKind|decisions_view|overview_view|survey_view|_hero\.html|_view_toggle|_d_view|_b_view|_app_shell|_decision_card|_decision_filter|_decision_note|_edit_select|_story_card|overview\.html|overview_fallback|survey\.html|decisions\.html" dashboard/ backend/ --include="*.py" --include="*.html" 2>&1 | grep -v __pycache__ | head -50
```

记录输出 — 这些是后续 task 的清理目标(避免 Task 8 漏 grep 的教训)。

- [ ] **Step 0.3:Read main.html 当前结构(后续重写参考)**

```bash
cat dashboard/templates/main.html
```

应该看到 hero + view-toggle + view-content(D-view 或 B-view) + app-shell。

---

## Task 1:topology_layout.py + _topology_diagram.html SVG

**Files:**
- Create: `dashboard/derive/topology_layout.py`
- Create: `dashboard/templates/_topology_diagram.html`
- Test: `dashboard/tests/unit/test_topology_layout.py`

**Topology 视觉锚定**(论文 §2.3 语义):
```
viewBox="0 0 960 540"

   顶部横切带 (y 14-58):G · 治理(x 20-150) | O · 可观测(x 170-300, 后续 — 仅 left side)
   中段三件套 (y 90-200):T(x 20-150) | C(x 170-300) | L(x 310-440)
   底盘 (y 232-280):E · Execution & Sandbox(x 20-440,宽底)
   旁路 V (y 232-280, x 460-540):紧贴右侧

   连线(MVP — 装饰性,不强语义):
   - G → T/C/L cross-cut
   - O → T/C/L cross-cut
   - T/C/L → E vertical
   - V → L horizontal arrow
```

> **简化:**SVG viewBox 0 0 600 320 即可(实际 layout 在 600×320 内,响应式 100% 宽度自适应)。

- [ ] **Step 1.1:Create topology_layout.py**

```python
"""Plan 3 Task 1 — 首页 Topology SVG 7 模块坐标 + 进度计算。

论文 §2.3 关系语义:G/O 顶横切 · TCL 中段三件套 · V 旁路 · E 底盘。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModuleBox:
    dim_id: str
    letter: str  # E/T/C/L/O/V/G
    name_cn: str
    paper_section: str  # 论文 § N
    x: int
    y: int
    width: int
    height: int


# viewBox: 600 x 320
MODULES: tuple[ModuleBox, ...] = (
    # 顶部横切带 (y 14-58)
    ModuleBox("governance",    "G", "治理",      "§ 9", 20,  14,  220, 44),
    ModuleBox("observability", "O", "可观测",    "§ 7", 260, 14,  220, 44),
    # 中段三件套 (y 90-200)
    ModuleBox("tool",          "T", "工具",      "§ 4", 20,  90,  140, 100),
    ModuleBox("context",       "C", "上下文",    "§ 5", 180, 90,  140, 100),
    ModuleBox("lifecycle",     "L", "生命周期",  "§ 6", 340, 90,  140, 100),
    # 底盘 (y 232-280)
    ModuleBox("execution",     "E", "执行环境",  "§ 3", 20,  232, 380, 48),
    # 旁路 V (右侧紧贴)
    ModuleBox("verification",  "V", "验证",      "§ 8", 420, 232, 80,  48),
)


@dataclass(frozen=True)
class ConnLine:
    """模块间连线:from box id → to box id;type 决定样式(dashed=cross-cut, solid=runtime)。"""

    from_id: str
    to_id: str
    type: str  # "cross_cut" | "runtime" | "bypass"


CONNECTIONS: tuple[ConnLine, ...] = (
    # G/O cross-cut → TCL
    ConnLine("governance", "tool", "cross_cut"),
    ConnLine("governance", "context", "cross_cut"),
    ConnLine("governance", "lifecycle", "cross_cut"),
    ConnLine("observability", "tool", "cross_cut"),
    ConnLine("observability", "context", "cross_cut"),
    ConnLine("observability", "lifecycle", "cross_cut"),
    # TCL → E (runtime)
    ConnLine("tool", "execution", "runtime"),
    ConnLine("context", "execution", "runtime"),
    ConnLine("lifecycle", "execution", "runtime"),
    # V bypass → L
    ConnLine("verification", "lifecycle", "bypass"),
)


@dataclass(frozen=True)
class ModuleProgress:
    dim_id: str
    letter: str
    name_cn: str
    paper_section: str
    x: int
    y: int
    width: int
    height: int
    lit: int
    wip: int
    todo: int
    total: int

    @property
    def pct(self) -> int:
        return int((self.lit / self.total) * 100) if self.total else 0


def layout_with_progress(
    snap_layers: list[dict],
) -> list[ModuleProgress]:
    """合并 MODULES 几何 + snapshot 进度。snap_layers from build_snapshot().to_dict()['layers']。"""
    by_id = {L["id"]: L for L in snap_layers}
    out: list[ModuleProgress] = []
    for m in MODULES:
        L = by_id.get(m.dim_id)
        if L is None:
            out.append(
                ModuleProgress(
                    dim_id=m.dim_id, letter=m.letter, name_cn=m.name_cn,
                    paper_section=m.paper_section,
                    x=m.x, y=m.y, width=m.width, height=m.height,
                    lit=0, wip=0, todo=0, total=0,
                )
            )
            continue
        out.append(
            ModuleProgress(
                dim_id=m.dim_id, letter=m.letter, name_cn=m.name_cn,
                paper_section=m.paper_section,
                x=m.x, y=m.y, width=m.width, height=m.height,
                lit=int(L.get("lit", 0)),
                wip=int(L.get("wip", 0)),
                todo=int(L.get("todo", 0)),
                total=int(L.get("total", 0)),
            )
        )
    return out


def connection_endpoints(
    modules_by_id: dict[str, ModuleProgress],
) -> list[tuple[ConnLine, tuple[int, int], tuple[int, int]]]:
    """计算每条连线的起止点(box edge 中点)。"""
    out = []
    for c in CONNECTIONS:
        a = modules_by_id.get(c.from_id)
        b = modules_by_id.get(c.to_id)
        if a is None or b is None:
            continue
        # MVP: from box bottom-center to to box top-center(适合上→下场景);
        # 横向情况下用 right-center → left-center
        if a.y + a.height <= b.y:
            ax, ay = a.x + a.width // 2, a.y + a.height
            bx, by = b.x + b.width // 2, b.y
        elif b.y + b.height <= a.y:
            ax, ay = a.x + a.width // 2, a.y
            bx, by = b.x + b.width // 2, b.y + b.height
        else:
            # 横向
            if a.x < b.x:
                ax, ay = a.x + a.width, a.y + a.height // 2
                bx, by = b.x, b.y + b.height // 2
            else:
                ax, ay = a.x, a.y + a.height // 2
                bx, by = b.x + b.width, b.y + b.height // 2
        out.append((c, (ax, ay), (bx, by)))
    return out
```

- [ ] **Step 1.2:Write unit test for topology_layout**

Create `dashboard/tests/unit/test_topology_layout.py`:

```python
"""Plan 3 Task 1 — topology_layout 单测。"""

from __future__ import annotations

from dashboard.derive.topology_layout import (
    CONNECTIONS,
    MODULES,
    connection_endpoints,
    layout_with_progress,
)


def test_modules_have_all_7_dims() -> None:
    ids = {m.dim_id for m in MODULES}
    assert ids == {
        "execution", "tool", "context", "lifecycle",
        "observability", "verification", "governance",
    }


def test_connections_use_valid_ids() -> None:
    valid_ids = {m.dim_id for m in MODULES}
    for c in CONNECTIONS:
        assert c.from_id in valid_ids
        assert c.to_id in valid_ids


def test_connections_have_3_types() -> None:
    types = {c.type for c in CONNECTIONS}
    assert types == {"cross_cut", "runtime", "bypass"}


def test_layout_with_progress_returns_7() -> None:
    fake_layers = [
        {"id": dim_id, "lit": 3, "wip": 1, "todo": 5, "total": 9}
        for dim_id in [
            "execution", "tool", "context", "lifecycle",
            "observability", "verification", "governance",
        ]
    ]
    out = layout_with_progress(fake_layers)
    assert len(out) == 7
    for m in out:
        assert m.lit == 3
        assert m.pct == int(3 / 9 * 100)


def test_layout_handles_missing_dim() -> None:
    """snapshot 没有某 dim 时, 该 module 的 lit/wip/todo/total 全 0。"""
    fake_layers = [{"id": "execution", "lit": 1, "wip": 0, "todo": 0, "total": 1}]
    out = layout_with_progress(fake_layers)
    by_id = {m.dim_id: m for m in out}
    assert by_id["governance"].total == 0
    assert by_id["execution"].lit == 1


def test_connection_endpoints_no_dangling() -> None:
    """所有连线都能算出端点。"""
    fake_layers = [
        {"id": dim_id, "lit": 0, "wip": 0, "todo": 0, "total": 0}
        for dim_id in [
            "execution", "tool", "context", "lifecycle",
            "observability", "verification", "governance",
        ]
    ]
    progress = layout_with_progress(fake_layers)
    by_id = {m.dim_id: m for m in progress}
    endpoints = connection_endpoints(by_id)
    assert len(endpoints) == len(CONNECTIONS)
    for _, (ax, ay), (bx, by) in endpoints:
        assert 0 <= ax <= 600
        assert 0 <= ay <= 320
        assert 0 <= bx <= 600
        assert 0 <= by <= 320
```

- [ ] **Step 1.3:Run test**(6 PASS)

`uv run pytest dashboard/tests/unit/test_topology_layout.py -v 2>&1 | tail -10`

- [ ] **Step 1.4:Create `_topology_diagram.html`**

```html
{# Plan 3 Task 1 — ETCLOVG Topology 关系图 (论文 §2.3) #}
<svg class="topology-svg"
     viewBox="0 0 600 320"
     xmlns="http://www.w3.org/2000/svg"
     role="img"
     aria-label="ETCLOVG 7 模块关系图">
  <defs>
    <marker id="arrowhead" viewBox="0 0 8 8" refX="6" refY="4"
            markerWidth="6" markerHeight="6" orient="auto">
      <path d="M 0 0 L 8 4 L 0 8 z" fill="rgba(94,92,230,0.45)"/>
    </marker>
  </defs>

  {# 连线层 (在 boxes 下面渲染) #}
  <g class="topology-edges">
    {% for c, (ax, ay), (bx, by) in topology_endpoints %}
      <line x1="{{ ax }}" y1="{{ ay }}" x2="{{ bx }}" y2="{{ by }}"
            class="edge edge-{{ c.type }}"
            stroke="rgba(94,92,230,0.40)"
            stroke-width="1"
            stroke-dasharray="{{ '4 3' if c.type == 'cross_cut' else ('2 2' if c.type == 'bypass' else 'none') }}"
            marker-end="url(#arrowhead)"/>
    {% endfor %}
  </g>

  {# 模块矩形层 #}
  <g class="topology-boxes">
    {% for m in topology_modules %}
      <a href="/m/{{ m.dim_id }}" class="topology-link">
        <g class="topology-box topology-box--{{ m.dim_id }}"
           data-dim-id="{{ m.dim_id }}">
          <rect x="{{ m.x }}" y="{{ m.y }}"
                width="{{ m.width }}" height="{{ m.height }}"
                rx="8" ry="8"
                class="box-rect"
                fill="white"
                stroke="rgba(60,60,67,0.18)"
                stroke-width="1"/>
          {# Letter (大代号) #}
          <text x="{{ m.x + 12 }}" y="{{ m.y + 26 }}"
                class="box-letter"
                font-family="'Geist Mono', monospace"
                font-size="18"
                font-weight="600"
                fill="#5E5CE6">{{ m.letter }}</text>
          {# 中文名 #}
          <text x="{{ m.x + 36 }}" y="{{ m.y + 22 }}"
                class="box-name"
                font-family="-apple-system, 'SF Pro Text', sans-serif"
                font-size="13"
                font-weight="500"
                fill="#1C1C1E">{{ m.name_cn }}</text>
          {# 论文 § 锚 #}
          <text x="{{ m.x + m.width - 8 }}" y="{{ m.y + 14 }}"
                class="box-anchor"
                text-anchor="end"
                font-family="-apple-system, sans-serif"
                font-size="9"
                fill="#86868B">{{ m.paper_section }}</text>
          {# 状态条 (3 段颜色:lit绿 / wip橙 / todo灰) — 只在 box 高 ≥ 60 时画 #}
          {% if m.height >= 60 and m.total > 0 %}
            {% set bar_y = m.y + m.height - 14 %}
            {% set bar_x = m.x + 10 %}
            {% set bar_w = m.width - 20 %}
            {% set lit_w = (bar_w * m.lit / m.total) | int %}
            {% set wip_w = (bar_w * m.wip / m.total) | int %}
            {% set todo_w = bar_w - lit_w - wip_w %}
            <rect x="{{ bar_x }}" y="{{ bar_y }}"
                  width="{{ lit_w }}" height="4" rx="2"
                  fill="#34C759"/>
            <rect x="{{ bar_x + lit_w }}" y="{{ bar_y }}"
                  width="{{ wip_w }}" height="4"
                  fill="#FF9F0A"/>
            <rect x="{{ bar_x + lit_w + wip_w }}" y="{{ bar_y }}"
                  width="{{ todo_w }}" height="4" rx="2"
                  fill="#C7C7CC"/>
            <text x="{{ bar_x }}" y="{{ bar_y - 4 }}"
                  class="box-stat"
                  font-family="'Geist Mono', monospace"
                  font-size="9"
                  fill="#86868B">{{ m.lit }}/{{ m.total }}</text>
          {% else %}
            {# 横/扁 box(E + V):右侧显示统计 #}
            <text x="{{ m.x + m.width - 8 }}" y="{{ m.y + m.height - 8 }}"
                  text-anchor="end"
                  class="box-stat"
                  font-family="'Geist Mono', monospace"
                  font-size="10"
                  fill="#86868B">{{ m.lit }}/{{ m.total }}</text>
          {% endif %}
        </g>
      </a>
    {% endfor %}
  </g>

  {# Legend (顶部右侧小注) #}
  <g class="topology-legend">
    <text x="590" y="305" text-anchor="end"
          font-family="-apple-system, sans-serif" font-size="9"
          fill="#86868B">— cross-cut · ⋯ bypass · → runtime</text>
  </g>
</svg>
```

- [ ] **Step 1.5:Commit Task 1**

```bash
git add dashboard/derive/topology_layout.py dashboard/templates/_topology_diagram.html dashboard/tests/unit/test_topology_layout.py
git commit -m "feat(harness-board): topology layout + _topology_diagram.html SVG (Plan 3 step 1)"
```

---

## Task 2:重写 main.html(Topology 占首页 + hero 简文)

**Files:**
- Rewrite: `dashboard/templates/main.html`
- Modify: `dashboard/server.py`(`index` handler 改造 — 把 layers 转 topology_modules + endpoints 喂模板)
- Modify: `dashboard/static/style.css`(加 .topology-* CSS)
- Test: `dashboard/tests/integration/test_topology_homepage.py`

- [ ] **Step 2.1:Read 当前 index handler**

```bash
grep -nA 30 "async def index" dashboard/server.py
```
看当前 index 怎么拼 ctx。

- [ ] **Step 2.2:改造 index handler — 加 topology 数据**

定位 `async def index`,在已有 snapshot build 之后(snap 拿到后)加:

```python
    # Plan 3 Task 2 — Topology 数据
    from dashboard.derive.topology_layout import (
        connection_endpoints, layout_with_progress,
    )
    topology_modules = layout_with_progress(snap["layers"])
    topology_endpoints = connection_endpoints({m.dim_id: m for m in topology_modules})
```

并在 ctx 中追加:
```python
        "topology_modules": topology_modules,
        "topology_endpoints": topology_endpoints,
```

> 注:原 `wips` / `app_shell` 等仍然保留(main.html 重写后 wips 仍用,但 app_shell 不用 — 还是先保留 ctx,模板不用即可,后续 Task 6 退役)。

- [ ] **Step 2.3:重写 main.html**

替换整文件内容:

```html
{# Plan 3 Task 2 — 首页:hero 简文 + ETCLOVG Topology 关系图 #}
{% extends "base.html" %}
{% block nav %}{% include "_board_nav.html" %}{% endblock %}
{% block content %}

<section class="hero-block">
  <div class="stage">
    <div class="hero-meta reveal d1">
      <span class="pill">Li et al. · ETCLOVG · 2026</span>
      <span>{{ today }} · {{ snap.total }} capabilities · {{ snap.total_lit }} lit / {{ snap.total_wip }} wip / {{ snap.total_todo }} todo</span>
    </div>
    <h1 class="hero-title reveal d2">
      <em>Harness</em>,<br>
      不是<em class="cool">模型</em>。
    </h1>
    <p class="hero-sub reveal d3">
      <em>Prompt</em>(2022) → <em class="cool">Context</em>(2025) → <em>Harness</em>(2026),
      工程重心正在迁移。下图是论文 §2.3 的 ETCLOVG 7 模块关系 — <span class="accent">点任意模块进入详情</span>。
    </p>
  </div>
</section>

<section class="topology-block">
  <div class="stage">
    {% include "_topology_diagram.html" %}
    <p class="topology-caption">
      <span class="caption-tag">G · 治理</span> +
      <span class="caption-tag">O · 可观测</span> 横切所有层 ·
      <span class="caption-tag">T · 工具</span> /
      <span class="caption-tag">C · 上下文</span> /
      <span class="caption-tag">L · 生命周期</span> 是每一步的三件套 ·
      <span class="caption-tag">V · 验证</span> 离线旁路 ·
      <span class="caption-tag">E · 执行环境</span> 底盘 chassis
    </p>
  </div>
</section>

{% if wips %}
<section class="hero-wips-block">
  <div class="stage">
    <div class="hero-wips">
      <span class="label">In flux ›</span>
      {% for c in wips %}
        <a href="/m/{{ c.dimension }}#cap-{{ c.id }}">{{ c.name_cn }}</a>
      {% endfor %}
    </div>
  </div>
</section>
{% endif %}

{% endblock %}
```

- [ ] **Step 2.4:加 .topology-* CSS(style.css 末尾追加)**

```css
/* ============================================================
 * Plan 3 Task 2 — Topology homepage
 * ============================================================ */
.topology-block { padding: 24px 0 40px; }
.topology-svg {
  max-width: 880px;
  margin: 30px auto 20px;
  display: block;
  width: 100%;
  height: auto;
}
.topology-box {
  cursor: pointer;
  transition: transform 0.18s, filter 0.18s;
}
.topology-box .box-rect {
  transition: stroke 0.18s, fill 0.18s;
}
.topology-box:hover .box-rect {
  stroke: #5E5CE6;
  stroke-width: 1.5;
  fill: rgba(94,92,230,0.04);
}
.topology-box:hover { filter: drop-shadow(0 2px 4px rgba(94,92,230,0.15)); }

/* G / O 顶横切带 — 浅 indigo 背景 */
.topology-box--governance .box-rect,
.topology-box--observability .box-rect { fill: rgba(94,92,230,0.06); }
/* E 底盘 — 浅灰 */
.topology-box--execution .box-rect { fill: rgba(245,245,247,0.6); }

.topology-link { text-decoration: none; outline: none; }
.topology-link:focus .box-rect { stroke: #5E5CE6; stroke-width: 2; }

.topology-caption {
  text-align: center;
  font-size: 12px;
  color: #86868B;
  margin: 12px auto 0;
  max-width: 760px;
  line-height: 1.8;
}
.caption-tag {
  display: inline-block;
  padding: 1px 8px;
  background: rgba(60,60,67,0.05);
  border-radius: 10px;
  margin: 0 2px;
  font-family: 'Geist Mono', monospace;
  font-size: 11px;
  color: #1C1C1E;
}

.hero-wips-block { padding: 8px 0 24px; }
```

- [ ] **Step 2.5:Write tests**

Create `dashboard/tests/integration/test_topology_homepage.py`:

```python
"""Plan 3 Task 2 — 首页 Topology 渲染测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from dashboard import server


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    db = tmp_path / "test.db"
    monkeypatch.setattr(server, "DB_PATH", db)
    return TestClient(server.app)


def test_homepage_returns_200(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200


def test_homepage_renders_topology_svg(client: TestClient) -> None:
    resp = client.get("/")
    body = resp.text
    assert "topology-svg" in body
    assert 'viewBox="0 0 600 320"' in body


def test_homepage_shows_all_7_modules(client: TestClient) -> None:
    resp = client.get("/")
    body = resp.text
    # 7 letters + 7 dim_id 链接
    for letter in ["E", "T", "C", "L", "O", "V", "G"]:
        # box-letter text 含 letter
        assert f">{letter}</text>" in body, f"missing letter {letter}"
    for dim_id in [
        "execution", "tool", "context", "lifecycle",
        "observability", "verification", "governance",
    ]:
        assert f'href="/m/{dim_id}"' in body, f"missing link for {dim_id}"


def test_homepage_shows_paper_anchors(client: TestClient) -> None:
    """每个模块都有论文 § N 标注。"""
    resp = client.get("/")
    body = resp.text
    for sec in ["§ 3", "§ 4", "§ 5", "§ 6", "§ 7", "§ 8", "§ 9"]:
        assert sec in body


def test_homepage_includes_status_bars(client: TestClient) -> None:
    """状态条 — lit / wip / todo 颜色都在 SVG 里。"""
    resp = client.get("/")
    body = resp.text
    assert "#34C759" in body  # lit
    assert "#FF9F0A" in body  # wip
    assert "#C7C7CC" in body  # todo


def test_homepage_no_old_views(client: TestClient) -> None:
    """旧 D-view / B-view / view-toggle / app-shell 已退役。"""
    resp = client.get("/")
    body = resp.text
    assert "view-toggle" not in body
    assert "layer-stack" not in body
    assert "kanban" not in body
    assert "app-shell-row" not in body
```

- [ ] **Step 2.6:Run tests**(6 PASS)

`uv run pytest dashboard/tests/integration/test_topology_homepage.py -v 2>&1 | tail -10`

- [ ] **Step 2.7:Run existing test_main_endpoint.py — may need updates**

```bash
uv run pytest dashboard/tests/server/test_main_endpoint.py -v 2>&1 | tail -10
```

Expected: 若 fail(因为它断言旧 D-view / B-view 内容),改测试用新模板的断言(类似上面 test_homepage_no_old_views 的反向)。修复 test_main_endpoint.py 中失败的断言。

- [ ] **Step 2.8:Smoke**

```bash
uv run python -c "
from starlette.testclient import TestClient
from dashboard.server import app
client = TestClient(app)
r = client.get('/')
print('status:', r.status_code)
print('topology-svg:', 'topology-svg' in r.text)
print('href to /m/execution:', 'href=\"/m/execution\"' in r.text)
"
```

- [ ] **Step 2.9:Commit Task 2**

```bash
git add dashboard/server.py dashboard/templates/main.html dashboard/static/style.css dashboard/tests/integration/test_topology_homepage.py dashboard/tests/server/test_main_endpoint.py
git commit -m "feat(harness-board): rewrite main.html homepage = Topology SVG + hero + In flux (Plan 3 step 2)"
```

---

## Task 3:退役 /overview + cytoscape + graph_builder

**Files:**
- Delete: `dashboard/templates/overview.html`
- Delete: `dashboard/templates/overview_fallback.html`
- Delete: `dashboard/derive/graph_builder.py`
- Delete: `dashboard/static/overview.js`
- Delete: `dashboard/static/cytoscape.min.js`
- Delete: `dashboard/static/cytoscape-cose-bilkent.min.js`
- Delete: `dashboard/static/mockup-v2.html`
- Delete: `dashboard/tests/unit/test_graph_builder.py`
- Delete: `dashboard/tests/integration/test_overview_endpoint.py`
- Delete: `dashboard/tests/integration/test_overview_after_seed.py`
- Modify: `dashboard/server.py`(删 `overview_view`, `overview_fallback`, `overview_graph_json` handler + 3 Route)

- [ ] **Step 3.1:Confirm no external refs to graph_builder**

```bash
grep -rnE "graph_builder|build_graph|cytoscape" dashboard/ backend/ --include="*.py" --include="*.html" --include="*.js" | grep -v __pycache__ | head -10
```
Expected: 只在 待删文件本身 + 测试中。

- [ ] **Step 3.2:删 server.py 中 3 个 overview handler + Routes + imports**

```bash
grep -nE "async def overview_view|async def overview_fallback|async def overview_graph_json" dashboard/server.py
```

定位 3 个 handler,整段删除。然后定位 routes block 中:
```python
        Route("/overview", overview_view),
        Route("/overview/fallback", overview_fallback),
        Route("/api/overview/graph.json", overview_graph_json),
```
全部删。

最后清相关 import:
```bash
grep -nE "from dashboard\.derive\.graph_builder|import.*graph_builder" dashboard/server.py
```
所有 hit 行整行删。

- [ ] **Step 3.3:Smoke server import**

```bash
uv run python -c "from dashboard.server import app; print('routes count:', len(app.routes))"
```
Expected: import 通过,routes 比之前少 3。

- [ ] **Step 3.4:删 templates + static + derive + tests**

```bash
git rm dashboard/templates/overview.html \
       dashboard/templates/overview_fallback.html \
       dashboard/derive/graph_builder.py \
       dashboard/static/overview.js \
       dashboard/static/cytoscape.min.js \
       dashboard/static/cytoscape-cose-bilkent.min.js \
       dashboard/static/mockup-v2.html \
       dashboard/tests/unit/test_graph_builder.py \
       dashboard/tests/integration/test_overview_endpoint.py \
       dashboard/tests/integration/test_overview_after_seed.py
```

- [ ] **Step 3.5:Smoke /overview 应 404**

```bash
uv run python -c "
from starlette.testclient import TestClient
from dashboard.server import app
client = TestClient(app)
for path in ['/overview', '/overview/fallback', '/api/overview/graph.json']:
    print(f'{client.get(path).status_code}  {path}')
"
```
Expected: 全 404。

- [ ] **Step 3.6:全 pytest verify**

`uv run pytest dashboard/tests/ -q 2>&1 | tail -3`

- [ ] **Step 3.7:Commit**

```bash
git add dashboard/server.py
git commit -m "refactor(harness-board): retire /overview + cytoscape + graph_builder (Plan 3 step 3)"
```

---

## Task 4:退役 /decisions + handlers + partials + test

**Files:**
- Delete: `dashboard/templates/decisions.html`
- Delete: `dashboard/templates/_decision_card.html`
- Delete: `dashboard/templates/_decision_filter.html`
- Delete: `dashboard/templates/_decision_note_form.html`
- Delete: `dashboard/templates/_edit_select.html`
- Delete: `dashboard/static/decisions-filter.js`(若存在)
- Delete: `dashboard/tests/server/test_decisions_endpoint.py`
- Modify: `dashboard/server.py`(删 `decisions_view`, `post_decision_note`, `delete_decision_note`, `edit_capability`, `post_override` 5 handler + Routes;但保留 `decision_extractor.py` derive — 它是给 Plan 4 DeepCard 字段 5 用的数据源)

> **Note:** `post_override` 在 Plan 2 时 deprecate(被 `post_status` 取代),Plan 3 真正删除。但要 verify 没有遗留引用。

- [ ] **Step 4.1:Confirm**

```bash
grep -rnE "decisions_view|post_decision_note|delete_decision_note|edit_capability|post_override|_decision_card|_decision_filter|_decision_note_form|_edit_select|decisions-filter\.js" dashboard/ backend/ --include="*.py" --include="*.html" --include="*.js" | grep -v __pycache__ | head -20
```

- [ ] **Step 4.2:删 server.py 5 handler + 对应 Routes**

定位 5 个 handler:
```bash
grep -nE "^async def (decisions_view|post_decision_note|delete_decision_note|edit_capability|post_override)" dashboard/server.py
```
逐个整段删除函数体。

Routes block 中删:
```python
        Route("/decisions", decisions_view),
        Route("/decisions/{decision_id}/note", post_decision_note, methods=["POST"]),
        Route("/decisions/{decision_id}/note", delete_decision_note, methods=["DELETE"]),
        Route("/capability/{cap_id}/edit", edit_capability),
        Route("/capability/{cap_id}/override", post_override, methods=["POST"]),
```

- [ ] **Step 4.3:删 templates + tests**

```bash
git rm dashboard/templates/decisions.html \
       dashboard/templates/_decision_card.html \
       dashboard/templates/_decision_filter.html \
       dashboard/templates/_decision_note_form.html \
       dashboard/templates/_edit_select.html \
       dashboard/tests/server/test_decisions_endpoint.py
test -f dashboard/static/decisions-filter.js && git rm dashboard/static/decisions-filter.js || echo "no decisions-filter.js"
```

- [ ] **Step 4.4:Server smoke import + /decisions 404**

```bash
uv run python -c "
from starlette.testclient import TestClient
from dashboard.server import app
client = TestClient(app)
print(client.get('/decisions').status_code, '/decisions')
print(client.post('/decisions/x/note').status_code, '/decisions/x/note')
print(client.get('/capability/x/edit').status_code, '/capability/x/edit')
print(client.post('/capability/x/override').status_code, '/capability/x/override')
"
```
Expected: 全 404 / 405。

- [ ] **Step 4.5:全 pytest verify**

`uv run pytest dashboard/tests/ -q 2>&1 | tail -3`

- [ ] **Step 4.6:Commit**

```bash
git add dashboard/server.py
git commit -m "refactor(harness-board): retire /decisions routes + templates + 5 handlers (Plan 3 step 4)"
```

---

## Task 5:退役 /survey + survey_loader

**Files:**
- Delete: `dashboard/templates/survey.html`
- Delete: `dashboard/derive/survey_loader.py`
- Modify: `dashboard/server.py`(删 `survey_view` handler + Route)
- Modify: `dashboard/state/repositories.py`(若有 SurveyRepo,删)

- [ ] **Step 5.1:grep**

```bash
grep -rnE "survey_view|survey_loader|SurveyRepo|external_agent_survey" dashboard/ backend/ --include="*.py" --include="*.html" | grep -v __pycache__ | head -10
```

- [ ] **Step 5.2:删 handler + Route + import**

定位:`grep -nE "async def survey_view" dashboard/server.py`,整段删。删 Route `Route("/survey", survey_view)`. 删 `from dashboard.derive.survey_loader import ...` import。

- [ ] **Step 5.3:删 template + derive 模块**

```bash
git rm dashboard/templates/survey.html dashboard/derive/survey_loader.py
```

如有 `dashboard/tests/integration/test_survey_*.py` 或类似,也 git rm。

- [ ] **Step 5.4:Smoke /survey 404**

```bash
uv run python -c "
from starlette.testclient import TestClient
from dashboard.server import app
print(TestClient(app).get('/survey').status_code)
"
```
Expected: 404.

- [ ] **Step 5.5:全 pytest verify**

- [ ] **Step 5.6:Commit**

```bash
git add dashboard/server.py
git commit -m "refactor(harness-board): retire /survey + survey_loader (Plan 3 step 5)"
```

---

## Task 6:退役 _hero / view-toggle / d-view / b-view / app-shell / d-b-toggle + app_shell_stat derive

**Files:**
- Delete: 6 partial 模板
- Delete: `dashboard/derive/app_shell_stat.py`
- Delete: `dashboard/tests/derive/test_app_shell_stat.py`(若存在)
- Modify: `dashboard/server.py`(删 app_shell 相关 ctx + import)

- [ ] **Step 6.1:grep**

```bash
grep -rnE "_hero\.html|_view_toggle|_d_view|_b_view|_app_shell|_d_b_toggle|app_shell_stat|compute_app_shell_stat" dashboard/ backend/ --include="*.py" --include="*.html" | grep -v __pycache__ | head -10
```
Expected: 仅在 Plan 3 重写后未 cleanup 的 server.py 残留(在 Task 2 改 index ctx 时若没全删,会 hit 这里);其他无引用。

- [ ] **Step 6.2:确保 server.py 不再使用 app_shell**

```bash
grep -nE "app_shell|compute_app_shell_stat" dashboard/server.py
```
所有 hit 行整行删除。

- [ ] **Step 6.3:删 partials + derive + tests**

```bash
git rm dashboard/templates/_hero.html \
       dashboard/templates/_view_toggle.html \
       dashboard/templates/_d_view.html \
       dashboard/templates/_b_view.html \
       dashboard/templates/_app_shell.html \
       dashboard/templates/_d_b_toggle.html \
       dashboard/derive/app_shell_stat.py
test -f dashboard/tests/derive/test_app_shell_stat.py && git rm dashboard/tests/derive/test_app_shell_stat.py || true
```

- [ ] **Step 6.4:Server smoke**

```bash
uv run python -c "from dashboard.server import app; from starlette.testclient import TestClient; c = TestClient(app); print('/', c.get('/').status_code)"
```
Expected: 200.

- [ ] **Step 6.5:全 pytest verify**

- [ ] **Step 6.6:Commit**

```bash
git add dashboard/server.py
git commit -m "refactor(harness-board): retire _hero/_view_toggle/_d_view/_b_view/_app_shell + app_shell_stat (Plan 3 step 6)"
```

---

## Task 7:nav-rail 重写(去 letter shortcuts + 退役的子页入口)

**Files:**
- Rewrite: `dashboard/templates/_board_nav.html`

**目标 nav 内容**:
- Logo / 标识(保留)
- 首页(/)
- 故事(/story)
- refresh button

**移除:**
- Plan 2 加的 7 维 letter shortcuts(首页直接 Topology 图就能点)
- 决策 / 鸟瞰 / 调查 入口(子页退役)

- [ ] **Step 7.1:Read _board_nav.html**

`cat dashboard/templates/_board_nav.html`

- [ ] **Step 7.2:重写**

具体改造:删除所有 `<a href="/decisions">`, `<a href="/overview">`, `<a href="/survey">` 块,以及 Plan 2 加的 `<hr class="nav-sep">` + `<div class="nav-modules">` 整块。

保留:logo / 首页 / 故事 / refresh-btn(若有)。

- [ ] **Step 7.3:Smoke /**

```bash
uv run python -c "
from starlette.testclient import TestClient
from dashboard.server import app
r = TestClient(app).get('/')
# 检查 nav 里没有这些
print('/decisions in nav:', '/decisions' in r.text)
print('/overview in nav:', '/overview' in r.text)
print('/survey in nav:', '/survey' in r.text)
print('/story in nav:', '/story' in r.text)
print('letter shortcut E:', 'nav-mod' in r.text)
"
```
Expected: decisions / overview / survey False, story True, nav-mod False。

- [ ] **Step 7.4:Commit**

```bash
git add dashboard/templates/_board_nav.html
git commit -m "refactor(harness-board): rewrite nav-rail (drop letter shortcuts + retired subpage entries) (Plan 3 step 7)"
```

---

## Task 8:清 SrsState / Flashcard / TemplateKind 类型(deep_card_types.py)

**Files:**
- Modify: `dashboard/derive/deep_card_types.py`
- Modify: `dashboard/tests/unit/test_deep_card_types.py`(删 SrsState / Flashcard / TemplateKind 测试)

- [ ] **Step 8.1:Confirm 无引用**

```bash
grep -rnE "SrsState|TemplateKind|\bFlashcard\b" dashboard/ backend/ --include="*.py" --include="*.html" | grep -v __pycache__ | head -20
```
Expected: 仅在 `deep_card_types.py` 自身 + `test_deep_card_types.py` 中(其他文件 Plan 1 + Plan 3 之前已清)。

- [ ] **Step 8.2:删 SrsState class + TemplateKind type alias + Flashcard class(整 class 段删)**

打开 `dashboard/derive/deep_card_types.py`,定位:
- `class SrsState` 整段
- `TemplateKind = ...` 行
- `class Flashcard` 整段

整段删除。保留 DeepCard / CodeAnchor / FieldProvenance 等仍在用的类型。

- [ ] **Step 8.3:删 test 中相关测试**

打开 `dashboard/tests/unit/test_deep_card_types.py`,定位:
```bash
grep -nE "^def test_.*(srs|template_kind|flashcard)" dashboard/tests/unit/test_deep_card_types.py
```
逐个删除函数(整 `def test_xxx(...): ... ` 块直到下一个 `def` 或 EOF)。

也清头部 import 中 SrsState / Flashcard / TemplateKind token(留 DeepCard / CodeAnchor 等)。

- [ ] **Step 8.4:Run tests**(确认不含 sub class 的测试 pass)

`uv run pytest dashboard/tests/unit/test_deep_card_types.py -v 2>&1 | tail -10`

- [ ] **Step 8.5:mypy 整盘**

`uv run mypy dashboard/ 2>&1 | tail -3`
Expected: Success no issues。

- [ ] **Step 8.6:Commit**

```bash
git add dashboard/derive/deep_card_types.py dashboard/tests/unit/test_deep_card_types.py
git commit -m "refactor(harness-board): remove SrsState/Flashcard/TemplateKind types (Plan 3 step 8)"
```

---

## Task 9:CSS 大瘦身(style.css)

**Files:**
- Modify: `dashboard/static/style.css`

**目标:**删除 Plan 1 + Plan 3 已退役组件的 CSS — `.layer-stack` / `.layer` / `.kanban` / `.view-toggle` / `.view-tab` / `.hero-block` 的旧 grid layout / `.app-shell-row` / `.overview-frame` / `.overview-toolbar` / `.overview-canvas` / `.overview-legend` / `.overview-tooltip` / `.fingerprint` / `.fingerprint-caption` / `.dot-prompt` / `.dot-tools` / `.dot-orch` / `.dot-memory` / `.dot-rag` / `.dot-guard` / `.dot-eval` / `.dot-cost` / `.section-marker`(如果不再使用) 等。

**保留:** nav-rail / modal-overlay / toast-container / refresh-panel / cap-chip / cap-detail / module-page / breadcrumb / topology-* / markdown-body / screenshot-uploader / hero-* / status-* / etc.

> **保守原则:**Plan 3 仅删 grep 确认不在用的 selectors,不动现有 hero / 字体 / token vars。

- [ ] **Step 9.1:grep CSS selectors 用法 — 找出 "未使用" 的**

```bash
# 列出 style.css 所有 selectors
grep -E "^\.[a-zA-Z_-]+" dashboard/static/style.css | head -80
# 然后 grep 模板中是否引用每个
```

(实际操作建议:打开 style.css 找以下注释段或 selectors,整段删除:)

**整段删除候选(在 Plan 1 / Plan 3 已经退役的组件):**
- `.layer-stack` + `.layer:nth-child(...)` grids + `.layer .numeral` 等
- `.kanban*` 全部
- `.view-toggle` + `.view-tab` + `.tab-num`
- `.app-shell-row` + `.app-shell-*`
- `.overview-frame` + `.overview-toolbar` + `.overview-canvas` + `.overview-legend` + `.overview-tooltip`
- `.fingerprint` + `.fingerprint-caption`
- `.dot-prompt / .dot-tools / .dot-orch / .dot-memory / .dot-rag / .dot-guard / .dot-eval / .dot-cost`
- `.section-marker` + `.sm-num/sm-title/sm-desc`(如不再用)
- `.chip / .chip.lit / .chip.wip / .chip.todo` 等旧 chip 样式(已被 .cap-chip-- 替代)

**Approach:**
1. 在文件搜索特定 selector
2. 找到 selector 起始 `.name {` 和对应 `}` 结束
3. 整段 cut

可使用 Python 脚本辅助:
```bash
uv run python -c "
import re
content = open('dashboard/static/style.css').read()
# 简单粗暴:统计每个 selector 出现次数(可用于决定哪些可删)
selectors = re.findall(r'^\.[a-zA-Z][a-zA-Z0-9_-]+', content, re.MULTILINE)
print('total unique selectors:', len(set(selectors)))
print('sample old:', [s for s in set(selectors) if s in ['.layer-stack', '.kanban', '.view-toggle', '.app-shell-row']])
"
```

- [ ] **Step 9.2:逐个 selector 删段(grep + Edit)**

对每一类(layer / kanban / view-toggle / app-shell / overview / fingerprint / 旧 dot-*),Edit 工具找 `.selectorName {` 到对应 `}`,整段删。

> 如果某个 selector 仍有引用(grep 模板 + 找到),则保留。

- [ ] **Step 9.3:Verify CSS 仍 valid(浏览器 / 跑 CI lint 若有)**

```bash
# 简单 check: file 仍 parse-able (Python re 无法 perfect, 但能粗略)
uv run python -c "
content = open('dashboard/static/style.css').read()
opens = content.count('{')
closes = content.count('}')
print(f'braces: open={opens} close={closes} (should equal)')
print(f'lines: {len(content.splitlines())}')
"
```
Expected: opens == closes;lines 从 ~2750 (Plan 2 + chip CSS) 降到 ~2000-2200。

- [ ] **Step 9.4:Smoke 浏览器(用 TestClient 检查首页 + 模块页 不损坏)**

```bash
uv run python -c "
from starlette.testclient import TestClient
from dashboard.server import app
client = TestClient(app)
print('/ status:', client.get('/').status_code)
print('/m/execution status:', client.get('/m/execution').status_code)
"
```
Expected: 都 200。

- [ ] **Step 9.5:全 pytest**

Expected: 0 regression。

- [ ] **Step 9.6:Commit**

```bash
git add dashboard/static/style.css
git commit -m "refactor(harness-board): CSS slim — drop retired selectors (layer/kanban/view-toggle/overview/fingerprint/old dot-*) (Plan 3 step 9)"
```

---

## Task 10:Smoke + spec ship 标记

**Files:**
- Modify: `docs/superpowers/specs/2026-05-24-harness-board-framework-rebuild-design.md`

- [ ] **Step 10.1:全 pytest + mypy + ruff**

```bash
uv run pytest dashboard/tests/ -q 2>&1 | tail -3
uv run mypy dashboard/ 2>&1 | tail -3
uv run ruff check dashboard/ 2>&1 | tail -2
```

- [ ] **Step 10.2:End-to-end smoke**

```bash
uv run python -c "
from starlette.testclient import TestClient
from dashboard.server import app
client = TestClient(app)

# 应工作的 endpoint
ok = [
    ('GET', '/', 200),
    ('GET', '/m/execution', 200),
    ('GET', '/m/tool', 200),
    ('GET', '/m/context', 200),
    ('GET', '/m/lifecycle', 200),
    ('GET', '/m/observability', 200),
    ('GET', '/m/verification', 200),
    ('GET', '/m/governance', 200),
    ('GET', '/cap/execution.docker_compose/expand', 200),
    ('GET', '/healthz', 200),
    ('GET', '/story', 200),     # Plan 4 改造,Plan 3 不动
]

# 退役的 endpoint 应 404
retired = [
    ('GET', '/overview', 404),
    ('GET', '/overview/fallback', 404),
    ('GET', '/api/overview/graph.json', 404),
    ('GET', '/decisions', 404),
    ('GET', '/survey', 404),
    ('POST', '/capability/x/override', [404, 405]),  # 405 if route gone too
]

for method, path, expected in ok + retired:
    r = client.request(method, path)
    if isinstance(expected, list):
        ok_mark = '✓' if r.status_code in expected else '✗'
    else:
        ok_mark = '✓' if r.status_code == expected else '✗'
    print(f'{ok_mark}  {method} {path} → {r.status_code}')
"
```

记下输出。

- [ ] **Step 10.3:Update spec ship marker**

打开 `docs/superpowers/specs/2026-05-24-harness-board-framework-rebuild-design.md`,定位:
```markdown
**状态**:Spec — Plan 1 ship ... + Plan 2 ship 2026-05-24(...)
```

改为:
```markdown
**状态**:Spec — Plan 1 + Plan 2 + Plan 3 ship 2026-05-24(首页 Topology 关系图 / 退役 overview-decisions-survey / 清 SrsState-Flashcard-TemplateKind + graph_builder;/story 改造留 Plan 4)
```

- [ ] **Step 10.4:Commit ship marker**

```bash
git add docs/superpowers/specs/2026-05-24-harness-board-framework-rebuild-design.md
git commit -m "docs(harness-board): mark Plan 3 ship in spec — Topology homepage + subpages retired + types cleaned"
```

- [ ] **Step 10.5:Final git log + diff stat**

```bash
git log --oneline -20
git diff main...HEAD --stat | tail -30
```

---

## Self-Review

| Plan 3 Spec 要求 | Task | 状态 |
|---|---|---|
| 首页 Topology 关系图 | Task 1+2 | ✓ |
| /overview 退役 | Task 3 | ✓ |
| /decisions 退役 | Task 4 | ✓ |
| /survey 退役 | Task 5 | ✓ |
| _hero / view-toggle / d-view / b-view / app-shell 退役 | Task 6 | ✓ |
| nav-rail 重写 | Task 7 | ✓ |
| SrsState / Flashcard / TemplateKind 清 | Task 8 | ✓ |
| graph_builder 退役 | Task 3 | ✓ |
| survey_loader 退役 | Task 5 | ✓ |
| app_shell_stat 退役 | Task 6 | ✓ |
| CSS 大瘦身 | Task 9 | ✓ |
| /story 改造 | Plan 4 | 不在本 plan |
| story_builder / _story_card 退役 | Plan 4 | 不在本 plan |

**Placeholders:** 0
**Type consistency:** Topology SVG 模板用的 `topology_modules`(`list[ModuleProgress]`)+ `topology_endpoints`(`list[tuple[ConnLine, tuple[int,int], tuple[int,int]]]`)与 server.py index handler 注入一致;tests 一致。
**Risks:**
- CSS 瘦身可能误删仍在用的 selector — Task 9 Step 9.4 用 TestClient smoke 主页 / 模块页 verify
- nav-rail Plan 2 加的 letter shortcuts 删后,要 verify 不破坏 `active_nav` 高亮逻辑(/m/{dim} 时高亮哪个)— Task 7 重写时考虑是否保留 active_nav 概念,可能简化为 home / story 两态
- Topology SVG 在小屏(< 600px)的响应式不在 Plan 3 范围;移动端用户少,接受 desktop-first

---

## 实施清单(commits 顺序)

1. `feat(harness-board): topology layout + _topology_diagram.html SVG (Plan 3 step 1)`
2. `feat(harness-board): rewrite main.html homepage = Topology SVG + hero + In flux (Plan 3 step 2)`
3. `refactor(harness-board): retire /overview + cytoscape + graph_builder (Plan 3 step 3)`
4. `refactor(harness-board): retire /decisions routes + templates + 5 handlers (Plan 3 step 4)`
5. `refactor(harness-board): retire /survey + survey_loader (Plan 3 step 5)`
6. `refactor(harness-board): retire _hero/_view_toggle/_d_view/_b_view/_app_shell + app_shell_stat (Plan 3 step 6)`
7. `refactor(harness-board): rewrite nav-rail (drop letter shortcuts + retired subpage entries) (Plan 3 step 7)`
8. `refactor(harness-board): remove SrsState/Flashcard/TemplateKind types (Plan 3 step 8)`
9. `refactor(harness-board): CSS slim — drop retired selectors (Plan 3 step 9)`
10. `docs(harness-board): mark Plan 3 ship in spec`

共 10 work commits + 1 plan doc commit。

---

## After Plan 3 — Plan 4 预告

```
Plan 4 — /story 改造
   - story.html 重写为 textarea + 渲染区(marked + mermaid 已在 base.html, Plan 2 引)
   - story.js 客户端渲染逻辑
   - 退役 _story_card.html / story_builder.py
   - 测试改造 test_story_endpoint
   - spec ship 标记
```

Plan 4 估算 4-5 task / ~25 step / 1 PR / 短 plan(< 500 行 doc)。

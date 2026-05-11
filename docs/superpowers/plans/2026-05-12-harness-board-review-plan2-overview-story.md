# Harness Board Review Mode — Plan 2: V3 系统鸟瞰 + V4 故事时间线

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans`. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** [`docs/superpowers/specs/2026-05-12-harness-board-review-mode-design.md`](../specs/2026-05-12-harness-board-review-mode-design.md)

**前置依赖:** Plan 1 已 ship(DeepCard 底座 + V2 modal + Milvus collection 已建)

**Goal:** 落地 V3 系统鸟瞰(cytoscape 依赖图,C 系统化视角)+ V4 故事时间线(三段式叙事弧,A 面试讲项目场景),让复合型工具的"系统化 + 模块化 + 叙事"三视角联动可用。

**Architecture:** V3 沿用项目已有 cytoscape + cose-bilkent 布局(c5-plan7b MemoryGraph 用过);后端 `GET /api/overview/graph.json` 输出节点/边数据,前端 cytoscape 渲染 + cluster 染色 + 8 维分组。V4 从 git log 抽 cap 命中文件首个 commit 作为"诞生时间",sort 后用 Jinja 模板 render 三段式卡片流。两视图节点 / 卡片点击均跳 V2 modal,联动闭环。

**Tech Stack:** cytoscape 3.30 + cytoscape-cose-bilkent 4.x(已在 package.json)/ subprocess git log / Jinja2 / htmx

**Plan 2 ship checklist 摘要:**
- V3 `/overview` 路由 + cytoscape 渲染 + 节点点击 → V2 modal
- V3 工具栏(维度过滤 / status 过滤 / confidence 过滤)
- V3 cytoscape 加载失败 → 8 维卡片墙 fallback
- Milvus 相关推荐真路径 wire(Plan 1 Task 9 简化为 fallback,本 plan 完整接)
- V4 `/story` 路由 + commit-time 抽取 + 三段式 render
- V4 维度 + 时间窗过滤
- dashboard 总测试不破 + 新增 +20 L0 / +10 L1 PASS
- mypy strict + ruff clean

---

## File Structure(Plan 2 范围)

**新建:**
- `dashboard/derive/commit_time_extractor.py` — git log 抽取 cap 首个 commit
- `dashboard/derive/graph_builder.py` — V3 节点/边 JSON 构造
- `dashboard/derive/story_builder.py` — V4 三段式卡片数据构造
- `dashboard/templates/overview.html` — V3 主页(含 cytoscape canvas)
- `dashboard/templates/overview_fallback.html` — V3 cytoscape 失败 fallback
- `dashboard/templates/story.html` — V4 主页(三段式卡片流 + 工具栏)
- `dashboard/templates/_story_card.html` — V4 单卡片子模板
- `dashboard/static/overview.js` — cytoscape 初始化 + 交互
- `dashboard/static/cytoscape.min.js` + `cytoscape-cose-bilkent.min.js`(vendored from npm 或 CDN)
- `dashboard/tests/unit/test_commit_time_extractor.py`
- `dashboard/tests/unit/test_graph_builder.py`
- `dashboard/tests/unit/test_story_builder.py`
- `dashboard/tests/integration/test_overview_endpoint.py`
- `dashboard/tests/integration/test_story_endpoint.py`
- `dashboard/tests/integration/test_milvus_recommend_real.py`(Milvus 真路径补)

**修改:**
- `dashboard/server.py` — 加 `GET /overview` / `GET /api/overview/graph.json` / `GET /story` 3 个 route + 完善 `_try_milvus_related`
- `dashboard/static/style.css` — overview / story CSS
- `dashboard/templates/main.html` — 顶部 nav 加 "🌐 鸟瞰" / "📖 故事" 按钮

---

## Task 1: commit-time 抽取器

**Files:**
- Create: `dashboard/derive/commit_time_extractor.py`
- Test: `dashboard/tests/unit/test_commit_time_extractor.py`

- [ ] **Step 1: Write test**

```python
# dashboard/tests/unit/test_commit_time_extractor.py
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from dashboard.derive.commit_time_extractor import (
    extract_cap_commit_time,
    extract_first_commit_for_paths,
)


def test_extract_first_commit_simple(tmp_path: Path) -> None:
    """模拟 subprocess git log 返回单行 ISO 时间。"""
    fake_output = "2026-04-15T10:23:00+08:00"
    with patch("dashboard.derive.commit_time_extractor.subprocess.check_output",
               return_value=fake_output):
        ts = extract_first_commit_for_paths(["backend/app/services/llm_service.py"],
                                            cwd=tmp_path)
    assert ts is not None
    assert ts.startswith("2026-04-15")


def test_extract_first_commit_no_paths_returns_none(tmp_path: Path) -> None:
    assert extract_first_commit_for_paths([], cwd=tmp_path) is None


def test_extract_first_commit_subprocess_fail(tmp_path: Path) -> None:
    import subprocess
    with patch("dashboard.derive.commit_time_extractor.subprocess.check_output",
               side_effect=subprocess.CalledProcessError(1, "git")):
        ts = extract_first_commit_for_paths(["x.py"], cwd=tmp_path)
    assert ts is None


def test_extract_cap_commit_time_code_grep_rule(tmp_path: Path) -> None:
    """code_grep / file_exists / spec_section 都有 path/path_glob,可抽 commit。"""
    fake_output = "2026-03-01T08:00:00+00:00"
    with patch("dashboard.derive.commit_time_extractor.subprocess.check_output",
               return_value=fake_output):
        # cap_cfg dict-style 输入避免 import 循环
        rule = {"type": "code_grep", "path_glob": "backend/**/*.py", "pattern": "x"}
        ts = extract_cap_commit_time(rule, cwd=tmp_path)
    assert ts is not None
    assert "2026-03-01" in ts


def test_extract_cap_commit_time_manual_rule_returns_none(tmp_path: Path) -> None:
    """manual rule 无 path_glob → None(spec § 5.4 fallback 由调用者处理)。"""
    ts = extract_cap_commit_time({"type": "manual"}, cwd=tmp_path)
    assert ts is None


def test_glob_expansion_passes_to_git(tmp_path: Path) -> None:
    """path_glob 包含 ** 应该展开成实际 path 列表(避免 git 不支持 glob)。"""
    # 创建几个真实文件
    (tmp_path / "a.py").write_text("x")
    (tmp_path / "b.py").write_text("x")
    with patch("dashboard.derive.commit_time_extractor.subprocess.check_output") as m:
        m.return_value = "2026-01-01T00:00:00+00:00"
        rule = {"type": "code_grep", "path_glob": "*.py", "pattern": "x"}
        extract_cap_commit_time(rule, cwd=tmp_path)
        # subprocess 调用时 args 应含展开后的 path
        called_args = m.call_args[0][0]
        assert "a.py" in called_args or any("a.py" in a for a in called_args)
```

- [ ] **Step 2: Run + fails**

Run: `uv run --project backend pytest dashboard/tests/unit/test_commit_time_extractor.py -v`
Expected: ImportError

- [ ] **Step 3: Implement**

```python
# dashboard/derive/commit_time_extractor.py
"""从 git log 抽取 capability 命中文件的首个 commit 时间。spec § 5.4。"""

from __future__ import annotations

import logging
import subprocess
from glob import glob
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def extract_first_commit_for_paths(paths: list[str], *, cwd: Path) -> str | None:
    """对一组 path 跑 git log --diff-filter=A,取最早的 commit ISO 时间。

    spec § 5.4:cap 的"诞生时间"。
    paths 已展开实际文件路径(不接受 glob)。
    """
    if not paths:
        return None
    try:
        out = subprocess.check_output(
            [
                "git", "log",
                "--diff-filter=A",  # added
                "--reverse",
                "--format=%aI",
                "--",
                *paths,
            ],
            cwd=str(cwd),
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    first_line = out.strip().split("\n", 1)[0] if out.strip() else ""
    return first_line or None


def extract_cap_commit_time(rule: dict[str, Any], *, cwd: Path) -> str | None:
    """对单个 cap 的 derive_rule 抽 commit time。

    支持 rule.type in {file_exists, code_grep, spec_section, memory_frontmatter}。
    manual rule 返回 None — 调用者用 DeepCard.prefill_at fallback(spec § 5.4)。
    """
    rtype = rule.get("type")
    if rtype == "manual":
        return None
    path_field = "path_glob" if rtype in {"code_grep"} else "path"
    glob_pat = rule.get(path_field)
    if not glob_pat:
        return None
    expanded = sorted(glob(str(cwd / glob_pat), recursive=True))
    if not expanded:
        return None
    # 转 relative,git 友好
    rel = [str(Path(p).relative_to(cwd)) for p in expanded]
    return extract_first_commit_for_paths(rel, cwd=cwd)
```

- [ ] **Step 4: Run + passes**

Run: `uv run --project backend pytest dashboard/tests/unit/test_commit_time_extractor.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add dashboard/derive/commit_time_extractor.py dashboard/tests/unit/test_commit_time_extractor.py
git commit -m "feat(harness-review-plan2): commit-time 抽取器 (V4 故事时间线用)"
```

---

## Task 2: V3 graph_builder — 节点/边 JSON 构造

**Files:**
- Create: `dashboard/derive/graph_builder.py`
- Test: `dashboard/tests/unit/test_graph_builder.py`

- [ ] **Step 1: Write test**

```python
# dashboard/tests/unit/test_graph_builder.py
from __future__ import annotations

from dashboard.derive.deep_card_types import CodeAnchor, DeepCard, SrsState
from dashboard.derive.graph_builder import build_graph_payload
from dashboard.derive.types import Capability


def test_graph_payload_basic_node_edge() -> None:
    caps = [
        Capability(id="01.a", dimension="prompt_context", name_cn="A", name_en="A",
                   status="lit", derived_status="lit"),
        Capability(id="02.b", dimension="tools_function", name_cn="B", name_en="B",
                   status="lit", derived_status="lit"),
    ]
    cards = [
        DeepCard(cap_id="01.a", linked_capabilities=["02.b"],
                 srs_state=SrsState(confidence=3),
                 code_anchors=[CodeAnchor(file="x.py", line=1)]),
        DeepCard(cap_id="02.b", linked_capabilities=["01.a"],
                 srs_state=SrsState(confidence=5)),
    ]
    payload = build_graph_payload(caps, cards)
    # 2 nodes
    assert len(payload["nodes"]) == 2
    a = next(n for n in payload["nodes"] if n["data"]["id"] == "01.a")
    assert a["data"]["dimension"] == "prompt_context"
    assert a["data"]["confidence"] == 3
    assert a["data"]["size"] == 1  # 1 code_anchor
    # bi-directional link → 1 edge (dedupe)
    assert len(payload["edges"]) == 1
    edge = payload["edges"][0]
    assert {edge["data"]["source"], edge["data"]["target"]} == {"01.a", "02.b"}


def test_graph_self_loop_deduped() -> None:
    caps = [Capability(id="x.a", dimension="memory", name_cn="A", name_en="A",
                       status="lit", derived_status="lit")]
    cards = [DeepCard(cap_id="x.a", linked_capabilities=["x.a"])]
    payload = build_graph_payload(caps, cards)
    assert payload["edges"] == []  # self-loop 去掉


def test_graph_no_deep_card_shows_dashed_node() -> None:
    """无 DeepCard 的 cap 仍出现在图,带 has_deep_card=False"""
    caps = [Capability(id="x.a", dimension="memory", name_cn="A", name_en="A",
                       status="todo", derived_status="todo")]
    payload = build_graph_payload(caps, [])
    n = payload["nodes"][0]
    assert n["data"]["has_deep_card"] is False
    assert n["data"]["confidence"] == 0
    assert n["data"]["size"] == 1  # min size


def test_graph_filter_by_dimension() -> None:
    caps = [
        Capability(id="01.a", dimension="prompt_context", name_cn="A", name_en="A",
                   status="lit", derived_status="lit"),
        Capability(id="04.b", dimension="memory", name_cn="B", name_en="B",
                   status="lit", derived_status="lit"),
    ]
    payload = build_graph_payload(caps, [], filter_dimensions={"prompt_context"})
    assert len(payload["nodes"]) == 1
    assert payload["nodes"][0]["data"]["id"] == "01.a"


def test_graph_filter_low_confidence_only() -> None:
    caps = [Capability(id="x.a", dimension="memory", name_cn="A", name_en="A",
                       status="lit", derived_status="lit"),
            Capability(id="x.b", dimension="memory", name_cn="B", name_en="B",
                       status="lit", derived_status="lit")]
    cards = [DeepCard(cap_id="x.a", srs_state=SrsState(confidence=2)),
             DeepCard(cap_id="x.b", srs_state=SrsState(confidence=5))]
    payload = build_graph_payload(caps, cards, only_low_confidence=True)
    ids = {n["data"]["id"] for n in payload["nodes"]}
    assert "x.a" in ids and "x.b" not in ids
```

- [ ] **Step 2: Run + fails**

Run: `uv run --project backend pytest dashboard/tests/unit/test_graph_builder.py -v`
Expected: ImportError

- [ ] **Step 3: Implement**

```python
# dashboard/derive/graph_builder.py
"""V3 cytoscape 节点/边 payload 构造。spec § 5.3。"""

from __future__ import annotations

from typing import Any

from dashboard.derive.deep_card_types import DeepCard
from dashboard.derive.types import Capability


def build_graph_payload(
    capabilities: list[Capability],
    deep_cards: list[DeepCard],
    *,
    filter_dimensions: set[str] | None = None,
    filter_statuses: set[str] | None = None,
    only_low_confidence: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    """构造 cytoscape JSON elements:{nodes: [...], edges: [...]}。

    spec § 5.3:
    - 节点 colour = dimension(前端 CSS)
    - 节点 size = code_anchors 数 + 1
    - 节点 border color = confidence(前端 CSS)
    - 边 = linked_capabilities,无向 dedupe + self-loop 去除
    """
    cards_by_id = {c.cap_id: c for c in deep_cards}

    # filter caps
    visible_caps = []
    for cap in capabilities:
        if filter_dimensions and cap.dimension not in filter_dimensions:
            continue
        if filter_statuses and cap.status not in filter_statuses:
            continue
        if only_low_confidence:
            dc = cards_by_id.get(cap.id)
            if dc and dc.srs_state.confidence >= 3:
                continue
        visible_caps.append(cap)

    visible_ids = {c.id for c in visible_caps}

    nodes: list[dict[str, Any]] = []
    for cap in visible_caps:
        dc = cards_by_id.get(cap.id)
        size = (len(dc.code_anchors) + 1) if dc else 1
        confidence = dc.srs_state.confidence if dc else 0
        nodes.append({
            "data": {
                "id": cap.id,
                "label": cap.name_cn,
                "dimension": cap.dimension,
                "status": cap.status,
                "confidence": confidence,
                "size": size,
                "has_deep_card": dc is not None,
            }
        })

    # edges — 无向 dedupe + self-loop 去
    edge_pairs: set[tuple[str, str]] = set()
    for dc in deep_cards:
        if dc.cap_id not in visible_ids:
            continue
        for other in dc.linked_capabilities:
            if other == dc.cap_id:  # self-loop
                continue
            if other not in visible_ids:
                continue
            pair = tuple(sorted([dc.cap_id, other]))
            edge_pairs.add(pair)
    edges = [{"data": {"source": s, "target": t, "id": f"{s}__{t}"}}
             for s, t in sorted(edge_pairs)]

    return {"nodes": nodes, "edges": edges}
```

- [ ] **Step 4: Run + passes**

Run: `uv run --project backend pytest dashboard/tests/unit/test_graph_builder.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add dashboard/derive/graph_builder.py dashboard/tests/unit/test_graph_builder.py
git commit -m "feat(harness-review-plan2): V3 graph_builder (nodes / edges / filter)"
```

---

## Task 3: V3 endpoints (`GET /overview` + `GET /api/overview/graph.json`)

**Files:**
- Modify: `dashboard/server.py`
- Create: `dashboard/templates/overview.html`
- Create: `dashboard/templates/overview_fallback.html`
- Test: `dashboard/tests/integration/test_overview_endpoint.py`

- [ ] **Step 1: Write test**

```python
# dashboard/tests/integration/test_overview_endpoint.py
from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    from dashboard import server
    monkeypatch.setattr(server, "DB_PATH", tmp_path / "board.db")
    return TestClient(server.app)


def test_overview_html_contains_cytoscape_init(client: TestClient) -> None:
    resp = client.get("/overview")
    assert resp.status_code == 200
    assert "cytoscape" in resp.text.lower()
    assert "overview-canvas" in resp.text


def test_graph_json_returns_nodes_edges(client: TestClient) -> None:
    resp = client.get("/api/overview/graph.json")
    assert resp.status_code == 200
    body = resp.json()
    assert "nodes" in body and "edges" in body
    # 至少应有 capabilities.yaml 的 62 cap (无过滤)
    assert len(body["nodes"]) >= 60


def test_graph_json_filter_by_dim(client: TestClient) -> None:
    resp = client.get("/api/overview/graph.json?dim=memory")
    body = resp.json()
    for n in body["nodes"]:
        assert n["data"]["dimension"] == "memory"


def test_graph_json_only_low_confidence(client: TestClient) -> None:
    resp = client.get("/api/overview/graph.json?low_conf=1")
    body = resp.json()
    # 当前所有 cap 无 DeepCard → confidence=0 → 都应入
    assert len(body["nodes"]) >= 10
```

- [ ] **Step 2: Run + fails**

Run: `uv run --project backend pytest dashboard/tests/integration/test_overview_endpoint.py -v`
Expected: 404

- [ ] **Step 3: Implement overview.html**

```html
{# dashboard/templates/overview.html #}
{% extends "base.html" %}
{% block content %}
<div class="overview-toolbar">
  <a href="/" class="btn-back">← 返回网格</a>
  <span>📊 系统鸟瞰 ({{ total_nodes }} 节点)</span>
  <div class="filter-group">
    {% for d in dimensions %}
      <label><input type="checkbox" class="filter-dim" value="{{ d.id }}" checked />
        <span class="dim-color dim-color--{{ d.id }}"></span>{{ d.name_cn }}</label>
    {% endfor %}
  </div>
  <div class="filter-group">
    <label><input type="radio" name="conf-filter" value="all" checked /> 全部</label>
    <label><input type="radio" name="conf-filter" value="low" /> 仅需复习 (conf<3)</label>
  </div>
</div>

<div id="overview-canvas" style="width:100%;height:80vh;border:1px solid #ddd;"></div>

<div id="modal-overlay" class="modal-overlay" style="display:none;"></div>

<script src="/static/cytoscape.min.js"></script>
<script src="/static/cytoscape-cose-bilkent.min.js"></script>
<script src="/static/htmx.min.js"></script>
<script src="/static/overview.js"></script>
{% endblock %}
```

- [ ] **Step 4: Implement overview_fallback.html**

```html
{# dashboard/templates/overview_fallback.html — cytoscape 加载失败兜底 #}
{% extends "base.html" %}
{% block content %}
<div class="overview-toolbar">
  <a href="/" class="btn-back">← 返回网格</a>
  <span>📊 系统鸟瞰(图加载失败,显示卡片墙)</span>
</div>
<div class="overview-fallback-grid">
  {% for dim in dimensions_with_caps %}
    <div class="dim-block dim-color--{{ dim.id }}">
      <h3>{{ dim.number }} {{ dim.name_cn }}</h3>
      <div class="caps-row">
        {% for cap in dim.capabilities %}
          <a href="/cap/{{ cap.id }}" class="capability-chip">{{ cap.name_cn }}</a>
        {% endfor %}
      </div>
    </div>
  {% endfor %}
</div>
{% endblock %}
```

- [ ] **Step 5: Implement endpoints**

```python
# dashboard/server.py — additions

async def overview_view(request: Request) -> HTMLResponse:
    """V3 鸟瞰主页 — 渲染含 cytoscape 容器,数据由 /api/overview/graph.json 拉。"""
    main_dims, _ = load_dimensions(CONFIG_DIR / "dimensions.yaml")
    template = templates.get_template("overview.html")
    html = template.render(
        dimensions=main_dims,
        total_nodes=len(load_capabilities(CONFIG_DIR / "capabilities.yaml")),
    )
    return HTMLResponse(html)


async def overview_graph_json(request: Request) -> JSONResponse:
    """V3 cytoscape 数据源。支持 ?dim=memory,prompt_context / ?status=lit / ?low_conf=1。"""
    from dashboard.derive.graph_builder import build_graph_payload

    qp = request.query_params
    filter_dims = set(qp.get("dim", "").split(",")) - {""} if qp.get("dim") else None
    filter_statuses = set(qp.get("status", "").split(",")) - {""} if qp.get("status") else None
    only_low_conf = qp.get("low_conf") == "1"

    snap = _get_or_build_snapshot()
    all_caps = []
    for layer in snap["layers"]:
        for c_dict in layer["capabilities"]:
            all_caps.append(Capability(
                id=c_dict["id"], dimension=c_dict["dimension"],
                name_cn=c_dict["name_cn"], name_en=c_dict["name_en"],
                status=c_dict["status"], derived_status=c_dict["derived_status"],
            ))

    conn = open_db(DB_PATH)
    try:
        cards = DeepCardRepo(conn).get_all()
    finally:
        conn.close()

    payload = build_graph_payload(
        all_caps, cards,
        filter_dimensions=filter_dims,
        filter_statuses=filter_statuses,
        only_low_confidence=only_low_conf,
    )
    return JSONResponse(payload)


# Routes append:
#   Route("/overview", overview_view),
#   Route("/api/overview/graph.json", overview_graph_json),
```

- [ ] **Step 6: Run + passes**

Run: `uv run --project backend pytest dashboard/tests/integration/test_overview_endpoint.py -v`
Expected: 4 passed

- [ ] **Step 7: Commit**

```bash
git add dashboard/server.py dashboard/templates/overview.html \
        dashboard/templates/overview_fallback.html \
        dashboard/tests/integration/test_overview_endpoint.py
git commit -m "feat(harness-review-plan2): V3 /overview + /api/overview/graph.json endpoints"
```

---

## Task 4: V3 cytoscape.js 初始化 + 节点点击 → V2 modal

**Files:**
- Create: `dashboard/static/cytoscape.min.js` / `cytoscape-cose-bilkent.min.js`(vendored)
- Create: `dashboard/static/overview.js`
- Modify: `dashboard/static/style.css`

- [ ] **Step 1: Vendor cytoscape**

```bash
mkdir -p dashboard/static
# 沿用 c5-plan7b 已有的 cytoscape 版本(npm 链接已在 frontend/package.json)
# 简单做:从 frontend/node_modules 拷
cp frontend/node_modules/cytoscape/dist/cytoscape.min.js dashboard/static/
cp frontend/node_modules/cytoscape-cose-bilkent/cytoscape-cose-bilkent.js \
   dashboard/static/cytoscape-cose-bilkent.min.js
```

(若 frontend 未装,先 `cd frontend && npm install` — 沿用 c5-plan7b 用过的依赖)

- [ ] **Step 2: Implement overview.js**

```javascript
// dashboard/static/overview.js
(function () {
  const DIM_COLORS = {
    prompt_context: '#3b82f6',
    tools_function: '#06b6d4',
    orchestration: '#8b5cf6',
    memory: '#f59e0b',
    rag_knowledge: '#10b981',
    guardrails: '#ef4444',
    eval_observability: '#84cc16',
    cost_routing: '#ec4899',
  };

  function statusOpacity(status) {
    return status === 'lit' ? 1.0 : status === 'wip' ? 0.7 : 0.4;
  }

  function confidenceBorder(c) {
    // 灰 → 绿 渐变
    const stops = ['#cccccc', '#a8d8a8', '#80c080', '#5ca85c', '#3a903a', '#1a781a'];
    return stops[Math.max(0, Math.min(5, c || 0))];
  }

  async function loadAndRender(query = '') {
    let payload;
    try {
      payload = await (await fetch('/api/overview/graph.json' + query)).json();
    } catch (e) {
      console.error('cytoscape data fetch failed', e);
      document.getElementById('overview-canvas').innerHTML =
        '<div class="error">数据加载失败 — <a href="/">返回网格</a></div>';
      return;
    }

    const elements = [...payload.nodes, ...payload.edges];
    const cy = cytoscape({
      container: document.getElementById('overview-canvas'),
      elements,
      style: [
        {
          selector: 'node',
          style: {
            label: 'data(label)',
            'font-size': 11,
            width: 'mapData(size, 1, 10, 30, 60)',
            height: 'mapData(size, 1, 10, 30, 60)',
            'background-color': (ele) => DIM_COLORS[ele.data('dimension')] || '#999',
            'background-opacity': (ele) => statusOpacity(ele.data('status')),
            'border-width': 3,
            'border-color': (ele) => confidenceBorder(ele.data('confidence')),
            'border-style': (ele) => ele.data('has_deep_card') ? 'solid' : 'dashed',
            'text-valign': 'bottom',
            'text-margin-y': 4,
          },
        },
        {
          selector: 'edge',
          style: {
            width: 1,
            'line-color': '#ccc',
            'curve-style': 'bezier',
            opacity: 0.6,
          },
        },
      ],
      layout: { name: 'cose-bilkent', animate: false, randomize: false },
    });

    cy.on('tap', 'node', async (evt) => {
      const id = evt.target.data('id');
      const overlay = document.getElementById('modal-overlay');
      overlay.innerHTML = `<div class="modal-loading">载入...</div>`;
      overlay.style.display = 'flex';
      const html = await (await fetch(`/cap/${id}`)).text();
      overlay.innerHTML = html;
    });
  }

  function reload() {
    const dims = [...document.querySelectorAll('.filter-dim:checked')].map(el => el.value);
    const lowConf = document.querySelector('input[name="conf-filter"]:checked').value === 'low';
    const params = new URLSearchParams();
    if (dims.length < 8) params.set('dim', dims.join(','));
    if (lowConf) params.set('low_conf', '1');
    loadAndRender('?' + params.toString());
  }

  document.querySelectorAll('.filter-dim').forEach(el => el.addEventListener('change', reload));
  document.querySelectorAll('input[name="conf-filter"]').forEach(el =>
    el.addEventListener('change', reload));

  loadAndRender();
})();
```

- [ ] **Step 3: CSS additions**

```css
/* dashboard/static/style.css — append */
.overview-toolbar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 8px 16px;
  background: #f9f9f9;
  border-bottom: 1px solid #ddd;
}
.dim-color {
  display: inline-block;
  width: 10px;
  height: 10px;
  margin-right: 4px;
  border-radius: 2px;
}
.dim-color--prompt_context { background: #3b82f6; }
.dim-color--tools_function { background: #06b6d4; }
.dim-color--orchestration { background: #8b5cf6; }
.dim-color--memory { background: #f59e0b; }
.dim-color--rag_knowledge { background: #10b981; }
.dim-color--guardrails { background: #ef4444; }
.dim-color--eval_observability { background: #84cc16; }
.dim-color--cost_routing { background: #ec4899; }

.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  z-index: 50;
}
.overview-fallback-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 16px;
  padding: 16px;
}
```

- [ ] **Step 4: 手动验证**

```bash
make board
# 浏览器开 http://localhost:8910/overview
# 验证:
#  - 节点按 8 维上色
#  - 节点边框颜色 = confidence
#  - 维度复选框过滤工作
#  - 点节点 → V2 modal 弹出
```

- [ ] **Step 5: Commit**

```bash
git add dashboard/static/cytoscape.min.js dashboard/static/cytoscape-cose-bilkent.min.js \
        dashboard/static/overview.js dashboard/static/style.css
git commit -m "feat(harness-review-plan2): V3 cytoscape 渲染 + 节点点击 → V2 modal 联动"
```

---

## Task 5: V3 fallback — cytoscape 加载失败退回卡片墙

**Files:**
- Modify: `dashboard/server.py`(给 overview 加 User-Agent / Accept 检测;或直接路由分离)
- Test: 加 in test_overview_endpoint.py

简化策略:不做服务端 UA 检测(JS 失败 = client-side 就近显示)。让 overview.js 抓 fetch 异常时,fetch `/overview/fallback` 替换 DOM:

- [ ] **Step 1: Add fallback test**

```python
# 加 to test_overview_endpoint.py
def test_overview_fallback_renders_cards(client: TestClient) -> None:
    resp = client.get("/overview/fallback")
    assert resp.status_code == 200
    assert "overview-fallback-grid" in resp.text
    # 至少含 62 cap 中的几个
    assert "<a href=\"/cap/" in resp.text
```

- [ ] **Step 2: Implement fallback endpoint**

```python
# dashboard/server.py
async def overview_fallback(request: Request) -> HTMLResponse:
    main_dims, _ = load_dimensions(CONFIG_DIR / "dimensions.yaml")
    caps = load_capabilities(CONFIG_DIR / "capabilities.yaml")
    by_dim: dict[str, list[Any]] = {d.id: [] for d in main_dims}
    for c in caps:
        by_dim.setdefault(c.dimension, []).append({"id": c.id, "name_cn": c.name_cn})
    dims_with_caps = [
        {"id": d.id, "number": d.number, "name_cn": d.name_cn,
         "capabilities": by_dim.get(d.id, [])}
        for d in main_dims
    ]
    template = templates.get_template("overview_fallback.html")
    return HTMLResponse(template.render(dimensions_with_caps=dims_with_caps))


# Route: Route("/overview/fallback", overview_fallback),
```

- [ ] **Step 3: Modify overview.js to fallback**

```javascript
// dashboard/static/overview.js — 替换 catch 块
} catch (e) {
  // fallback: 替换 DOM 为 fallback HTML
  const html = await (await fetch('/overview/fallback')).text();
  document.body.innerHTML = html;
  return;
}
```

- [ ] **Step 4: Run + passes**

Run: `uv run --project backend pytest dashboard/tests/integration/test_overview_endpoint.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add dashboard/server.py dashboard/static/overview.js dashboard/tests/integration/test_overview_endpoint.py
git commit -m "feat(harness-review-plan2): V3 cytoscape fail fallback → 卡片墙"
```

---

## Task 6: Milvus 相关推荐真路径补全(Plan 1 Task 9 简化处)

**Files:**
- Modify: `dashboard/server.py`(完整 `_try_milvus_related`)
- Test: `dashboard/tests/integration/test_milvus_recommend_real.py`

- [ ] **Step 1: Write integration test (Milvus 必须 up,跳过 if not)**

```python
# dashboard/tests/integration/test_milvus_recommend_real.py
from __future__ import annotations

import os

import pytest
from starlette.testclient import TestClient

milvus_skip = pytest.mark.skipif(
    os.getenv("MILVUS_HOST") is None, reason="needs Milvus"
)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from dashboard import server
    monkeypatch.setattr(server, "DB_PATH", tmp_path / "board.db")
    monkeypatch.setenv("HARNESS_BOARD_MILVUS_HOST", os.environ["MILVUS_HOST"])
    monkeypatch.setattr(server, "MILVUS_HOST", os.environ["MILVUS_HOST"])
    return TestClient(server.app)


@milvus_skip
def test_milvus_recommend_returns_real_hits(client: TestClient) -> None:
    """Seed 3 DeepCard,Milvus upsert,再 query。"""
    from dashboard.derive.deep_card_types import DeepCard
    from dashboard.state.db import open_db
    from dashboard.state.repositories import DeepCardRepo
    conn = open_db(client.app.state.db_path)  # type: ignore[attr-defined]
    repo = DeepCardRepo(conn)
    repo.upsert(DeepCard(cap_id="x.a", what="LangGraph supervisor + planner",
                         why="multi-agent 编排"))
    repo.upsert(DeepCard(cap_id="x.b", what="LangGraph Send API subgraph"))
    repo.upsert(DeepCard(cap_id="x.c", what="完全无关内容"))

    # 手动触发 upsert 到 Milvus(实际应在 DeepCard upsert 时自动触发,见 Step 3)
    resp = client.post("/admin/milvus/reindex")  # 见 Step 3
    assert resp.status_code == 200

    resp = client.get("/cap/x.a/related?k=2")
    assert resp.headers.get("X-Milvus-Status") == "ok"
    body = resp.json()
    ids = [r["cap_id"] for r in body]
    assert "x.b" in ids
    assert "x.c" not in ids  # 应该在低位 / 不返回
```

- [ ] **Step 2: Run + fails**

Run: `uv run --project backend pytest dashboard/tests/integration/test_milvus_recommend_real.py -v`
Expected: fails or all skipped(若无 Milvus)

- [ ] **Step 3: Implement reindex endpoint + 完善 _try_milvus_related**

```python
# dashboard/server.py — replace _try_milvus_related + 加 reindex

async def _build_milvus_client():
    """lazy Milvus init,失败抛 ConnectionError。"""
    if not MILVUS_HOST:
        raise ConnectionError("MILVUS_HOST not set")
    from dashboard.state.milvus_collection import DeepCardMilvusClient
    client = DeepCardMilvusClient(host=MILVUS_HOST, port=MILVUS_PORT)
    await client.ensure_collection()
    return client


async def _build_embedder():
    from app.services.embedding_factory import build_embedding_service_from_env
    return build_embedding_service_from_env()


async def _try_milvus_related(cap_id: str, k: int) -> tuple[list[dict[str, object]] | None, str]:
    if MILVUS_HOST is None:
        return None, "milvus_disabled"
    try:
        from dashboard.state.milvus_collection import embedding_text
        client = await _build_milvus_client()
        embedder = await _build_embedder()

        conn = open_db(DB_PATH)
        try:
            pivot = DeepCardRepo(conn).get(cap_id)
        finally:
            conn.close()
        if pivot is None:
            return None, "no_pivot_card"

        caps_cfg = load_capabilities(CONFIG_DIR / "capabilities.yaml")
        name_cn = next((c.name_cn for c in caps_cfg if c.id == cap_id), "")
        text = embedding_text(pivot, name_cn=name_cn)
        vec = (await embedder.embed([text]))[0]
        hits = await client.search(vec, top_k=k + 1)
        # filter self
        hits = [h for h in hits if h["cap_id"] != cap_id][:k]
        return hits, "ok"
    except Exception as e:
        logger.warning("Milvus related fallback: %s", e)
        return None, f"milvus_error:{e}"


async def post_admin_milvus_reindex(request: Request) -> JSONResponse:
    """全量 reindex — Plan 1 Task 9 简化为不自动 upsert,本 endpoint 显式触发。"""
    if MILVUS_HOST is None:
        return JSONResponse({"error": "milvus disabled"}, status_code=503)
    from dashboard.state.milvus_collection import embedding_text
    client = await _build_milvus_client()
    embedder = await _build_embedder()

    conn = open_db(DB_PATH)
    try:
        cards = DeepCardRepo(conn).get_all()
    finally:
        conn.close()

    caps_cfg = load_capabilities(CONFIG_DIR / "capabilities.yaml")
    name_by_id = {c.id: c.name_cn for c in caps_cfg}

    rows = []
    texts = []
    for card in cards:
        name_cn = name_by_id.get(card.cap_id, "")
        text = embedding_text(card, name_cn=name_cn)
        texts.append(text)
        rows.append({
            "cap_id": card.cap_id,
            "dimension": card.cap_id.split(".", 1)[0] if "." in card.cap_id else "",
            "name_cn": name_cn,
            "status": "lit",  # snapshot 期内 status 已派生,简化为 lit
            "confidence": card.srs_state.confidence,
        })
    vecs = await embedder.embed(texts)
    for r, v in zip(rows, vecs, strict=True):
        r["embedding"] = v
    await client.upsert(rows)
    return JSONResponse({"upserted": len(rows)})


# routes:
#   Route("/admin/milvus/reindex", post_admin_milvus_reindex, methods=["POST"]),
```

注:Plan 1 Task 9 endpoint 已有 `_try_milvus_related` stub,本 task 完全替换实现。

- [ ] **Step 4: Run + passes**

Run: `uv run --project backend pytest dashboard/tests/integration/test_milvus_recommend_real.py -v`
Expected: 1 passed(若 Milvus up)or 1 skipped

- [ ] **Step 5: Commit**

```bash
git add dashboard/server.py dashboard/tests/integration/test_milvus_recommend_real.py
git commit -m "feat(harness-review-plan2): Milvus 相关推荐真路径 + reindex admin endpoint"
```

---

## Task 7: V4 story_builder — 三段式卡片数据构造

**Files:**
- Create: `dashboard/derive/story_builder.py`
- Test: `dashboard/tests/unit/test_story_builder.py`

- [ ] **Step 1: Write test**

```python
# dashboard/tests/unit/test_story_builder.py
from __future__ import annotations

from datetime import datetime, UTC
from pathlib import Path

from dashboard.derive.deep_card_types import DeepCard
from dashboard.derive.story_builder import StoryCard, build_story_cards
from dashboard.derive.types import Capability


def test_story_card_has_three_sections() -> None:
    cap = Capability(id="x.a", dimension="memory", name_cn="A", name_en="A",
                     status="lit", derived_status="lit")
    card = DeepCard(
        cap_id="x.a",
        why="为了避免下游解析失败",
        tradeoff="选 schema 因为 OpenAI 协议支持",
        lessons_learned="撞过 LLM 输出 escape 错误",
    )
    cards = build_story_cards(
        [cap], [card], commit_times={"x.a": "2026-05-01T00:00:00+00:00"},
    )
    assert len(cards) == 1
    sc = cards[0]
    assert sc.cap_id == "x.a"
    assert "为了避免" in sc.problem
    assert "选 schema" in sc.decision
    assert "escape 错误" in sc.outcome


def test_story_sort_by_time() -> None:
    caps = [
        Capability(id="x.a", dimension="memory", name_cn="A", name_en="A",
                   status="lit", derived_status="lit"),
        Capability(id="x.b", dimension="memory", name_cn="B", name_en="B",
                   status="lit", derived_status="lit"),
    ]
    cards = [DeepCard(cap_id="x.a", why="...", tradeoff="..."),
             DeepCard(cap_id="x.b", why="...", tradeoff="...")]
    times = {"x.a": "2026-05-10T00:00:00+00:00",
             "x.b": "2026-04-01T00:00:00+00:00"}
    out = build_story_cards(caps, cards, commit_times=times)
    assert out[0].cap_id == "x.b"  # earlier first
    assert out[1].cap_id == "x.a"


def test_story_fallback_to_prefill_at() -> None:
    """commit_times 缺 → 用 DeepCard.prefill_at;两者都无 → 'no_time_group'"""
    caps = [
        Capability(id="x.a", dimension="memory", name_cn="A", name_en="A",
                   status="lit", derived_status="lit"),
    ]
    cards = [DeepCard(cap_id="x.a", why="w", tradeoff="t",
                      prefill_at=datetime(2026, 3, 1, tzinfo=UTC))]
    out = build_story_cards(caps, cards, commit_times={})
    assert out[0].sort_time is not None
    assert "2026-03-01" in out[0].sort_time


def test_story_no_time_group_sentinel() -> None:
    caps = [Capability(id="x.a", dimension="memory", name_cn="A", name_en="A",
                       status="lit", derived_status="lit")]
    cards = [DeepCard(cap_id="x.a", why="w", tradeoff="t")]
    out = build_story_cards(caps, cards, commit_times={})
    assert out[0].in_no_time_group is True
    assert out[0].sort_time is None


def test_story_filter_by_dimension() -> None:
    caps = [Capability(id="01.a", dimension="prompt_context", name_cn="A", name_en="A",
                       status="lit", derived_status="lit"),
            Capability(id="04.b", dimension="memory", name_cn="B", name_en="B",
                       status="lit", derived_status="lit")]
    cards = [DeepCard(cap_id="01.a", why="...", tradeoff="..."),
             DeepCard(cap_id="04.b", why="...", tradeoff="...")]
    out = build_story_cards(caps, cards, commit_times={},
                             filter_dimensions={"prompt_context"})
    assert len(out) == 1
    assert out[0].cap_id == "01.a"


def test_story_filter_time_window() -> None:
    caps = [Capability(id="x.a", dimension="memory", name_cn="A", name_en="A",
                       status="lit", derived_status="lit"),
            Capability(id="x.b", dimension="memory", name_cn="B", name_en="B",
                       status="lit", derived_status="lit")]
    cards = [DeepCard(cap_id="x.a", why="...", tradeoff="..."),
             DeepCard(cap_id="x.b", why="...", tradeoff="...")]
    times = {"x.a": "2026-05-10T00:00:00+00:00",
             "x.b": "2026-04-01T00:00:00+00:00"}
    out = build_story_cards(caps, cards, commit_times=times,
                             time_after="2026-05-01")
    assert len(out) == 1
    assert out[0].cap_id == "x.a"
```

- [ ] **Step 2: Run + fails**

Run: `uv run --project backend pytest dashboard/tests/unit/test_story_builder.py -v`
Expected: ImportError

- [ ] **Step 3: Implement**

```python
# dashboard/derive/story_builder.py
"""V4 故事时间线 — 三段式卡片数据构造。spec § 5.4。"""

from __future__ import annotations

from dataclasses import dataclass

from dashboard.derive.deep_card_types import DeepCard
from dashboard.derive.types import Capability


@dataclass(frozen=True)
class StoryCard:
    cap_id: str
    name_cn: str
    dimension: str
    sort_time: str | None  # ISO timestamp,None 表示无时间归属
    in_no_time_group: bool
    problem: str  # from why
    decision: str  # from tradeoff
    outcome: str  # from lessons_learned (可能为空)
    linked_specs: list[str]
    linked_decisions: list[str]


def build_story_cards(
    capabilities: list[Capability],
    deep_cards: list[DeepCard],
    *,
    commit_times: dict[str, str],
    filter_dimensions: set[str] | None = None,
    time_after: str | None = None,
    time_before: str | None = None,
    order: str = "asc",  # asc | desc
) -> list[StoryCard]:
    """从 cap + deep_card + commit_times 构造按时间排序的三段式卡片。

    时间归属顺序(spec § 5.4):
    1. commit_times[cap_id](git log 首个 commit)
    2. DeepCard.prefill_at(LLM prefill 时间)
    3. None → in_no_time_group=True,排在末尾
    """
    cards_by_id = {c.cap_id: c for c in deep_cards}

    out: list[StoryCard] = []
    for cap in capabilities:
        if filter_dimensions and cap.dimension not in filter_dimensions:
            continue
        dc = cards_by_id.get(cap.id)
        if dc is None or (dc.why is None and dc.tradeoff is None):
            continue  # 没内容的不渲染

        # 时间归属
        sort_time = commit_times.get(cap.id)
        in_no_time = False
        if sort_time is None and dc.prefill_at:
            sort_time = dc.prefill_at.isoformat()
        if sort_time is None:
            in_no_time = True

        # 时间窗筛选(仅对有时间的)
        if sort_time is not None:
            if time_after and sort_time < time_after:
                continue
            if time_before and sort_time > time_before:
                continue

        out.append(StoryCard(
            cap_id=cap.id,
            name_cn=cap.name_cn,
            dimension=cap.dimension,
            sort_time=sort_time,
            in_no_time_group=in_no_time,
            problem=dc.why or "",
            decision=dc.tradeoff or "",
            outcome=dc.lessons_learned or "",
            linked_specs=list(dc.linked_specs),
            linked_decisions=list(dc.linked_decisions),
        ))

    # 排序:有时间的在前(按时间),无时间的在后
    def _key(sc: StoryCard) -> tuple[int, str]:
        if sc.in_no_time_group:
            return (1, "")
        return (0, sc.sort_time or "")
    out.sort(key=_key, reverse=(order == "desc"))
    return out
```

- [ ] **Step 4: Run + passes**

Run: `uv run --project backend pytest dashboard/tests/unit/test_story_builder.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add dashboard/derive/story_builder.py dashboard/tests/unit/test_story_builder.py
git commit -m "feat(harness-review-plan2): V4 story_builder (三段式 + 时间排序 + 过滤)"
```

---

## Task 8: V4 `/story` endpoint + 三段式模板

**Files:**
- Modify: `dashboard/server.py`
- Create: `dashboard/templates/story.html`
- Create: `dashboard/templates/_story_card.html`
- Test: `dashboard/tests/integration/test_story_endpoint.py`

- [ ] **Step 1: Write test**

```python
# dashboard/tests/integration/test_story_endpoint.py
from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    from dashboard import server
    monkeypatch.setattr(server, "DB_PATH", tmp_path / "board.db")
    return TestClient(server.app)


def test_story_empty_renders_placeholder(client: TestClient) -> None:
    resp = client.get("/story")
    assert resp.status_code == 200
    # 无 DeepCard 时显示引导文案
    assert "未填" in resp.text or "no story" in resp.text.lower() or \
           "暂无" in resp.text


def test_story_renders_3_section_card(client: TestClient, tmp_path) -> None:
    from dashboard.derive.deep_card_types import DeepCard
    from dashboard.state.db import open_db
    from dashboard.state.repositories import DeepCardRepo
    conn = open_db(client.app.state.db_path)  # type: ignore[attr-defined]
    DeepCardRepo(conn).upsert(DeepCard(
        cap_id="01.constrained_schema",
        why="避免 LLM 自由生成导致下游解析失败",
        tradeoff="选 constrained JSON schema 因为 OpenAI 协议支持",
        lessons_learned="撞过 ruff 行宽对齐撞了 3 次",
    ))
    resp = client.get("/story")
    assert resp.status_code == 200
    assert "避免 LLM 自由生成" in resp.text
    assert "constrained JSON schema" in resp.text
    assert "ruff 行宽" in resp.text


def test_story_filter_dim_via_query(client: TestClient) -> None:
    resp = client.get("/story?dim=memory")
    assert resp.status_code == 200
```

- [ ] **Step 2: Run + fails**

Run: `uv run --project backend pytest dashboard/tests/integration/test_story_endpoint.py -v`
Expected: 404

- [ ] **Step 3: Implement story.html + _story_card.html**

```html
{# dashboard/templates/story.html #}
{% extends "base.html" %}
{% block content %}
<div class="story-toolbar">
  <a href="/">← 返回网格</a>
  <span>📖 项目故事时间线 ({{ stories | length }} 条)</span>
  <form method="get" class="story-filter">
    {% for d in dimensions %}
      <label><input type="checkbox" name="dim" value="{{ d.id }}"
        {% if d.id in selected_dims %}checked{% endif %} />
        {{ d.name_cn }}</label>
    {% endfor %}
    时间窗 <input type="date" name="after" value="{{ time_after or '' }}" />
    ~ <input type="date" name="before" value="{{ time_before or '' }}" />
    <select name="order">
      <option value="asc" {% if order=='asc' %}selected{% endif %}>正序</option>
      <option value="desc" {% if order=='desc' %}selected{% endif %}>倒序</option>
    </select>
    <button type="submit">应用</button>
  </form>
</div>

<div class="story-list">
  {% if stories %}
    {% for sc in stories %}
      {% include "_story_card.html" %}
    {% endfor %}
  {% else %}
    <div class="story-empty">
      📭 暂无 DeepCard 内容 — 先到 <a href="/">网格</a> 给一些 cap 填 DeepCard
    </div>
  {% endif %}
</div>

<div id="modal-overlay" class="modal-overlay" style="display:none;"></div>
<script src="/static/htmx.min.js"></script>
<script src="/static/story.js"></script>
{% endblock %}
```

```html
{# dashboard/templates/_story_card.html #}
<div class="story-card dim-color--{{ sc.dimension }}">
  <div class="story-card-header">
    <a href="/cap/{{ sc.cap_id }}" class="story-card-link"
       hx-get="/cap/{{ sc.cap_id }}"
       hx-target="#modal-overlay"
       hx-swap="innerHTML"
       onclick="document.getElementById('modal-overlay').style.display='flex';">
      {{ sc.name_cn }}
    </a>
    <span class="story-card-time">
      {% if sc.in_no_time_group %}
        ⏱ 无时间归属
      {% else %}
        🗓 {{ sc.sort_time[:10] }}
      {% endif %}
    </span>
  </div>
  <div class="story-card-body">
    <div class="story-section story-section--problem">
      <div class="story-section-label">难题</div>
      <div>{{ sc.problem }}</div>
    </div>
    <div class="story-section story-section--decision">
      <div class="story-section-label">决策</div>
      <div>{{ sc.decision }}</div>
    </div>
    {% if sc.outcome %}
      <div class="story-section story-section--outcome">
        <div class="story-section-label">收获</div>
        <div>{{ sc.outcome }}</div>
      </div>
    {% endif %}
  </div>
  {% if sc.linked_specs or sc.linked_decisions %}
    <div class="story-card-footer">
      {% for sp in sc.linked_specs %}
        <a href="/{{ sp }}" target="_blank" class="link-tag">📄 {{ sp.split('/')[-1] }}</a>
      {% endfor %}
      {% for did in sc.linked_decisions %}
        <a href="/decisions#dec_{{ did }}" class="link-tag">⚖ {{ did }}</a>
      {% endfor %}
    </div>
  {% endif %}
</div>
```

- [ ] **Step 4: Implement endpoint**

```python
# dashboard/server.py
async def story_view(request: Request) -> HTMLResponse:
    from dashboard.derive.commit_time_extractor import extract_cap_commit_time
    from dashboard.derive.story_builder import build_story_cards

    qp = request.query_params
    dims = qp.getlist("dim")
    selected_dims = set(dims) if dims else None
    time_after = qp.get("after") or None
    time_before = qp.get("before") or None
    order = qp.get("order", "asc")

    main_dims, _ = load_dimensions(CONFIG_DIR / "dimensions.yaml")
    caps_cfg = load_capabilities(CONFIG_DIR / "capabilities.yaml")

    # 抽 commit_time(可缓存,Plan 3 改为后台 job;Plan 2 每次现抽)
    commit_times: dict[str, str] = {}
    for c in caps_cfg:
        ts = extract_cap_commit_time(c.derive_rule, cwd=PROJECT_ROOT)
        if ts:
            commit_times[c.id] = ts

    snap = _get_or_build_snapshot()
    all_caps = []
    for layer in snap["layers"]:
        for cd in layer["capabilities"]:
            all_caps.append(Capability(
                id=cd["id"], dimension=cd["dimension"],
                name_cn=cd["name_cn"], name_en=cd["name_en"],
                status=cd["status"], derived_status=cd["derived_status"],
            ))

    conn = open_db(DB_PATH)
    try:
        cards = DeepCardRepo(conn).get_all()
    finally:
        conn.close()

    stories = build_story_cards(
        all_caps, cards,
        commit_times=commit_times,
        filter_dimensions=selected_dims,
        time_after=time_after,
        time_before=time_before,
        order=order,
    )
    template = templates.get_template("story.html")
    return HTMLResponse(template.render(
        stories=stories,
        dimensions=main_dims,
        selected_dims=selected_dims or set(),
        time_after=time_after, time_before=time_before, order=order,
    ))


# Route: Route("/story", story_view),
```

- [ ] **Step 5: 加 CSS for story**

```css
/* dashboard/static/style.css — append */
.story-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid #ddd;
  flex-wrap: wrap;
}
.story-list {
  padding: 16px;
  max-width: 900px;
  margin: 0 auto;
}
.story-card {
  background: white;
  margin-bottom: 16px;
  padding: 16px;
  border-left: 4px solid #999;
  border-radius: 4px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.08);
}
.story-card.dim-color--prompt_context { border-left-color: #3b82f6; }
.story-card.dim-color--memory { border-left-color: #f59e0b; }
/* ... 其他维度颜色同 Task 4 css ... */
.story-card-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 12px;
}
.story-card-link {
  font-weight: 600;
  font-size: 16px;
  color: #1e40af;
  text-decoration: none;
}
.story-card-time {
  font-size: 12px;
  color: #666;
}
.story-section {
  margin-bottom: 8px;
}
.story-section-label {
  font-size: 11px;
  text-transform: uppercase;
  color: #999;
  margin-bottom: 2px;
}
.story-section--problem .story-section-label { color: #dc2626; }
.story-section--decision .story-section-label { color: #2563eb; }
.story-section--outcome .story-section-label { color: #16a34a; }
.story-card-footer {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed #eee;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.link-tag {
  font-size: 11px;
  padding: 2px 6px;
  background: #f3f4f6;
  border-radius: 3px;
  text-decoration: none;
  color: #4b5563;
}
.story-empty {
  text-align: center;
  padding: 64px 16px;
  color: #666;
}
```

- [ ] **Step 6: Run + passes**

Run: `uv run --project backend pytest dashboard/tests/integration/test_story_endpoint.py -v`
Expected: 3 passed

- [ ] **Step 7: 手动验证**

```bash
make board && open http://localhost:8910/story
# 验证:
#  - 至少 10 张样本 cap 渲染成卡片
#  - 难题/决策/收获三段式
#  - 时间排序
#  - 维度复选框过滤工作
#  - 卡片点击 → V2 modal
```

- [ ] **Step 8: Commit**

```bash
git add dashboard/server.py dashboard/templates/story.html \
        dashboard/templates/_story_card.html dashboard/static/style.css \
        dashboard/tests/integration/test_story_endpoint.py
git commit -m "feat(harness-review-plan2): V4 /story endpoint + 三段式卡片 render"
```

---

## Task 9: 顶部 nav 加 "🌐 鸟瞰" / "📖 故事" 入口

**Files:**
- Modify: `dashboard/templates/main.html`(or base.html / _hero.html)

- [ ] **Step 1: 找到顶部 nav 模板**

Read `dashboard/templates/main.html` 和 `dashboard/templates/_hero.html` 确认 nav 位置。

- [ ] **Step 2: 加入 nav link**

```html
{# dashboard/templates/main.html 顶部 #}
<nav class="board-nav">
  <a href="/" class="nav-link active">📊 网格</a>
  <a href="/overview" class="nav-link">🌐 鸟瞰</a>
  <a href="/story" class="nav-link">📖 故事</a>
  <a href="/decisions" class="nav-link">⚖ 决策</a>
</nav>
```

(实际 class active 切换 — 用 jinja 当前 route 比对;沿用 Harness Board 已有 nav 模式)

```css
/* style.css append */
.board-nav {
  display: flex;
  gap: 16px;
  padding: 8px 16px;
  border-bottom: 1px solid #ddd;
  background: #f9fafb;
}
.nav-link {
  text-decoration: none;
  padding: 4px 10px;
  border-radius: 4px;
  color: #4b5563;
}
.nav-link.active {
  background: #1f2937;
  color: white;
}
.nav-link:hover { background: #e5e7eb; }
```

- [ ] **Step 3: 手动验证 4 nav 都能正常跳转**

```bash
make board
```

- [ ] **Step 4: Commit**

```bash
git add dashboard/templates/main.html dashboard/static/style.css
git commit -m "feat(harness-review-plan2): 顶部 nav 加 V3 / V4 / decisions 入口"
```

---

## Task 10: 跨视图联动闭环 wire up

**Files:** Modify 各 view 模板 + JS 确认所有跳转 work

跨视图联动清单(spec § 8):

| from | to | mechanism |
|---|---|---|
| V1 chip | V2 modal | htmx swap into overlay(Plan 1 已实现) |
| V3 node | V2 modal | cytoscape 'tap' → fetch /cap/{id}(Task 4) |
| V4 卡片 | V2 modal | a + htmx hx-get(Task 8 已实现) |
| V2 modal linked_capability | V3 with anchor | a href="/overview#cap_{id}" |
| V2 modal linked_decision | decisions tab | a href="/decisions#dec_{id}"(Plan 1 已实现) |

- [ ] **Step 1: Verify V2 modal 链接 jump anchor 工作**

在 V3 `overview.js` 末尾加 anchor jump 逻辑:

```javascript
// overview.js 末尾
window.addEventListener('hashchange', () => {
  const anchor = location.hash.replace('#cap_', '');
  if (anchor && cy) {
    const node = cy.getElementById(anchor);
    if (node.length) {
      cy.center(node);
      node.flashClass('highlight', 1500);
    }
  }
});
// 启动时也处理一次
if (location.hash.startsWith('#cap_')) {
  // wait cy init
  setTimeout(() => window.dispatchEvent(new HashChangeEvent('hashchange')), 500);
}
```

CSS:
```css
.cy-flash-highlight { background-color: yellow !important; }
```

- [ ] **Step 2: V2 modal 模板生成 anchor 链接**

Modify `_deep_card_modal.html` linked_capabilities section:

```html
<h3>linked capability</h3>
<ul>
  {% for other_id in deep_card.linked_capabilities if deep_card %}
    <li><a href="/overview#cap_{{ other_id }}">{{ other_id }}</a></li>
  {% endfor %}
</ul>
```

- [ ] **Step 3: 手动验证 5 个跳转**

```bash
make board
```

1. 主页 chip 点击 → modal 弹
2. /overview 节点点击 → modal 弹
3. /story 卡片点击 → modal 弹
4. modal 内 linked_decision → 跳 /decisions#dec_{id}
5. modal 内 linked_capability → 跳 /overview#cap_{id} + highlight

- [ ] **Step 4: Commit**

```bash
git add dashboard/static/overview.js dashboard/static/style.css \
        dashboard/templates/_deep_card_modal.html
git commit -m "feat(harness-review-plan2): 跨视图联动闭环 (V2↔V3 anchor / V4→V2)"
```

---

## Task 11: Plan 2 ship checklist + 收尾测试

**Files:** 测试整体跑通,知识卡

- [ ] **Step 1: 跑全部测试**

```bash
uv run --project backend pytest dashboard/tests/ -v
```

Expected: Plan 1 后的基线 + 新增 ≥ +25 (L0 +20 / L1 +10)= 总 ≥ 140 全 PASS

- [ ] **Step 2: mypy strict**

```bash
uv run --project backend mypy dashboard/ --strict
```

- [ ] **Step 3: ruff**

```bash
uv run --project backend ruff format --check dashboard/
uv run --project backend ruff check dashboard/
```

- [ ] **Step 4: 4 nav 端到端 smoke**

```bash
make board
# 浏览器逐 nav 验证:
#  - / 网格 chip + 完成度角标
#  - /overview cytoscape 图渲染 + 节点点击 modal
#  - /story 三段式卡片 + 时间排序 + 过滤
#  - /decisions 不退化
make board-stop
```

- [ ] **Step 5: 知识卡 + CLAUDE.md**

```bash
cat > docs/claude-context/harness-board-review-plan2-done.md <<'EOF'
---
name: harness-board-review-plan2-done
description: Plan 2 ship — V3 cytoscape 鸟瞰 + V4 故事时间线 + Milvus 真路径 + 跨视图联动
type: project
---

Plan 2 ship 内容:
- V3 `/overview`:cytoscape cose-bilkent 布局 + 8 维染色 + 节点大小 = code_anchors + 边框 = confidence
- V3 工具栏:维度复选 + low_conf 过滤
- V3 cytoscape 失败 fallback → 卡片墙
- V4 `/story`:commit-time 抽取(git log)+ DeepCard.prefill_at fallback + 三段式 render
- V4 工具栏:维度 + 时间窗 + 排序
- 顶部 nav:📊/🌐/📖/⚖ 四 view 入口
- Milvus 相关推荐真路径 wire(POST /admin/milvus/reindex + GET /cap/{id}/related)
- 跨视图联动闭环 5 条全通

**Why**:复习场景 A(面试讲项目)+ C(系统化视角)走通。

**How to apply**:
- 复习"全局架构" → /overview 看鸟瞰图
- 准备面试时讲项目 → /story 按时间顺序 walk through 三段式卡片
- 看某 cap 的相关模块 → modal 右栏相关推荐 (Milvus or keyword fallback)
EOF

# 更新 CLAUDE.md
git add docs/claude-context/harness-board-review-plan2-done.md CLAUDE.md
git commit -m "docs(harness-review-plan2): 知识卡 + CLAUDE.md 索引"
```

- [ ] **Step 6: Push + PR(沿用 Plan 1 同 branch 或新 branch — 看 ship 节奏)**

```bash
git push
# gh pr create ...
```

---

## Plan 2 总结

**交付内容:**
- 6 个新 Python module + 4 个新 template + 1 新 JS + CSS 扩展
- 11 task,TDD step 完整
- 测试覆盖:+20 L0 / +10 L1
- 跨视图联动闭环 5 条全通
- Milvus 真路径补全(Plan 1 简化处)

**用户价值:**
- 复习场景 A(面试讲项目)+ C(系统化)走通
- Plan 1 + Plan 2 合并后,B + C + A 三场景都可用,只缺 D(主动召回 → Plan 3)

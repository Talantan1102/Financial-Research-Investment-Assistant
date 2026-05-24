# Harness Board 框架重做 — Plan 2:DeepCard v2 schema + 模块页 /m/{dim} + 三色 chip + 右键 + 就地展开 + 图上传

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship 看板框架重做的核心 UI 层:DeepCard 字段从自由 JSON 固化为 v2 6 字段(scenario / design / tradeoff / review / decisions / evidence)+ 新增 7 个模块页 `/m/{dim_id}` + chip 三色 + 右键菜单切状态 + 单击就地展开 + 图上传 endpoint(screenshots 进 git)+ markdown + mermaid 客户端渲染。Plan 2 ship 后,「点开任意 capability 看 6 字段 + 改状态 + 上传截图」的最小闭环工作。

**Architecture:** 自下而上 — 先数据层(Pydantic model 加字段 + sqlite payload migration 脚本 + Repo CRUD)→ 模块页骨架(/m/{dim_id} handler + 7 维渲染)→ chip 三色 + 右键菜单(POST /cap/{id}/status rename 复用现有 override 逻辑)→ 就地展开(GET /cap/{id}/expand fragment + slide JS)→ markdown + mermaid 渲染(base.html 引 CDN + render-field.js)→ 图上传(POST /cap/{id}/screenshot + screenshots/ 进 git)→ CSS 收尾。每一步独立可 verify,test 跟上。

**Tech Stack:** Python 3.11 · Starlette · Jinja2 · htmx (already wired) · Pydantic v2 · sqlite3 · marked.js + mermaid.js (CDN) · uv · pytest · pre-commit (ruff + mypy + commit-msg layer validator)。

---

## File Structure

```
新增 — Python:
  dashboard/derive/screenshot_repo.py          (图上传文件系统管理 + path 校验)
  dashboard/scripts/migrate_deepcard_v2.py     (一次性 v1 → v2 schema migration)
  dashboard/tests/unit/test_screenshot_repo.py
  dashboard/tests/unit/test_migrate_deepcard_v2.py
  dashboard/tests/integration/test_module_page.py
  dashboard/tests/integration/test_status_post.py
  dashboard/tests/integration/test_screenshot_upload.py
  dashboard/tests/integration/test_inline_expand.py

新增 — 模板:
  dashboard/templates/_module_page.html        (主结构:breadcrumb + module-head + cap 列表)
  dashboard/templates/_context_menu.html       (右键菜单:3 状态 + 复制锚点)
  dashboard/templates/_deep_card_inline.html   (就地展开 6 字段视图;改 _deep_card_modal 改名)
  dashboard/templates/_screenshot_uploader.html
  dashboard/templates/_field_block.html        (单字段块:label + markdown render + 编辑按钮)

新增 — 静态:
  dashboard/static/inline-expand.js
  dashboard/static/context-menu.js
  dashboard/static/render-field.js
  dashboard/static/screenshot-upload.js
  dashboard/screenshots/.gitkeep               (上传目录占位)

修改:
  dashboard/derive/deep_card_types.py          (DeepCard 加 6 字段 + screenshots list)
  dashboard/state/repositories.py              (DeepCardRepo.update_field 接 v2)
  dashboard/server.py                          (新 routes:/m/{dim} GET / /cap/{id}/expand GET / /cap/{id}/status POST / /cap/{id}/screenshot POST;原 capability/{id}/override → /cap/{id}/status rename)
  dashboard/templates/_capability_chip.html    (重写:三色 + contextmenu hook + onclick toggle expand)
  dashboard/templates/_board_nav.html          (临时加 7 维入口锚;Plan 3 重做主 nav)
  dashboard/templates/base.html                (引 marked.js + mermaid.js CDN)
  dashboard/static/style.css                   (.cap-chip 三色 + .cap-detail + .ctx-menu + .module-page + .markdown-body + .screenshot-uploader)

不动:
  capabilities.yaml / dimensions.yaml          (Plan 1 已稳)
  derive/snapshot_builder / capability_resolver / refresh_pipeline  (核心 derive 不动)
```

---

## Task 0:准备 — baseline grep + verify clean

**Files:** None modified

- [ ] **Step 0.1:验证仓库 clean + 当前 baseline**

```bash
git status --short
uv run pytest dashboard/tests/ -q 2>&1 | tail -3
uv run mypy dashboard/ 2>&1 | tail -3
```

Expected: clean / all pass / 0 mypy issue / 3 skip。**记录 baseline pytest pass 数(后续每个 task 后对比)**。

- [ ] **Step 0.2:grep DeepCard 引用面 — 后续修改不漏**

```bash
grep -rnE "DeepCard\(|DeepCardRepo|deep_cards\.payload|deep_cards|model_validate" dashboard/ backend/ --include="*.py" --include="*.html" 2>&1 | grep -v __pycache__ | head -30
```

Expected: 找出所有 DeepCard 构造点 + Repo CRUD 调用点(用于后续 task verify 改造完整性)。**把输出存为 mental note。**

- [ ] **Step 0.3:grep 现有 _deep_card_modal.html 用法**

```bash
grep -rnE "_deep_card_modal|deep_card_modal" dashboard/ --include="*.py" --include="*.html" 2>&1 | grep -v __pycache__
```

Expected: 1-2 hit(/cap/{id} handler + template include)。**Plan 2 把 modal 改名成 _deep_card_inline.html,这些 hit 要全 rename。**

---

## Task 1:DeepCard model 加 6 字段(deep_card_types.py)

**Files:**
- Modify: `dashboard/derive/deep_card_types.py`
- Test: `dashboard/tests/unit/test_deep_card_types.py`

**重要约束:**
- 保留旧字段(spec / how / effect / scenario / 等)兼容 Plan 1 时迁移留下的旧 payload
- 新加 6 字段(scenario / design / tradeoff / review / decisions / evidence)用 Optional[str] = None,允许 null
- 加 `screenshots: list[str]` 默认空 list
- 加 `schema_version: int = 2`(老 payload 无此字段时默认 1,migration 写入 2)
- **不删** SrsState / Flashcard / TemplateKind(graph_builder 在 Plan 3 退役一并清)

- [ ] **Step 1.1:Read 现有 DeepCard model**

```bash
grep -nE "^class DeepCard" dashboard/derive/deep_card_types.py
```
看 DeepCard 类的当前字段(估计 ~30-50 行),记录已有 field name。

- [ ] **Step 1.2:加 6 字段 + screenshots + schema_version**

在 `DeepCard(BaseModel)` 类的字段定义区域,在最后一个字段后面追加(具体放在 prefill_source 等 audit 字段之前):

```python
    # ----- v2 schema (Plan 2 framework rebuild) -----
    schema_version: int = 1  # 1 = legacy 自由 JSON;2 = 6 字段固化
    scenario: str | None = None  # 需求场景 — markdown
    design: str | None = None  # 设计方案 — markdown + 图 + mermaid
    tradeoff: str | None = None  # Tradeoff — markdown 表格
    review: str | None = None  # 方案点评 — markdown
    decisions_extracted_ids: list[str] = Field(default_factory=list)  # 自动从 spec/plan 抽的 decision_id
    decisions_user_notes: list[str] = Field(default_factory=list)  # 用户手动加 note
    evidence: str | None = None  # 实现效果 — markdown + 截图(仅 lit 必填)
    screenshots: list[str] = Field(default_factory=list)  # path = "screenshots/{cap_id}/{file}.png"
```

> 注:`decisions` 在 spec 里是 nested object;实施时拆成两个 list(`decisions_extracted_ids` + `decisions_user_notes`)避免 Pydantic nested model 复杂,效果同。

如果 `Field` 不在 import 里,顶部加 `from pydantic import Field`(估计已经有 BaseModel import 了)。

- [ ] **Step 1.3:Write the test — verify model 接受 v2 字段**

打开 `dashboard/tests/unit/test_deep_card_types.py`,在 test_deep_card_repo 等已有测试之后追加:

```python
def test_deepcard_accepts_v2_fields() -> None:
    card = DeepCard(
        cap_id="x.y",
        schema_version=2,
        scenario="why this exists",
        design="how it works",
        tradeoff="A vs B",
        review="pros and cons",
        decisions_extracted_ids=["dec_001"],
        decisions_user_notes=["my note"],
        evidence="proof of work",
        screenshots=["screenshots/x.y/foo.png"],
    )
    assert card.schema_version == 2
    assert card.scenario == "why this exists"
    assert card.screenshots == ["screenshots/x.y/foo.png"]


def test_deepcard_v2_fields_default_safe() -> None:
    card = DeepCard(cap_id="x.y")
    assert card.schema_version == 1  # 老数据默认 v1
    assert card.scenario is None
    assert card.screenshots == []
    assert card.decisions_extracted_ids == []
```

- [ ] **Step 1.4:Run test — verify PASS**

```bash
uv run pytest dashboard/tests/unit/test_deep_card_types.py -v 2>&1 | tail -10
```
Expected: 所有 test PASS(包含新 2 个 + 原有的)。

- [ ] **Step 1.5:mypy 整盘 verify**

```bash
uv run mypy dashboard/ 2>&1 | tail -5
```
Expected: `Success: no issues found in 68 source files`。

- [ ] **Step 1.6:Commit**

```bash
git add dashboard/derive/deep_card_types.py dashboard/tests/unit/test_deep_card_types.py
git commit -m "feat(harness-board): DeepCard model add v2 fields (scenario/design/tradeoff/review/decisions/evidence/screenshots) (Plan 2 step 1)"
```

---

## Task 2:Migration script v1 → v2 + 测试

**Files:**
- Create: `dashboard/scripts/migrate_deepcard_v2.py`
- Create: `dashboard/tests/unit/test_migrate_deepcard_v2.py`

**Migration 语义**:
- 读 sqlite `deep_cards.payload` JSON
- 若 `schema_version == 2`(已迁移),跳过
- 否则:把整个 v1 payload 备份到 `legacy_payload` key,新建 v2 字段(全部 None / 空 list),写回 schema_version = 2
- 幂等(跑两遍结果一致)

- [ ] **Step 2.1:Write the failing test**

Create `dashboard/tests/unit/test_migrate_deepcard_v2.py`:

```python
"""Plan 2 Task 2 — DeepCard payload v1 → v2 migration 幂等测试。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from dashboard.scripts.migrate_deepcard_v2 import migrate_payloads


@pytest.fixture
def db_with_v1_cards(tmp_path: Path) -> Path:
    """构造一个含 v1 payload 的 deep_cards 表。"""
    db_path = tmp_path / "board.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE deep_cards (
            cap_id TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            last_edited_at TEXT NOT NULL
        );
        """
    )
    # 模拟 v1 (legacy 自由 JSON) 与已是 v2 的混合
    v1_payload = json.dumps({"cap_id": "a", "spec": "old spec", "how": "old how"})
    v2_payload = json.dumps(
        {
            "cap_id": "b",
            "schema_version": 2,
            "scenario": "already v2",
            "screenshots": [],
        }
    )
    conn.execute(
        "INSERT INTO deep_cards VALUES (?, ?, ?)", ("a", v1_payload, "2026-01-01")
    )
    conn.execute(
        "INSERT INTO deep_cards VALUES (?, ?, ?)", ("b", v2_payload, "2026-01-01")
    )
    conn.commit()
    conn.close()
    return db_path


def _load_payload(db_path: Path, cap_id: str) -> dict[str, object]:
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT payload FROM deep_cards WHERE cap_id = ?", (cap_id,)
    ).fetchone()
    conn.close()
    return json.loads(row[0])  # type: ignore[no-any-return]


def test_migrate_v1_becomes_v2(db_with_v1_cards: Path) -> None:
    n = migrate_payloads(db_with_v1_cards)
    assert n == 1  # 只迁了 cap_a (cap_b 已 v2)
    payload_a = _load_payload(db_with_v1_cards, "a")
    assert payload_a["schema_version"] == 2
    assert payload_a["scenario"] is None
    assert "legacy_payload" in payload_a
    assert payload_a["legacy_payload"]["spec"] == "old spec"


def test_migrate_v2_unchanged(db_with_v1_cards: Path) -> None:
    migrate_payloads(db_with_v1_cards)
    payload_b = _load_payload(db_with_v1_cards, "b")
    assert payload_b["schema_version"] == 2
    assert payload_b["scenario"] == "already v2"
    # cap_b 不应该被迁移再加 legacy_payload
    assert "legacy_payload" not in payload_b


def test_migrate_idempotent(db_with_v1_cards: Path) -> None:
    n1 = migrate_payloads(db_with_v1_cards)
    n2 = migrate_payloads(db_with_v1_cards)
    assert n1 == 1
    assert n2 == 0  # 第二遍 0 项需要迁


def test_migrate_on_empty_table(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE deep_cards (
            cap_id TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            last_edited_at TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()
    n = migrate_payloads(db_path)
    assert n == 0
```

- [ ] **Step 2.2:Run test — verify FAIL**

```bash
uv run pytest dashboard/tests/unit/test_migrate_deepcard_v2.py -v 2>&1 | tail -10
```
Expected: ModuleNotFoundError 或类似(脚本未实现)。

- [ ] **Step 2.3:实现脚本**

Create `dashboard/scripts/migrate_deepcard_v2.py`:

```python
"""一次性脚本:DeepCard payload v1 → v2 migration(Plan 2)。

Usage:
    uv run python -m dashboard.scripts.migrate_deepcard_v2 [/path/to/db]

幂等:已是 v2 (schema_version == 2) 的 payload 跳过。
"""

from __future__ import annotations

import json
import logging
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


V2_BLANK_FIELDS: dict[str, object] = {
    "scenario": None,
    "design": None,
    "tradeoff": None,
    "review": None,
    "decisions_extracted_ids": [],
    "decisions_user_notes": [],
    "evidence": None,
    "screenshots": [],
}


def migrate_payloads(db_path: Path) -> int:
    """迁移 deep_cards.payload from v1 to v2。返回迁移行数。"""
    if not db_path.exists():
        logger.info("db not found at %s — skip", db_path)
        return 0
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    migrated = 0
    try:
        rows = conn.execute("SELECT cap_id, payload FROM deep_cards").fetchall()
        for row in rows:
            payload = json.loads(row["payload"])
            if payload.get("schema_version") == 2:
                continue  # 已迁移
            # 把整个 v1 payload 包进 legacy_payload (保留所有旧字段)
            new_payload = {
                "cap_id": payload.get("cap_id", row["cap_id"]),
                "schema_version": 2,
                "legacy_payload": payload,
                **V2_BLANK_FIELDS,
            }
            with conn:
                conn.execute(
                    "UPDATE deep_cards SET payload = ?, last_edited_at = ? WHERE cap_id = ?",
                    (
                        json.dumps(new_payload),
                        datetime.now(UTC).isoformat(),
                        row["cap_id"],
                    ),
                )
            migrated += 1
        logger.info("migrated %d deep_cards payloads to v2", migrated)
    finally:
        conn.close()
    return migrated


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(sys.argv) > 1:
        db_path = Path(sys.argv[1])
    else:
        db_path = Path(__file__).resolve().parents[1] / "data" / "harness_board.db"
    n = migrate_payloads(db_path)
    print(f"migrated {n} payloads")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2.4:Run test — verify PASS**

```bash
uv run pytest dashboard/tests/unit/test_migrate_deepcard_v2.py -v 2>&1 | tail -10
```
Expected: 4 passed.

- [ ] **Step 2.5:跑全 pytest**

```bash
uv run pytest dashboard/tests/ -q 2>&1 | tail -3
```
Expected: 全 pass(原 baseline + 4 新)。

- [ ] **Step 2.6:Commit**

```bash
git add dashboard/scripts/migrate_deepcard_v2.py dashboard/tests/unit/test_migrate_deepcard_v2.py
git commit -m "feat(harness-board): one-shot DeepCard v1 → v2 payload migration script (Plan 2 step 2)"
```

---

## Task 3:DeepCardRepo.update_field 支持 v2 字段(repositories.py)

**Files:**
- Modify: `dashboard/state/repositories.py`
- Test: `dashboard/tests/integration/test_deep_card_repo.py`

**目标:** 让 `update_field` 能改 v2 的 6 字段 + screenshots。当前实现已经是通用 field map,但需要 verify 6 字段都在 DeepCard.model_fields 中能被识别。

- [ ] **Step 3.1:Read 现有 update_field**

```bash
grep -nA 15 "def update_field" dashboard/state/repositories.py
```
Expected: 看到当前 update_field 实现(check `if field_name not in DeepCard.model_fields: raise KeyError`)。

- [ ] **Step 3.2:Write tests for v2 field update**

打开 `dashboard/tests/integration/test_deep_card_repo.py`,追加:

```python
def test_update_field_scenario(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "t.db")
    repo = DeepCardRepo(conn)
    repo.upsert(DeepCard(cap_id="x", schema_version=2))
    repo.update_field("x", "scenario", "this solves Y")
    got = repo.get("x")
    assert got is not None
    assert got.scenario == "this solves Y"


def test_update_field_screenshots(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "t.db")
    repo = DeepCardRepo(conn)
    repo.upsert(DeepCard(cap_id="x", schema_version=2))
    repo.update_field("x", "screenshots", ["screenshots/x/a.png", "screenshots/x/b.png"])
    got = repo.get("x")
    assert got is not None
    assert got.screenshots == ["screenshots/x/a.png", "screenshots/x/b.png"]


def test_update_field_unknown_raises(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "t.db")
    repo = DeepCardRepo(conn)
    repo.upsert(DeepCard(cap_id="x"))
    with pytest.raises(KeyError):
        repo.update_field("x", "not_a_field", "value")
```

(若顶部缺 `pytest` import,加 `import pytest`)

- [ ] **Step 3.3:Run test**

```bash
uv run pytest dashboard/tests/integration/test_deep_card_repo.py -v 2>&1 | tail -10
```
Expected: 3 个新 test PASS(若已有 update_field 通用实现)。若 FAIL,可能是 update_field 有 hard-coded 字段 list,需调整为通用。

- [ ] **Step 3.4:若需要,修 update_field 通用化**

打开 `dashboard/state/repositories.py`,找 `update_field` 函数。现有实现应该是 `new_data[field_name] = value`,如果没有就调整为:

```python
    def update_field(self, cap_id: str, field_name: str, value: object) -> None:
        """改单个字段。任何 DeepCard.model_fields 中的字段均可。"""
        card = self.get(cap_id) or DeepCard(cap_id=cap_id)
        if field_name not in DeepCard.model_fields:
            raise KeyError(f"DeepCard has no field {field_name}")
        new_data = card.model_dump()
        new_data[field_name] = value
        new_data["last_edited_at"] = datetime.now(UTC).isoformat()
        # prefill_source 转换 (v0 留的逻辑) — 仅在 prefill_source 字段还存在时生效
        if card.prefill_source == "llm":
            new_data["prefill_source"] = "hybrid"
        updated = DeepCard.model_validate(new_data)
        self.upsert(updated)
```

- [ ] **Step 3.5:Run test 再次**

```bash
uv run pytest dashboard/tests/integration/test_deep_card_repo.py -v 2>&1 | tail -5
```
Expected: 全 PASS。

- [ ] **Step 3.6:Commit**

```bash
git add dashboard/state/repositories.py dashboard/tests/integration/test_deep_card_repo.py
git commit -m "feat(harness-board): DeepCardRepo update_field supports v2 fields (Plan 2 step 3)"
```

---

## Task 4:模块页 /m/{dim_id} handler + _module_page.html 模板

**Files:**
- Modify: `dashboard/server.py`(加 `module_page_view` handler + Route)
- Create: `dashboard/templates/_module_page.html`
- Create: `dashboard/tests/integration/test_module_page.py`

**模块页职责**:
- URL `/m/{dim_id}`,dim_id ∈ 7 维(execution / tool / context / lifecycle / observability / verification / governance)
- 显示该维度下所有 capability(读 snapshot)
- 每个 cap 是个 chip + 折叠的 detail 容器(具体 chip 在 Task 5 重写)
- 顶部 breadcrumb 回 / + module-head 显示维度名 + 论文 § 锚 + lit/wip/todo 统计

- [ ] **Step 4.1:加 handler `module_page_view`**

打开 `dashboard/server.py`,在 `index` handler 附近(或 `decisions_view` 之前)加:

```python
async def module_page_view(request: Request) -> HTMLResponse:
    """模块页 — 单维度 capability 列表。Plan 2 Task 4。"""
    dim_id = request.path_params["dim_id"]
    main_dims, _ = load_dimensions(CONFIG_DIR / "dimensions.yaml")
    dim = next((d for d in main_dims if d.id == dim_id), None)
    if dim is None:
        return HTMLResponse(f"unknown dim_id: {dim_id}", status_code=404)

    conn = open_db(DB_PATH)
    try:
        snap_repo = SnapshotRepo(conn)
        snap = snap_repo.get_latest()
        if snap is None:
            # 没快照 — 走 lazy rebuild (复用 index handler 的逻辑)
            from dashboard.derive.snapshot_builder import build_snapshot
            override_repo = OverrideRepo(conn)
            overrides = override_repo.get_all()
            snapshot = build_snapshot(
                PROJECT_ROOT, CONFIG_DIR, overrides=overrides
            )
            snap = snapshot.to_dict()
            snap_repo.save(snap["refreshed_at"], snap)
    finally:
        conn.close()

    # 找到当前维度 layer
    layer = next((L for L in snap["layers"] if L["id"] == dim_id), None)
    if layer is None:
        return HTMLResponse(f"no layer data for dim_id: {dim_id}", status_code=404)

    ctx = {
        "request": request,
        "dim": dim,
        "layer": layer,
        "asset_v": ASSET_V,
    }
    return cast(HTMLResponse, templates.TemplateResponse("_module_page.html", ctx))
```

注意 imports(在文件顶部 verify 已有 `from dashboard.state.repositories import SnapshotRepo, OverrideRepo`)。

- [ ] **Step 4.2:加 Route**

在 routes block 中,加在 `Route("/", index)` 之后:

```python
        Route("/m/{dim_id}", module_page_view),
```

- [ ] **Step 4.3:Create `_module_page.html` template**

```html
{# Plan 2 Task 4 — 模块页主结构 #}
{% extends "base.html" %}
{% block nav %}{% include "_board_nav.html" %}{% endblock %}
{% block content %}

<div class="module-page" data-dim-id="{{ dim.id }}">
  <nav class="breadcrumb">
    <a href="/">首页</a>
    <span class="sep">/</span>
    <span class="current">{{ dim.number }} {{ dim.name_cn }}</span>
  </nav>

  <header class="module-head">
    <h1>
      <span class="num">{{ dim.number }}</span>
      {{ dim.name_cn }}
      <span class="en">{{ dim.name_en }}</span>
    </h1>
    <div class="module-stats">
      <span class="stat stat-lit">{{ layer.lit }} lit</span>
      <span class="stat stat-wip">{{ layer.wip }} wip</span>
      <span class="stat stat-todo">{{ layer.todo }} todo</span>
      <span class="stat-total">/ {{ layer.total }}</span>
      <span class="stat-pct">{{ "%.0f"|format((layer.lit / layer.total * 100) if layer.total else 0) }}%</span>
    </div>
  </header>

  <section class="capabilities">
    <ol class="cap-list">
      {% for c in layer.capabilities %}
        <li class="cap-item" id="cap-{{ c.id }}">
          {% include "_capability_chip.html" %}
          <div class="cap-detail" id="detail-{{ c.id }}" hidden></div>
        </li>
      {% endfor %}
    </ol>
  </section>
</div>

{# 右键菜单 — 固定 hidden,JS show + position #}
{% include "_context_menu.html" %}

<script src="/static/inline-expand.js?v={{ asset_v }}" defer></script>
<script src="/static/context-menu.js?v={{ asset_v }}" defer></script>
<script src="/static/render-field.js?v={{ asset_v }}" defer></script>
{% endblock %}
```

- [ ] **Step 4.4:Stub `_context_menu.html`(Task 6 内容填充,这里空 placeholder 避免 include 报错)**

```html
{# Plan 2 Task 6 — 右键菜单 placeholder; Task 6 真实现 #}
<div id="context-menu" class="ctx-menu" hidden role="menu" aria-hidden="true"></div>
```

- [ ] **Step 4.5:Stub 4 个 JS(empty IIFE,避免 404)**

Create empty stubs:

```bash
for js in inline-expand.js context-menu.js render-field.js screenshot-upload.js; do
  cat > dashboard/static/$js << 'EOF'
// Placeholder — implemented in Plan 2 later tasks
(function(){})();
EOF
done
ls dashboard/static/*.js
```

- [ ] **Step 4.6:Write test for /m/{dim_id}**

Create `dashboard/tests/integration/test_module_page.py`:

```python
"""Plan 2 Task 4 — 模块页 /m/{dim_id} 渲染测试。"""

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


def test_module_page_execution(client: TestClient) -> None:
    resp = client.get("/m/execution")
    assert resp.status_code == 200
    body = resp.text
    assert "module-page" in body
    assert 'data-dim-id="execution"' in body
    assert "执行环境" in body


def test_module_page_all_7_dims(client: TestClient) -> None:
    """7 维度全部 200。"""
    for dim_id in [
        "execution",
        "tool",
        "context",
        "lifecycle",
        "observability",
        "verification",
        "governance",
    ]:
        resp = client.get(f"/m/{dim_id}")
        assert resp.status_code == 200, f"failed for {dim_id}"
        assert f'data-dim-id="{dim_id}"' in resp.text


def test_module_page_unknown_dim_404(client: TestClient) -> None:
    resp = client.get("/m/totally_invalid")
    assert resp.status_code == 404


def test_module_page_shows_capability_chips(client: TestClient) -> None:
    """每维度页面 render capability chip — chip 数 > 0。"""
    resp = client.get("/m/execution")
    body = resp.text
    # 简单断言:cap-item li 出现至少 N 次(execution 维度估计有 ~10 个 cap)
    assert body.count('class="cap-item"') >= 5
```

- [ ] **Step 4.7:Run test**

```bash
uv run pytest dashboard/tests/integration/test_module_page.py -v 2>&1 | tail -15
```
Expected: 4 PASS。若 FAIL,常见原因:
- `data-dim-id` not in body — template render 有问题
- `cap-item` count 不够 — snapshot 没 build,或 dimensions.yaml 与 capabilities.yaml 不一致

- [ ] **Step 4.8:Smoke /m/{dim} 浏览器风格(curl)**

```bash
uv run python -c "
from starlette.testclient import TestClient
from dashboard.server import app
client = TestClient(app)
r = client.get('/m/execution')
print('status:', r.status_code)
print('chip count:', r.text.count('cap-item'))
"
```
Expected: status 200, chip count ≥ 5。

- [ ] **Step 4.9:Commit**

```bash
git add dashboard/server.py dashboard/templates/_module_page.html dashboard/templates/_context_menu.html dashboard/static/*.js dashboard/tests/integration/test_module_page.py
git commit -m "feat(harness-board): module page /m/{dim_id} handler + template + 4 JS stubs (Plan 2 step 4)"
```

---

## Task 5:_capability_chip.html 重写(三色 + contextmenu hook + onclick toggle)

**Files:**
- Modify: `dashboard/templates/_capability_chip.html`
- Modify: `dashboard/static/style.css`(在 Task 10 统一,此处加最小 inline 样式占位)

**目标:** chip 显示三色背景 + 状态 badge + 单击 toggle 就地展开 + 右键打开菜单。

- [ ] **Step 5.1:Read 现有 _capability_chip.html**

```bash
cat dashboard/templates/_capability_chip.html
```
看现有结构(已知:chip 是 `<a>` 标签 + status class)。

- [ ] **Step 5.2:重写 _capability_chip.html**

替换整个文件内容:

```html
{# Plan 2 Task 5 — 三色 chip + 右键菜单 + 单击就地展开 #}
{% set status = c.status|default('todo') %}
<button
  type="button"
  class="cap-chip cap-chip--{{ status }}"
  data-cap-id="{{ c.id }}"
  data-status="{{ status }}"
  hx-get="/cap/{{ c.id }}/expand"
  hx-target="#detail-{{ c.id }}"
  hx-swap="innerHTML"
  hx-trigger="click[ctrlKey === false]"
  onclick="window.harness?.toggleExpand?.('{{ c.id }}')"
  oncontextmenu="return window.harness?.showContextMenu?.(event, '{{ c.id }}') ?? true">
  <span class="cap-dot dot-{{ status }}"></span>
  <span class="cap-name">{{ c.name_cn }}</span>
  <span class="cap-en">{{ c.name_en }}</span>
  <span class="cap-status status--{{ status }}">{{ {'lit':'已实现','wip':'开发中','todo':'未开发'}.get(status, status) }}</span>
</button>
```

> 注:`window.harness` namespace 在 Task 6 / Task 7 JS 里挂载。chip 模板这一步只搭 hook,JS 实现下面 task 填。

- [ ] **Step 5.3:加 CSS chip 三色基础(style.css 末尾追加,Task 10 再完善)**

打开 `dashboard/static/style.css`,在文件末尾追加:

```css
/* ============================================================
 * Plan 2 Task 5 — chip 三色 (full polish in Task 10)
 * ============================================================ */
.cap-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  border-radius: 999px;
  border: 1px solid transparent;
  background: white;
  font-family: inherit;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.16s ease-out;
}
.cap-chip:hover { transform: translateY(-1px); box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
.cap-chip--lit  { background: rgba(52,199,89,0.10); border-color: rgba(52,199,89,0.30); }
.cap-chip--wip  { background: rgba(255,159,10,0.10); border-color: rgba(255,159,10,0.35); border-style: dashed; }
.cap-chip--todo { background: white; border-color: rgba(199,199,204,0.6); }

.cap-dot { width: 8px; height: 8px; border-radius: 50%; }
.dot-lit  { background: #34C759; }
.dot-wip  { background: #FF9F0A; }
.dot-todo { background: #C7C7CC; }

.cap-name { font-weight: 500; }
.cap-en { color: #86868B; font-size: 11px; }
.cap-status { font-size: 11px; padding: 2px 8px; border-radius: 10px; background: rgba(0,0,0,0.04); color: #6E6E73; }

.cap-item { list-style: none; margin: 10px 0; }
.cap-detail { margin-top: 10px; padding: 0 18px; overflow: hidden; }
.cap-detail[hidden] { display: none; }

.module-page { max-width: 1100px; margin: 30px auto; padding: 0 32px; }
.breadcrumb { font-size: 13px; color: #86868B; margin-bottom: 18px; }
.breadcrumb a { color: #86868B; text-decoration: none; }
.breadcrumb a:hover { color: #5E5CE6; }
.breadcrumb .sep { margin: 0 8px; opacity: 0.4; }
.breadcrumb .current { color: #1C1C1E; }

.module-head h1 { font-size: 28px; font-weight: 600; margin-bottom: 8px; }
.module-head h1 .num { color: #5E5CE6; margin-right: 12px; font-family: 'Geist Mono', monospace; font-size: 22px; }
.module-head h1 .en { color: #86868B; font-weight: 400; font-size: 18px; margin-left: 14px; font-style: italic; }
.module-stats { font-size: 12px; color: #6E6E73; margin-bottom: 24px; }
.module-stats .stat { margin-right: 14px; font-family: 'Geist Mono', monospace; }
.module-stats .stat-lit  { color: #34C759; }
.module-stats .stat-wip  { color: #FF9F0A; }
.module-stats .stat-todo { color: #86868B; }
.module-stats .stat-total { color: #86868B; }
.module-stats .stat-pct { color: #5E5CE6; margin-left: 8px; font-weight: 600; }

.cap-list { padding: 0; list-style: none; }
```

- [ ] **Step 5.4:Smoke /m/execution — chip 三色显示**

```bash
uv run python -c "
from starlette.testclient import TestClient
from dashboard.server import app
client = TestClient(app)
r = client.get('/m/execution')
body = r.text
# 验证三色 class 都出现
print('lit chip:', 'cap-chip--lit' in body)
print('wip chip:', 'cap-chip--wip' in body)
print('todo chip:', 'cap-chip--todo' in body)
print('three colors expected for execution dim')
"
```
Expected: True / True / True(execution 维度有 7-8 项 cap,三种状态都该有)。

- [ ] **Step 5.5:跑全 pytest verify**

```bash
uv run pytest dashboard/tests/ -q 2>&1 | tail -3
```
Expected: 0 regression。

- [ ] **Step 5.6:Commit**

```bash
git add dashboard/templates/_capability_chip.html dashboard/static/style.css
git commit -m "feat(harness-board): chip 三色 + contextmenu hook + module page CSS scaffold (Plan 2 step 5)"
```

---

## Task 6:右键菜单 + POST /cap/{id}/status

**Files:**
- Modify: `dashboard/templates/_context_menu.html`
- Modify: `dashboard/static/context-menu.js`
- Modify: `dashboard/server.py`(rename `/capability/{id}/override` → `/cap/{id}/status`,return chip fragment)
- Test: `dashboard/tests/integration/test_status_post.py`

- [ ] **Step 6.1:Read 现有 `/capability/{cap_id}/override` handler**

```bash
grep -nA 20 "async def post_override" dashboard/server.py
```
看当前 handler 做什么(应该是 upsert OverrideRepo)。

- [ ] **Step 6.2:加新 handler `post_status` + Route**

在 server.py 加(rename 的对应位置):

```python
async def post_status(request: Request) -> HTMLResponse:
    """右键菜单切状态。Plan 2 Task 6;原 /capability/{id}/override 简化版。"""
    cap_id = request.path_params["cap_id"]
    form = await request.form()
    status = form.get("status", "")
    if status not in {"lit", "wip", "todo"}:
        return HTMLResponse(f"invalid status: {status}", status_code=400)

    conn = open_db(DB_PATH)
    try:
        OverrideRepo(conn).upsert(cap_id, cast(CapabilityStatus, status), reason="right-click")
        # invalidate snapshot — 下次 GET 刷新
        SnapshotRepo(conn).invalidate()
    finally:
        conn.close()

    # 返回单 chip fragment(htmx swap)
    # 注:为了简洁,这里返回 chip-only 的最小 HTML 让 htmx swap;不重新跑 snapshot rebuild
    # capability_resolver 等等的 derived 还得等 next GET / rebuild
    cfg = next(
        (c for c in load_capabilities(CONFIG_DIR / "capabilities.yaml") if c.id == cap_id),
        None,
    )
    if cfg is None:
        return HTMLResponse(f"unknown cap: {cap_id}", status_code=404)
    chip_ctx = {
        "request": request,
        "c": {
            "id": cfg.id,
            "name_cn": cfg.name_cn,
            "name_en": cfg.name_en,
            "status": status,
        },
    }
    return cast(HTMLResponse, templates.TemplateResponse("_capability_chip.html", chip_ctx))
```

> 注:`CapabilityStatus` import 应该已在 server.py 顶部。`load_capabilities` 同。

加 Route:
```python
        Route("/cap/{cap_id}/status", post_status, methods=["POST"]),
```

**保留** 原 `/capability/{cap_id}/override` Route(避免现有可能调用方坏掉)— 但 nav 和模板都不用它了,后续 Plan 3 清除。

- [ ] **Step 6.3:写 _context_menu.html 真实内容**

替换 stub 内容:

```html
{# Plan 2 Task 6 — 右键菜单 (3 状态切换 + 复制锚点链接) #}
<div id="context-menu" class="ctx-menu" hidden role="menu" aria-hidden="true" data-cap-id="">
  <button class="ctx-item ctx-item--lit"
          type="button"
          hx-post="/cap/__CAP__/status"
          hx-target="closest .cap-chip, button[data-cap-id='__CAP__']"
          hx-swap="outerHTML"
          hx-vals='{"status":"lit"}'
          data-status="lit">
    <span class="ctx-dot dot-lit"></span> 标为已实现
  </button>
  <button class="ctx-item ctx-item--wip"
          type="button"
          hx-post="/cap/__CAP__/status"
          hx-vals='{"status":"wip"}'
          data-status="wip">
    <span class="ctx-dot dot-wip"></span> 标为开发中
  </button>
  <button class="ctx-item ctx-item--todo"
          type="button"
          hx-post="/cap/__CAP__/status"
          hx-vals='{"status":"todo"}'
          data-status="todo">
    <span class="ctx-dot dot-todo"></span> 标为未开发
  </button>
  <hr>
  <button class="ctx-item ctx-item--anchor"
          type="button"
          onclick="window.harness?.copyAnchor?.()">
    📋 复制锚点链接
  </button>
</div>
```

> JS 会动态把 `__CAP__` 替换成实际 cap_id,因为同一个菜单 dom 在不同 chip 之间复用。

- [ ] **Step 6.4:实现 context-menu.js**

```javascript
// Plan 2 Task 6 — 右键菜单 show / position / dispatch
(function () {
  let currentCapId = null;
  const menu = () => document.getElementById('context-menu');

  function showContextMenu(event, capId) {
    event.preventDefault();
    currentCapId = capId;
    const m = menu();
    if (!m) return false;
    m.dataset.capId = capId;
    // 替换 hx-post URL 占位
    m.querySelectorAll('[hx-post]').forEach(btn => {
      const orig = btn.getAttribute('hx-post');
      btn.setAttribute('hx-post', orig.replace(/__CAP__/g, capId));
      btn.setAttribute('hx-target', `button[data-cap-id="${capId}"]`);
      btn.setAttribute('hx-swap', 'outerHTML');
    });
    // 重处理 htmx
    if (window.htmx) window.htmx.process(m);
    // 定位
    m.style.left = event.pageX + 'px';
    m.style.top = event.pageY + 'px';
    m.hidden = false;
    m.setAttribute('aria-hidden', 'false');
    return false;  // 阻止默认右键菜单
  }

  function hideContextMenu() {
    const m = menu();
    if (!m) return;
    m.hidden = true;
    m.setAttribute('aria-hidden', 'true');
    // restore hx-post 占位(下次右键不同 cap 时)
    m.querySelectorAll('[hx-post]').forEach(btn => {
      btn.setAttribute(
        'hx-post',
        btn.getAttribute('hx-post').replace(/\/cap\/[^/]+\//, '/cap/__CAP__/')
      );
    });
  }

  function copyAnchor() {
    if (!currentCapId) return;
    const dim = location.pathname.split('/').pop();
    const url = `${location.origin}/m/${dim}#cap-${currentCapId}`;
    navigator.clipboard.writeText(url).then(
      () => window.harness?.toast?.('锚点已复制'),
      () => alert(url)
    );
    hideContextMenu();
  }

  // 点击 menu 外侧关闭
  document.addEventListener('click', (e) => {
    const m = menu();
    if (m && !m.hidden && !m.contains(e.target)) hideContextMenu();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') hideContextMenu();
  });
  // status 切换成功后(htmx 完成 swap),关闭菜单
  document.addEventListener('htmx:afterSwap', (e) => {
    if (e.detail.target && e.detail.target.classList?.contains('cap-chip')) {
      hideContextMenu();
      window.harness?.toast?.('状态已更新');
    }
  });

  window.harness = window.harness || {};
  window.harness.showContextMenu = showContextMenu;
  window.harness.copyAnchor = copyAnchor;
})();
```

- [ ] **Step 6.5:加 .ctx-menu CSS(style.css 末尾追加)**

```css
/* Plan 2 Task 6 — 右键菜单 */
.ctx-menu {
  position: absolute;
  z-index: 1000;
  min-width: 180px;
  padding: 6px;
  background: white;
  border: 1px solid rgba(60,60,67,0.12);
  border-radius: 10px;
  box-shadow: 0 8px 28px rgba(0,0,0,0.12);
}
.ctx-menu[hidden] { display: none; }
.ctx-menu hr { margin: 4px 8px; border: 0; border-top: 1px solid rgba(60,60,67,0.10); }
.ctx-item {
  display: flex; align-items: center; gap: 10px;
  width: 100%; padding: 8px 12px;
  background: transparent; border: 0; border-radius: 6px;
  font: inherit; font-size: 13px; color: #1C1C1E;
  text-align: left; cursor: pointer;
}
.ctx-item:hover { background: rgba(94,92,230,0.08); }
.ctx-dot { width: 8px; height: 8px; border-radius: 50%; }
```

- [ ] **Step 6.6:Write tests**

Create `dashboard/tests/integration/test_status_post.py`:

```python
"""Plan 2 Task 6 — POST /cap/{id}/status 三色切换测试。"""

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


def test_status_post_sets_lit(client: TestClient) -> None:
    resp = client.post("/cap/execution.docker_compose/status", data={"status": "lit"})
    assert resp.status_code == 200
    assert "cap-chip--lit" in resp.text


def test_status_post_sets_wip(client: TestClient) -> None:
    resp = client.post("/cap/execution.docker_compose/status", data={"status": "wip"})
    assert resp.status_code == 200
    assert "cap-chip--wip" in resp.text


def test_status_post_invalid_status_400(client: TestClient) -> None:
    resp = client.post("/cap/execution.docker_compose/status", data={"status": "invalid"})
    assert resp.status_code == 400


def test_status_post_unknown_cap_404(client: TestClient) -> None:
    resp = client.post("/cap/not_a_cap/status", data={"status": "lit"})
    assert resp.status_code == 404


def test_status_post_persists_in_override(client: TestClient, tmp_path: Path) -> None:
    """切状态后 override 表里应有记录。"""
    from dashboard.state.db import open_db
    from dashboard.state.repositories import OverrideRepo

    client.post("/cap/execution.docker_compose/status", data={"status": "lit"})
    # client fixture monkeypatches server.DB_PATH = tmp_path / "test.db"
    conn = open_db(tmp_path / "test.db")
    overrides = OverrideRepo(conn).get_all()
    conn.close()
    assert overrides.get("execution.docker_compose") == "lit"
```

- [ ] **Step 6.7:Run tests**

```bash
uv run pytest dashboard/tests/integration/test_status_post.py -v 2>&1 | tail -10
```
Expected: 5 PASS.

- [ ] **Step 6.8:跑全 pytest + mypy**

```bash
uv run pytest dashboard/tests/ -q 2>&1 | tail -3
uv run mypy dashboard/ 2>&1 | tail -3
```
Expected: 全 pass / 0 mypy issue.

- [ ] **Step 6.9:Commit**

```bash
git add dashboard/server.py dashboard/templates/_context_menu.html dashboard/static/context-menu.js dashboard/static/style.css dashboard/tests/integration/test_status_post.py
git commit -m "feat(harness-board): right-click context menu + POST /cap/{id}/status (Plan 2 step 6)"
```

---

## Task 7:就地展开 GET /cap/{id}/expand + _deep_card_inline.html + inline-expand.js

**Files:**
- Modify: `dashboard/server.py`(改 `deep_card_modal` handler → `cap_expand` 简化版,返回 fragment)
- Rename: `dashboard/templates/_deep_card_modal.html` → `dashboard/templates/_deep_card_inline.html`
- Create: `dashboard/templates/_field_block.html`(可复用单字段块)
- Modify: `dashboard/static/inline-expand.js`(slide animation)
- Test: `dashboard/tests/integration/test_inline_expand.py`

- [ ] **Step 7.1:Rename _deep_card_modal.html → _deep_card_inline.html**

```bash
git mv dashboard/templates/_deep_card_modal.html dashboard/templates/_deep_card_inline.html
grep -rn "_deep_card_modal\|deep_card_modal" dashboard/ --include="*.py" --include="*.html"
```

把所有 hit 改成 `_deep_card_inline` / `deep_card_inline`(预期 ~2 hit,在 server.py + 模板内 include)。

- [ ] **Step 7.2:重写 _deep_card_inline.html 为 6 字段 inline 视图**

```html
{# Plan 2 Task 7 — inline expand 6 字段视图 #}
<div class="cap-detail-inner">
  <header class="cap-detail-head">
    <span class="cap-detail-id">{{ cap.id }}</span>
    <span class="cap-detail-status status--{{ cap.status }}">{{ cap.status }}</span>
    <span class="cap-detail-dim">§ {{ cap.dimension }}</span>
  </header>

  {% set fields = [
    ('scenario',   '需求场景',    card.scenario if card else None,   true),
    ('design',     '设计方案',    card.design if card else None,     true),
    ('tradeoff',   'Tradeoff',    card.tradeoff if card else None,   true),
    ('review',     '方案点评',    card.review if card else None,     true),
    ('evidence',   '实现效果',    card.evidence if card else None,   cap.status == 'lit'),
  ] %}

  {% for fid, label, value, enabled in fields %}
    {% set c = {'id': cap.id, 'field_id': fid, 'label': label, 'value': value, 'enabled': enabled} %}
    {% include "_field_block.html" %}
  {% endfor %}

  {# 决策记录 (字段 5) — 派生自 spec/plan 抽 + 用户 note #}
  <section class="field-block field-decisions">
    <header class="field-head">
      <span class="field-label">§ 决策记录</span>
      <span class="field-meta">{{ (card.decisions_extracted_ids|length if card else 0) }} 派生 · {{ (card.decisions_user_notes|length if card else 0) }} note</span>
    </header>
    <div class="field-body">
      {% if card and card.decisions_extracted_ids %}
        <ul class="decisions-list">
          {% for did in card.decisions_extracted_ids %}
            <li>◇ <code>{{ did }}</code></li>
          {% endfor %}
        </ul>
      {% else %}
        <p class="field-empty">(暂无关联决策 — 后续从 spec/plan 自动抽取)</p>
      {% endif %}
    </div>
  </section>
</div>
```

- [ ] **Step 7.3:Create _field_block.html**

```html
{# Plan 2 Task 7 — 单字段块 (可复用):label + markdown render + 编辑按钮 #}
<section class="field-block field-{{ c.field_id }}{% if not c.enabled %} field-disabled{% endif %}"
         data-field="{{ c.field_id }}">
  <header class="field-head">
    <span class="field-label">§ {{ c.label }}</span>
    {% if c.enabled %}
      <button type="button"
              class="field-edit-btn"
              onclick="window.harness?.editField?.('{{ c.id }}', '{{ c.field_id }}')">
        ✎ 编辑
      </button>
    {% else %}
      <span class="field-disabled-hint">(状态切到 lit 时启用)</span>
    {% endif %}
  </header>
  <div class="field-body markdown-body"
       id="field-{{ c.id }}-{{ c.field_id }}"
       data-raw-markdown="{{ c.value|default('') }}">
    {% if c.value %}
      {# 客户端 marked.js + mermaid 渲染;服务端只塞 raw markdown 到 data attr #}
      <pre class="markdown-fallback">{{ c.value }}</pre>
    {% else %}
      <p class="field-empty">(待填)</p>
    {% endif %}
  </div>
</section>
```

> 渲染策略:服务端把 raw markdown 放 `data-raw-markdown`,客户端 `render-field.js` 在 expand 完成后扫描 .field-body[data-raw-markdown] 调 marked.js + mermaid 渲染。

- [ ] **Step 7.4:改 server.py — `deep_card_modal` handler 改名 + 简化为 `cap_expand`**

```bash
grep -nE "async def deep_card_modal|deep_card_modal" dashboard/server.py
```

把 `async def deep_card_modal` 改名为 `cap_expand`。函数内容主要逻辑保留(读 DeepCard + cfg + render template),但 template 用 `_deep_card_inline.html`,Response 是 fragment(不需要 full page wrap)。

具体改造(改 handler 体 + route path):

```python
async def cap_expand(request: Request) -> HTMLResponse:
    """单击 capability chip 触发 — 返回 6 字段 inline fragment。Plan 2 Task 7。"""
    cap_id = request.path_params["cap_id"]
    cfg = next(
        (c for c in load_capabilities(CONFIG_DIR / "capabilities.yaml") if c.id == cap_id),
        None,
    )
    if cfg is None:
        return HTMLResponse(f"unknown cap: {cap_id}", status_code=404)

    conn = open_db(DB_PATH)
    try:
        card = DeepCardRepo(conn).get(cap_id)
    finally:
        conn.close()

    derived_status = resolve_status(cfg, PROJECT_ROOT)
    cap = {
        "id": cfg.id,
        "name_cn": cfg.name_cn,
        "status": derived_status,
        "dimension": cfg.dimension,
    }

    ctx = {"request": request, "cap": cap, "card": card}
    return cast(HTMLResponse, templates.TemplateResponse("_deep_card_inline.html", ctx))
```

Route 改:从 `/cap/{cap_id}` 改为 `/cap/{cap_id}/expand`(因为 GET /cap/{cap_id} 既不直观也跟 status POST 不一致;chip 模板已经写 `hx-get="/cap/{cap_id}/expand"`)。

旧 Route(`Route("/cap/{cap_id}", deep_card_modal, methods=["GET"])`)改为:
```python
        Route("/cap/{cap_id}/expand", cap_expand, methods=["GET"]),
```

注意 mypy:函数内 cfg 类型注解可能需要 `Optional`(`from typing import Optional`)— 看 mypy 怎么说。

- [ ] **Step 7.5:实现 inline-expand.js**

```javascript
// Plan 2 Task 7 — inline expand toggle (slide animation)
(function () {
  function toggleExpand(capId) {
    const detail = document.getElementById(`detail-${capId}`);
    if (!detail) return;
    if (detail.hidden) {
      detail.hidden = false;
      detail.style.maxHeight = '0';
      detail.style.opacity = '0';
      detail.style.transition = 'max-height 0.24s ease-out, opacity 0.18s';
      requestAnimationFrame(() => {
        detail.style.maxHeight = detail.scrollHeight + 'px';
        detail.style.opacity = '1';
      });
      // 渲染完成后触发 markdown + mermaid render
      detail.addEventListener('htmx:afterSwap', () => {
        window.harness?.renderField?.(detail);
      }, { once: true });
    } else {
      detail.style.maxHeight = '0';
      detail.style.opacity = '0';
      setTimeout(() => {
        detail.hidden = true;
        detail.innerHTML = '';  // 清空,下次重新 fetch
      }, 240);
    }
  }

  // URL hash 自动展开 (锚点链接)
  window.addEventListener('DOMContentLoaded', () => {
    if (location.hash && location.hash.startsWith('#cap-')) {
      const capId = location.hash.substring(5);
      const chip = document.querySelector(`button[data-cap-id="${capId}"]`);
      if (chip) {
        chip.scrollIntoView({ behavior: 'smooth', block: 'center' });
        setTimeout(() => chip.click(), 400);
      }
    }
  });

  window.harness = window.harness || {};
  window.harness.toggleExpand = toggleExpand;
})();
```

- [ ] **Step 7.6:加 .cap-detail / .field-block CSS(style.css 末尾追加)**

```css
/* Plan 2 Task 7 — inline expand layout */
.cap-detail-inner {
  background: rgba(245,245,247,0.5);
  border-radius: 12px;
  padding: 24px 28px;
  margin: 4px 0 20px;
}
.cap-detail-head {
  display: flex; align-items: baseline; gap: 14px;
  margin-bottom: 18px;
  padding-bottom: 12px;
  border-bottom: 1px solid rgba(60,60,67,0.08);
}
.cap-detail-id { font-family: 'Geist Mono', monospace; font-size: 12px; color: #5E5CE6; }
.cap-detail-status { font-size: 11px; padding: 2px 8px; border-radius: 10px; }
.status--lit  { background: rgba(52,199,89,0.14); color: #1B7A33; }
.status--wip  { background: rgba(255,159,10,0.14); color: #B25800; }
.status--todo { background: rgba(199,199,204,0.30); color: #6E6E73; }
.cap-detail-dim { color: #86868B; font-size: 11px; }

.field-block { margin-bottom: 18px; }
.field-block.field-disabled { opacity: 0.45; }
.field-head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 6px; }
.field-label { font-weight: 600; font-size: 13px; color: #1C1C1E; }
.field-meta  { font-size: 11px; color: #86868B; font-family: 'Geist Mono', monospace; }
.field-edit-btn {
  background: transparent; border: 0; color: #5E5CE6;
  font: inherit; font-size: 12px; cursor: pointer; padding: 2px 8px;
  border-radius: 6px;
}
.field-edit-btn:hover { background: rgba(94,92,230,0.10); }
.field-disabled-hint { font-size: 11px; color: #C7C7CC; font-style: italic; }

.field-body { font-size: 14px; line-height: 1.6; color: #1C1C1E; }
.field-empty { color: #C7C7CC; font-size: 12px; font-style: italic; }
.markdown-fallback { font-family: inherit; white-space: pre-wrap; background: rgba(60,60,67,0.03); padding: 8px 12px; border-radius: 6px; }

.decisions-list { padding-left: 18px; font-size: 13px; color: #6E6E73; }
.decisions-list code { font-family: 'Geist Mono', monospace; font-size: 12px; background: rgba(94,92,230,0.08); padding: 1px 6px; border-radius: 4px; color: #5E5CE6; }
```

- [ ] **Step 7.7:Write tests**

Create `dashboard/tests/integration/test_inline_expand.py`:

```python
"""Plan 2 Task 7 — GET /cap/{id}/expand inline expand fragment 测试。"""

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


def test_expand_returns_fragment(client: TestClient) -> None:
    resp = client.get("/cap/execution.docker_compose/expand")
    assert resp.status_code == 200
    body = resp.text
    assert "cap-detail-inner" in body
    assert "需求场景" in body
    assert "设计方案" in body
    assert "Tradeoff" in body
    assert "方案点评" in body
    assert "实现效果" in body
    assert "决策记录" in body


def test_expand_unknown_cap_404(client: TestClient) -> None:
    resp = client.get("/cap/not_a_cap/expand")
    assert resp.status_code == 404


def test_expand_lit_status_shows_evidence_enabled(client: TestClient) -> None:
    """状态 lit 的 cap,evidence 字段应该 enabled(没有 field-disabled class)。"""
    # docker_compose 默认 derive_rule 是 file_exists docker-compose.yml — 实际环境通常 lit
    resp = client.get("/cap/execution.docker_compose/expand")
    # 简单断言:evidence section 存在
    assert "field-evidence" in resp.text


def test_expand_with_existing_card_shows_content(client: TestClient, tmp_path: Path) -> None:
    """若 deep_cards 表里有内容,expand 应该显示它。"""
    from dashboard.derive.deep_card_types import DeepCard
    from dashboard.state.db import open_db
    from dashboard.state.repositories import DeepCardRepo

    db = tmp_path / "test.db"
    conn = open_db(db)
    DeepCardRepo(conn).upsert(
        DeepCard(
            cap_id="execution.docker_compose",
            schema_version=2,
            scenario="this is the scenario text for testing",
        )
    )
    conn.close()

    resp = client.get("/cap/execution.docker_compose/expand")
    assert resp.status_code == 200
    assert "this is the scenario text for testing" in resp.text
```

- [ ] **Step 7.8:Run tests**

```bash
uv run pytest dashboard/tests/integration/test_inline_expand.py -v 2>&1 | tail -10
```
Expected: 4 PASS.

- [ ] **Step 7.9:Commit**

```bash
git add dashboard/server.py dashboard/templates/_deep_card_inline.html dashboard/templates/_field_block.html dashboard/static/inline-expand.js dashboard/static/style.css dashboard/tests/integration/test_inline_expand.py
# 注意:git mv 已经 stage了 _deep_card_modal -> _deep_card_inline 这一 rename
git commit -m "feat(harness-board): inline expand 6-field view + GET /cap/{id}/expand + slide animation (Plan 2 step 7)"
```

---

## Task 8:base.html 引 marked + mermaid CDN + render-field.js

**Files:**
- Modify: `dashboard/templates/base.html`
- Modify: `dashboard/static/render-field.js`

- [ ] **Step 8.1:Read base.html 顶部**

```bash
head -25 dashboard/templates/base.html
```

- [ ] **Step 8.2:在 base.html 加 marked + mermaid CDN(`</head>` 前)**

打开 `dashboard/templates/base.html`,在已有 `<link rel="stylesheet" href="/static/style.css...">` 之后追加:

```html
  {# Plan 2 Task 8 — marked.js (markdown render) + mermaid.js (sequence diagram render) #}
  <script src="https://cdn.jsdelivr.net/npm/marked@12/marked.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
  <script>
    if (window.mermaid) {
      mermaid.initialize({ startOnLoad: false, theme: 'neutral', fontFamily: 'inherit' });
    }
  </script>
```

- [ ] **Step 8.3:实现 render-field.js**

```javascript
// Plan 2 Task 8 — 客户端 markdown + mermaid 渲染
(function () {
  function renderMarkdown(raw) {
    if (!window.marked || !raw) return raw;
    let html = window.marked.parse(raw, { breaks: true });
    // mermaid 代码块包装成 <div class="mermaid">
    html = html.replace(
      /<pre><code class="language-mermaid">([\s\S]*?)<\/code><\/pre>/g,
      (_, code) => `<div class="mermaid">${decodeHtml(code)}</div>`
    );
    return html;
  }

  function decodeHtml(s) {
    const t = document.createElement('textarea');
    t.innerHTML = s;
    return t.value;
  }

  function renderField(container) {
    if (!container) return;
    const nodes = container.querySelectorAll('.field-body[data-raw-markdown]');
    nodes.forEach(node => {
      const raw = node.getAttribute('data-raw-markdown');
      if (!raw) return;
      node.innerHTML = renderMarkdown(raw);
    });
    // mermaid 渲染
    if (window.mermaid) {
      const mermaids = container.querySelectorAll('.mermaid');
      if (mermaids.length > 0) {
        window.mermaid.run({ nodes: mermaids });
      }
    }
  }

  // story 页:textarea oninput 触发(预留 hook for Plan 4)
  function renderStory(raw) {
    const out = document.getElementById('story-out');
    if (!out) return;
    out.innerHTML = renderMarkdown(raw);
    renderField(out);
  }

  window.harness = window.harness || {};
  window.harness.renderField = renderField;
  window.harness.renderStory = renderStory;
  window.harness.renderMarkdown = renderMarkdown;
})();
```

- [ ] **Step 8.4:加 markdown-body CSS(style.css 末尾追加)**

```css
/* Plan 2 Task 8 — markdown rendered content typography */
.markdown-body { font-size: 14px; line-height: 1.7; color: #1C1C1E; }
.markdown-body h1, .markdown-body h2, .markdown-body h3 { margin-top: 16px; margin-bottom: 8px; font-weight: 600; }
.markdown-body h1 { font-size: 18px; }
.markdown-body h2 { font-size: 16px; }
.markdown-body h3 { font-size: 14px; }
.markdown-body p { margin: 8px 0; }
.markdown-body ul, .markdown-body ol { padding-left: 24px; margin: 8px 0; }
.markdown-body li { margin: 4px 0; }
.markdown-body code { font-family: 'Geist Mono', monospace; font-size: 12px; background: rgba(60,60,67,0.05); padding: 1px 6px; border-radius: 4px; }
.markdown-body pre { background: rgba(60,60,67,0.04); padding: 12px 16px; border-radius: 8px; overflow-x: auto; font-size: 12px; }
.markdown-body pre code { background: transparent; padding: 0; }
.markdown-body img { max-width: 100%; border-radius: 8px; margin: 8px 0; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
.markdown-body table { border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 13px; }
.markdown-body th, .markdown-body td { padding: 6px 10px; border: 1px solid rgba(60,60,67,0.10); }
.markdown-body th { background: rgba(60,60,67,0.04); font-weight: 600; }
.markdown-body blockquote { padding: 8px 14px; border-left: 3px solid #5E5CE6; background: rgba(94,92,230,0.05); margin: 12px 0; }
.markdown-body .mermaid { background: rgba(245,245,247,0.6); padding: 12px; border-radius: 8px; margin: 12px 0; text-align: center; }
```

- [ ] **Step 8.5:Smoke /m/{dim} 浏览器加载 CDN scripts**

```bash
uv run python -c "
from starlette.testclient import TestClient
from dashboard.server import app
client = TestClient(app)
r = client.get('/m/execution')
print('marked CDN:', 'cdn.jsdelivr.net/npm/marked' in r.text)
print('mermaid CDN:', 'cdn.jsdelivr.net/npm/mermaid' in r.text)
print('render-field.js include:', 'render-field.js' in r.text)
"
```
Expected: 三个 True。

- [ ] **Step 8.6:Commit**

```bash
git add dashboard/templates/base.html dashboard/static/render-field.js dashboard/static/style.css
git commit -m "feat(harness-board): marked + mermaid CDN + render-field.js client-side render (Plan 2 step 8)"
```

---

## Task 9:图上传 endpoint + screenshot_repo + uploader UI

**Files:**
- Create: `dashboard/derive/screenshot_repo.py`
- Create: `dashboard/templates/_screenshot_uploader.html`
- Modify: `dashboard/static/screenshot-upload.js`
- Modify: `dashboard/server.py`(POST /cap/{id}/screenshot)
- Test: `dashboard/tests/integration/test_screenshot_upload.py`
- Test: `dashboard/tests/unit/test_screenshot_repo.py`
- Create: `dashboard/screenshots/.gitkeep`

- [ ] **Step 9.1:Create screenshot_repo.py**

```python
"""Plan 2 Task 9 — 截图上传文件系统管理。

存储路径:`dashboard/screenshots/{cap_id}/{timestamp}-{safe_name}.{ext}`
进 git (`.gitkeep` 占位 + 用户 git add 实际文件)。

校验:
- 类型白名单:png / jpg / jpeg / gif / webp
- 大小:≤ 500_000 bytes (500KB)
- 文件名 sanitize:剔除非 ASCII / 路径分隔符
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

ALLOWED_TYPES = frozenset(
    ["image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp"]
)
ALLOWED_EXTS = frozenset(["png", "jpg", "jpeg", "gif", "webp"])
MAX_SIZE = 500_000  # 500KB


class UploadError(Exception):
    """上传校验失败。"""


@dataclass(frozen=True)
class UploadResult:
    rel_path: str  # "screenshots/{cap_id}/{filename}"
    markdown: str  # "![{filename}]({rel_path})"
    git_hint: str  # "git add dashboard/{rel_path}"


def sanitize_filename(name: str) -> str:
    """剔除非 ASCII + 路径分隔符 + 危险字符。"""
    # 取 ext
    parts = name.rsplit(".", 1)
    ext = parts[1].lower() if len(parts) == 2 else ""
    stem = parts[0]
    # 仅保留 [a-zA-Z0-9._-]
    safe_stem = re.sub(r"[^a-zA-Z0-9._-]", "_", stem)[:60] or "image"
    if ext and ext in ALLOWED_EXTS:
        return f"{safe_stem}.{ext}"
    return f"{safe_stem}.png"  # fallback


def save_screenshot(
    base_dir: Path,
    cap_id: str,
    content: bytes,
    content_type: str,
    original_filename: str,
) -> UploadResult:
    """保存截图。返回 UploadResult。"""
    if content_type not in ALLOWED_TYPES:
        raise UploadError(f"unsupported type: {content_type}")
    if len(content) > MAX_SIZE:
        raise UploadError(f"size {len(content)} > {MAX_SIZE}")

    # cap_id 也 sanitize 一下(防路径遍历)
    safe_cap = re.sub(r"[^a-zA-Z0-9._-]", "_", cap_id)
    if safe_cap != cap_id:
        raise UploadError(f"invalid cap_id: {cap_id}")

    out_dir = base_dir / "screenshots" / safe_cap
    out_dir.mkdir(parents=True, exist_ok=True)

    safe_name = sanitize_filename(original_filename)
    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out_path = out_dir / f"{ts}-{safe_name}"
    out_path.write_bytes(content)

    rel_path = f"screenshots/{safe_cap}/{out_path.name}"
    return UploadResult(
        rel_path=rel_path,
        markdown=f"![{safe_name}]({rel_path})",
        git_hint=f"git add dashboard/{rel_path}",
    )
```

- [ ] **Step 9.2:Write unit tests for screenshot_repo**

Create `dashboard/tests/unit/test_screenshot_repo.py`:

```python
"""Plan 2 Task 9 — screenshot_repo 校验测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from dashboard.derive.screenshot_repo import (
    MAX_SIZE,
    UploadError,
    sanitize_filename,
    save_screenshot,
)


def test_sanitize_filename_strips_unsafe() -> None:
    assert sanitize_filename("arch design.png") == "arch_design.png"
    assert sanitize_filename("../../../etc/passwd") == "_._.._etc_passwd.png"  # 路径分隔符全 escape
    assert sanitize_filename("中文.gif") == "_.gif"  # 非 ASCII strip
    assert sanitize_filename("no_ext") == "no_ext.png"


def test_save_screenshot_creates_file(tmp_path: Path) -> None:
    content = b"\x89PNG\r\n\x1a\n" + b"x" * 100  # fake PNG-ish
    result = save_screenshot(
        tmp_path, "execution.docker_compose", content, "image/png", "arch.png"
    )
    assert result.rel_path.startswith("screenshots/execution.docker_compose/")
    assert result.rel_path.endswith("-arch.png")
    assert "(screenshots/execution.docker_compose/" in result.markdown
    assert (tmp_path / result.rel_path).exists()


def test_save_screenshot_rejects_unsupported_type(tmp_path: Path) -> None:
    with pytest.raises(UploadError, match="unsupported type"):
        save_screenshot(tmp_path, "x.y", b"data", "application/pdf", "foo.pdf")


def test_save_screenshot_rejects_too_large(tmp_path: Path) -> None:
    big = b"x" * (MAX_SIZE + 1)
    with pytest.raises(UploadError, match="size"):
        save_screenshot(tmp_path, "x.y", big, "image/png", "big.png")


def test_save_screenshot_rejects_path_traversal_cap_id(tmp_path: Path) -> None:
    with pytest.raises(UploadError, match="invalid cap_id"):
        save_screenshot(tmp_path, "../etc", b"x", "image/png", "x.png")
```

- [ ] **Step 9.3:Run tests**

```bash
uv run pytest dashboard/tests/unit/test_screenshot_repo.py -v 2>&1 | tail -8
```
Expected: 5 PASS.

- [ ] **Step 9.4:加 server.py POST /cap/{id}/screenshot handler**

```python
async def post_screenshot(request: Request) -> JSONResponse:
    """图上传 endpoint。Plan 2 Task 9。"""
    from dashboard.derive.screenshot_repo import UploadError, save_screenshot

    cap_id = request.path_params["cap_id"]
    form = await request.form()
    upload = form.get("file")
    if upload is None or not hasattr(upload, "read"):
        return JSONResponse({"error": "no file uploaded"}, status_code=400)

    try:
        content = await upload.read()
        result = save_screenshot(
            DASHBOARD_ROOT,
            cap_id,
            content,
            upload.content_type or "",
            upload.filename or "image.png",
        )
    except UploadError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    return JSONResponse(
        {
            "path": result.rel_path,
            "markdown": result.markdown,
            "git_hint": result.git_hint,
        }
    )
```

加 Route:
```python
        Route("/cap/{cap_id}/screenshot", post_screenshot, methods=["POST"]),
```

注意 import:`from starlette.responses import JSONResponse`(已在顶部)。

- [ ] **Step 9.5:实现 _screenshot_uploader.html**

```html
{# Plan 2 Task 9 — 单字段编辑时的图上传组件 #}
<div class="screenshot-uploader" data-cap-id="{{ cap_id }}" data-field="{{ field_id }}">
  <input type="file"
         id="upload-{{ cap_id }}-{{ field_id }}"
         class="upload-input"
         accept="image/png,image/jpeg,image/gif,image/webp"
         onchange="window.harness?.uploadScreenshot?.(this, '{{ cap_id }}', '{{ field_id }}')"
         hidden>
  <button type="button"
          class="upload-btn"
          onclick="document.getElementById('upload-{{ cap_id }}-{{ field_id }}').click()">
    📷 上传图(≤ 500KB · png/jpg/gif/webp)
  </button>
  <span class="upload-status" id="status-{{ cap_id }}-{{ field_id }}"></span>
</div>
```

- [ ] **Step 9.6:实现 screenshot-upload.js**

```javascript
// Plan 2 Task 9 — 图上传 client side
(function () {
  async function uploadScreenshot(inputEl, capId, fieldId) {
    const file = inputEl.files[0];
    if (!file) return;
    const statusEl = document.getElementById(`status-${capId}-${fieldId}`);
    const setStatus = (msg, isErr) => {
      if (!statusEl) return;
      statusEl.textContent = msg;
      statusEl.className = 'upload-status' + (isErr ? ' upload-status--err' : ' upload-status--ok');
    };

    if (file.size > 500_000) {
      setStatus(`文件 ${(file.size/1024).toFixed(1)}KB 超过 500KB 限制`, true);
      return;
    }
    setStatus('上传中...', false);

    const formData = new FormData();
    formData.append('file', file);

    try {
      const resp = await fetch(`/cap/${capId}/screenshot`, { method: 'POST', body: formData });
      if (!resp.ok) {
        const err = await resp.json();
        setStatus(`失败:${err.error || resp.statusText}`, true);
        return;
      }
      const data = await resp.json();
      setStatus(`✓ 已保存 (记得 ${data.git_hint})`, false);

      // 把 markdown 插入当前字段的 textarea
      const ta = document.querySelector(`textarea[data-cap-id="${capId}"][data-field="${fieldId}"]`);
      if (ta) {
        const cursor = ta.selectionStart || ta.value.length;
        ta.value = ta.value.slice(0, cursor) + '\n' + data.markdown + '\n' + ta.value.slice(cursor);
        ta.dispatchEvent(new Event('input'));
      } else {
        // copy markdown to clipboard
        navigator.clipboard.writeText(data.markdown).then(
          () => setStatus(`✓ markdown 已复制(${data.markdown})`, false),
          () => setStatus(`✓ 路径:${data.path}(${data.git_hint})`, false)
        );
      }

      // 也 push 到 toast
      window.harness?.toast?.('截图已上传');
    } catch (e) {
      setStatus(`错误:${e.message}`, true);
    } finally {
      inputEl.value = '';  // reset 让相同文件可再上传
    }
  }

  window.harness = window.harness || {};
  window.harness.uploadScreenshot = uploadScreenshot;
})();
```

- [ ] **Step 9.7:加 CSS for uploader(style.css 末尾追加)**

```css
/* Plan 2 Task 9 — screenshot uploader */
.screenshot-uploader { display: inline-flex; align-items: center; gap: 12px; margin: 6px 0; }
.upload-btn {
  background: rgba(94,92,230,0.10); color: #5E5CE6;
  border: 1px dashed rgba(94,92,230,0.4); border-radius: 6px;
  padding: 6px 12px; font: inherit; font-size: 12px;
  cursor: pointer;
}
.upload-btn:hover { background: rgba(94,92,230,0.18); }
.upload-status { font-size: 11px; color: #86868B; font-family: 'Geist Mono', monospace; }
.upload-status--ok  { color: #1B7A33; }
.upload-status--err { color: #B22222; }
```

- [ ] **Step 9.8:Create dashboard/screenshots/.gitkeep**

```bash
mkdir -p dashboard/screenshots
echo "# Plan 2 — 截图上传目录 (cap_id 子目录在 first upload 时创建)" > dashboard/screenshots/.gitkeep
```

- [ ] **Step 9.9:Write integration tests for upload endpoint**

Create `dashboard/tests/integration/test_screenshot_upload.py`:

```python
"""Plan 2 Task 9 — POST /cap/{id}/screenshot endpoint 测试。"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from dashboard import server


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(server, "DASHBOARD_ROOT", tmp_path)
    return TestClient(server.app)


def _png_bytes(size: int = 200) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"x" * size


def test_upload_screenshot_success(client: TestClient, tmp_path: Path) -> None:
    files = {"file": ("arch.png", io.BytesIO(_png_bytes()), "image/png")}
    resp = client.post("/cap/execution.docker_compose/screenshot", files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert data["path"].startswith("screenshots/execution.docker_compose/")
    assert data["path"].endswith("-arch.png")
    assert "git add dashboard/screenshots/" in data["git_hint"]
    assert (tmp_path / data["path"]).exists()


def test_upload_screenshot_rejects_unsupported_type(client: TestClient) -> None:
    files = {"file": ("doc.pdf", io.BytesIO(b"%PDF-1.4\n"), "application/pdf")}
    resp = client.post("/cap/x.y/screenshot", files=files)
    assert resp.status_code == 400
    assert "unsupported" in resp.json()["error"]


def test_upload_screenshot_rejects_too_large(client: TestClient) -> None:
    big = b"\x89PNG\r\n\x1a\n" + b"x" * 600_000
    files = {"file": ("big.png", io.BytesIO(big), "image/png")}
    resp = client.post("/cap/x.y/screenshot", files=files)
    assert resp.status_code == 400
    assert "size" in resp.json()["error"]


def test_upload_screenshot_rejects_path_traversal(client: TestClient) -> None:
    files = {"file": ("x.png", io.BytesIO(_png_bytes()), "image/png")}
    resp = client.post("/cap/..%2F..%2Fetc/screenshot", files=files)
    # 路径里的 .. 应该不会真的到 etc — 但 cap_id sanitize 应该拦
    assert resp.status_code in (400, 404)


def test_upload_screenshot_no_file(client: TestClient) -> None:
    resp = client.post("/cap/x.y/screenshot")
    assert resp.status_code == 400
```

- [ ] **Step 9.10:Run tests**

```bash
uv run pytest dashboard/tests/integration/test_screenshot_upload.py -v 2>&1 | tail -10
```
Expected: 5 PASS.

- [ ] **Step 9.11:Smoke 浏览器流(curl 模拟)**

```bash
uv run python -c "
import io
from starlette.testclient import TestClient
from dashboard.server import app
client = TestClient(app)
files = {'file': ('test.png', io.BytesIO(b'\x89PNG\r\n\x1a\n' + b'x'*200), 'image/png')}
r = client.post('/cap/execution.docker_compose/screenshot', files=files)
print('status:', r.status_code)
print('data:', r.json())
"
```
Expected: status 200 + path / markdown / git_hint 字段。

- [ ] **Step 9.12:Commit**

```bash
git add dashboard/derive/screenshot_repo.py dashboard/templates/_screenshot_uploader.html dashboard/static/screenshot-upload.js dashboard/static/style.css dashboard/server.py dashboard/screenshots/.gitkeep dashboard/tests/unit/test_screenshot_repo.py dashboard/tests/integration/test_screenshot_upload.py
git commit -m "feat(harness-board): screenshot upload endpoint + sanitize + uploader UI + screenshots/ scaffold (Plan 2 step 9)"
```

---

## Task 10:nav-rail 加临时 7 维入口(Plan 3 重做主导航前的过渡)

**Files:**
- Modify: `dashboard/templates/_board_nav.html`

**目标:** 让用户能从首页临时点进 7 个模块页(Plan 3 会做正式 Topology 图 + 主 nav 重做)。

- [ ] **Step 10.1:Read _board_nav.html 现状**

```bash
cat dashboard/templates/_board_nav.html
```

- [ ] **Step 10.2:加 7 维入口区块(在 Story 和 Forge 之间或末尾追加)**

具体改造:在 `</nav>` 之前追加(用 Geist Mono 字母代号作为视觉锚,Plan 3 替换):

```html
  <hr class="nav-sep">
  <div class="nav-modules" title="7 模块页(临时入口,Plan 3 主导航替代)">
    {% for dim_id, letter, name in [
      ('execution',     'E', '执行'),
      ('tool',          'T', '工具'),
      ('context',       'C', '上下文'),
      ('lifecycle',     'L', '生命周期'),
      ('observability', 'O', '可观测'),
      ('verification',  'V', '验证'),
      ('governance',    'G', '治理'),
    ] %}
      <a href="/m/{{ dim_id }}" class="nav-mod{% if active_nav == 'm.' ~ dim_id %} active{% endif %}" title="{{ name }}">
        {{ letter }}
      </a>
    {% endfor %}
  </div>
```

- [ ] **Step 10.3:加 .nav-mod CSS(style.css 末尾追加)**

```css
/* Plan 2 Task 10 — nav-rail 7 维临时入口 (Plan 3 重做主 nav 时替换) */
.nav-sep { width: 60%; margin: 12px auto; border: 0; border-top: 1px solid rgba(60,60,67,0.08); }
.nav-modules { display: flex; flex-direction: column; gap: 8px; padding: 4px 0; align-items: center; }
.nav-mod {
  width: 32px; height: 32px;
  display: flex; align-items: center; justify-content: center;
  border-radius: 6px;
  font-family: 'Geist Mono', monospace; font-size: 14px; font-weight: 600;
  color: #86868B;
  text-decoration: none;
}
.nav-mod:hover { background: rgba(94,92,230,0.08); color: #5E5CE6; }
.nav-mod.active { background: #5E5CE6; color: white; }
```

- [ ] **Step 10.4:Smoke / 浏览器 — 看到 E/T/C/L/O/V/G 7 个入口**

```bash
uv run python -c "
from starlette.testclient import TestClient
from dashboard.server import app
client = TestClient(app)
r = client.get('/')
for letter in ['E','T','C','L','O','V','G']:
    assert f'>{letter}</a>' in r.text, f'missing {letter}'
print('all 7 nav letters present')
"
```
Expected: `all 7 nav letters present`。

- [ ] **Step 10.5:Commit**

```bash
git add dashboard/templates/_board_nav.html dashboard/static/style.css
git commit -m "feat(harness-board): nav-rail 7 module shortcuts (transitional; Plan 3 main nav rewrite later) (Plan 2 step 10)"
```

---

## Task 11:Smoke + e2e dogfood

**Files:** None (verification only)

- [ ] **Step 11.1:全测试套件**

```bash
uv run pytest dashboard/tests/ -q 2>&1 | tail -3
```
Expected: 全 pass / 3 skip / 0 fail。

- [ ] **Step 11.2:mypy**

```bash
uv run mypy dashboard/ 2>&1 | tail -3
```
Expected: `Success: no issues found in N source files`(N 应该 ≥ 68)。

- [ ] **Step 11.3:ruff**

```bash
uv run ruff check dashboard/ 2>&1 | tail -3
```
Expected: `All checks passed!`。

- [ ] **Step 11.4:Server smoke 全 endpoint**

```bash
uv run python -c "
import io
from starlette.testclient import TestClient
from dashboard.server import app
client = TestClient(app)

checks = [
    ('GET', '/', 200),
    ('GET', '/m/execution', 200),
    ('GET', '/m/tool', 200),
    ('GET', '/m/context', 200),
    ('GET', '/m/lifecycle', 200),
    ('GET', '/m/observability', 200),
    ('GET', '/m/verification', 200),
    ('GET', '/m/governance', 200),
    ('GET', '/m/totally_invalid', 404),
    ('GET', '/cap/execution.docker_compose/expand', 200),
]
for method, path, expected in checks:
    r = client.request(method, path)
    ok = '✓' if r.status_code == expected else '✗'
    print(f'{ok}  {method} {path} → {r.status_code} (expected {expected})')

# POST status
r = client.post('/cap/execution.docker_compose/status', data={'status': 'wip'})
print(f'POST status: {r.status_code} (expected 200)')

# POST screenshot
files = {'file': ('a.png', io.BytesIO(b'\x89PNG\r\n\x1a\n' + b'x'*50), 'image/png')}
r = client.post('/cap/execution.docker_compose/screenshot', files=files)
print(f'POST screenshot: {r.status_code} (expected 200) — path: {r.json().get(\"path\")}')
"
```
Expected: 全 ✓ + POST 都 200。

- [ ] **Step 11.5:grep cruft 兜底 — 无未删 modal / 无 dead import**

```bash
grep -rnE "_deep_card_modal\.html|deep_card_modal" dashboard/ --include="*.py" --include="*.html" | grep -v __pycache__
```
Expected: 0 hit(都改成 inline 了)。

- [ ] **Step 11.6:report 给 controller**

记录:
- pytest pass / fail / skip 数
- mypy issue 数
- ruff check 状态
- /m/{dim} 7 个全 200
- /cap/{id}/expand 200
- POST status 200(切到 wip)
- POST screenshot 200(返回 path / markdown / git_hint)

---

## Task 12:Spec ship 标记 + final commit

**Files:**
- Modify: `docs/superpowers/specs/2026-05-24-harness-board-framework-rebuild-design.md`

- [ ] **Step 12.1:加 Plan 2 ship 标记**

打开 spec doc,定位 §0 头部 "状态" 行:

```markdown
**状态**:Spec — Plan 1 ship 2026-05-24(flashcards 整条退役;DeepCard schema migration 留 Plan 2)
```

改为:
```markdown
**状态**:Spec — Plan 1 ship 2026-05-24 + Plan 2 ship 2026-05-XX(DeepCard v2 schema + 模块页 /m/{dim} + 三色 chip + 右键 + 就地展开 + 图上传;首页 Topology 留 Plan 3,/story 改造留 Plan 4)
```

(2026-05-XX 用今天日期)

- [ ] **Step 12.2:Commit ship 标记**

```bash
git add docs/superpowers/specs/2026-05-24-harness-board-framework-rebuild-design.md
git commit -m "docs(harness-board): mark Plan 2 ship in spec — DeepCard v2 + module page + chip + expand + upload"
```

- [ ] **Step 12.3:Final git log + diff stat**

```bash
git log --oneline -15
git diff main...HEAD --stat | tail -25
```

记下数字给 PR description。

---

## Self-Review

实施前已对照 spec § 2-§ 6 检查:

| Spec 要求 | Plan 2 task | 状态 |
|---|---|---|
| 首页 Topology 图 | Plan 3 | 不在本 plan |
| 模块页 `/m/{dim_id}` × 7 | Task 4 | ✓ |
| chip 三色 (lit/wip/todo) | Task 5 | ✓ |
| 右键菜单 4 项 | Task 6 | ✓ |
| 单击就地展开 | Task 7 | ✓ |
| DeepCard 6 字段固化 | Task 1 + 2 + 3 + 7 | ✓ |
| 图上传 + screenshots/ 进 git | Task 9 | ✓ |
| markdown + mermaid 渲染 | Task 8 | ✓ |
| `/story` skill 接口 | Plan 4 | 不在本 plan |
| /decisions 吸进字段 5 | Task 7 (decisions section) | ✓(显示派生 id;后续 follow-up 填实) |
| /survey / /overview 退役 | Plan 3 | 不在本 plan |

**Placeholders:** 0(已检)
**Type consistency:** `window.harness` namespace 在 Task 6 / 7 / 8 / 9 都 self.harness = ... 模式一致挂载;函数签名 `showContextMenu(event, capId)` / `toggleExpand(capId)` / `renderField(container)` / `uploadScreenshot(input, capId, fieldId)` 与模板调用一致。
**Risks:**
- 旧 `_deep_card_modal.html` 已经 git mv 到 inline,所有引用都改了(grep 兜底 Step 11.5)
- screenshot_repo 路径校验:cap_id 含 `..` 被 sanitize 拦(test_screenshot_repo Step 9.2 测过)
- mermaid CDN 失联时:base.html 的 `if (window.mermaid)` guard,render-field.js fallback 到 raw markdown
- nav 模块入口是 Plan 3 临时方案,Plan 3 会重写 nav

---

## After Plan 2 — Plan 3 / Plan 4 预告

```
Plan 3 — 首页 Topology 关系图 (替代当前 D-view + B-view + App Shell + view-toggle)
        + nav-rail 主导航重做 (Plan 2 的临时 7 维入口移除)
        + 其他子页退役 (decisions/overview/survey + 对应 partials + derive)
        + CSS 全量重写 (style.css 大幅瘦身)
Plan 4 — /story 改造 (textarea + 客户端 marked + mermaid render — base.html 已 Plan 2 引)
        + Plan 1 暂留的 SrsState/Flashcard/TemplateKind 类型清理
        + graph_builder.py 退役
```

每个 plan 完成后 Squash merge 到 main + 起下一个 plan。

---

## 实施清单(本 plan 内的 commits 顺序预期)

1. `feat(harness-board): DeepCard model add v2 fields ...`(Task 1)
2. `feat(harness-board): one-shot DeepCard v1 → v2 payload migration script`(Task 2)
3. `feat(harness-board): DeepCardRepo update_field supports v2 fields`(Task 3)
4. `feat(harness-board): module page /m/{dim_id} handler + template + 4 JS stubs`(Task 4)
5. `feat(harness-board): chip 三色 + contextmenu hook + module page CSS scaffold`(Task 5)
6. `feat(harness-board): right-click context menu + POST /cap/{id}/status`(Task 6)
7. `feat(harness-board): inline expand 6-field view + GET /cap/{id}/expand + slide animation`(Task 7)
8. `feat(harness-board): marked + mermaid CDN + render-field.js client-side render`(Task 8)
9. `feat(harness-board): screenshot upload endpoint + sanitize + uploader UI + screenshots/ scaffold`(Task 9)
10. `feat(harness-board): nav-rail 7 module shortcuts (transitional)`(Task 10)
11. `docs(harness-board): mark Plan 2 ship in spec`(Task 12)

共 11 commits + Self-review report。

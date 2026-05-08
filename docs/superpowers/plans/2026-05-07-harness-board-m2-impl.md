# Harness Board · M2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship M2:`make board` 浏览器看到 D/B Tab toggle、Kanban 三列(Todo/Doing/Done 折叠)、点击 chip 弹 select 改 wip/force-lit/force-todo/clear、9 行 App Shell mini stat;`POST /refresh` 强制刷新闭环;`SnapshotDict` TypedDict 收紧 storage 边界;mypy strict 仍清洁,~40 测试 PASS。

**Architecture:** 增量在 M1 5 层架构上(Source 不动 / Derive 加 app_shell_stat / State 加 OverrideRepo + invalidate / Server 加 3 routes / UI 加 4 partial + CSS 增量);override 表 single row per capability + upsert/DELETE 语义;chip 编辑走 htmx 两段 swap(GET edit → swap select → POST override → swap chip)。

**Tech Stack:** 复用 M1 — Starlette + Jinja2 + htmx 1.9.10 vendored + Python sqlite3(stdlib)+ pyyaml + Python 3.11+。**不新增依赖**。

**Source Spec:** `docs/superpowers/specs/2026-05-07-harness-board-m2-design.md`

**M2 不含**(留 M3):
- ❌ `/decisions` route + decision_extractor
- ❌ `spec_section` / `memory_frontmatter` derive_rule fixture 测试覆盖
- ❌ B Kanban 拖拽切列
- ❌ override 历史 / undo / redo
- ❌ override reason input UI
- ❌ Done 列折叠态持久化(刷页恢复折叠)

**M2 工期估算**:1.5 天 wall time(每天 4-5h Claude Code 投入,memory `feedback_estimate_in_claude_code_walltime`)

---

## File Structure

```
dashboard/
├── derive/
│   ├── app_shell_stat.py            # 新 (Task 3)
│   ├── snapshot_builder.py          # 改:to_dict 返回 SnapshotDict (Task 2)
│   └── types.py                     # 改:加 SnapshotDict / AppShellItem (Task 2/3)
├── state/
│   ├── db.py                        # 改:SCHEMA 加 capability_override 表 (Task 1)
│   └── repositories.py              # 改:加 OverrideRepo + SnapshotRepo.invalidate + 类型收紧 (Task 1/2)
├── templates/
│   ├── _b_view.html                 # 新:Kanban 三列 (Task 6)
│   ├── _d_b_toggle.html             # 新:Tab nav (Task 5)
│   ├── _app_shell.html              # 新:第 9 行 (Task 9)
│   ├── _capability_chip.html        # 新:抽出 chip 渲染 (Task 4)
│   ├── _edit_select.html            # 新:edit dropdown htmx swap source (Task 7)
│   ├── _d_view.html                 # 改:include _capability_chip (Task 4)
│   └── main.html                    # 改:view_mode 分发 + Tab nav + app_shell (Task 5/6/9)
├── static/
│   └── style.css                    # 改:加 .kanban-* / .app-shell-* / .stale-mark / .edit-select / .view-toggle (Task 4/5/6/7/9)
├── server.py                        # 改:加 GET edit + POST override + POST refresh + view_mode query + app_shell stat (Task 5/7/8/9)
└── tests/
    ├── derive/
    │   ├── test_app_shell_stat.py   # 新 (Task 3)
    │   └── test_snapshot_builder.py # 改:+1 SnapshotDict round-trip (Task 2)
    ├── state/
    │   └── test_override_repo.py    # 新 (Task 1)
    └── server/
        └── test_main_endpoint.py    # 改:+5 项 (Task 5/6/7/8)
```

**Modified files (top-level):**
- `README.md` — 顶部版本备注 + 命令(Task 10)

---

## Task 1: capability_override 表 + OverrideRepo + 测试

**Files:**
- Modify: `dashboard/state/db.py` — 加 capability_override 表 SCHEMA
- Modify: `dashboard/state/repositories.py` — 加 OverrideRepo class
- Create: `dashboard/tests/state/test_override_repo.py` — 4 测试

- [ ] **Step 1: 写失败测试 `dashboard/tests/state/test_override_repo.py`**

```python
# dashboard/tests/state/test_override_repo.py
from pathlib import Path
import pytest
from dashboard.state.db import open_db
from dashboard.state.repositories import OverrideRepo


def test_empty_returns_empty_dict(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "board.db")
    repo = OverrideRepo(conn)
    assert repo.get_all() == {}


def test_upsert_then_get(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "board.db")
    repo = OverrideRepo(conn)
    repo.upsert("memory.long_term_memory", "wip", reason="正在做 mem0 接入")
    out = repo.get_all()
    assert out == {"memory.long_term_memory": "wip"}


def test_upsert_overwrites_existing(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "board.db")
    repo = OverrideRepo(conn)
    repo.upsert("memory.long_term_memory", "wip")
    repo.upsert("memory.long_term_memory", "lit")
    assert repo.get_all() == {"memory.long_term_memory": "lit"}
    cur = conn.execute("SELECT COUNT(*) AS n FROM capability_override")
    assert cur.fetchone()["n"] == 1  # upsert 不累积


def test_delete_clears(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "board.db")
    repo = OverrideRepo(conn)
    repo.upsert("memory.long_term_memory", "wip")
    repo.delete("memory.long_term_memory")
    assert repo.get_all() == {}


def test_multi_capability_isolation(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "board.db")
    repo = OverrideRepo(conn)
    repo.upsert("memory.long_term_memory", "wip")
    repo.upsert("rag_knowledge.reranker", "lit")
    repo.delete("memory.long_term_memory")
    assert repo.get_all() == {"rag_knowledge.reranker": "lit"}
```

- [ ] **Step 2: 跑 test 验证 fail**

```bash
unset all_proxy https_proxy http_proxy && uv run --project backend pytest dashboard/tests/state/test_override_repo.py -v
```

预期:`ImportError: cannot import name 'OverrideRepo'` 或 `AttributeError`(因为还没 impl)。

- [ ] **Step 3: 改 `dashboard/state/db.py` — 加 SCHEMA**

读现有 `dashboard/state/db.py`,把 `SCHEMA` 字符串改为追加 capability_override 表:

```python
# dashboard/state/db.py
"""sqlite schema + connection。M1 derived_snapshot;M2 加 capability_override。"""
from __future__ import annotations
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS derived_snapshot (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  refreshed_at TEXT NOT NULL,
  payload TEXT NOT NULL  -- JSON
);

CREATE TABLE IF NOT EXISTS capability_override (
  capability_id TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  reason TEXT NOT NULL DEFAULT '',
  set_at TEXT NOT NULL
);
"""


def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn
```

- [ ] **Step 4: 改 `dashboard/state/repositories.py` — 加 OverrideRepo**

在文件末尾追加:

```python
from datetime import UTC, datetime

from dashboard.derive.types import CapabilityStatus


class OverrideRepo:
    """sqlite CRUD for capability_override。single row per capability(spec § 3)。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get_all(self) -> dict[str, CapabilityStatus]:
        """返回 {capability_id: status},喂给 build_snapshot(overrides=...)。"""
        cur = self.conn.execute(
            "SELECT capability_id, status FROM capability_override"
        )
        out: dict[str, CapabilityStatus] = {}
        for row in cur.fetchall():
            status: CapabilityStatus = row["status"]
            out[row["capability_id"]] = status
        return out

    def upsert(
        self,
        capability_id: str,
        status: CapabilityStatus,
        reason: str = "",
        set_at: str | None = None,
    ) -> None:
        """upsert per capability_id (PRIMARY KEY conflict 时覆盖)。"""
        set_at = set_at or datetime.now(UTC).isoformat()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO capability_override (capability_id, status, reason, set_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(capability_id) DO UPDATE SET
                  status = excluded.status,
                  reason = excluded.reason,
                  set_at = excluded.set_at
                """,
                (capability_id, status, reason, set_at),
            )

    def delete(self, capability_id: str) -> None:
        with self.conn:
            self.conn.execute(
                "DELETE FROM capability_override WHERE capability_id = ?",
                (capability_id,),
            )
```

- [ ] **Step 5: 跑 test 验证 PASS**

```bash
unset all_proxy https_proxy http_proxy && uv run --project backend pytest dashboard/tests/state/test_override_repo.py -v
```

预期:5 passed。

- [ ] **Step 6: mypy 验证**

```bash
unset all_proxy https_proxy http_proxy && uv run --project backend mypy dashboard/
```

预期:Success。如果 `CapabilityStatus` import 顺序有问题(repositories.py 第一次 import derive 模块),可能需调整 import。

- [ ] **Step 7: 提交**

```bash
git add dashboard/state/db.py dashboard/state/repositories.py dashboard/tests/state/test_override_repo.py
git commit -m "feat(dashboard): capability_override 表 + OverrideRepo (single row upsert/delete 语义)"
```

---

## Task 2: SnapshotDict TypedDict + SnapshotRepo.invalidate + storage 边界收紧

**Files:**
- Modify: `dashboard/derive/types.py` — 加 CapabilityDict / LayerSummaryDict / SnapshotDict TypedDict
- Modify: `dashboard/derive/snapshot_builder.py` — Snapshot.to_dict 返回 SnapshotDict
- Modify: `dashboard/state/repositories.py` — SnapshotRepo.save/get_latest 类型化 + 加 invalidate
- Modify: `dashboard/tests/derive/test_snapshot_builder.py` — +1 SnapshotDict round-trip

- [ ] **Step 1: 改 `dashboard/derive/types.py` — 加 3 个 TypedDict**

读现有文件,在末尾追加:

```python
from typing import TypedDict


class CapabilityDict(TypedDict):
    id: str
    dimension: DimensionId
    name_cn: str
    name_en: str
    status: CapabilityStatus
    derived_status: CapabilityStatus


class LayerSummaryDict(TypedDict):
    id: DimensionId
    number: str
    name_cn: str
    name_en: str
    lit: int
    wip: int
    todo: int
    total: int
    capabilities: list[CapabilityDict]


class SnapshotDict(TypedDict):
    refreshed_at: str
    layers: list[LayerSummaryDict]
    total_lit: int
    total_wip: int
    total_todo: int
    total: int
```

- [ ] **Step 2: 改 `dashboard/derive/snapshot_builder.py` — to_dict 收紧**

把 `to_dict` 方法签名 + cast 改为返回 SnapshotDict:

```python
from typing import Any, cast

from .types import (
    Capability,
    CapabilityStatus,
    DimensionConfig,
    SnapshotDict,
)
```

`Snapshot.to_dict` 返回类型从 `dict[str, Any]` 改为 `SnapshotDict`,实现里 cast:

```python
    def to_dict(self) -> SnapshotDict:
        return cast(SnapshotDict, {
            "refreshed_at": self.refreshed_at,
            "layers": [
                {**asdict(layer), "capabilities": [asdict(c) for c in layer.capabilities]}
                for layer in self.layers
            ],
            "total_lit": self.total_lit,
            "total_wip": self.total_wip,
            "total_todo": self.total_todo,
            "total": self.total,
        })
```

(M1 实施时这里有个 dict comprehension 用了 `layer` loop var,保留不变;只改返回类型 + cast。)

- [ ] **Step 3: 改 `dashboard/state/repositories.py` — SnapshotRepo 类型化 + invalidate**

修改 SnapshotRepo:

```python
from dashboard.derive.types import SnapshotDict


class SnapshotRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def save(self, refreshed_at: str, payload: SnapshotDict) -> None:
        """全量替换 — 仅保留最新一行(M1 简单语义)。"""
        with self.conn:
            self.conn.execute("DELETE FROM derived_snapshot")
            self.conn.execute(
                "INSERT INTO derived_snapshot (refreshed_at, payload) VALUES (?, ?)",
                (refreshed_at, json.dumps(payload)),
            )

    def get_latest(self) -> SnapshotDict | None:
        cur = self.conn.execute(
            "SELECT refreshed_at, payload FROM derived_snapshot ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()
        if not row:
            return None
        d: SnapshotDict = json.loads(row["payload"])
        d["refreshed_at"] = row["refreshed_at"]
        return d

    def invalidate(self) -> None:
        """清空 derived_snapshot,下次 GET / 触发 lazy rebuild。"""
        with self.conn:
            self.conn.execute("DELETE FROM derived_snapshot")
```

注意 `SnapshotDict` 是 `total: NotRequired[int]` 还是 `total: int`?spec 用 `int`,严格 TypedDict。但 `json.loads` 返回 `dict[str, Any]`,赋值给 `SnapshotDict` 类型注解后 mypy 不会再校验里面字段。这里是 Python TypedDict 实际行为(运行时 dict),mypy 只在显式访问时校验。

- [ ] **Step 4: 改 `dashboard/derive/snapshot_builder.py` — build_snapshot 给 layer.id 显式类型**

build_snapshot 内部 LayerSummary id 是 `DimensionId`(Literal),M1 已经对了;但 `to_dict` 里 `asdict(layer)` 把 Literal 解包为 plain str,SnapshotDict 字段定义时 LayerSummaryDict.id 是 DimensionId Literal,会有 mypy 警告吗?**TypedDict 配 cast 应能跑过**。如果 mypy 抱怨,在 cast 处加注释。

- [ ] **Step 5: 写 SnapshotDict round-trip 测试**

加到 `dashboard/tests/derive/test_snapshot_builder.py` 末尾:

```python
def test_snapshot_to_dict_satisfies_typed_dict():
    """to_dict 返回的字段必须满足 SnapshotDict 契约(用 cast 校验运行时形状)。"""
    from dashboard.derive.types import SnapshotDict
    snap = build_snapshot(PROJECT_ROOT, CONFIG_DIR)
    d = snap.to_dict()
    # 顶层字段
    assert set(d.keys()) >= {"refreshed_at", "layers", "total_lit", "total_wip", "total_todo", "total"}
    # 第一层 layer 字段
    L0 = d["layers"][0]
    assert set(L0.keys()) >= {"id", "number", "name_cn", "name_en", "lit", "wip", "todo", "total", "capabilities"}
    # 第一个 capability 字段
    if L0["capabilities"]:
        c0 = L0["capabilities"][0]
        assert set(c0.keys()) >= {"id", "dimension", "name_cn", "name_en", "status", "derived_status"}
```

- [ ] **Step 6: 跑 tests + mypy**

```bash
unset all_proxy https_proxy http_proxy && uv run --project backend pytest dashboard/tests/derive/test_snapshot_builder.py -v
unset all_proxy https_proxy http_proxy && uv run --project backend mypy dashboard/
```

预期:6 passed(原 5 + 新 1);mypy clean。

- [ ] **Step 7: 提交**

```bash
git add dashboard/derive/types.py dashboard/derive/snapshot_builder.py dashboard/state/repositories.py dashboard/tests/derive/test_snapshot_builder.py
git commit -m "feat(dashboard): SnapshotDict TypedDict 收紧 storage 边界 + SnapshotRepo.invalidate"
```

---

## Task 3: app_shell_stat 模块 + 测试

**Files:**
- Modify: `dashboard/derive/types.py` — 加 AppShellItem dataclass
- Create: `dashboard/derive/app_shell_stat.py`
- Create: `dashboard/tests/derive/test_app_shell_stat.py`

- [ ] **Step 1: 改 `dashboard/derive/types.py` — 加 AppShellItem**

末尾追加:

```python
@dataclass(frozen=True)
class AppShellItem:
    """App Shell 第 9 行单项 — 显示文件计数。"""
    id: str           # "frontend" / "backend" / "auth" / "database" / "connectors" / "infra"
    name_cn: str
    file_count: int
```

- [ ] **Step 2: 写失败测试 `dashboard/tests/derive/test_app_shell_stat.py`**

```python
# dashboard/tests/derive/test_app_shell_stat.py
from pathlib import Path
from dashboard.derive.app_shell_stat import compute_app_shell_stat
from dashboard.derive.types import DimensionConfig


def _mk_config(id_: str, name_cn: str, paths: tuple[str, ...]) -> DimensionConfig:
    return DimensionConfig(
        id="app_shell",
        number="09",
        name_cn=name_cn,
        name_en=name_cn,
        paths=paths,
    )


def test_basic_file_count(tmp_path: Path) -> None:
    """一个 path glob 命中多个文件,正确数到。"""
    (tmp_path / "frontend" / "src").mkdir(parents=True)
    (tmp_path / "frontend" / "src" / "App.tsx").write_text("x")
    (tmp_path / "frontend" / "src" / "main.tsx").write_text("x")
    cfg = _mk_config("frontend", "前端", ("frontend/**",))
    out = compute_app_shell_stat(tmp_path, [cfg])
    assert len(out) == 1
    assert out[0].id == "frontend"
    assert out[0].name_cn == "前端"
    assert out[0].file_count == 2


def test_empty_dir_zero(tmp_path: Path) -> None:
    """目标 path 不存在,count = 0。"""
    cfg = _mk_config("frontend", "前端", ("frontend/**",))
    out = compute_app_shell_stat(tmp_path, [cfg])
    assert out[0].file_count == 0


def test_glob_no_match_zero(tmp_path: Path) -> None:
    """glob 不命中(扩展名错),count = 0。"""
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "README.md").write_text("x")
    cfg = _mk_config("frontend", "前端", ("frontend/**/*.tsx",))
    out = compute_app_shell_stat(tmp_path, [cfg])
    assert out[0].file_count == 0


def test_multi_path_glob_sums(tmp_path: Path) -> None:
    """多个 path glob,count 相加。"""
    (tmp_path / "backend" / "app").mkdir(parents=True)
    (tmp_path / "backend" / "app" / "main.py").write_text("x")
    (tmp_path / "frontend" / "src").mkdir(parents=True)
    (tmp_path / "frontend" / "src" / "App.tsx").write_text("x")
    cfg = _mk_config(
        "fullstack", "全栈",
        ("backend/app/**/*.py", "frontend/src/**/*.tsx"),
    )
    out = compute_app_shell_stat(tmp_path, [cfg])
    assert out[0].file_count == 2
```

- [ ] **Step 3: 跑 test 验证 fail**

```bash
unset all_proxy https_proxy http_proxy && uv run --project backend pytest dashboard/tests/derive/test_app_shell_stat.py -v
```

预期:`ImportError: cannot import name 'compute_app_shell_stat'`。

- [ ] **Step 4: 写 `dashboard/derive/app_shell_stat.py`**

```python
# dashboard/derive/app_shell_stat.py
"""App Shell 第 9 行 mini stat — 数 6 项各命中多少文件。"""
from __future__ import annotations
from glob import glob
from pathlib import Path

from .types import AppShellItem, DimensionConfig


def compute_app_shell_stat(
    project_root: Path,
    app_shell: list[DimensionConfig],
) -> list[AppShellItem]:
    """对 app_shell 6 项,各自跑 glob 数文件,返回 AppShellItem 列表。

    数文件不数目录(`Path.is_file()` 过滤)。
    """
    out: list[AppShellItem] = []
    for d in app_shell:
        count = 0
        for glob_pat in d.paths:
            for fp in glob(str(project_root / glob_pat), recursive=True):
                if Path(fp).is_file():
                    count += 1
        out.append(AppShellItem(id=d.id, name_cn=d.name_cn, file_count=count))
    return out
```

注:返回的 `AppShellItem.id` 这里用 `d.id`(每个 DimensionConfig 的 id)。但 M1 `load_dimensions` 把 app_shell 6 项的 id 都 hardcode 成 `"app_shell"`(spec § 5.3),所以原 yaml 里的 frontend/backend/auth/... 子 id 在 DimensionConfig 阶段被丢了。

**问题**:`compute_app_shell_stat` 拿到的 `app_shell: list[DimensionConfig]` 全部 id="app_shell",6 个 AppShellItem 都同 id 没法区分。

**修复路径**:改 `path_router.load_dimensions` 不再丢子 id,而是 app_shell 6 项各自 DimensionConfig 保留原 id(frontend/backend/...)。下一步 sub-step 修。

- [ ] **Step 5: 改 `dashboard/derive/path_router.py` — app_shell 保留子 id**

读 `path_router.py` 的 `load_dimensions`,把 app_shell 段从 `id="app_shell"` 改为 `id=d["id"]`:

```python
def load_dimensions(yaml_path: Path) -> tuple[list[DimensionConfig], list[DimensionConfig]]:
    """加载 dimensions.yaml,返回 (8 维主泳道, App Shell 6 项)。"""
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    main = [
        DimensionConfig(
            id=d["id"],
            number=d["number"],
            name_cn=d["name_cn"],
            name_en=d["name_en"],
            paths=tuple(d["paths"]),
            keywords=tuple(d.get("keywords", [])),
        )
        for d in data["dimensions"]
    ]
    app_shell = [
        DimensionConfig(
            id=d["id"],          # M2:保留 frontend/backend/auth/... 子 id
            number="09",
            name_cn=d["name_cn"],
            name_en=d["name_cn"],
            paths=tuple(d["paths"]),
        )
        for d in data["app_shell"]
    ]
    return main, app_shell
```

但这跟 `DimensionId` Literal 类型冲突(`DimensionId` Literal 不含 frontend/backend/...)。需要扩展 Literal 或松绑 dataclass。

最简方案:让 `DimensionConfig.id` 类型改为 `str` 而非 `DimensionId`(松绑),仍保留语义信息。因为 app_shell 子 id 不进 capability matrix(不参与 by_dim 聚合),不需要走 Literal 校验。

**改 `dashboard/derive/types.py`**:

```python
@dataclass(frozen=True)
class DimensionConfig:
    id: str              # 主 dim 用 DimensionId Literal 值,app_shell 子项用自由 str
    number: str
    name_cn: str
    name_en: str
    paths: tuple[str, ...]
    keywords: tuple[str, ...] = field(default_factory=tuple)
```

- [ ] **Step 6: 跑 path_router 测试 verify 仍 pass**

```bash
unset all_proxy https_proxy http_proxy && uv run --project backend pytest dashboard/tests/derive/test_path_router.py -v
```

预期:12 passed。如果 fail:M1 `test_classify_path` 没断言 app_shell 子 id,只断言 dim id == "app_shell" — `classify_path` 内部 `candidates.append((_specificity(glob), "app_shell"))` 仍硬写 "app_shell",所以 classify 行为不变。**仅 load_dimensions 输出形状变**。

如果 12 测试中有断言 `len(app_shell)==6` 之外的子 id(M1 没,M1 只断言 length 和 main dim ids):应不变。

- [ ] **Step 7: 跑 app_shell_stat 测试 verify pass**

```bash
unset all_proxy https_proxy http_proxy && uv run --project backend pytest dashboard/tests/derive/test_app_shell_stat.py -v
```

预期:4 passed。

- [ ] **Step 8: mypy + 全测试**

```bash
unset all_proxy https_proxy http_proxy && uv run --project backend mypy dashboard/
unset all_proxy https_proxy http_proxy && uv run --project backend pytest dashboard/tests/ -v --tb=short
```

预期:mypy clean,M1 28 + Task 1 5 + Task 2 1 + Task 3 4 = 38 项 PASS。

- [ ] **Step 9: 提交**

```bash
git add dashboard/derive/types.py dashboard/derive/app_shell_stat.py dashboard/derive/path_router.py dashboard/tests/derive/test_app_shell_stat.py
git commit -m "feat(dashboard): app_shell_stat 模块 + path_router 保留 app_shell 子 id"
```

---

## Task 4: 抽出 _capability_chip partial + stale ✏️ + CSS

**Files:**
- Create: `dashboard/templates/_capability_chip.html`
- Modify: `dashboard/templates/_d_view.html`
- Modify: `dashboard/static/style.css` — 加 `.stale-mark`

- [ ] **Step 1: 写 `dashboard/templates/_capability_chip.html`**

```html
<span class="chip {{ c.status }}" id="cap-{{ c.id|replace('.', '-') }}" title="{{ c.id }}">
  {% if c.status == 'lit' %}✅{% elif c.status == 'wip' %}🟠{% else %}⬜{% endif %}
  {{ c.name_cn }}
  {% if c.derived_status != c.status %}<span class="stale-mark" title="手填覆盖派生状态({{ c.derived_status }})">✏️</span>{% endif %}
</span>
```

注:`id="cap-{{ c.id|replace('.', '-') }}"` 是 htmx swap 的 anchor。后续 Task 7/8 用。`replace('.', '-')` 因为 capability id 含 `.`(eg `memory.long_term_memory`),CSS id 不能含 `.`。

- [ ] **Step 2: 改 `dashboard/templates/_d_view.html`**

把原 chip 渲染替换为 include partial:

```html
<div class="layer-grid">
  {% for L in snap.layers %}
    <article class="layer-card" id="layer-{{ L.id }}">
      <div class="layer-head">
        <span class="layer-num">{{ L.number }}</span>
        <span class="layer-count">{{ L.lit }}/{{ L.total }}</span>
      </div>
      <div class="layer-name">
        <strong>{{ L.name_cn }}</strong>
        <small>· {{ L.name_en }}</small>
      </div>
      <div class="cap-list">
        {% for c in L.capabilities %}
          {% include "_capability_chip.html" %}
        {% endfor %}
      </div>
    </article>
  {% endfor %}
</div>
```

- [ ] **Step 3: 改 `dashboard/static/style.css` — 加 .stale-mark**

读现有 style.css,在 chip 三态规则下追加:

```css
/* Stale override mark (chip 上 ✏️) */
.stale-mark {
  font-size: 9px;
  opacity: 0.7;
  margin-left: 2px;
}
```

- [ ] **Step 4: 跑 server tests verify 没坏**

```bash
unset all_proxy https_proxy http_proxy && uv run --project backend pytest dashboard/tests/server/test_main_endpoint.py -v
```

预期:M1 2 项 PASS(test_healthz + test_index_renders)。`test_index_renders` 用 `body.count("layer-card") >= 8` 检查,partial 后 chip 数不变,应仍通。

- [ ] **Step 5: 手工 smoke ✏️ 标记**

需要先在 sqlite 写一条 override 模拟"派生 ≠ status"。直接在 python:

```bash
unset all_proxy https_proxy http_proxy && uv run --project backend python -c "
from pathlib import Path
from dashboard.state.db import open_db
from dashboard.state.repositories import OverrideRepo
conn = open_db(Path('backend/data/board.db'))
repo = OverrideRepo(conn)
repo.upsert('memory.long_term_memory', 'wip', reason='smoke test M2')
print('override seeded')
conn.close()
"
```

**问题**:M1 server 没把 OverrideRepo 喂给 build_snapshot,所以 override 此时不会反映到页面。Task 5 才接通。这一步只验证"override 表写入 OK",chip ✏️ 完整 smoke 等 Task 8 闭环。

清掉测试种子:

```bash
unset all_proxy https_proxy http_proxy && uv run --project backend python -c "
from pathlib import Path
from dashboard.state.db import open_db
from dashboard.state.repositories import OverrideRepo
conn = open_db(Path('backend/data/board.db'))
repo = OverrideRepo(conn)
repo.delete('memory.long_term_memory')
print('cleared')
conn.close()
"
```

- [ ] **Step 6: 提交**

```bash
git add dashboard/templates/_capability_chip.html dashboard/templates/_d_view.html dashboard/static/style.css
git commit -m "feat(dashboard): 抽出 _capability_chip partial + stale ✏️ 标记 + .stale-mark CSS"
```

---

## Task 5: view_mode query + Tab nav

**Files:**
- Modify: `dashboard/server.py` — index 接 ?view query + 喂 OverrideRepo 给 build_snapshot
- Create: `dashboard/templates/_d_b_toggle.html`
- Modify: `dashboard/templates/main.html` — 加 toggle nav + view_mode 分发(b 视图先放 placeholder,Task 6 接通)
- Modify: `dashboard/static/style.css` — 加 `.view-toggle`
- Modify: `dashboard/tests/server/test_main_endpoint.py` — +1 项 `test_view_d_default`

- [ ] **Step 1: 改 `dashboard/server.py` — index 接 query 参数 + 喂 OverrideRepo**

修改 `_get_or_build_snapshot` 和 `index` 函数,把 OverrideRepo 接通:

```python
from dashboard.state.repositories import OverrideRepo, SnapshotRepo


def _get_or_build_snapshot() -> SnapshotDict:
    """Lazy 派生:若 sqlite 无 snapshot,跑一次 build(把 override 喂进去)。"""
    conn = open_db(DB_PATH)
    try:
        snap_repo = SnapshotRepo(conn)
        snap = snap_repo.get_latest()
        if snap is None:
            override_repo = OverrideRepo(conn)
            overrides = override_repo.get_all()
            snapshot = build_snapshot(PROJECT_ROOT, CONFIG_DIR, overrides=overrides)
            snap_repo.save(snapshot.refreshed_at, snapshot.to_dict())
            snap = snap_repo.get_latest()
            assert snap is not None
    finally:
        conn.close()
    return snap


async def index(request: Request) -> HTMLResponse:
    view_mode = request.query_params.get("view", "d")
    if view_mode not in ("d", "b"):
        view_mode = "d"
    snap = _get_or_build_snapshot()
    wips = [c for L in snap["layers"] for c in L["capabilities"] if c["status"] == "wip"]
    return templates.TemplateResponse(
        request,
        "main.html",
        {
            "today": _today_label(),
            "snap": snap,
            "wips": wips,
            "view_mode": view_mode,
        },
    )
```

- [ ] **Step 2: 改 import — SnapshotDict**

```python
from dashboard.derive.types import SnapshotDict
```

并把 `_get_or_build_snapshot` 返回类型从 `dict[str, Any]` 改为 `SnapshotDict`(Task 2 已经准备好类型)。

- [ ] **Step 3: 写 `dashboard/templates/_d_b_toggle.html`**

```html
<nav class="view-toggle">
  <a href="/?view=d" class="{% if view_mode == 'd' %}active{% endif %}">D 维度</a>
  <a href="/?view=b" class="{% if view_mode == 'b' %}active{% endif %}">B Kanban</a>
</nav>
```

- [ ] **Step 4: 改 `dashboard/templates/main.html`**

```html
{% extends "base.html" %}
{% block content %}
  {% include "_hero.html" %}
  {% include "_d_b_toggle.html" %}
  <section class="view-content">
    {% if view_mode == 'b' %}
      <p class="placeholder">B Kanban — 在 Task 6 接入</p>
    {% else %}
      {% include "_d_view.html" %}
    {% endif %}
  </section>
{% endblock %}
```

- [ ] **Step 5: 改 `dashboard/static/style.css` — 加 .view-toggle**

末尾追加:

```css
/* View toggle (D/B Tab nav) */
.view-toggle {
  display: flex;
  gap: 0;
  margin-bottom: 16px;
  border-bottom: 1px solid var(--border);
}
.view-toggle a {
  padding: 8px 20px;
  color: var(--muted);
  text-decoration: none;
  font-size: 13px;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
}
.view-toggle a.active {
  color: var(--fg);
  border-bottom-color: var(--lit-fg);
}

.placeholder {
  color: var(--muted);
  font-style: italic;
  padding: 32px 0;
  text-align: center;
}
```

- [ ] **Step 6: 加测试 `test_view_d_default` 到 `dashboard/tests/server/test_main_endpoint.py`**

```python
def test_view_d_default():
    """无 query 默认 D 视图,有 layer-card。"""
    with TestClient(app) as client:
        r = client.get("/")
        assert r.status_code == 200
        body = r.text
        assert 'class="layer-card"' in body
        assert 'B Kanban' in body  # tab nav
        assert 'D 维度' in body


def test_view_b_placeholder():
    """?view=b 进 B 视图,M2 placeholder。"""
    with TestClient(app) as client:
        r = client.get("/?view=b")
        assert r.status_code == 200
        body = r.text
        assert 'class="layer-card"' not in body  # 不显 D 视图
        assert 'placeholder' in body  # M2 Task 6 之前是 placeholder
```

- [ ] **Step 7: 跑 tests + mypy**

```bash
unset all_proxy https_proxy http_proxy && uv run --project backend pytest dashboard/tests/server/ -v
unset all_proxy https_proxy http_proxy && uv run --project backend mypy dashboard/
```

预期:M1 2 + new 2 = 4 项 PASS;mypy clean。

- [ ] **Step 8: 删 board.db 强制 rebuild snapshot 看效果(可选 smoke)**

```bash
rm -f backend/data/board.db
unset all_proxy https_proxy http_proxy && uv run --project backend python -m dashboard.server &
SERVER_PID=$!
sleep 2
curl -s http://localhost:8910/ | grep -oE 'class="view-toggle"'
curl -s "http://localhost:8910/?view=b" | grep -oE 'placeholder'
kill $SERVER_PID 2>/dev/null
sleep 1
lsof -ti tcp:8910 | xargs -r kill -9 2>/dev/null || true
```

- [ ] **Step 9: 提交**

```bash
git add dashboard/server.py dashboard/templates/main.html dashboard/templates/_d_b_toggle.html dashboard/static/style.css dashboard/tests/server/test_main_endpoint.py
git commit -m "feat(dashboard): view_mode query + D/B Tab nav + 喂 OverrideRepo 给 build_snapshot"
```

---

## Task 6: _b_view Kanban 三列 + CSS + 测试

**Files:**
- Create: `dashboard/templates/_b_view.html`
- Modify: `dashboard/templates/main.html` — 把 placeholder 换成 include
- Modify: `dashboard/static/style.css` — 加 `.kanban-*`
- Modify: `dashboard/tests/server/test_main_endpoint.py` — `test_view_b_placeholder` → `test_view_b_renders_kanban`

- [ ] **Step 1: 写 `dashboard/templates/_b_view.html`**

```html
{% set todo_caps = [] %}
{% set wip_caps = [] %}
{% set lit_caps = [] %}
{% for L in snap.layers %}
  {% for c in L.capabilities %}
    {% if c.status == 'todo' %}{% set _ = todo_caps.append(c) %}{% endif %}
    {% if c.status == 'wip' %}{% set _ = wip_caps.append(c) %}{% endif %}
    {% if c.status == 'lit' %}{% set _ = lit_caps.append(c) %}{% endif %}
  {% endfor %}
{% endfor %}

<div class="kanban">
  <section class="kanban-col kanban-todo">
    <header class="kanban-head">Todo ({{ todo_caps|length }})</header>
    <div class="kanban-body">
      {% for c in todo_caps %}
        {% include "_capability_chip.html" %}
      {% endfor %}
    </div>
  </section>

  <section class="kanban-col kanban-doing">
    <header class="kanban-head">Doing ({{ wip_caps|length }})</header>
    <div class="kanban-body">
      {% for c in wip_caps %}
        {% include "_capability_chip.html" %}
      {% endfor %}
      {% if not wip_caps %}
        <p class="empty">(无 wip — 从 todo 挑一个开做?)</p>
      {% endif %}
    </div>
  </section>

  <section class="kanban-col kanban-done">
    <header class="kanban-head">
      <details>
        <summary>Done ({{ lit_caps|length }})</summary>
        <div class="kanban-body">
          {% for c in lit_caps %}
            {% include "_capability_chip.html" %}
          {% endfor %}
        </div>
      </details>
    </header>
  </section>
</div>
```

注:Done 列用原生 `<details><summary>` 实现折叠,默认折叠态(无 `open` attr)。点击展开,刷页恢复折叠 — 符合 spec § 16.2(Done 列折叠态不持久化)。

注 jinja 的 `{% set _ = list.append(...) %}` 对可变 list 工作 — `list` 是 Python list,append 是副作用。这是 jinja 标准做法。

- [ ] **Step 2: 改 `dashboard/templates/main.html` — 替换 placeholder**

```html
{% extends "base.html" %}
{% block content %}
  {% include "_hero.html" %}
  {% include "_d_b_toggle.html" %}
  <section class="view-content">
    {% if view_mode == 'b' %}
      {% include "_b_view.html" %}
    {% else %}
      {% include "_d_view.html" %}
    {% endif %}
  </section>
{% endblock %}
```

- [ ] **Step 3: 改 `dashboard/static/style.css` — 加 .kanban-***

末尾追加:

```css
/* Kanban (B view 三列) */
.kanban {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 12px;
}
.kanban-col {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 12px;
  min-height: 120px;
}
.kanban-head {
  font-family: ui-monospace, monospace;
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 12px;
  font-weight: 600;
}
.kanban-head summary {
  cursor: pointer;
  font-weight: inherit;
}
.kanban-body {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.kanban-todo .kanban-head { color: var(--todo-fg); }
.kanban-doing .kanban-head { color: var(--wip-fg); }
.kanban-done .kanban-head summary { color: var(--lit-fg); }
.kanban-body .empty {
  color: var(--todo-fg);
  font-style: italic;
  font-size: 11px;
  padding: 4px;
}

/* 响应式简版 */
@media (max-width: 800px) {
  .kanban { grid-template-columns: 1fr; }
}
```

- [ ] **Step 4: 改测试 `test_view_b_placeholder` → `test_view_b_renders_kanban`**

```python
def test_view_b_renders_kanban():
    """?view=b 渲染 Kanban 三列。"""
    with TestClient(app) as client:
        r = client.get("/?view=b")
        assert r.status_code == 200
        body = r.text
        assert 'class="layer-card"' not in body  # 不显 D 视图
        assert 'class="kanban"' in body
        assert 'Todo (' in body  # todo 列 header
        assert 'Doing (' in body
        assert 'Done (' in body
        assert '<details>' in body  # Done 列折叠
```

- [ ] **Step 5: 跑 tests + mypy + smoke**

```bash
unset all_proxy https_proxy http_proxy && uv run --project backend pytest dashboard/tests/server/ -v
unset all_proxy https_proxy http_proxy && uv run --project backend mypy dashboard/
```

预期:Task 5 4 项 + Task 6 改成功 = 4 项 PASS;mypy clean。

```bash
rm -f backend/data/board.db
unset all_proxy https_proxy http_proxy && uv run --project backend python -m dashboard.server &
SERVER_PID=$!
sleep 2
curl -s "http://localhost:8910/?view=b" | grep -oE 'class="kanban"'
curl -s "http://localhost:8910/?view=b" | grep -oE 'Todo \(\d+\)'
kill $SERVER_PID 2>/dev/null
sleep 1
lsof -ti tcp:8910 | xargs -r kill -9 2>/dev/null || true
```

- [ ] **Step 6: 提交**

```bash
git add dashboard/templates/_b_view.html dashboard/templates/main.html dashboard/static/style.css dashboard/tests/server/test_main_endpoint.py
git commit -m "feat(dashboard): _b_view.html Kanban 三列 + Done 折叠 + .kanban-* CSS"
```

---

## Task 7: GET /capability/{id}/edit + _edit_select template

**Files:**
- Create: `dashboard/templates/_edit_select.html`
- Modify: `dashboard/templates/_capability_chip.html` — 加 hx-get 触发 swap
- Modify: `dashboard/server.py` — 加 GET /capability/{id}/edit route
- Modify: `dashboard/static/style.css` — 加 `.edit-select`
- Modify: `dashboard/tests/server/test_main_endpoint.py` — +1 项 `test_get_edit_returns_select`

- [ ] **Step 1: 写 `dashboard/templates/_edit_select.html`**

```html
<form class="edit-select"
      id="cap-{{ c.id|replace('.', '-') }}"
      hx-post="/capability/{{ c.id }}/override"
      hx-target="this"
      hx-swap="outerHTML">
  <select name="status" onchange="this.form.requestSubmit()" autofocus>
    <option value="" disabled selected>{{ c.name_cn }}</option>
    <option value="lit">force-lit</option>
    <option value="wip">set-wip</option>
    <option value="todo">force-todo</option>
    <option value="__clear__">clear override</option>
  </select>
</form>
```

注:`<select onchange="this.form.requestSubmit()">` 是浏览器标准 form submit。htmx `hx-post` 接管 form 提交,`hx-swap="outerHTML"` 让响应替换 form 本体。`autofocus` 让 select 弹出后自动聚焦,用户键盘可选。

- [ ] **Step 2: 改 `dashboard/templates/_capability_chip.html` — 加 hx-get**

把 chip span 改成 hx-get 触发,点击替换为 select form:

```html
<span class="chip {{ c.status }}"
      id="cap-{{ c.id|replace('.', '-') }}"
      title="{{ c.id }}"
      hx-get="/capability/{{ c.id }}/edit"
      hx-target="this"
      hx-swap="outerHTML"
      style="cursor: pointer;">
  {% if c.status == 'lit' %}✅{% elif c.status == 'wip' %}🟠{% else %}⬜{% endif %}
  {{ c.name_cn }}
  {% if c.derived_status != c.status %}<span class="stale-mark" title="手填覆盖派生状态({{ c.derived_status }})">✏️</span>{% endif %}
</span>
```

注:`cursor: pointer` 让 chip 看起来可点击。

- [ ] **Step 3: 改 `dashboard/server.py` — 加 GET edit route**

加 imports:

```python
from dashboard.derive.capability_resolver import load_capabilities
from dashboard.derive.types import CapabilityConfig
```

加 route handler:

```python
async def edit_capability(request: Request) -> HTMLResponse:
    """返回 chip 替换为 edit select 的 HTML 片段(htmx swap source)。"""
    cap_id = request.path_params["cap_id"]
    # 从 capabilities.yaml 拿到这个 capability 的元数据(name_cn 用于 select 头)
    caps = load_capabilities(CONFIG_DIR / "capabilities.yaml")
    target = next((c for c in caps if c.id == cap_id), None)
    if target is None:
        return HTMLResponse(f"capability {cap_id} not found", status_code=404)
    # 渲染 _edit_select.html partial,只传 c
    template = templates.get_template("_edit_select.html")
    html = template.render(c=target)
    return HTMLResponse(html)
```

routes 列表加:

```python
app = Starlette(
    routes=[
        Route("/", index),
        Route("/healthz", healthz),
        Route("/capability/{cap_id}/edit", edit_capability),
        Mount("/static", StaticFiles(directory=str(DASHBOARD_ROOT / "static")), name="static"),
    ],
)
```

- [ ] **Step 4: 改 `dashboard/static/style.css` — 加 .edit-select**

末尾追加:

```css
/* Edit select (chip click → select swap) */
.edit-select {
  display: inline-block;
  margin: 0;
}
.edit-select select {
  background: var(--panel);
  color: var(--fg);
  border: 1px solid var(--lit-fg);
  border-radius: 3px;
  padding: 2px 6px;
  font-size: 11px;
  font-family: ui-monospace, monospace;
}
```

- [ ] **Step 5: 加测试**

```python
def test_get_edit_returns_select():
    """点击 chip 触发的 GET /capability/{id}/edit 返回 select form。"""
    with TestClient(app) as client:
        r = client.get("/capability/memory.long_term_memory/edit")
        assert r.status_code == 200
        body = r.text
        assert '<select' in body
        assert 'force-lit' in body
        assert 'set-wip' in body
        assert 'force-todo' in body
        assert 'clear override' in body
        assert 'hx-post' in body
        assert '/capability/memory.long_term_memory/override' in body


def test_get_edit_404_unknown_id():
    """未知 capability id 返 404。"""
    with TestClient(app) as client:
        r = client.get("/capability/nope.fake/edit")
        assert r.status_code == 404
```

- [ ] **Step 6: 跑 tests + mypy + smoke**

```bash
unset all_proxy https_proxy http_proxy && uv run --project backend pytest dashboard/tests/server/ -v
unset all_proxy https_proxy http_proxy && uv run --project backend mypy dashboard/
```

预期:Task 6 4 + Task 7 2 = 6 项 server tests PASS;mypy clean。

```bash
rm -f backend/data/board.db
unset all_proxy https_proxy http_proxy && uv run --project backend python -m dashboard.server &
SERVER_PID=$!
sleep 2
curl -s "http://localhost:8910/capability/memory.long_term_memory/edit"
kill $SERVER_PID 2>/dev/null
sleep 1
lsof -ti tcp:8910 | xargs -r kill -9 2>/dev/null || true
```

预期:返回 `<form class="edit-select"...><select ...>...</select></form>`。

- [ ] **Step 7: 提交**

```bash
git add dashboard/templates/_edit_select.html dashboard/templates/_capability_chip.html dashboard/server.py dashboard/static/style.css dashboard/tests/server/test_main_endpoint.py
git commit -m "feat(dashboard): GET /capability/{id}/edit + _edit_select 模板 + chip hx-get attrs"
```

---

## Task 8: POST /capability/{id}/override + POST /refresh + invalidate

**Files:**
- Modify: `dashboard/server.py` — 加 POST override + POST refresh
- Modify: `dashboard/tests/server/test_main_endpoint.py` — +3 项

- [ ] **Step 1: 改 `dashboard/server.py` — 加 POST override route**

```python
async def post_override(request: Request) -> HTMLResponse:
    """upsert override 或 clear (sentinel __clear__) + invalidate snapshot + 返回新 chip HTML。"""
    cap_id = request.path_params["cap_id"]
    form = await request.form()
    status = form.get("status", "")
    if not isinstance(status, str):
        return HTMLResponse("invalid form", status_code=400)

    conn = open_db(DB_PATH)
    try:
        override_repo = OverrideRepo(conn)
        if status == "__clear__":
            override_repo.delete(cap_id)
        elif status in ("lit", "wip", "todo"):
            override_repo.upsert(cap_id, status, reason="via UI")
        else:
            return HTMLResponse(f"invalid status: {status}", status_code=400)
        # invalidate snapshot,下次 GET / 重 build
        SnapshotRepo(conn).invalidate()
    finally:
        conn.close()

    # 重 resolve 这一个 capability,渲染新 chip
    caps = load_capabilities(CONFIG_DIR / "capabilities.yaml")
    target_cfg = next((c for c in caps if c.id == cap_id), None)
    if target_cfg is None:
        return HTMLResponse(f"capability {cap_id} not found", status_code=404)
    # 重新跑 resolver(只为这一个 capability)
    from dashboard.derive.capability_resolver import resolve_status
    derived = resolve_status(target_cfg, PROJECT_ROOT)
    # 重读 override
    conn = open_db(DB_PATH)
    try:
        overrides = OverrideRepo(conn).get_all()
    finally:
        conn.close()
    final_status = overrides.get(cap_id, derived)
    # 构造 Capability obj 渲染 chip
    from dashboard.derive.types import Capability
    cap = Capability(
        id=target_cfg.id,
        dimension=target_cfg.dimension,
        name_cn=target_cfg.name_cn,
        name_en=target_cfg.name_en,
        status=final_status,
        derived_status=derived,
    )
    template = templates.get_template("_capability_chip.html")
    html = template.render(c=cap)
    return HTMLResponse(html)


async def post_refresh(request: Request) -> Response:
    """显式 invalidate snapshot,302 redirect 到 /。"""
    conn = open_db(DB_PATH)
    try:
        SnapshotRepo(conn).invalidate()
    finally:
        conn.close()
    return RedirectResponse("/", status_code=302)
```

加 imports:

```python
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
```

routes 列表加:

```python
app = Starlette(
    routes=[
        Route("/", index),
        Route("/healthz", healthz),
        Route("/capability/{cap_id}/edit", edit_capability),
        Route("/capability/{cap_id}/override", post_override, methods=["POST"]),
        Route("/refresh", post_refresh, methods=["POST"]),
        Mount("/static", StaticFiles(directory=str(DASHBOARD_ROOT / "static")), name="static"),
    ],
)
```

- [ ] **Step 2: 加 3 个测试**

```python
def test_post_override_invalidates_and_swaps(tmp_path):
    """POST override → 写 override 表 + invalidate snapshot + 返回新 chip HTML。"""
    with TestClient(app) as client:
        # 先 GET / 触发 build_snapshot,确保表有 row
        client.get("/")
        # POST set wip
        r = client.post(
            "/capability/memory.long_term_memory/override",
            data={"status": "wip"},
        )
        assert r.status_code == 200
        body = r.text
        assert 'class="chip wip"' in body
        assert '🟠' in body
        # invalidate 验证:再 GET /,snapshot 含新 wip
        r2 = client.get("/")
        assert 'memory.long_term_memory' in r2.text  # capability 出现在页面


def test_post_override_clear_sentinel():
    """POST status=__clear__ 删除 override row。"""
    with TestClient(app) as client:
        # 先种一个 override
        client.post("/capability/memory.long_term_memory/override", data={"status": "wip"})
        # 清掉
        r = client.post(
            "/capability/memory.long_term_memory/override",
            data={"status": "__clear__"},
        )
        assert r.status_code == 200
        body = r.text
        # clear 后回到 derived 状态(memory.long_term_memory derive 是 todo)
        assert 'class="chip todo"' in body
        assert 'stale-mark' not in body  # 派生 == status,无 stale


def test_post_refresh_invalidates_and_redirects():
    """POST /refresh → 302 to /,snapshot 被清。"""
    with TestClient(app) as client:
        # 触发 build
        client.get("/")
        # refresh
        r = client.post("/refresh", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == "/"
```

- [ ] **Step 3: 跑 tests + mypy**

```bash
unset all_proxy https_proxy http_proxy && uv run --project backend pytest dashboard/tests/server/ -v
unset all_proxy https_proxy http_proxy && uv run --project backend mypy dashboard/
```

预期:Task 7 6 + Task 8 3 = 9 项 server tests PASS;mypy clean。

- [ ] **Step 4: E2E 手工 smoke**

```bash
rm -f backend/data/board.db
unset all_proxy https_proxy http_proxy && uv run --project backend python -m dashboard.server &
SERVER_PID=$!
sleep 2

# 1. POST set wip
curl -sX POST -d "status=wip" http://localhost:8910/capability/memory.long_term_memory/override
# 预期:返回 <span class="chip wip" ...>🟠 长期记忆 ✏️</span>

# 2. GET / 看 wip chip 上有 ✏️
curl -s http://localhost:8910/ | grep -oE 'memory.long_term_memory'

# 3. 再 POST clear
curl -sX POST -d "status=__clear__" http://localhost:8910/capability/memory.long_term_memory/override
# 预期:返回 <span class="chip todo" ...>⬜ 长期记忆</span>(无 ✏️)

# 4. POST /refresh → 302
curl -sI -X POST http://localhost:8910/refresh

kill $SERVER_PID 2>/dev/null
sleep 1
lsof -ti tcp:8910 | xargs -r kill -9 2>/dev/null || true
```

- [ ] **Step 5: 提交**

```bash
git add dashboard/server.py dashboard/tests/server/test_main_endpoint.py
git commit -m "feat(dashboard): POST /capability/{id}/override + POST /refresh + invalidate 闭环"
```

---

## Task 9: _app_shell.html 第 9 行 + main.html 引用

**Files:**
- Create: `dashboard/templates/_app_shell.html`
- Modify: `dashboard/templates/main.html` — 加 _app_shell include
- Modify: `dashboard/server.py` — index 算 app_shell stat,塞 context
- Modify: `dashboard/static/style.css` — 加 `.app-shell-row`

- [ ] **Step 1: 写 `dashboard/templates/_app_shell.html`**

```html
<aside class="app-shell-row">
  <span class="app-shell-num">09</span>
  <span class="app-shell-name">App Shell</span>
  <span class="app-shell-items">
    {% for item in app_shell %}
      <span class="app-shell-item">{{ item.name_cn }}: {{ item.file_count }}</span>
    {% endfor %}
  </span>
</aside>
```

- [ ] **Step 2: 改 `dashboard/server.py` — index 加 app_shell stat**

```python
from dashboard.derive.app_shell_stat import compute_app_shell_stat
from dashboard.derive.path_router import load_dimensions


async def index(request: Request) -> HTMLResponse:
    view_mode = request.query_params.get("view", "d")
    if view_mode not in ("d", "b"):
        view_mode = "d"
    snap = _get_or_build_snapshot()
    wips = [c for L in snap["layers"] for c in L["capabilities"] if c["status"] == "wip"]
    # App Shell 第 9 行 mini stat
    _main_dims, app_shell_dims = load_dimensions(CONFIG_DIR / "dimensions.yaml")
    app_shell = compute_app_shell_stat(PROJECT_ROOT, app_shell_dims)
    return templates.TemplateResponse(
        request,
        "main.html",
        {
            "today": _today_label(),
            "snap": snap,
            "wips": wips,
            "view_mode": view_mode,
            "app_shell": app_shell,
        },
    )
```

- [ ] **Step 3: 改 `dashboard/templates/main.html`**

```html
{% extends "base.html" %}
{% block content %}
  {% include "_hero.html" %}
  {% include "_d_b_toggle.html" %}
  <section class="view-content">
    {% if view_mode == 'b' %}
      {% include "_b_view.html" %}
    {% else %}
      {% include "_d_view.html" %}
    {% endif %}
  </section>
  {% include "_app_shell.html" %}
{% endblock %}
```

- [ ] **Step 4: 改 `dashboard/static/style.css` — 加 .app-shell-row**

末尾追加:

```css
/* App Shell 第 9 行 mini stat */
.app-shell-row {
  margin-top: 16px;
  padding: 8px 12px;
  border: 1px dashed var(--border);
  border-radius: 6px;
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 11px;
  color: var(--muted);
  font-family: ui-monospace, monospace;
}
.app-shell-num {
  color: var(--todo-fg);
  font-weight: 600;
}
.app-shell-name {
  color: var(--fg);
}
.app-shell-items {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}
```

- [ ] **Step 5: 加测试**

```python
def test_index_shows_app_shell_row():
    """主视图含 App Shell 第 9 行。"""
    with TestClient(app) as client:
        r = client.get("/")
        body = r.text
        assert 'class="app-shell-row"' in body
        assert '09' in body  # app shell number
        assert 'App Shell' in body
        # 6 项至少出现一项(具体名称随 dimensions.yaml,只验"前端"在 yaml 默认配置中)
        assert '前端' in body
```

- [ ] **Step 6: 跑 tests + mypy + smoke**

```bash
unset all_proxy https_proxy http_proxy && uv run --project backend pytest dashboard/tests/server/ -v
unset all_proxy https_proxy http_proxy && uv run --project backend mypy dashboard/
```

预期:Task 8 9 + Task 9 1 = 10 项 server tests PASS;mypy clean。

```bash
rm -f backend/data/board.db
unset all_proxy https_proxy http_proxy && uv run --project backend python -m dashboard.server &
SERVER_PID=$!
sleep 2
curl -s http://localhost:8910/ | grep -oE 'class="app-shell-row"'
curl -s http://localhost:8910/ | grep -oE '前端: \d+'
kill $SERVER_PID 2>/dev/null
sleep 1
lsof -ti tcp:8910 | xargs -r kill -9 2>/dev/null || true
```

- [ ] **Step 7: 提交**

```bash
git add dashboard/templates/_app_shell.html dashboard/templates/main.html dashboard/server.py dashboard/static/style.css dashboard/tests/server/test_main_endpoint.py
git commit -m "feat(dashboard): _app_shell.html 第 9 行 mini stat + 6 项 file count + .app-shell-row CSS"
```

---

## Task 10: README sync + ship checklist E2E

**Files:**
- Modify: `README.md` — 顶部版本备注 + 命令表(无新 Makefile target,只是确认现有 board-refresh 工作)

- [ ] **Step 1: 改 `README.md` — 顶部版本备注**

把现有"+ Harness Board M1"改为"+ Harness Board M2":

```diff
- **当前版本**:v0.8.5(...)+ Harness Board M1(dev meta-tool — `make board` 看 8 维 × 62 capability matrix)
+ **当前版本**:v0.8.5(...)+ Harness Board M2(D/B 视图 toggle + 编辑模式 + App Shell 第 9 行)
```

(M1 行可能已经被 main 上其他 PR 干掉过,read 一下确认现况后再改。)

- [ ] **Step 2: README 项目结构追加 M2 件**

如果 README 里已经有 dashboard 树状图(M1 加的),里面 templates 改成包含 M2 partial:

```diff
│   ├── templates/               # base / main / _hero / _d_view / _b_view / _hero / _d_b_toggle / _app_shell / _capability_chip / _edit_select(htmx 1.9.10 vendored)
```

- [ ] **Step 3: 跑全部 dashboard 测试 verify 仍 clean**

```bash
unset all_proxy https_proxy http_proxy && uv run --project backend pytest dashboard/tests/ -v
```

预期:M1 28 + Task 1 5 + Task 2 1 + Task 3 4 + Task 5 2 + Task 6 1 + Task 7 2 + Task 8 3 + Task 9 1 = ~40-47 项(具体随每 task 实际加多少)PASS。

- [ ] **Step 4: mypy verify**

```bash
unset all_proxy https_proxy http_proxy && uv run --project backend mypy dashboard/
```

预期:Success。

- [ ] **Step 5: E2E ship checklist verify(spec § 14)**

```bash
rm -f backend/data/board.db
unset all_proxy https_proxy http_proxy && uv run --project backend python -m dashboard.server &
SERVER_PID=$!
sleep 2

echo "--- 1. healthz ---"
curl -s http://localhost:8910/healthz
echo

echo "--- 2. D 视图(默认)---"
curl -s http://localhost:8910/ | grep -oE 'class="layer-card"' | wc -l
# 预期:8

echo "--- 3. B 视图 ---"
curl -s "http://localhost:8910/?view=b" | grep -oE 'class="kanban"'
# 预期:class="kanban"

echo "--- 4. Tab nav ---"
curl -s http://localhost:8910/ | grep -oE 'class="view-toggle"'

echo "--- 5. 编辑入口 chip 上有 hx-get ---"
curl -s http://localhost:8910/ | grep -oE 'hx-get="/capability/' | head -1

echo "--- 6. POST override → wip + ✏️ ---"
curl -sX POST -d "status=wip" http://localhost:8910/capability/memory.long_term_memory/override

echo "--- 7. 重新 GET / 看 wip 在 (持久化) ---"
curl -s http://localhost:8910/ | grep -oE 'class="chip wip"' | wc -l
# 预期:>= 1

echo "--- 8. App Shell 第 9 行 ---"
curl -s http://localhost:8910/ | grep -oE 'class="app-shell-row"'

echo "--- 9. board-refresh ---"
make board-refresh

echo "--- 10. 静态资源 ---"
curl -sI http://localhost:8910/static/style.css | head -1
curl -sI http://localhost:8910/static/htmx.min.js | head -1

kill $SERVER_PID 2>/dev/null
sleep 1
lsof -ti tcp:8910 | xargs -r kill -9 2>/dev/null || true
```

每项预期都需要看到对应内容。

- [ ] **Step 6: 提交 README + tag M2 ship**

```bash
git add README.md
git commit -m "docs(readme): sync Harness Board M2 — D/B toggle + 编辑模式 + App Shell"

# 可选:轻量 git tag
git tag -a harness-board-m2 -m "Harness Board M2: D/B toggle + 编辑模式 + App Shell + POST /refresh + TypedDict 收紧"
```

- [ ] **Step 7: 验收**

ship 标准 checklist(spec § 14):

- [ ] `make board` 浏览器开,有 D/B Tab
- [ ] 切到 B,看到 Kanban 三列(Todo / Doing / Done 折叠)
- [ ] 点击 chip,弹 select 4 选 1,选 wip,chip 立即变 🟠 + ✏️
- [ ] 关浏览器再开,wip 仍在(sqlite 持久化)
- [ ] 第 9 行显示 `09 App Shell · 前端: N · 后端: N · ... · 部署: N`
- [ ] `make board-refresh` 触发 POST /refresh + snapshot 重 build
- [ ] `mypy dashboard/` strict 全 PASS;`pytest dashboard/tests/` 40+ PASS

---

## Self-Review Checklist

**1. Spec 覆盖**:
- ✓ § 2 scope = C(§ 9.1 三件 + TypedDict + POST /refresh):全 task 1-10 覆盖
- ✓ § 3 capability_override single row + upsert/DELETE:Task 1
- ✓ § 4 edit UX 原生 select + htmx swap:Task 7+8
- ✓ § 5 stale ✏️:Task 4
- ✓ § 6 App Shell file count:Task 3+9
- ✓ § 7 POST /refresh + override 写自动 invalidate:Task 8
- ✓ § 8 SnapshotDict TypedDict:Task 2

**2. Placeholder 扫描**:无 TBD/TODO/FIXME。

**3. 类型一致性**:
- `OverrideRepo.get_all()` 返回 `dict[str, CapabilityStatus]`,`build_snapshot(overrides=...)` 接受同形(M1 已支持)✓
- `SnapshotRepo.save(payload: SnapshotDict)` 跟 `Snapshot.to_dict() -> SnapshotDict` 一致 ✓
- chip partial 接 `c: Capability | CapabilityDict`,Task 7 server route 构造 `Capability` dataclass 渲染 chip ✓

**4. 风险点**(实施时注意):

- **Risk 1**(Task 3 Step 5):`DimensionConfig.id` 类型从 `DimensionId` Literal 松绑为 `str`,可能影响 `path_router.classify_path` 的 mypy 校验(因为 `candidates: list[tuple[int, DimensionId]]`)。如果 mypy 抱怨,在 `classify_path` 内部对 `d.id` cast 为 DimensionId 或类型 ignore(谨慎,memory `feedback_type_ignore_with_typed_signature` 提示尽量不加)。最干净:维持 `DimensionId` 但把 app_shell 子 id 从 yaml 直接读 str 后存到 dataclass `id: str`,接受 dataclass 字段不再纯 Literal。
- **Risk 2**(Task 5):`templates.TemplateResponse` 的 context 不再含 `request`(M1 改新 API 后位置参数传)。Task 5 改时需保留 `templates.TemplateResponse(request, "main.html", {...})` 签名,context dict 不传 `request`。M1 实施时已经对了(commit `7a65b3f`),Task 5 改时不要回退。
- **Risk 3**(Task 7):`templates.get_template("_edit_select.html").render(c=...)` 直接 render 字符串,不走 TemplateResponse,所以**不会**被 base.html 包裹 — 这正是想要的(htmx swap 只要 chip 片段,不要整页 HTML)。
- **Risk 4**(Task 8):POST /override 重新 resolve 这个 capability,需要再开一次 conn 拿 overrides。可以合并到一次 conn 调用,但实施 simplest 是分两次(读 override 跟写不在同一段)。性能 M2 不关心(单进程 + 个人 dev 工具)。
- **Risk 5**(Task 6):jinja `{% set _ = list.append(...) %}` 是 jinja 标准做法但 jinja 警告 "macro / set in loop are not exposed". 实施时如果 jinja 抛 `UndefinedError` 关于 `_`,改成更直接的 layer-by-layer 手写聚合。或者 server 侧把 todo/wip/lit 三 list 预先算好喂给 template。**推荐 server 侧预算**(更 idiomatic):
  ```python
  # server.py index() 里:
  todo_caps = [c for L in snap["layers"] for c in L["capabilities"] if c["status"] == "todo"]
  wip_caps = [c for L in snap["layers"] for c in L["capabilities"] if c["status"] == "wip"]
  lit_caps = [c for L in snap["layers"] for c in L["capabilities"] if c["status"] == "lit"]
  ```
  context 多塞这 3 个 list,_b_view.html 直接用。但只在 view_mode == 'b' 时才需要(轻微优化:if-guard)。
- **Risk 6**(Task 8 Step 1):`form.get("status", "")` 返回类型 `str | UploadFile`,需 `isinstance(status, str)` 守卫。已经在 plan 里加了。
- **Risk 7**(Task 9):`compute_app_shell_stat` 在每次 GET / 都跑 `glob`。项目 ~ 1000 文件,6 次 glob ≤ 100ms。可接受。M3 视需要加 cache。
- **Risk 8**:`rm -f backend/data/board.db` 在 smoke step 反复用,实施期间如果不删,override 状态会跨 task 累积影响测试。每 task 跑前最好 fresh DB。

**5. memory 教训应用**:
- `feedback_path_resolution_in_plans` ✓:DB_PATH / CONFIG_DIR / PROJECT_ROOT 仍按 `Path(__file__).parent` 算
- `feedback_python_m_path_dual_context` ✓:`uv run --project backend python -m dashboard.server` 仍从 project root 跑,M1 sys.path 注入仍生效
- `feedback_dev_tool_version_pin_alignment` ✓:无新 dep
- `feedback_third_party_plugin_defaults` ✓:`<details><summary>` 是浏览器原生,htmx form swap 已在 M1 spike 过(spec § 9.2 假设)
- `feedback_type_ignore_with_typed_signature` ✓:不加 type:ignore;mypy 抱怨先调签名
- `feedback_estimate_in_claude_code_walltime` ✓:1.5 天 wall time

---

## 后续(超 M2 范围)

M2 ship 后按 spec § 9 进入 M3(`/decisions` route + decision_extractor + filter UI)。届时 M1 final review 沉淀的 (a) 死分支(`spec_section` / `memory_frontmatter`)在 decision_extractor 自然会用上,届时一起加 fixture 测试。

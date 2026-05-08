# Harness Board · M3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship M3:`make board` 切到第三 tab "决策" 看到 ~30-50 项决策列表(memory + spec 合并,时间倒序);layer chip + state chip + keyword input client-side filter;每决策卡可填 note 持久化 sqlite。同时清 M2 final review 沉淀的 test infra fixture 升级 + M1 test files mypy strict 老债。

**Architecture:** 增量在 M2 5 层架构上 — Source 加 memory_path 配置;Derive 加 decision_extractor 单文件模块(spec 扫 + memory frontmatter 扫 + layer 关键字归类);State 加 decision_note 表 + DecisionNoteRepo(平行 M2 OverrideRepo);Server 加 GET /decisions + POST/DELETE /decisions/{id}/note;UI 加 decisions.html + 4 partial + decisions-filter.js;test infra 加 server/conftest.py autouse fixture。

**Tech Stack:** 复用 M2 — Starlette + Jinja2 + htmx 1.9.10 vendored + sqlite3(stdlib)+ pyyaml + Python 3.11+。新加 `hashlib`(stdlib)用于决策稳定 ID。**不新增依赖**。

**Source Spec:** `docs/superpowers/specs/2026-05-07-harness-board-m3-design.md`

**M3 不含**(留 M3.x / M4):
- ❌ `state: deprecated` 自动 detection(留 M3.x;用户可在 note 字段手填)
- ❌ URL filter state 同步(`?layer=04,06`)— 留 M3.x
- ❌ 决策来自 git log / commit message — 留 M4
- ❌ B Kanban `[XX]` dim prefix(M2 polish PR)
- ❌ memory frontmatter convention 升级 — 留 M3.x

**M3 工期估算**:1.3 天 wall time(M3 1 天 + (b)+(c) 0.3 天)

---

## File Structure

```
dashboard/
├── derive/
│   ├── decision_extractor.py        # 新 (Task 4) ~80 LoC
│   └── types.py                     # 改:加 Decision dataclass + compute_decision_id helper (Task 3)
├── state/
│   ├── repositories.py              # 改:加 DecisionNoteRepo (Task 2)
│   └── db.py                        # 改:SCHEMA 加 decision_note 表 (Task 2)
├── templates/
│   ├── decisions.html               # 新 (Task 6) 主 page
│   ├── _decision_card.html          # 新 (Task 6) 单卡 partial 含 note form
│   ├── _decision_filter.html        # 新 (Task 7) layer/state chip + keyword input
│   ├── _view_toggle.html            # 新名(改自 _d_b_toggle.html)+ 第三 tab 决策 (Task 5)
│   ├── _d_b_toggle.html             # 删 (Task 5,内容迁到 _view_toggle.html)
│   └── main.html                    # 改:_d_b_toggle 改 _view_toggle (Task 5)
├── static/
│   ├── decisions-filter.js          # 新 (Task 7) ~30 LoC
│   └── style.css                    # 改:加 .decision-card / .filter-chip / .filter-keyword 等 (Task 7)
├── server.py                        # 改:加 GET /decisions + POST/DELETE note + memory_path resolve (Task 4/6/8)
└── tests/
    ├── derive/
    │   └── test_decision_extractor.py   # 新 (Task 4) 5 项
    ├── state/
    │   └── test_decision_note_repo.py   # 新 (Task 2) 4 项
    └── server/
        ├── conftest.py                  # 新 (Task 1) autouse fixture
        ├── test_decisions_endpoint.py   # 新 (Task 6/8) 4 项
        └── test_main_endpoint.py        # 改 (Task 1) 撤销 inline __clear__ + 加 -> None
```

**Modified files (top-level):**
- `README.md`(Task 9)— 顶部版本备注 + 项目结构

---

## Task 1: M1/M2 test mypy 清债 + server/conftest.py fixture(prelude follow-up b/c)

**Files:**
- Create: `dashboard/tests/server/conftest.py`
- Modify: `dashboard/tests/derive/test_path_router.py` — 加 type args
- Modify: `dashboard/tests/derive/test_snapshot_builder.py` — 加 -> None
- Modify: `dashboard/tests/derive/test_capability_resolver.py` — 加 -> None
- Modify: `dashboard/tests/derive/test_app_shell_stat.py` — 加 -> None
- Modify: `dashboard/tests/state/test_repositories.py` — 加 -> None
- Modify: `dashboard/tests/server/test_main_endpoint.py` — 撤销 inline `__clear__` + 加 -> None
- Modify: `pyproject.toml` — 加 `mypy.ini_options` 显式包含 `dashboard/tests/`(若未含)

- [ ] **Step 1: 跑当前 mypy strict 看 errors 数**

```bash
unset all_proxy https_proxy http_proxy && uv run --project backend mypy dashboard/tests/ 2>&1 | tail -20
```

记录每个 error file:line。预期 ~8 errors(M2 final review M-3 引用)。

- [ ] **Step 2: 写 `dashboard/tests/server/conftest.py`**

```python
# dashboard/tests/server/conftest.py
"""Server tests autouse fixture — 隔离 dashboard.server.DB_PATH 到 tmp_path,
不污染 prod backend/data/board.db。"""
from __future__ import annotations
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_dashboard_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """每个 server test 用独立 sqlite。"""
    monkeypatch.setattr("dashboard.server.DB_PATH", tmp_path / "board.db")
```

只放 `tests/server/conftest.py`(不放 tests/conftest.py),范围限定 server 测试。

- [ ] **Step 3: 撤销 M2 server tests 里的 inline `__clear__`**

读 `dashboard/tests/server/test_main_endpoint.py`,找出 `client.post(..., data={"status": "__clear__"})` 出现位置(M2 实施时为隔离防漏加的 cleanup,fixture 后不需要)。

例:`test_post_override_invalidates_and_swaps` 开头的 cleanup 行 + 末尾的 cleanup 行删除。`test_post_override_clear_sentinel` 开头的 seed 保留(它是测试主体逻辑,不是 cleanup)。

具体:删除 4 行(2 测试 × 头/尾各一)。

- [ ] **Step 4: 加 `-> None` 注解到所有 dashboard test functions**

批量改:

```bash
# 找所有 def test_xxx(...) 没有 -> None 的
unset all_proxy https_proxy http_proxy && uv run --project backend mypy dashboard/tests/ 2>&1 | grep "no-untyped-def"
```

逐个文件加 `-> None`(测试函数都不返回值)。注意 fixture 函数也要加 `-> None` 或对应类型。

具体涉及:
- `test_path_router.py`:fixture `dims()` 改返回 `tuple[list[DimensionConfig], list[DimensionConfig]]`(目前是 `tuple[list, list]`),`test_*` 加 `-> None`
- `test_snapshot_builder.py:10/25/31/36/43`:5 函数加 `-> None`
- `test_capability_resolver.py`:某些函数缺 `-> None`
- `test_app_shell_stat.py`:大概率已加(M2 Task 3 实施时检查过)
- `test_repositories.py`:某些函数缺 `-> None`
- `test_main_endpoint.py`:某些函数缺 `-> None`

- [ ] **Step 5: 跑 mypy strict verify clean**

```bash
unset all_proxy https_proxy http_proxy && uv run --project backend mypy dashboard/
```

预期:Success: no issues found in 30+ source files(含 test files)。如果还有 error,逐个 fix(不加 type:ignore,memory `feedback_type_ignore_with_typed_signature`)。

- [ ] **Step 6: 跑全部 dashboard tests verify 仍 47 PASS**

```bash
unset all_proxy https_proxy http_proxy && uv run --project backend pytest dashboard/tests/ -v
```

预期:47 passed(M2 ship 数量,Task 1 不增不减)。

- [ ] **Step 7: 提交**

```bash
git add dashboard/tests/server/conftest.py dashboard/tests/
git commit -m "chore(dashboard): test infra 升级 — server/conftest.py autouse fixture + M1/M2 test mypy strict 清债"
```

(`chore:` 不是 `fix:`,无需 `原因 layer:` marker。)

---

## Task 2: decision_note 表 + DecisionNoteRepo + 4 测试

**Files:**
- Modify: `dashboard/state/db.py` — SCHEMA 加 decision_note 表
- Modify: `dashboard/state/repositories.py` — 加 DecisionNoteRepo class
- Create: `dashboard/tests/state/test_decision_note_repo.py` — 4 测试

- [ ] **Step 1: 写失败测试 `dashboard/tests/state/test_decision_note_repo.py`**

```python
# dashboard/tests/state/test_decision_note_repo.py
from pathlib import Path

from dashboard.state.db import open_db
from dashboard.state.repositories import DecisionNoteRepo


def test_empty_returns_empty_dict(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "board.db")
    repo = DecisionNoteRepo(conn)
    assert repo.get_all() == {}


def test_upsert_then_get(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "board.db")
    repo = DecisionNoteRepo(conn)
    repo.upsert("a1b2c3d4e5f6", "回头看 plan_correctness 是否真的够好")
    assert repo.get_all() == {"a1b2c3d4e5f6": "回头看 plan_correctness 是否真的够好"}


def test_delete_clears(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "board.db")
    repo = DecisionNoteRepo(conn)
    repo.upsert("a1b2c3d4e5f6", "test")
    repo.delete("a1b2c3d4e5f6")
    assert repo.get_all() == {}


def test_multi_decision_isolation(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "board.db")
    repo = DecisionNoteRepo(conn)
    repo.upsert("aaaaaaaaaaaa", "决策 A note")
    repo.upsert("bbbbbbbbbbbb", "决策 B note")
    repo.delete("aaaaaaaaaaaa")
    assert repo.get_all() == {"bbbbbbbbbbbb": "决策 B note"}
```

- [ ] **Step 2: 跑 test 验证 fail**

```bash
unset all_proxy https_proxy http_proxy && uv run --project backend pytest dashboard/tests/state/test_decision_note_repo.py -v
```

预期:`ImportError: cannot import name 'DecisionNoteRepo'`。

- [ ] **Step 3: 改 `dashboard/state/db.py` — SCHEMA 加 decision_note**

读现有 SCHEMA。在 `capability_override` 表后追加:

```python
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

CREATE TABLE IF NOT EXISTS decision_note (
  decision_id TEXT PRIMARY KEY,
  note TEXT NOT NULL DEFAULT '',
  set_at TEXT NOT NULL
);
"""
```

- [ ] **Step 4: 改 `dashboard/state/repositories.py` — 加 DecisionNoteRepo**

读 OverrideRepo 实现,在文件末尾追加 mirror class:

```python
class DecisionNoteRepo:
    """sqlite CRUD for decision_note。single row per decision(spec § 4)。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get_all(self) -> dict[str, str]:
        """返回 {decision_id: note}"""
        cur = self.conn.execute(
            "SELECT decision_id, note FROM decision_note"
        )
        return {row["decision_id"]: row["note"] for row in cur.fetchall()}

    def upsert(
        self,
        decision_id: str,
        note: str,
        set_at: str | None = None,
    ) -> None:
        """upsert per decision_id (PRIMARY KEY conflict 时覆盖)。"""
        set_at = set_at or datetime.now(UTC).isoformat()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO decision_note (decision_id, note, set_at)
                VALUES (?, ?, ?)
                ON CONFLICT(decision_id) DO UPDATE SET
                  note = excluded.note,
                  set_at = excluded.set_at
                """,
                (decision_id, note, set_at),
            )

    def delete(self, decision_id: str) -> None:
        with self.conn:
            self.conn.execute(
                "DELETE FROM decision_note WHERE decision_id = ?",
                (decision_id,),
            )
```

`datetime` + `UTC` 已经在 M2 OverrideRepo import 进来了,无需重复。

- [ ] **Step 5: 跑 test verify PASS + mypy**

```bash
unset all_proxy https_proxy http_proxy && uv run --project backend pytest dashboard/tests/state/test_decision_note_repo.py -v
unset all_proxy https_proxy http_proxy && uv run --project backend mypy dashboard/
```

预期:4 passed,mypy clean。

- [ ] **Step 6: 提交**

```bash
git add dashboard/state/db.py dashboard/state/repositories.py dashboard/tests/state/test_decision_note_repo.py
git commit -m "feat(dashboard): decision_note 表 + DecisionNoteRepo (single row upsert/delete,平行 OverrideRepo)"
```

---

## Task 3: Decision dataclass + compute_decision_id helper

**Files:**
- Modify: `dashboard/derive/types.py` — 加 Decision dataclass + compute_decision_id 函数

- [ ] **Step 1: 改 `dashboard/derive/types.py`**

读现有 types.py,在末尾追加:

```python
import hashlib


@dataclass(frozen=True)
class Decision:
    """决策(从 spec section 或 memory frontmatter 派生)。spec § 11.3。"""
    id: str           # sha256(version + layer + title)[:12]
    date: str         # ISO date(file mtime 或 frontmatter date)
    version: str      # "v0.8.5" / "M2" / "unversioned" / "unknown"
    layer: str        # "01" - "08" / "META"(spec § 3.1 keywords 反向归类后)
    title: str        # frontmatter name 或 spec ## § 标题
    why: str          # description 或 spec 段第一段
    refs: tuple[str, ...]   # 文件相对路径(frozen 用 tuple)
    state: str = "active"   # M3 默认 active,M3.x deprecated detect


def compute_decision_id(version: str, layer: str, title: str) -> str:
    """spec § 7.4:sha256(version + layer + title)[:12]。"""
    payload = f"{version}|{layer}|{title}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:12]
```

注:`hashlib` 是 stdlib;`refs: tuple[str, ...]` 因 frozen dataclass 不能存 list(`field(default_factory=list)` 配 frozen 不行)。

- [ ] **Step 2: 加单元测 ID 稳定**

加到 `dashboard/tests/derive/test_decision_extractor.py`(虽然 Task 4 创建该文件,Task 3 这一项 test 提前写也行)。**为了避免 Task 3/4 文件碰撞,把 ID 测试放进 `test_capability_resolver.py` 或新建 `test_types.py`**。**最简:跟 Task 4 一并测**。

Task 3 跳过单测,合并到 Task 4 step 4 一起验证。

- [ ] **Step 3: mypy 验证**

```bash
unset all_proxy https_proxy http_proxy && uv run --project backend mypy dashboard/
```

预期:clean。

- [ ] **Step 4: 提交**

```bash
git add dashboard/derive/types.py
git commit -m "feat(dashboard): Decision dataclass + compute_decision_id (sha256[:12])"
```

---

## Task 4: decision_extractor 模块 + 5 测试

**Files:**
- Create: `dashboard/derive/decision_extractor.py` — ~80 LoC 单文件
- Create: `dashboard/tests/derive/test_decision_extractor.py` — 5 测试

- [ ] **Step 1: 写失败测试 `dashboard/tests/derive/test_decision_extractor.py`**

```python
# dashboard/tests/derive/test_decision_extractor.py
from pathlib import Path

import pytest

from dashboard.derive.decision_extractor import (
    classify_layer,
    extract_from_memory,
    extract_from_specs,
    resolve_memory_path,
)
from dashboard.derive.path_router import load_dimensions
from dashboard.derive.types import compute_decision_id


@pytest.fixture
def main_dims():
    yaml_path = Path(__file__).parent.parent.parent / "config" / "dimensions.yaml"
    main, _ = load_dimensions(yaml_path)
    return main


def test_extract_from_specs_basic(tmp_path: Path) -> None:
    """spec section 扫:抓 ## § X 决策 N 段。"""
    spec_file = tmp_path / "2026-05-05-v0.8.5-test-design.md"
    spec_file.write_text("""# Test Spec

## § 0 元信息

非决策段。

## § 2 决策一:Constrained LLM Router

**问题陈述**:prompt 漂移。
**业界 alternatives**:LangChain / Pydantic AI。

## § 3 决策二:Skills Bundle

**问题陈述**:skill 复用。
""", encoding="utf-8")
    decisions = extract_from_specs(tmp_path)
    assert len(decisions) == 2
    titles = sorted(d.title for d in decisions)
    assert "Constrained LLM Router" in titles[0] or "Constrained LLM Router" in titles[1]
    # version 从文件名 regex
    assert all(d.version == "v0.8.5" for d in decisions)


def test_extract_from_memory_frontmatter(tmp_path: Path, main_dims) -> None:
    """memory 文件 frontmatter 扫:type=feedback|project 才进入。"""
    mem_a = tmp_path / "feedback_test_lesson.md"
    mem_a.write_text("""---
name: 测试教训
description: prompt 漂移要用 constrained schema 防御
type: feedback
---

正文内容。
""", encoding="utf-8")

    mem_b = tmp_path / "project_v0.8.5_landed.md"
    mem_b.write_text("""---
name: v0.8.5 落地
description: Constrained LLM Router + Skills bundle
type: project
---
""", encoding="utf-8")

    mem_c = tmp_path / "user_role.md"
    mem_c.write_text("""---
name: user role
description: senior LLM dev
type: user
---
""", encoding="utf-8")

    decisions = extract_from_memory(tmp_path, main_dims)
    # type=user 不进入,只有 feedback + project 共 2 项
    assert len(decisions) == 2
    titles = {d.title for d in decisions}
    assert "测试教训" in titles
    assert "v0.8.5 落地" in titles
    # version derive
    versions = {d.version for d in decisions}
    assert "v0.8.5" in versions
    assert "unversioned" in versions


def test_layer_keyword_classification(main_dims) -> None:
    """关键字归类:文本含 dim keywords → 命中该 dim,无命中 → META。"""
    # constrained_router → guardrails(其 keywords 含 "Schema")— 但实际 dimensions.yaml.06 keywords = ["Schema", "Pydantic", "retry"]
    text_06 = "Pydantic schema 验证 + retry edge"
    assert classify_layer(text_06, main_dims) == "guardrails"

    # tier_router → cost_routing(keywords ["TierRouter", "pricing"])
    text_08 = "TierRouter 3 层选 model"
    assert classify_layer(text_08, main_dims) == "cost_routing"

    # 无 keyword → META
    text_no = "随便写点没 keyword 的"
    assert classify_layer(text_no, main_dims) == "META"


def test_decision_id_stable() -> None:
    """同 input → 同 ID(12 字 hex)。"""
    id1 = compute_decision_id("v0.8.5", "06", "Constrained Router")
    id2 = compute_decision_id("v0.8.5", "06", "Constrained Router")
    assert id1 == id2
    assert len(id1) == 12
    assert all(c in "0123456789abcdef" for c in id1)
    # 不同 input → 不同 ID
    id3 = compute_decision_id("v0.8.5", "07", "Constrained Router")
    assert id1 != id3


def test_resolve_memory_path_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """env var 优先于 auto-detect。"""
    custom = tmp_path / "custom_memory"
    custom.mkdir()
    monkeypatch.setenv("HARNESS_MEMORY_PATH", str(custom))
    assert resolve_memory_path() == custom


def test_resolve_memory_path_fallback_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """env 没设 + auto-detect 不存在 → None。"""
    monkeypatch.delenv("HARNESS_MEMORY_PATH", raising=False)
    monkeypatch.setattr("dashboard.derive.decision_extractor.PROJECT_ROOT", Path("/nonexistent/path"))
    assert resolve_memory_path() is None
```

注:7 个测试(超过 spec § 14.1 计的 5 个,加了 resolve_memory_path 2 项)。Spec target 12 增量 → 实际 13 增量,可接受。

- [ ] **Step 2: 跑 test 验证 fail**

```bash
unset all_proxy https_proxy http_proxy && uv run --project backend pytest dashboard/tests/derive/test_decision_extractor.py -v
```

预期:`ImportError`。

- [ ] **Step 3: 写 `dashboard/derive/decision_extractor.py`**

```python
# dashboard/derive/decision_extractor.py
"""Decision extractor:从 spec sections + memory frontmatter 派生 ~47 项 Decision。

spec § 3:layer 用 dimensions.yaml.keywords 反向归类
spec § 9:memory_path resolve(env override + auto-detect + None fallback)
"""
from __future__ import annotations
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .types import Decision, DimensionConfig, compute_decision_id

PROJECT_ROOT = Path(__file__).parent.parent.parent  # dashboard 顶级到 repo 根

# spec filename:2026-05-05-v0.8.5-...md → v0.8.5
# spec filename:2026-05-07-harness-board-m2-design.md → M2
SPEC_VERSION_RE = re.compile(r"\d{4}-\d{2}-\d{2}-(v\d+\.\d+(?:\.\d+)?|M\d+|m\d+)")
# memory filename:project_v0.8.5_architecture_landed.md → v0.8.5
MEM_VERSION_RE = re.compile(r"^project_v(\d+\.\d+(?:\.\d+)?)_")
# spec section header:## § 2 决策一:Constrained Router → "Constrained Router"
SPEC_DECISION_RE = re.compile(r"^## § \d+ 决策\S*[:：](.*)$", re.MULTILINE)
# memory frontmatter delimiters
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def resolve_memory_path() -> Path | None:
    """三层 fallback:env override → auto-detect → None。spec § 9.1。"""
    env = os.environ.get("HARNESS_MEMORY_PATH")
    if env:
        p = Path(env)
        return p if p.exists() else None
    auto = (
        Path.home()
        / ".claude"
        / "projects"
        / ("-" + str(PROJECT_ROOT).replace("/", "-"))
        / "memory"
    )
    return auto if auto.exists() else None


def classify_layer(text: str, main_dims: list[DimensionConfig]) -> str:
    """text 里 keyword scan 8 dim,返回最多匹配的 dim id;无匹配返 'META'。"""
    text_lower = text.lower()
    scores: dict[str, int] = {}
    for d in main_dims:
        for kw in d.keywords:
            if kw.lower() in text_lower:
                scores[d.id] = scores.get(d.id, 0) + 1
    if not scores:
        return "META"
    return max(scores.items(), key=lambda kv: kv[1])[0]


def _spec_version(filename: str) -> str:
    m = SPEC_VERSION_RE.search(filename)
    return m.group(1) if m else "unknown"


def _mem_version(filename: str) -> str:
    m = MEM_VERSION_RE.match(filename)
    if m:
        return f"v{m.group(1)}"
    if filename.startswith("feedback_"):
        return "unversioned"
    return "unknown"


def extract_from_specs(specs_dir: Path) -> list[Decision]:
    """扫 specs_dir 下 *.md,抓每个 ## § X 决策\\S*[:：] 段为 Decision。"""
    out: list[Decision] = []
    if not specs_dir.exists():
        return out
    # 加载 dimensions for layer classify
    config_dir = PROJECT_ROOT / "dashboard" / "config"
    from .path_router import load_dimensions
    main_dims, _ = load_dimensions(config_dir / "dimensions.yaml")

    for spec_file in sorted(specs_dir.glob("*.md")):
        version = _spec_version(spec_file.name)
        date = datetime.fromtimestamp(spec_file.stat().st_mtime).strftime("%Y-%m-%d")
        text = spec_file.read_text(encoding="utf-8")
        # 拆分 sections,每个 ## 开头之间是一段
        # 用 SPEC_DECISION_RE 找 title,然后取该 section 的第一段(why)
        sections = re.split(r"^## ", text, flags=re.MULTILINE)
        for sec in sections:
            m = SPEC_DECISION_RE.match("## " + sec)
            if not m:
                continue
            title = m.group(1).strip()
            # why = 第一个非空段(在 ## 行之后)
            lines = sec.splitlines()[1:]  # 跳过 ## § X 决策 行(已被 split)
            why = ""
            for line in lines:
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    why = stripped[:200]  # 截断防超长
                    break
            layer = classify_layer(title + " " + why, main_dims)
            out.append(
                Decision(
                    id=compute_decision_id(version, layer, title),
                    date=date,
                    version=version,
                    layer=layer,
                    title=title,
                    why=why,
                    refs=(spec_file.name,),
                )
            )
    return out


def extract_from_memory(memory_dir: Path, main_dims: list[DimensionConfig]) -> list[Decision]:
    """扫 memory_dir 下 *.md frontmatter,filter type ∈ {feedback, project}。"""
    out: list[Decision] = []
    if not memory_dir.exists():
        return out
    for mem_file in sorted(memory_dir.glob("*.md")):
        if mem_file.name == "MEMORY.md":
            continue  # MEMORY.md 是索引,不是单决策
        text = mem_file.read_text(encoding="utf-8")
        m = FRONTMATTER_RE.match(text)
        if not m:
            continue
        try:
            fm: dict[str, Any] = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            continue
        if fm.get("type") not in ("feedback", "project"):
            continue
        title = str(fm.get("name", mem_file.stem))
        why = str(fm.get("description", ""))[:200]
        version = _mem_version(mem_file.name)
        layer = classify_layer(title + " " + why, main_dims)
        date = datetime.fromtimestamp(mem_file.stat().st_mtime).strftime("%Y-%m-%d")
        out.append(
            Decision(
                id=compute_decision_id(version, layer, title),
                date=date,
                version=version,
                layer=layer,
                title=title,
                why=why,
                refs=(mem_file.name,),
            )
        )
    return out


def extract_all() -> list[Decision]:
    """spec + memory 合并,去重(同 id 取 spec)+ 时间倒序。"""
    specs_dir = PROJECT_ROOT / "docs" / "superpowers" / "specs"
    config_dir = PROJECT_ROOT / "dashboard" / "config"
    from .path_router import load_dimensions
    main_dims, _ = load_dimensions(config_dir / "dimensions.yaml")

    spec_decisions = extract_from_specs(specs_dir)
    seen_ids = {d.id for d in spec_decisions}

    memory_dir = resolve_memory_path()
    mem_decisions = extract_from_memory(memory_dir, main_dims) if memory_dir else []
    # 去重:spec 优先于 memory
    mem_decisions = [d for d in mem_decisions if d.id not in seen_ids]

    all_decisions = spec_decisions + mem_decisions
    all_decisions.sort(key=lambda d: d.date, reverse=True)
    return all_decisions
```

注:
- `extract_from_specs` 内 `from .path_router import load_dimensions` 是 lazy import 防 circular(load_dimensions 引用 types,types 不引用其他)。
- spec section 拆分用 `re.split(r"^## ", ..., re.MULTILINE)`,每段 prepend "## " 后用正则 match。
- 决策 title 默认 200 字符截断防超长。
- MEMORY.md(index)显式跳过。

- [ ] **Step 4: 跑 test 验证 PASS**

```bash
unset all_proxy https_proxy http_proxy && uv run --project backend pytest dashboard/tests/derive/test_decision_extractor.py -v
```

预期:7 passed。

- [ ] **Step 5: 实跑 extract_all() 看真实数据**

```bash
unset all_proxy https_proxy http_proxy && uv run --project backend python -c "
from dashboard.derive.decision_extractor import extract_all, resolve_memory_path
print('memory_path:', resolve_memory_path())
decisions = extract_all()
print(f'共 {len(decisions)} 项决策')
print('前 5 项:')
for d in decisions[:5]:
    print(f'  {d.date} · {d.version} · [{d.layer}] {d.title[:40]}')
print('layer 分布:')
from collections import Counter
c = Counter(d.layer for d in decisions)
for layer, n in c.most_common():
    print(f'  {layer}: {n}')
"
```

预期:30-50 项,layer 分布展示;多数命中 8 dim 之一,少量 META。

如果 memory_path None(auto-detect 失败),输出仅 spec 决策 ~12 项。

- [ ] **Step 6: mypy + 全测试**

```bash
unset all_proxy https_proxy http_proxy && uv run --project backend mypy dashboard/
unset all_proxy https_proxy http_proxy && uv run --project backend pytest dashboard/tests/ -v
```

预期:mypy clean,M2 47 + Task 2 4 + Task 4 7 = 58 PASS。

- [ ] **Step 7: 提交**

```bash
git add dashboard/derive/decision_extractor.py dashboard/tests/derive/test_decision_extractor.py
git commit -m "feat(dashboard): decision_extractor (spec scan + memory frontmatter scan + layer 关键字归类)"
```

---

## Task 5: _view_toggle.html 改名 + 第三 tab + active_view 参数

**Files:**
- Rename: `dashboard/templates/_d_b_toggle.html` → `dashboard/templates/_view_toggle.html`
- Modify: 上述新文件加第三 tab + 接 active_view
- Modify: `dashboard/templates/main.html` — include 改名 + active_view 传值
- Modify: `dashboard/server.py` — index ctx 加 `active_view` 字段

- [ ] **Step 1: 改名 + 加第三 tab**

```bash
git mv dashboard/templates/_d_b_toggle.html dashboard/templates/_view_toggle.html
```

写新内容到 `dashboard/templates/_view_toggle.html`:

```html
<nav class="view-toggle">
  <a href="/?view=d" class="{% if active_view == 'd' %}active{% endif %}">D 维度</a>
  <a href="/?view=b" class="{% if active_view == 'b' %}active{% endif %}">B Kanban</a>
  <a href="/decisions" class="{% if active_view == 'decisions' %}active{% endif %}">决策</a>
</nav>
```

- [ ] **Step 2: 改 `dashboard/templates/main.html`**

```html
{% extends "base.html" %}
{% block content %}
  {% include "_hero.html" %}
  {% include "_view_toggle.html" %}
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

- [ ] **Step 3: 改 `dashboard/server.py` index 加 active_view**

读现有 `index` view,在 ctx dict 加 `active_view`:

```python
async def index(request: Request) -> HTMLResponse:
    view_mode = request.query_params.get("view", "d")
    if view_mode not in ("d", "b"):
        view_mode = "d"
    snap = _get_or_build_snapshot()
    wips = [c for L in snap["layers"] for c in L["capabilities"] if c["status"] == "wip"]
    _main_dims, app_shell_dims = load_dimensions(CONFIG_DIR / "dimensions.yaml")
    app_shell = compute_app_shell_stat(PROJECT_ROOT, app_shell_dims)
    ctx: dict[str, object] = {
        "today": _today_label(),
        "snap": snap,
        "wips": wips,
        "view_mode": view_mode,
        "active_view": view_mode,   # M3:同 view_mode("d" 或 "b"),decisions 用独立 route 不走这
        "app_shell": app_shell,
    }
    if view_mode == "b":
        ctx["todo_caps"] = [c for L in snap["layers"] for c in L["capabilities"] if c["status"] == "todo"]
        ctx["wip_caps"] = wips
        ctx["lit_caps"] = [c for L in snap["layers"] for c in L["capabilities"] if c["status"] == "lit"]
    return templates.TemplateResponse(request, "main.html", ctx)
```

- [ ] **Step 4: 跑 server tests verify 仍 PASS**

```bash
unset all_proxy https_proxy http_proxy && uv run --project backend pytest dashboard/tests/server/ -v
```

预期:M2 server 11 项 PASS。test_view_d_default 检查 "B Kanban" / "D 维度" 在 body — 仍命中。

- [ ] **Step 5: smoke 看第三 tab 渲染**

```bash
unset all_proxy https_proxy http_proxy && uv run --project backend python -m dashboard.server &
SERVER_PID=$!
sleep 2
echo "--- 三 tab nav ---"
curl -s http://localhost:8910/ | grep -oE 'D 维度|B Kanban|决策'
echo "--- /decisions 暂 404(Task 6 接通)---"
curl -sI http://localhost:8910/decisions | head -1
kill $SERVER_PID 2>/dev/null
sleep 1
lsof -ti tcp:8910 | xargs -r kill -9 2>/dev/null || true
```

预期:三个 tab 名都 render(D 维度 / B Kanban / 决策);/decisions 当前 404(Task 6 加 route)。

- [ ] **Step 6: 提交**

```bash
git add dashboard/templates/_view_toggle.html dashboard/templates/main.html dashboard/server.py
git rm dashboard/templates/_d_b_toggle.html  # 已 git mv 的话不需要,但 git mv 后有时 git status 仍显示 D 文件
git commit -m "feat(dashboard): _view_toggle.html (改自 _d_b_toggle) + 第三 tab 决策 + active_view 参数"
```

---

## Task 6: GET /decisions route + decisions.html + _decision_card.html + 1 测试

**Files:**
- Create: `dashboard/templates/decisions.html`
- Create: `dashboard/templates/_decision_card.html`
- Modify: `dashboard/server.py` — 加 decisions handler + route
- Create: `dashboard/tests/server/test_decisions_endpoint.py` — 1 测试 (Task 8 加另 3)

- [ ] **Step 1: 写 `dashboard/templates/decisions.html`**

```html
{% extends "base.html" %}
{% block content %}
  {% include "_hero.html" %}
  {% include "_view_toggle.html" %}
  {% if memory_path_warning %}
    <p class="warning-banner">⚠ memory 路径未找到,仅显示 spec 决策 ~{{ decisions|length }} 项</p>
  {% endif %}
  {% include "_decision_filter.html" %}
  <section class="decisions-list">
    {% for d in decisions %}
      {% include "_decision_card.html" %}
    {% endfor %}
  </section>
{% endblock %}
```

注意:`_decision_filter.html` 在 Task 7 创建,本 Task 暂时 include 它会报"file not found"。Task 6 先把 `{% include "_decision_filter.html" %}` 注掉,Task 7 加 partial 后再放开。

实际 Task 6 写:

```html
{% extends "base.html" %}
{% block content %}
  {% include "_hero.html" %}
  {% include "_view_toggle.html" %}
  {% if memory_path_warning %}
    <p class="warning-banner">⚠ memory 路径未找到,仅显示 spec 决策 ~{{ decisions|length }} 项</p>
  {% endif %}
  {# Task 7 will add: {% include "_decision_filter.html" %} #}
  <section class="decisions-list">
    {% for d in decisions %}
      {% include "_decision_card.html" %}
    {% endfor %}
  </section>
{% endblock %}
```

Task 7 解开注释。

- [ ] **Step 2: 写 `dashboard/templates/_decision_card.html`**

```html
<article class="decision-card"
         data-layer="{{ d.layer }}"
         data-state="{{ d.state }}"
         data-text="{{ (d.title + ' ' + d.why)|lower }}">
  <header class="decision-head">
    <span class="decision-date">{{ d.date }}</span>
    <span class="decision-version">{{ d.version }}</span>
    <span class="decision-layer">[{{ d.layer }}]</span>
  </header>
  <h3 class="decision-title">{{ d.title }}</h3>
  {% if d.why %}<p class="decision-why"><strong>Why:</strong> {{ d.why }}</p>{% endif %}
  <p class="decision-refs">
    refs:
    {% for ref in d.refs %}<code>{{ ref }}</code>{% endfor %}
  </p>
  <form class="decision-note"
        hx-post="/decisions/{{ d.id }}/note"
        hx-target="this"
        hx-swap="outerHTML">
    <input name="note" value="{{ note_lookup.get(d.id, '') }}" placeholder="(用户备注)">
    <button type="submit">保存</button>
  </form>
</article>
```

- [ ] **Step 3: 改 `dashboard/server.py` 加 GET /decisions**

加 imports:

```python
from dashboard.derive.decision_extractor import extract_all, resolve_memory_path
from dashboard.state.repositories import DecisionNoteRepo
```

加 handler:

```python
async def decisions_view(request: Request) -> HTMLResponse:
    """GET /decisions — render 全部决策卡 + filter UI(client JS)。"""
    decisions = extract_all()
    memory_path = resolve_memory_path()
    # 读 note 持久化
    conn = open_db(DB_PATH)
    try:
        note_repo = DecisionNoteRepo(conn)
        note_lookup = note_repo.get_all()
    finally:
        conn.close()
    # 加载 main_dims for filter chip(layer 列)
    main_dims, _ = load_dimensions(CONFIG_DIR / "dimensions.yaml")
    return templates.TemplateResponse(
        request,
        "decisions.html",
        {
            "today": _today_label(),
            "decisions": decisions,
            "note_lookup": note_lookup,
            "main_dims": main_dims,
            "active_view": "decisions",
            "memory_path_warning": memory_path is None,
        },
    )
```

加到 routes:

```python
app = Starlette(
    routes=[
        Route("/", index),
        Route("/healthz", healthz),
        Route("/decisions", decisions_view),
        Route("/capability/{cap_id}/edit", edit_capability),
        Route("/capability/{cap_id}/override", post_override, methods=["POST"]),
        Route("/refresh", post_refresh, methods=["POST"]),
        Mount("/static", StaticFiles(directory=str(DASHBOARD_ROOT / "static")), name="static"),
    ],
)
```

- [ ] **Step 4: 加测试 `dashboard/tests/server/test_decisions_endpoint.py`**

```python
# dashboard/tests/server/test_decisions_endpoint.py
from starlette.testclient import TestClient

from dashboard.server import app


def test_get_decisions_renders_cards() -> None:
    """/decisions 渲染决策卡 + filter UI + active_view='decisions'。"""
    with TestClient(app) as client:
        r = client.get("/decisions")
        assert r.status_code == 200
        body = r.text
        assert 'class="decision-card"' in body
        # 至少 1 决策(spec 总有,memory 不一定)
        # 三 tab 中决策 active
        assert 'class="active"' in body
        assert '决策</a>' in body
```

- [ ] **Step 5: 跑 tests + mypy**

```bash
unset all_proxy https_proxy http_proxy && uv run --project backend pytest dashboard/tests/server/ -v
unset all_proxy https_proxy http_proxy && uv run --project backend mypy dashboard/
```

预期:M2 11 + Task 6 1 = 12 server tests PASS;mypy clean。

- [ ] **Step 6: smoke**

```bash
unset all_proxy https_proxy http_proxy && uv run --project backend python -m dashboard.server &
SERVER_PID=$!
sleep 2
echo "--- /decisions ---"
curl -s http://localhost:8910/decisions | grep -oE 'class="decision-card"' | wc -l
echo "--- 决策 tab active ---"
curl -s http://localhost:8910/decisions | grep -oE '决策</a>'
kill $SERVER_PID 2>/dev/null
sleep 1
lsof -ti tcp:8910 | xargs -r kill -9 2>/dev/null || true
```

预期:decision-card count 12-50(取决于 memory_path 是否 detect 到);决策 tab 渲染。

- [ ] **Step 7: 提交**

```bash
git add dashboard/templates/decisions.html dashboard/templates/_decision_card.html dashboard/server.py dashboard/tests/server/test_decisions_endpoint.py
git commit -m "feat(dashboard): GET /decisions + decisions.html + _decision_card.html (note form 待 Task 8 接通)"
```

---

## Task 7: _decision_filter.html + decisions-filter.js + filter CSS

**Files:**
- Create: `dashboard/templates/_decision_filter.html`
- Create: `dashboard/static/decisions-filter.js`
- Modify: `dashboard/templates/decisions.html` — 解开 _decision_filter include 注释
- Modify: `dashboard/static/style.css` — 加 .filter-chip / .filter-keyword / .decision-card 等

- [ ] **Step 1: 写 `dashboard/templates/_decision_filter.html`**

```html
<section class="decision-filter">
  <div class="filter-group filter-layer-group">
    {% for dim in main_dims %}
      <button class="filter-chip filter-layer-chip" data-value="{{ dim.id }}">
        {{ dim.number }} {{ dim.name_cn }}
      </button>
    {% endfor %}
    <button class="filter-chip filter-layer-chip" data-value="META">META</button>
  </div>
  <div class="filter-group filter-state-group">
    <button class="filter-chip filter-state-chip" data-value="active">active</button>
    <button class="filter-chip filter-state-chip" data-value="deprecated">deprecated</button>
  </div>
  <div class="filter-group filter-keyword-group">
    <input class="filter-keyword" type="text" placeholder="关键字搜索...">
  </div>
</section>
```

- [ ] **Step 2: 写 `dashboard/static/decisions-filter.js`**

```javascript
// dashboard/static/decisions-filter.js
// Client-side filter for /decisions:layer chip + state chip + keyword AND 关系
(function () {
  const cards = document.querySelectorAll(".decision-card");
  const layerChips = document.querySelectorAll(".filter-layer-chip");
  const stateChips = document.querySelectorAll(".filter-state-chip");
  const keywordInput = document.querySelector(".filter-keyword");

  function applyFilter() {
    const activeLayer = new Set(
      Array.from(layerChips)
        .filter(c => c.classList.contains("active"))
        .map(c => c.dataset.value)
    );
    const activeState = new Set(
      Array.from(stateChips)
        .filter(c => c.classList.contains("active"))
        .map(c => c.dataset.value)
    );
    const keyword = (keywordInput?.value || "").toLowerCase();

    cards.forEach(card => {
      const layer = card.dataset.layer;
      const state = card.dataset.state;
      const text = card.dataset.text;
      const layerOK = activeLayer.size === 0 || activeLayer.has(layer);
      const stateOK = activeState.size === 0 || activeState.has(state);
      const kwOK = !keyword || text.includes(keyword);
      card.style.display = layerOK && stateOK && kwOK ? "" : "none";
    });
  }

  layerChips.forEach(c => c.addEventListener("click", () => {
    c.classList.toggle("active");
    applyFilter();
  }));
  stateChips.forEach(c => c.addEventListener("click", () => {
    c.classList.toggle("active");
    applyFilter();
  }));
  keywordInput?.addEventListener("input", applyFilter);
})();
```

- [ ] **Step 3: 解开 `dashboard/templates/decisions.html` filter include 注释**

把 `{# Task 7 will add: ... #}` 注释行换成实际 include + 加 script tag:

```html
{% extends "base.html" %}
{% block content %}
  {% include "_hero.html" %}
  {% include "_view_toggle.html" %}
  {% if memory_path_warning %}
    <p class="warning-banner">⚠ memory 路径未找到,仅显示 spec 决策 ~{{ decisions|length }} 项</p>
  {% endif %}
  {% include "_decision_filter.html" %}
  <section class="decisions-list">
    {% for d in decisions %}
      {% include "_decision_card.html" %}
    {% endfor %}
  </section>
  <script src="/static/decisions-filter.js" defer></script>
{% endblock %}
```

注:`<script defer>` 让 JS 在 DOM ready 后跑(避免 querySelector 找不到元素)。

- [ ] **Step 4: 改 `dashboard/static/style.css` — 加 decision + filter CSS**

末尾追加:

```css
/* Decision card */
.decision-card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 12px 16px;
  margin-bottom: 8px;
}
.decision-head {
  display: flex;
  gap: 12px;
  font-family: ui-monospace, monospace;
  font-size: 11px;
  color: var(--muted);
  margin-bottom: 4px;
}
.decision-date { color: var(--muted); }
.decision-version { color: var(--lit-fg); }
.decision-layer { color: var(--wip-fg); font-weight: 600; }
.decision-title {
  margin: 4px 0 6px;
  font-size: 14px;
}
.decision-why {
  font-size: 13px;
  color: var(--fg);
  margin: 4px 0;
}
.decision-refs {
  font-size: 11px;
  color: var(--muted);
}
.decision-refs code {
  background: var(--bg);
  padding: 1px 4px;
  border-radius: 2px;
  margin-right: 4px;
  font-size: 10px;
}
.decision-note {
  display: flex;
  gap: 4px;
  margin-top: 6px;
}
.decision-note input {
  flex: 1;
  background: var(--bg);
  color: var(--fg);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 4px 8px;
  font-size: 12px;
}
.decision-note button {
  background: var(--lit-bg);
  color: var(--lit-fg);
  border: 1px solid #166534;
  border-radius: 3px;
  padding: 4px 12px;
  font-size: 11px;
  cursor: pointer;
}

/* Filter UI */
.decision-filter {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 16px;
  padding: 12px;
  background: var(--panel);
  border-radius: 6px;
}
.filter-group {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.filter-chip {
  background: transparent;
  color: var(--muted);
  border: 1px dashed var(--todo-border);
  border-radius: 3px;
  padding: 4px 10px;
  font-size: 11px;
  font-family: ui-monospace, monospace;
  cursor: pointer;
}
.filter-chip.active {
  background: var(--lit-bg);
  color: var(--lit-fg);
  border: 1px solid #166534;
}
.filter-keyword {
  flex: 1;
  background: var(--bg);
  color: var(--fg);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 6px 10px;
  font-size: 12px;
  min-width: 200px;
}

/* Warning banner */
.warning-banner {
  background: var(--wip-bg);
  color: var(--wip-fg);
  padding: 8px 12px;
  border-radius: 4px;
  margin-bottom: 12px;
  font-size: 12px;
}
```

- [ ] **Step 5: 跑 tests + smoke**

```bash
unset all_proxy https_proxy http_proxy && uv run --project backend pytest dashboard/tests/server/ -v
```

预期:server tests 仍 12 PASS。

```bash
unset all_proxy https_proxy http_proxy && uv run --project backend python -m dashboard.server &
SERVER_PID=$!
sleep 2
echo "--- filter chip 数 ---"
curl -s http://localhost:8910/decisions | grep -oE 'class="filter-chip filter-layer-chip"' | wc -l
echo "--- filter chip state ---"
curl -s http://localhost:8910/decisions | grep -oE 'class="filter-chip filter-state-chip"' | wc -l
echo "--- keyword input ---"
curl -s http://localhost:8910/decisions | grep -oE 'class="filter-keyword"'
echo "--- JS file ---"
curl -sI http://localhost:8910/static/decisions-filter.js | head -1
kill $SERVER_PID 2>/dev/null
sleep 1
lsof -ti tcp:8910 | xargs -r kill -9 2>/dev/null || true
```

预期:9 layer chip(8 dim + META),2 state chip,1 keyword input,JS file 200。

- [ ] **Step 6: 提交**

```bash
git add dashboard/templates/_decision_filter.html dashboard/static/decisions-filter.js dashboard/templates/decisions.html dashboard/static/style.css
git commit -m "feat(dashboard): _decision_filter.html + decisions-filter.js (client-side layer/state/keyword filter)"
```

---

## Task 8: POST/DELETE /decisions/{id}/note + 2 测试

**Files:**
- Modify: `dashboard/server.py` — 加 POST + DELETE handlers
- Modify: `dashboard/tests/server/test_decisions_endpoint.py` — +2 测试

- [ ] **Step 1: 改 `dashboard/server.py` 加 2 routes**

加 handler:

```python
async def post_decision_note(request: Request) -> HTMLResponse:
    """upsert decision note + 返回新 form HTML(htmx swap)。"""
    decision_id = request.path_params["decision_id"]
    form = await request.form()
    note_raw = form.get("note", "")
    if not isinstance(note_raw, str):
        return HTMLResponse("invalid form", status_code=400)
    conn = open_db(DB_PATH)
    try:
        DecisionNoteRepo(conn).upsert(decision_id, note_raw)
    finally:
        conn.close()
    # 返回新 form HTML(同 _decision_card.html 内的 form 部分)
    template_str = """<form class="decision-note"
        hx-post="/decisions/{{ decision_id }}/note"
        hx-target="this"
        hx-swap="outerHTML">
  <input name="note" value="{{ note }}" placeholder="(用户备注)">
  <button type="submit">保存</button>
</form>"""
    from jinja2 import Template
    html = Template(template_str).render(decision_id=decision_id, note=note_raw)
    return HTMLResponse(html)


async def delete_decision_note(request: Request) -> HTMLResponse:
    """clear decision note + 返回空 form HTML。"""
    decision_id = request.path_params["decision_id"]
    conn = open_db(DB_PATH)
    try:
        DecisionNoteRepo(conn).delete(decision_id)
    finally:
        conn.close()
    template_str = """<form class="decision-note"
        hx-post="/decisions/{{ decision_id }}/note"
        hx-target="this"
        hx-swap="outerHTML">
  <input name="note" value="" placeholder="(用户备注)">
  <button type="submit">保存</button>
</form>"""
    from jinja2 import Template
    html = Template(template_str).render(decision_id=decision_id)
    return HTMLResponse(html)
```

加到 routes:

```python
app = Starlette(
    routes=[
        Route("/", index),
        Route("/healthz", healthz),
        Route("/decisions", decisions_view),
        Route("/decisions/{decision_id}/note", post_decision_note, methods=["POST"]),
        Route("/decisions/{decision_id}/note", delete_decision_note, methods=["DELETE"]),
        Route("/capability/{cap_id}/edit", edit_capability),
        Route("/capability/{cap_id}/override", post_override, methods=["POST"]),
        Route("/refresh", post_refresh, methods=["POST"]),
        Mount("/static", StaticFiles(directory=str(DASHBOARD_ROOT / "static")), name="static"),
    ],
)
```

- [ ] **Step 2: 加 2 测试**

```python
def test_post_decision_note() -> None:
    """POST note → 写 decision_note 表 + 返回新 form HTML。"""
    with TestClient(app) as client:
        r = client.post(
            "/decisions/abc123def456/note",
            data={"note": "测试 note"},
        )
        assert r.status_code == 200
        body = r.text
        assert '<form class="decision-note"' in body
        assert 'value="测试 note"' in body
        # verify persistence:再 GET / 看 note 在
        # 由 conftest fixture 隔离 DB,不污染


def test_delete_decision_note() -> None:
    """DELETE note → 清表 + 返回空 form HTML。"""
    with TestClient(app) as client:
        # seed
        client.post("/decisions/abc123def456/note", data={"note": "to be deleted"})
        # delete
        r = client.delete("/decisions/abc123def456/note")
        assert r.status_code == 200
        body = r.text
        assert '<form class="decision-note"' in body
        assert 'value=""' in body  # cleared
```

- [ ] **Step 3: 跑 tests + mypy**

```bash
unset all_proxy https_proxy http_proxy && uv run --project backend pytest dashboard/tests/ -v
unset all_proxy https_proxy http_proxy && uv run --project backend mypy dashboard/
```

预期:M2 47 + Task 1 改造 0 + Task 2 4 + Task 4 7 + Task 6 1 + Task 8 2 = 61 PASS;mypy clean。

- [ ] **Step 4: E2E htmx swap smoke**

```bash
unset all_proxy https_proxy http_proxy && uv run --project backend python -m dashboard.server &
SERVER_PID=$!
sleep 2

# get a real decision id
DECISION_ID=$(curl -s http://localhost:8910/decisions | grep -oE 'data-text="[^"]*" id="dec-[a-f0-9]{12}"' | head -1 | grep -oE '[a-f0-9]{12}')
# 或 simpler: 用 dummy 12-char id 测 endpoint
DECISION_ID="abc123def456"

echo "--- POST note ---"
curl -sX POST -d "note=测试 dogfood" "http://localhost:8910/decisions/${DECISION_ID}/note"
echo

echo "--- DELETE note ---"
curl -sX DELETE "http://localhost:8910/decisions/${DECISION_ID}/note"
echo

kill $SERVER_PID 2>/dev/null
sleep 1
lsof -ti tcp:8910 | xargs -r kill -9 2>/dev/null || true
```

预期:POST 返回 form HTML 含 `value="测试 dogfood"`;DELETE 返回 form HTML 含 `value=""`。

- [ ] **Step 5: 提交**

```bash
git add dashboard/server.py dashboard/tests/server/test_decisions_endpoint.py
git commit -m "feat(dashboard): POST + DELETE /decisions/{id}/note + htmx swap (note 持久化)"
```

---

## Task 9: README sync + ship verify

**Files:**
- Modify: `README.md` — 顶部版本备注 + 项目结构 + 命令表
- Optional: lightweight tag

- [ ] **Step 1: 改 README 顶部版本备注**

把现有 "Harness Board M2" 行改:

```diff
- **当前版本**:v0.8.5(...)+ Harness Board M2(D/B 视图 toggle + 编辑模式 + App Shell 第 9 行)
+ **当前版本**:v0.8.5(...)+ Harness Board M3(D/B/决策 三 tab + decision_extractor + filter UI + note 持久化)
```

- [ ] **Step 2: 改 README 项目结构 dashboard/ 节**

更新 `templates/` 行 + `derive/` 行 + `state/` 行 + `tests/` 行,加 M3 件:

```diff
│   ├── derive/                  # path_router / capability_resolver / snapshot_builder / app_shell_stat / decision_extractor(纯函数)
│   ├── state/                   # sqlite + SnapshotRepo + OverrideRepo + DecisionNoteRepo(全量替换 + upsert/DELETE × 2)
│   ├── templates/               # base / main / decisions / _hero / _d_view / _b_view / _view_toggle / _app_shell / _capability_chip / _edit_select / _decision_card / _decision_filter
│   ├── static/{style.css,htmx.min.js,decisions-filter.js}
│   └── tests/                   # 61 测试,mypy strict 清洁(含 test files)
```

- [ ] **Step 3: 跑全部 dashboard 测试 verify**

```bash
unset all_proxy https_proxy http_proxy && uv run --project backend pytest dashboard/tests/ -v
unset all_proxy https_proxy http_proxy && uv run --project backend mypy dashboard/
```

预期:~61 PASS;mypy strict clean(含 test files,M3 follow-up c 完成的标志)。

- [ ] **Step 4: E2E ship checklist verify(spec § 15)**

```bash
rm -f backend/data/board.db
unset all_proxy https_proxy http_proxy && uv run --project backend python -m dashboard.server &
SERVER_PID=$!
sleep 2

echo "--- 1. healthz ---"
curl -s http://localhost:8910/healthz
echo

echo "--- 2. 三 tab nav 渲染 ---"
curl -s http://localhost:8910/ | grep -oE 'D 维度|B Kanban|决策'

echo "--- 3. /decisions 列表 ~ 30-50 项 ---"
curl -s http://localhost:8910/decisions | grep -oE 'class="decision-card"' | wc -l

echo "--- 4. 决策 tab active class ---"
curl -s http://localhost:8910/decisions | grep -oE 'class="active">决策'

echo "--- 5. filter chip render ---"
curl -s http://localhost:8910/decisions | grep -oE 'class="filter-chip filter-layer-chip"' | wc -l
curl -s http://localhost:8910/decisions | grep -oE 'class="filter-chip filter-state-chip"' | wc -l
curl -s http://localhost:8910/decisions | grep -oE 'class="filter-keyword"'

echo "--- 6. JS file 200 ---"
curl -sI http://localhost:8910/static/decisions-filter.js | head -1

echo "--- 7. POST note 持久化 ---"
curl -sX POST -d "note=ship verify" "http://localhost:8910/decisions/abc123def456/note"
echo

echo "--- 8. memory_path warning(若 None)---"
curl -s http://localhost:8910/decisions | grep -c "warning-banner"

echo "--- 9. M2 D/B view 仍工作 ---"
curl -s http://localhost:8910/ | grep -oE 'class="layer-card"' | wc -l
curl -s "http://localhost:8910/?view=b" | grep -oE 'class="kanban"' | head -1

echo "--- 10. backend/data/board.db 不被 test 污染(verify 跑 pytest 后 mtime)---"
stat -f "%m" backend/data/board.db || echo "(no DB)"

kill $SERVER_PID 2>/dev/null
sleep 1
lsof -ti tcp:8910 | xargs -r kill -9 2>/dev/null || true
```

预期:
- 三 tab 名都显示
- decision-card count 12-50
- 决策 tab 含 active class
- 9 layer chip + 2 state chip + 1 keyword input + JS 200
- POST note 返回 form HTML
- M2 D/B 仍工作(8 layer-card / kanban)
- pytest 跑后 DB mtime 不变(fixture 隔离 work)

- [ ] **Step 5: 提交 + tag M3 ship**

```bash
git add README.md
git commit -m "docs(readme): sync Harness Board M3 — D/B/决策 三 tab + decision_extractor + note 持久化"

# Optional 轻量 tag
git tag -a harness-board-m3 -m "Harness Board M3: /decisions + decision_extractor + filter UI + note 持久化 + test infra fixture"
```

- [ ] **Step 6: 验收**

ship 标准 checklist(spec § 15):

- [ ] `make board` 切 D/B/决策 三 tab,active class 正确高亮
- [ ] `/decisions` page 显示 ~30-50 项决策(memory + spec 合并)+ time-desc 排序
- [ ] layer chip + state chip 多选 filter 工作(client-side 显隐)
- [ ] keyword input 实时 filter
- [ ] 决策卡 note 输入框 + 保存按钮工作,持久化关浏览器再开 note 仍在
- [ ] Server tests 用 conftest.py fixture(`backend/data/board.db` 不被污染)
- [ ] `mypy strict dashboard/`(含 test files)全 PASS;~61 dashboard tests PASS

---

## Self-Review Checklist

**1. Spec 覆盖**:
- ✓ § 2 scope = B(§ 9.1 三件 + (b) test fixture + (c) M1 mypy 清债):全 task 1-9 覆盖,Task 1 prelude 做 (b)+(c)
- ✓ § 3 decision_extractor 数据来源 + layer derive:Task 4
- ✓ § 4 decision_note schema:Task 2
- ✓ § 5 filter 数据流(server render + client JS):Task 6 + 7
- ✓ § 6 filter UI(chip + keyword input):Task 7
- ✓ § 7 nav entry(三 tab + active_view):Task 5
- ✓ § 8 module(单文件):Task 4
- ✓ § 9 memory_path resolve:Task 4(resolve_memory_path 函数)

**2. Placeholder 扫描**:无 TBD/TODO/FIXME(注释里的 `Task 7 will add` 在 Task 7 解开,不算 placeholder)。

**3. 类型一致性**:
- `Decision` dataclass(Task 3)+ `compute_decision_id` 引用一致 ✓
- `DecisionNoteRepo.get_all()` 返 `dict[str, str]`,server 端 `note_lookup.get(d.id, '')` 形状一致 ✓
- `extract_all()` 返 `list[Decision]`,server 直接喂 template ✓
- `_view_toggle.html` 接 `active_view: "d"|"b"|"decisions"`,server 在 index / decisions_view 都传 ✓

**4. 风险点**:

- **Risk 1**(Task 4):memory_path auto-detect 公式可能错。Step 5 实跑 `extract_all()` 看 memory_path log,不工作可设 env var。如果 macOS 路径 escape 规则跟 Claude 不一致,fix 后回归 Task 4 step 6。
- **Risk 2**(Task 4):layer 关键字归类命中率 < 70% 会造成 META 过多。Step 5 跑 layer 分布,< 70% 时调 dimensions.yaml.keywords(fix layer 标 plan,加 keyword 再跑)。
- **Risk 3**(Task 8):POST/DELETE handler inline jinja Template — 跟 _decision_card.html 内 form HTML 重复。M3.x 重构成 partial render。
- **Risk 4**(Task 1):autouse fixture 范围只 server/。如果 fixture 误生效到 derive/state tests,monkeypatch.setattr 会找不到 server 模块?不会 — Python 不导入不报错,只是无效操作。
- **Risk 5**(Task 5):`git mv` 跨 commit 可能 git 看作 add+delete 而非 rename。verify `git log --follow dashboard/templates/_view_toggle.html` 是否串到 _d_b_toggle.html。
- **Risk 6**(Task 4):specs_dir 内的 `## §` 段如果有跨行 title(eg `## § 2 决策一: \n  Constrained ...`)正则会失败。当前 spec 全部单行,M3 不处理多行 title。

**5. memory 教训应用**:
- `feedback_path_resolution_in_plans` ✓:`PROJECT_ROOT` / `MEMORY_PATH` 都用 absolute 计算
- `feedback_python_m_path_dual_context` ✓:不变,`uv run --project backend python -m dashboard.server`
- `feedback_dev_tool_version_pin_alignment` ✓:无新依赖
- `feedback_type_ignore_with_typed_signature` ✓:零 type:ignore
- `feedback_fix_commit_layer_marker` ✓:M3 plan 内 fix 类 commit 提示加 marker(本 plan 暂无 fix 类)
- `feedback_estimate_in_claude_code_walltime` ✓:1.3 天 wall time

---

## 后续(超 M3 范围)

M3 ship 后,根据 dogfood 反馈决定 M3.x 优先级:
- M3.1:layer 关键字归类命中率不够 → 加 dimensions.yaml.keywords / 升级 frontmatter convention
- M3.2:URL filter state 同步(`?layer=04,06`)
- M3.3:`state: deprecated` 自动 detect(扫"砍"/"已废弃"关键字)
- M3.4:决策来自 git log(commit message 提取)— 可能成 M4 主题

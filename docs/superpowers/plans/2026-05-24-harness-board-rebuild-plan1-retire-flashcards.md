# Harness Board 框架重做 — Plan 1:flashcards 整条退役

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 flashcards(SM-2 闪卡复习子系统)从看板代码库整条移除 — 2 张 sqlite 表、2 个 derive 模块、4 条 route handler、3 个模板、1 个 js、6 个测试文件,以及 nav-rail 入口。本 plan ship 后:flashcards 相关 URL 全 404,其他页面零 regression。

**Architecture:** 严格"数据层 + dead-code 清理"动作,不动 DeepCard schema、不动 UI 样式、不动模块页。退役顺序:先 DROP 表 → 删 repo → 删 handler/route → 删 derive 模块 → 删模板/js → 删测试 → 清 nav 入口。每步原子可回滚。

**Tech Stack:** Python 3.11 / Starlette / sqlite3 / pytest / uv / pre-commit (ruff + mypy + commit-msg layer validator)。

---

## File Structure(本 plan 涉及的所有文件)

```
修改:
  dashboard/state/db.py                            (删 flashcards/prefill_log schema)
  dashboard/state/repositories.py                  (删 FlashcardRepo / PrefillRepo)
  dashboard/server.py                              (删 4 handler + 4 Route + import)
  dashboard/templates/_board_nav.html              (删复习入口)
  dashboard/templates/base.html                    (删 flashcards.js 引用)

删除文件:
  dashboard/derive/flashcard_generator.py
  dashboard/derive/srs.py
  dashboard/templates/flashcards.html
  dashboard/templates/flashcards_stats.html
  dashboard/templates/_flashcard_review.html
  dashboard/static/flashcards.js
  dashboard/tests/unit/test_flashcard_generator.py
  dashboard/tests/unit/test_srs.py
  dashboard/tests/integration/test_flashcard_repo.py
  dashboard/tests/integration/test_flashcards_endpoint.py
  dashboard/tests/integration/test_flashcards_stats_endpoint.py
  dashboard/tests/integration/test_flashcard_regenerate_hook.py

新增:
  dashboard/scripts/drop_flashcards_tables.py      (一次性 DROP 脚本)
  dashboard/tests/unit/test_drop_flashcards.py     (脚本幂等测试)
```

---

## Task 0:准备 — backup + 摸底 import 链

**Files:**
- None modified

- [ ] **Step 0.1:验证仓库 clean(在 worktree 内)**

Run:
```bash
git status --short
```
Expected: empty(无 unstaged 改动)。如果有改动,先 stash 或 commit。

- [ ] **Step 0.2:backup sqlite db(若存在)**

Run:
```bash
test -f dashboard/data/harness_board.db && cp dashboard/data/harness_board.db dashboard/data/harness_board.db.bak-pre-plan1 || echo "no db file yet — fresh start"
ls dashboard/data/ 2>/dev/null || echo "no data dir"
```
Expected: 看到 `.bak-pre-plan1` 文件 OR 提示「fresh start」。

- [ ] **Step 0.3:grep flashcards 全引用面(确认 Plan 1 删除清单覆盖完整)**

Run:
```bash
grep -rnE "flashcard|FlashcardRepo|PrefillRepo|SrsState|TemplateKind|srs_state|prefill_log" dashboard/ --include="*.py" --include="*.html" --include="*.js" --include="*.yaml" 2>&1 | sort -u
```
Expected: 仅看到 File Structure 节里列出的文件(若有遗漏,加入 plan 的删除清单或修改清单)。**必须 0 漏网**,否则 Plan 1 ship 后会有 import error。

- [ ] **Step 0.4:跑 baseline 测试(留 baseline 数字给后续对比)**

Run:
```bash
uv run pytest dashboard/tests/ -q 2>&1 | tail -5
```
Expected: 记下 `N passed, M failed` 数字。本 plan ship 后,passed 数应该减少(被删的测试)但不能新增 failed。

---

## Task 1:删 sqlite schema(2 张表 + 2 个索引)

**Files:**
- Modify: `dashboard/state/db.py`

- [ ] **Step 1.1:打开 dashboard/state/db.py,删除 flashcards 表 + 索引 + prefill_log 表**

将下面这段(行号约 36-58)**整段删除**:

```python
CREATE TABLE IF NOT EXISTS flashcards (
  id TEXT PRIMARY KEY,             -- f"{cap_id}::{template_kind}"
  cap_id TEXT NOT NULL,
  template_kind TEXT NOT NULL,
  question TEXT NOT NULL,
  answer TEXT NOT NULL,
  srs_state TEXT NOT NULL,         -- JSON
  created_at TEXT NOT NULL,
  last_reviewed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_flashcards_cap_id ON flashcards(cap_id);
CREATE INDEX IF NOT EXISTS idx_flashcards_next_review
  ON flashcards(json_extract(srs_state, '$.next_review_at'));

CREATE TABLE IF NOT EXISTS prefill_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cap_id TEXT NOT NULL,
  field_name TEXT NOT NULL,
  status TEXT NOT NULL,            -- 'success' | 'rejected_quote' | 'llm_error' | 'skipped'
  detail TEXT,
  ran_at TEXT NOT NULL
);
```

剩下的 `SCHEMA` 字符串应该只含 `derived_snapshot / capability_override / decision_note / deep_cards` 4 个 CREATE TABLE。

- [ ] **Step 1.2:删 docstring 引用(line 1)**

把:
```python
"""sqlite schema + connection。M1 derived_snapshot;M2 加 capability_override;M3 加 decision_note。"""
```
改为(去掉历史 M 标记,跟新 spec 一致):
```python
"""sqlite schema + connection。
v2:derived_snapshot / capability_override / decision_note / deep_cards (4 表)。
(flashcards / prefill_log 已在 Plan 1 退役)"""
```

- [ ] **Step 1.3:Commit**

```bash
git add dashboard/state/db.py
git commit -m "refactor(harness-board): drop flashcards + prefill_log schema (Plan 1 step 1)"
```

---

## Task 2:写一次性 DROP 脚本 + 测试(让现有 db 也能升级)

**Files:**
- Create: `dashboard/scripts/__init__.py`(若不存在)
- Create: `dashboard/scripts/drop_flashcards_tables.py`
- Create: `dashboard/tests/unit/test_drop_flashcards.py`

> 为什么需要脚本:`db.py:open_db()` 用 `CREATE TABLE IF NOT EXISTS`,只新增不删。已存在的 sqlite 文件里 flashcards / prefill_log 表仍在,需要一次性 DROP。

- [ ] **Step 2.1:Write the failing test**

Create `dashboard/tests/unit/test_drop_flashcards.py`:

```python
"""Plan 1 — DROP flashcards / prefill_log 脚本幂等测试。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from dashboard.scripts.drop_flashcards_tables import drop_legacy_tables


@pytest.fixture
def db_with_legacy(tmp_path: Path) -> Path:
    """构造一个含 flashcards / prefill_log 的旧 db。"""
    db_path = tmp_path / "harness_board.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE flashcards (id TEXT PRIMARY KEY, cap_id TEXT);
        CREATE INDEX idx_flashcards_cap_id ON flashcards(cap_id);
        CREATE TABLE prefill_log (id INTEGER PRIMARY KEY, cap_id TEXT);
        CREATE TABLE deep_cards (cap_id TEXT PRIMARY KEY, payload TEXT);
        INSERT INTO flashcards VALUES ('f1', 'cap_a');
        INSERT INTO prefill_log VALUES (1, 'cap_a');
        INSERT INTO deep_cards VALUES ('cap_a', '{}');
        """
    )
    conn.commit()
    conn.close()
    return db_path


def _table_names(db_path: Path) -> set[str]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    conn.close()
    return {r[0] for r in rows}


def test_drop_removes_legacy_tables(db_with_legacy: Path) -> None:
    drop_legacy_tables(db_with_legacy)
    names = _table_names(db_with_legacy)
    assert "flashcards" not in names
    assert "prefill_log" not in names
    assert "deep_cards" in names  # 不动其他表


def test_drop_preserves_deep_cards_rows(db_with_legacy: Path) -> None:
    drop_legacy_tables(db_with_legacy)
    conn = sqlite3.connect(db_with_legacy)
    rows = conn.execute("SELECT cap_id FROM deep_cards").fetchall()
    conn.close()
    assert rows == [("cap_a",)]


def test_drop_idempotent(db_with_legacy: Path) -> None:
    """跑两遍不报错 — 第二遍发现表已不在,静默通过。"""
    drop_legacy_tables(db_with_legacy)
    drop_legacy_tables(db_with_legacy)  # 第二次:幂等
    names = _table_names(db_with_legacy)
    assert "flashcards" not in names


def test_drop_on_clean_db(tmp_path: Path) -> None:
    """从来没有这些表的新 db 也不报错。"""
    db_path = tmp_path / "clean.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("CREATE TABLE foo (x INTEGER);")
    conn.commit()
    conn.close()
    drop_legacy_tables(db_path)  # 不抛
    names = _table_names(db_path)
    assert names == {"foo"}
```

- [ ] **Step 2.2:Run test — 验证 FAIL**

Run:
```bash
uv run pytest dashboard/tests/unit/test_drop_flashcards.py -v 2>&1 | tail -15
```
Expected: 所有 4 个测试 ERROR with `ModuleNotFoundError: No module named 'dashboard.scripts'` 或类似。

- [ ] **Step 2.3:确保 dashboard/scripts/__init__.py 存在**

```bash
test -d dashboard/scripts || mkdir -p dashboard/scripts
test -f dashboard/scripts/__init__.py || touch dashboard/scripts/__init__.py
ls dashboard/scripts/
```
Expected: 看到 `__init__.py`。

- [ ] **Step 2.4:实现脚本**

Create `dashboard/scripts/drop_flashcards_tables.py`:

```python
"""一次性脚本:DROP flashcards / prefill_log 表(Plan 1 退役)。

Used by deploy / dev:
    python -m dashboard.scripts.drop_flashcards_tables [/path/to/db]
默认路径:dashboard/data/harness_board.db
"""

from __future__ import annotations

import logging
import sqlite3
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

LEGACY_TABLES = ("flashcards", "prefill_log")
LEGACY_INDEXES = ("idx_flashcards_cap_id", "idx_flashcards_next_review")


def drop_legacy_tables(db_path: Path) -> None:
    """幂等地 DROP flashcards / prefill_log 表与相关索引。

    - 表 / 索引若不存在,静默通过(`DROP TABLE IF EXISTS`)
    - 其他表不受影响
    """
    if not db_path.exists():
        logger.info("db not found at %s — skip", db_path)
        return
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            for idx in LEGACY_INDEXES:
                conn.execute(f"DROP INDEX IF EXISTS {idx}")
            for tbl in LEGACY_TABLES:
                conn.execute(f"DROP TABLE IF EXISTS {tbl}")
        logger.info("dropped legacy tables in %s", db_path)
    finally:
        conn.close()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(sys.argv) > 1:
        db_path = Path(sys.argv[1])
    else:
        db_path = Path(__file__).resolve().parents[1] / "data" / "harness_board.db"
    drop_legacy_tables(db_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2.5:Run test — 验证 PASS**

Run:
```bash
uv run pytest dashboard/tests/unit/test_drop_flashcards.py -v 2>&1 | tail -15
```
Expected: 4 passed.

- [ ] **Step 2.6:在本机已有 db 上跑一遍(若 backup 已建)**

Run:
```bash
test -f dashboard/data/harness_board.db && uv run python -m dashboard.scripts.drop_flashcards_tables || echo "no db — skip live drop"
# 验证表已删
test -f dashboard/data/harness_board.db && sqlite3 dashboard/data/harness_board.db ".tables" || true
```
Expected(若 db 存在): 输出表名不含 `flashcards` 和 `prefill_log`。

- [ ] **Step 2.7:Commit**

```bash
git add dashboard/scripts/__init__.py dashboard/scripts/drop_flashcards_tables.py dashboard/tests/unit/test_drop_flashcards.py
git commit -m "feat(harness-board): one-shot script to drop flashcards/prefill_log tables (Plan 1 step 2)"
```

---

## Task 3:删 FlashcardRepo / PrefillRepo

**Files:**
- Modify: `dashboard/state/repositories.py`

- [ ] **Step 3.1:定位两 repo 类边界**

Run:
```bash
grep -nE "^class (Flashcard|Prefill)" dashboard/state/repositories.py
```
Expected: 2 行,记下行号。

- [ ] **Step 3.2:删 FlashcardRepo 类**

打开 `dashboard/state/repositories.py`,找到 `class FlashcardRepo:` 开始到下一个顶层 `class` 之前的所有行,整段删除。

如果文件末尾就是 FlashcardRepo,删到 EOF。

- [ ] **Step 3.3:删 PrefillRepo / PrefillLogRepo 类(若有)**

同上,定位 `class PrefillRepo` 或 `class PrefillLogRepo`,整段删除。

- [ ] **Step 3.4:删 import 顶部的相关类型**

定位文件顶部 import:
```bash
grep -nE "Flashcard|SrsState|TemplateKind|PrefillLog|PrefillStatus" dashboard/state/repositories.py
```
所有 hit 行整行删除(包括 `from dashboard.derive.deep_card_types import Flashcard, SrsState, TemplateKind` 之类)。

注意:若该 import 同时 import 了**仍在使用**的类型(如 `DeepCard`),只删 Flashcard / SrsState / TemplateKind / PrefillLog / PrefillStatus 这些 token,保留 DeepCard。

- [ ] **Step 3.5:运行 repositories 测试,验证未坏其他 repo**

Run:
```bash
uv run pytest dashboard/tests/state/test_repositories.py -v 2>&1 | tail -10
```
Expected: 仅 FlashcardRepo / PrefillRepo 相关测试 ERROR / FAIL(因为类已删,但这些测试还存在 — 在 Task 6 一起删)。其他 SnapshotRepo / OverrideRepo / DecisionNoteRepo / DeepCardRepo 测试全 PASS。

- [ ] **Step 3.6:Commit**

```bash
git add dashboard/state/repositories.py
git commit -m "refactor(harness-board): remove FlashcardRepo + PrefillRepo (Plan 1 step 3)"
```

---

## Task 4:删 server.py 的 4 个 flashcards handler + 4 条 route + import

**Files:**
- Modify: `dashboard/server.py`

- [ ] **Step 4.1:定位 4 个 handler**

Run:
```bash
grep -nE "^async def (flashcards_today|flashcards_stats|flashcards_stats_json|post_flashcard_review)" dashboard/server.py
```
Expected: 4 行,记下行号。

- [ ] **Step 4.2:逐个删 handler**

打开 `dashboard/server.py`,找到 4 个 `async def flashcards_*` 或 `async def post_flashcard_review` 函数,从函数签名删到下一个顶层 `async def` 或 `def` 之前。

- [ ] **Step 4.3:删 4 条 Route 定义**

定位 routes block(约行 1020-1056),删除:
```python
        Route("/flashcards/today", flashcards_today),
        Route("/flashcards/stats", flashcards_stats),
        Route("/api/flashcards/stats.json", flashcards_stats_json),
        Route(
            "/flashcards/{flashcard_id:path}/review",
            post_flashcard_review,
            methods=["POST"],
        ),
```

- [ ] **Step 4.4:删 import 头部**

Run:
```bash
grep -nE "FlashcardRepo|flashcard_generator|srs|Flashcard|SrsState|TemplateKind" dashboard/server.py
```
所有 hit 整行删除(如果是 `from X import A, B, C`,只删被退役的 token,保留其他)。

- [ ] **Step 4.5:删 lifespan / startup 中可能引用 flashcards 的逻辑**

Run:
```bash
grep -nE "flashcard|FlashcardRepo|generate_flashcards" dashboard/server.py
```
Expected: **0 hit**。若有残留(可能在 `lifespan` async context 里的 seed 调用),整行删除。

- [ ] **Step 4.6:跑 server import 烟雾测试**

Run:
```bash
uv run python -c "from dashboard.server import app; print('ok'); print([r.path for r in app.routes if hasattr(r, 'path')])"
```
Expected: 输出 `ok` + route 列表,**列表中不应有 `/flashcards/*`**。若 ImportError,回到 Step 4.4 找漏。

- [ ] **Step 4.7:Commit**

```bash
git add dashboard/server.py
git commit -m "refactor(harness-board): remove flashcards routes + handlers from server (Plan 1 step 4)"
```

---

## Task 5:删 derive 模块 flashcard_generator + srs

**Files:**
- Delete: `dashboard/derive/flashcard_generator.py`
- Delete: `dashboard/derive/srs.py`

- [ ] **Step 5.1:确认无外部引用**

Run:
```bash
grep -rnE "from dashboard\.derive\.(flashcard_generator|srs)|import.*flashcard_generator|import.*srs" dashboard/ --include="*.py" | grep -v __pycache__
```
Expected: **0 hit**(若有,先回 Task 3/4 清掉)。

- [ ] **Step 5.2:删两文件**

Run:
```bash
git rm dashboard/derive/flashcard_generator.py dashboard/derive/srs.py
```

- [ ] **Step 5.3:删 derive/__init__.py 中的 re-export(若有)**

Run:
```bash
grep -nE "flashcard_generator|srs" dashboard/derive/__init__.py 2>/dev/null
```
Expected: 0 hit(empty file)。若有,整行删。

- [ ] **Step 5.4:删 derive/deep_card_types.py 中 flashcards 相关类型**

Run:
```bash
grep -nE "^class (Flashcard|SrsState|TemplateKind)|^SrsState =|^TemplateKind =" dashboard/derive/deep_card_types.py
```
对每个 hit:整 class 块或 type alias 删除。
保留 `DeepCard` 等仍在使用的类型。

- [ ] **Step 5.5:验证 derive 模块 import 完整**

Run:
```bash
uv run python -c "from dashboard.derive.deep_card_types import DeepCard; print('DeepCard ok')"
uv run python -c "import dashboard.derive.snapshot_builder; print('snapshot_builder ok')"
uv run python -c "import dashboard.derive.refresh_pipeline; print('refresh_pipeline ok')"
```
Expected: 3 个 "ok"。

- [ ] **Step 5.6:Commit**

```bash
git add dashboard/derive/__init__.py dashboard/derive/deep_card_types.py
git commit -m "refactor(harness-board): remove flashcard_generator + srs derive modules (Plan 1 step 5)"
```

---

## Task 6:删 flashcards 测试文件

**Files:**
- Delete: 6 个测试文件

- [ ] **Step 6.1:批量删除**

Run:
```bash
git rm dashboard/tests/unit/test_flashcard_generator.py \
       dashboard/tests/unit/test_srs.py \
       dashboard/tests/integration/test_flashcard_repo.py \
       dashboard/tests/integration/test_flashcards_endpoint.py \
       dashboard/tests/integration/test_flashcards_stats_endpoint.py \
       dashboard/tests/integration/test_flashcard_regenerate_hook.py
```

- [ ] **Step 6.2:跑全测试套件**

Run:
```bash
uv run pytest dashboard/tests/ -q 2>&1 | tail -10
```
Expected:
- 0 ERROR(无 ImportError / ModuleNotFoundError)
- 0 NEW failure(只允许 pass 数下降 — 因为测试被删)
- 与 Task 0.4 的 baseline 对比:passed 减少约 ~30-60(被删 6 个测试文件的测试数),0 failed 增加

如果有 ImportError,grep 残留:
```bash
grep -rn "flashcard\|FlashcardRepo\|srs_state\|TemplateKind" dashboard/tests/ --include="*.py" | grep -v __pycache__
```
逐个清理。

- [ ] **Step 6.3:Commit**

```bash
git commit -m "test(harness-board): remove flashcards test files (Plan 1 step 6)"
```

---

## Task 7:删模板 + 静态文件 + nav 入口

**Files:**
- Delete: `dashboard/templates/flashcards.html`
- Delete: `dashboard/templates/flashcards_stats.html`
- Delete: `dashboard/templates/_flashcard_review.html`
- Delete: `dashboard/static/flashcards.js`
- Modify: `dashboard/templates/_board_nav.html`
- Modify: `dashboard/templates/base.html`

- [ ] **Step 7.1:批量删模板与 js**

Run:
```bash
git rm dashboard/templates/flashcards.html \
       dashboard/templates/flashcards_stats.html \
       dashboard/templates/_flashcard_review.html \
       dashboard/static/flashcards.js
```

- [ ] **Step 7.2:清 nav 复习入口**

打开 `dashboard/templates/_board_nav.html`,定位含 `flashcards` 的 `<a>` 标签或 nav-item,整块删除。

Run 验证:
```bash
grep -nE "flashcard|复习" dashboard/templates/_board_nav.html
```
Expected: 0 hit.

- [ ] **Step 7.3:清 base.html 的 flashcards.js script include**

Run:
```bash
grep -nE "flashcards\.js" dashboard/templates/base.html
```
Expected: 至多 1 hit(若 base 引入了)。整行删除。

最终 base.html 的 JS includes 应该只剩 htmx + toast + modal + refresh-panel。

- [ ] **Step 7.4:Commit**

```bash
git add dashboard/templates/_board_nav.html dashboard/templates/base.html
git commit -m "refactor(harness-board): remove flashcards templates + nav entry (Plan 1 step 7)"
```

---

## Task 8:端到端 smoke + 全套测试

**Files:**
- None

- [ ] **Step 8.1:跑全测试套件,确认 0 regression**

Run:
```bash
uv run pytest dashboard/tests/ -q 2>&1 | tail -5
```
Expected:
- `N passed, 0 failed`(N < baseline N0,因为 flashcards 测试被删)
- 0 error
- 0 warning(关于 deprecated import)

- [ ] **Step 8.2:跑 mypy(确认无残留 type import)**

Run:
```bash
uv run mypy dashboard/ 2>&1 | tail -10
```
Expected: `Success: no issues found` 或仅有跟 flashcards 完全无关的现有 issue(若有,比对 Task 0.4 之前的 baseline mypy 输出,确认没新增)。

- [ ] **Step 8.3:跑 ruff(确认无未使用 import)**

Run:
```bash
uv run ruff check dashboard/ 2>&1 | tail -10
```
Expected: `All checks passed!` 或仅有跟 flashcards 无关的现有 lint warning。

- [ ] **Step 8.4:启动 server,smoke /flashcards 应 404**

Run:
```bash
uv run python -m dashboard.server &
SERVER_PID=$!
sleep 2

curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8780/flashcards/today
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8780/flashcards/stats
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8780/api/flashcards/stats.json
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8780/

kill $SERVER_PID
```
Expected: 前三个 `404`, `/` 返回 `200`(D-view 仍能渲染 — Plan 1 不动主路径)。

> 注:server port 可能不是 8780。先用 `grep -nE "uvicorn|app_main|port" dashboard/server.py | head -5` 看实际启动端口。

- [ ] **Step 8.5:最终 grep 兜底 — 全仓库无 flashcards 残留**

Run:
```bash
grep -rnE "flashcard|FlashcardRepo|PrefillRepo|srs_state|TemplateKind|SrsState|prefill_log" \
  dashboard/ --include="*.py" --include="*.html" --include="*.js" 2>&1 | \
  grep -v __pycache__ | grep -v ".git/"
```
Expected: **0 hit**。若有,逐个清理。

- [ ] **Step 8.6:最终 commit(若有零碎改动)**

```bash
git status --short
# 若有 unstaged,审查后:
# git add <files>
# git commit -m "refactor(harness-board): final flashcards cleanup (Plan 1 step 8)"
```

---

## Task 9:写 Plan 1 ship 报告 + 更新 spec 状态

**Files:**
- Modify: `docs/superpowers/specs/2026-05-24-harness-board-framework-rebuild-design.md`(只加一行 ship 标记)

- [ ] **Step 9.1:在 spec 开头加 Plan 1 ship 标记**

打开 spec 文件,定位 §0 元信息表附近(状态 / 起草那一段),在 "状态" 行下方加:

```markdown
**Plan 1 ship**:2026-05-XX(flashcards 整条退役;DeepCard schema migration 留 Plan 2)
```

(日期用今天的实际日期,Plan 1 完成当日)

- [ ] **Step 9.2:Commit ship 标记**

```bash
git add docs/superpowers/specs/2026-05-24-harness-board-framework-rebuild-design.md
git commit -m "docs(harness-board): mark Plan 1 ship in spec — flashcards retired"
```

- [ ] **Step 9.3:推 worktree 回去 + 准备 PR(可选,subagent-driven 模式由编排者决定)**

若在 worktree 内,执行最终:
```bash
git log --oneline -10  # 看一下 Plan 1 的 9-10 个 commit
git diff main...HEAD --stat  # 看变更摘要
```

PR 描述模板:
```
## Plan 1 — flashcards 整条退役

实施:docs/superpowers/plans/2026-05-24-harness-board-rebuild-plan1-retire-flashcards.md
Spec:docs/superpowers/specs/2026-05-24-harness-board-framework-rebuild-design.md

退役清单:
- sqlite:flashcards / prefill_log 2 表 (drop 脚本幂等)
- python:FlashcardRepo / PrefillRepo / flashcard_generator / srs
- routes:/flashcards/today /flashcards/stats /api/flashcards/stats.json /flashcards/{id}/review
- templates:flashcards.html / flashcards_stats.html / _flashcard_review.html
- static:flashcards.js
- tests:6 个测试文件
- nav-rail:复习入口

Plan 2 接:DeepCard v2 schema migration + 模块页 + 就地展开。
```

---

## Self-Review

实施前已对照 spec § 6.1 (routes) / § 6.2 (templates) / § 6.3 (sqlite) / § 6.4 (derive) / § 6.5 (static):

| Spec 退役项 | Plan 1 覆盖 |
|---|---|
| `/flashcards/today` route | ✓ Task 4 |
| `/flashcards/stats` route | ✓ Task 4 |
| `/api/flashcards/stats.json` route | ✓ Task 4 |
| `/flashcards/{id}/review` route | ✓ Task 4 |
| `flashcards.html` 模板 | ✓ Task 7 |
| `flashcards_stats.html` 模板 | ✓ Task 7 |
| `_flashcard_review.html` partial | ✓ Task 7 |
| `flashcards.js` 静态 | ✓ Task 7 |
| `flashcards` sqlite 表 | ✓ Task 1 + Task 2 |
| `prefill_log` sqlite 表 | ✓ Task 1 + Task 2 |
| `flashcard_generator.py` derive | ✓ Task 5 |
| `srs.py` derive | ✓ Task 5 |
| `FlashcardRepo` / `PrefillRepo` | ✓ Task 3 |
| 6 个 flashcards 测试文件 | ✓ Task 6 |
| nav-rail 复习入口 | ✓ Task 7 |

**Spec 中 Plan 1 不覆盖的项**(留 Plan 2-4):
- DeepCard v2 schema migration → Plan 2
- `decisions.html` / `overview.html` / `survey.html` 等其他退役 → Plan 3
- `_app_shell.html` / `_view_toggle.html` 等其他 partials → Plan 3
- `decision_extractor.py` / `story_builder.py` / `survey_loader.py` / `graph_builder.py` 等其他 derive → Plan 3

**Placeholders:**0(已检)
**Type consistency:**Step 2.1 的 `drop_legacy_tables(db_path: Path) -> None` 在 Step 2.4 实现签名一致,Step 2.6 使用方式一致。
**Risks:**
- 若 sqlite db 已有 flashcards 表数据,DROP 后数据不可恢复 — backup 在 Task 0.2 已做
- 若有外部脚本 / cron 调用 flashcards endpoint,会突然 404 — 本项目无外部 caller(单用户工具)

---

## 后续(Plan 2-4 预告,不在本 plan 范围)

```
Plan 2 — DeepCard v2 schema migration + 模块页 /m/{dim} + chip 三色 + 右键 + 就地展开
        + 图上传 endpoint + _screenshot_uploader
Plan 3 — 首页 Topology + nav 简化 + 其他子页退役 (decisions/overview/survey)
        + CSS 重写 + 删剩余 partials
Plan 4 — /story 改造 + base.html 引 mermaid CDN + render-field.js
```

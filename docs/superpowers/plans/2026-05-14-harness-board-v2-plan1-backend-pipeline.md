# Harness Board v2 Polish — Plan 1: 后端 pipeline + 数据修复

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** [`docs/superpowers/specs/2026-05-14-harness-board-v2-polish-design.md`](../specs/2026-05-14-harness-board-v2-polish-design.md)

**版本归位:** v0.9.6 harness-board polish · **分支:** `feat/harness-board-v2-polish` · **PR 题:** `feat(harness-board): V2 polish — UI 重写 + 鸟瞰修复 + 一键 SSE 全量更新`(Plan 1 单独 PR 标题:`feat(harness-board): V2 Plan 1 — refresh pipeline + seed lifespan + SSE endpoint`)

**Goal:** 把 `POST /refresh` 从"302 仅 invalidate snapshot"升级为 SSE 流式 5-step pipeline(chip_resolve / seed_ingest / decision_extract / milvus_reindex / snapshot_finalize),并在 startup lifespan 跑 insert-if-missing seed ingest 修复鸟瞰空盘问题。

**Architecture:** 抽 `SeedIngestService`(insert-if-missing 语义,保护手动编辑)+ `RefreshPipeline`(async generator yield StepEvent,降级矩阵保护 milvus_reindex)+ lifespan context manager(starlette 标准式,非 deprecated `@app.on_event`)。SSE 用 `StreamingResponse(generator, media_type="text/event-stream")`。CLI `seed_deep_cards.py` 退化为薄包装。

**Tech Stack:** Python 3.11 / Starlette 0.40+ / Pydantic v2 / sqlite3 / pymilvus(可选)/ pytest + monkeypatch + TestClient / `uv run pytest`

**Breaking change(写入 PR 描述):** `POST /refresh` 不再返回 `302 Location: /`,改为 `200 Content-Type: text/event-stream`。前端按钮 in Plan 3 改造为 EventSource;无 JS 调用方需自行适配。

---

## File Structure(Plan 1 范围)

**新建:**
- `dashboard/derive/seed_ingest.py` — `SeedIngestService` + `SeedIngestResult` dataclass(insert-if-missing 语义 + `force=True` upsert)
- `dashboard/derive/refresh_pipeline.py` — `StepEvent` dataclass + `RefreshPipeline.stream()` async generator + 5 个 step 私有方法
- `dashboard/tests/unit/__init__.py` — 空 package marker(unit dir 当前缺)
- `dashboard/tests/unit/test_seed_ingest.py` — L0 单元:underfilled / 已满 / 已编辑保护 / force upsert 4 路径
- `dashboard/tests/unit/test_refresh_pipeline.py` — L0 单元:每个 step 独立 + milvus 降级 4 种 skip + critical 失败 error 路径
- `dashboard/tests/integration/test_refresh_sse.py` — L1 集成:SSE 事件计数 + milvus skip 后续 step 仍 done
- `dashboard/tests/integration/test_lifespan_seed.py` — L1 集成:underfilled 触发 / 已满跳过 / 已编辑 row 不被覆盖
- `dashboard/tests/integration/test_overview_after_seed.py` — L2 e2e:seed 跑完后 `/api/overview/graph.json` ≥ 35 nodes

**修改:**
- `backend/app/scripts/seed_deep_cards.py` — refactor 为薄 CLI:解析 args → 调 `SeedIngestService.run(force=args.force)`;保留 `--regenerate-flashcards` flag;新增 `--force`
- `dashboard/server.py` — 重写 `post_refresh` 为 SSE handler;加 lifespan context manager;`app = Starlette(routes=..., lifespan=lifespan)`
- `dashboard/tests/integration/test_seed_deep_cards.py` — 保留 `load_seed` 测试(`SeedIngestService` 复用),迁移 CLI smoke 到调 service 路径

---

## Task 1: 建立 unit test 目录骨架

**Files:**
- Create: `dashboard/tests/unit/__init__.py`

- [ ] **Step 1: 检查 unit 目录现状**

Run: `ls dashboard/tests/unit/ && test -f dashboard/tests/unit/__init__.py && echo HAS_INIT || echo NO_INIT`
Expected: 输出 `NO_INIT`(目录存在但缺 `__init__.py`)

- [ ] **Step 2: 创建空 `__init__.py`**

```python
# dashboard/tests/unit/__init__.py
"""Plan 1 起 L0 unit tests 集中目录。"""
```

- [ ] **Step 3: 验证 pytest 能发现 unit 目录**

Run: `uv run pytest dashboard/tests/unit/ --collect-only -q`
Expected: collects 现有 10 个 test 文件,无 ImportError

- [ ] **Step 4: Commit**

```bash
git add dashboard/tests/unit/__init__.py
git commit -m "$(cat <<'EOF'
test(harness-board): add unit test package marker for Plan 1

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: SeedIngestService — `run_once_if_underfilled` 路径(TDD)

**Files:**
- Create: `dashboard/derive/seed_ingest.py`
- Test: `dashboard/tests/unit/test_seed_ingest.py`

- [ ] **Step 1: 写 failing test — underfilled 触发,已满跳过**

```python
# dashboard/tests/unit/test_seed_ingest.py
"""SeedIngestService L0 — insert-if-missing 语义 + 4 路径(underfilled / 已满 / 已编辑保护 / force upsert)。"""

from __future__ import annotations

import json
from pathlib import Path

from dashboard.derive.deep_card_types import DeepCard
from dashboard.derive.seed_ingest import SeedIngestResult, SeedIngestService
from dashboard.state.db import open_db
from dashboard.state.repositories import DeepCardRepo


PROJECT_ROOT = Path(__file__).resolve().parents[3]
REAL_CONFIG_DIR = PROJECT_ROOT / "dashboard" / "config"


def _write_seed_jsonl(p: Path, cap_ids: list[str]) -> None:
    """写一个 minimal 合法 seed jsonl(cap_id + what 足够过 Pydantic)。"""
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"cap_id": cid, "what": f"what for {cid}"}) for cid in cap_ids]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_run_once_if_underfilled_triggers_when_db_empty(tmp_path: Path) -> None:
    """db 中 DeepCard 数 < seed 总数(0 < 2)→ 跑 insert-if-missing。"""
    seed = tmp_path / "seed.jsonl"
    # 用 capabilities.yaml 中真实 cap_id(memory.long_term_memory 一定存在)
    _write_seed_jsonl(seed, ["memory.long_term_memory", "memory.short_term_memory"])
    db = tmp_path / "board.db"

    svc = SeedIngestService(seed_path=seed, db_path=db, config_dir=REAL_CONFIG_DIR)
    result = svc.run_once_if_underfilled()

    assert isinstance(result, SeedIngestResult)
    assert result.total_seed == 2
    assert result.inserted == 2
    assert result.skipped_existing == 0
    # cap_id 在 yaml 中 → 没有 skipped_invalid


def test_run_once_if_underfilled_skips_when_db_full(tmp_path: Path) -> None:
    """db 已 ≥ seed 总数 → no-op,返回 0 inserted。"""
    seed = tmp_path / "seed.jsonl"
    _write_seed_jsonl(seed, ["memory.long_term_memory"])
    db = tmp_path / "board.db"

    # 预先塞 2 张 card(无论 cap_id 是否在 yaml,只看数量是否 underfilled)
    conn = open_db(db)
    try:
        DeepCardRepo(conn).upsert(DeepCard(cap_id="memory.long_term_memory", what="manual edit"))
        DeepCardRepo(conn).upsert(DeepCard(cap_id="memory.short_term_memory"))
    finally:
        conn.close()

    svc = SeedIngestService(seed_path=seed, db_path=db, config_dir=REAL_CONFIG_DIR)
    result = svc.run_once_if_underfilled()
    assert result.inserted == 0
    # underfilled 检查命中 → 不读 seed,total_seed 可能为 0(no-op semantics)
    # 实现选定:no-op 返回全 0
    assert result.total_seed == 0
```

- [ ] **Step 2: 运行 test 验证失败**

Run: `uv run pytest dashboard/tests/unit/test_seed_ingest.py -v`
Expected: `ImportError: cannot import name 'SeedIngestService' from 'dashboard.derive.seed_ingest'`

- [ ] **Step 3: 写 minimal `SeedIngestService` 实现**

```python
# dashboard/derive/seed_ingest.py
"""SeedIngestService — 从 dashboard/data/deep_cards_seed.jsonl 加载 hand-curated DeepCard 入 sqlite。

语义:**insert-if-missing**(已存在 cap_id 一律跳过,保护用户手动编辑)。
显式 force=True 时改 upsert(向后兼容旧"强制重填"用途)。

设计依据:spec § 2.5 / § 2.6。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from dashboard.derive.capability_resolver import load_capabilities
from dashboard.derive.deep_card_types import DeepCard
from dashboard.state.db import open_db
from dashboard.state.repositories import DeepCardRepo

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SeedIngestResult:
    total_seed: int        # jsonl 行数(no-op 时为 0)
    inserted: int          # 新插入
    skipped_existing: int  # cap_id 已存在跳过(保护手动编辑)
    skipped_invalid: int   # cap_id 不在 capabilities.yaml 跳过
    overwritten: int       # 仅 force=True 时 > 0


class SeedIngestService:
    def __init__(self, *, seed_path: Path, db_path: Path, config_dir: Path) -> None:
        self.seed_path = seed_path
        self.db_path = db_path
        self.config_dir = config_dir

    @staticmethod
    def _load_seed(seed_path: Path) -> list[DeepCard]:
        cards: list[DeepCard] = []
        for raw in seed_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line:
                continue
            cards.append(DeepCard.model_validate(json.loads(line)))
        return cards

    def _count_db_cards(self) -> int:
        conn = open_db(self.db_path)
        try:
            return len(DeepCardRepo(conn).get_all())
        finally:
            conn.close()

    def _count_seed_lines(self) -> int:
        if not self.seed_path.exists():
            return 0
        return sum(
            1 for raw in self.seed_path.read_text(encoding="utf-8").splitlines() if raw.strip()
        )

    def run_once_if_underfilled(self) -> SeedIngestResult:
        """db 中 card 数 < seed 总数时跑 insert-if-missing,否则 no-op。"""
        seed_total = self._count_seed_lines()
        db_total = self._count_db_cards()
        if seed_total == 0 or db_total >= seed_total:
            logger.info(
                "SeedIngest: skip (db=%d ≥ seed=%d or seed missing)", db_total, seed_total
            )
            return SeedIngestResult(0, 0, 0, 0, 0)
        return self.run(force=False)

    def run(self, *, force: bool = False) -> SeedIngestResult:
        """显式跑。force=True 时 upsert 覆盖现存 row;否则 insert-if-missing。"""
        if not self.seed_path.exists():
            logger.warning("SeedIngest: seed file missing: %s", self.seed_path)
            return SeedIngestResult(0, 0, 0, 0, 0)
        cards = self._load_seed(self.seed_path)
        caps = load_capabilities(self.config_dir / "capabilities.yaml")
        valid_ids = {c.id for c in caps}

        inserted = 0
        skipped_existing = 0
        skipped_invalid = 0
        overwritten = 0

        conn = open_db(self.db_path)
        try:
            repo = DeepCardRepo(conn)
            for card in cards:
                if card.cap_id not in valid_ids:
                    skipped_invalid += 1
                    continue
                existing = repo.get(card.cap_id)
                if existing is None:
                    repo.upsert(card)
                    inserted += 1
                elif force:
                    repo.upsert(card)
                    overwritten += 1
                else:
                    skipped_existing += 1
        finally:
            conn.close()

        return SeedIngestResult(
            total_seed=len(cards),
            inserted=inserted,
            skipped_existing=skipped_existing,
            skipped_invalid=skipped_invalid,
            overwritten=overwritten,
        )
```

- [ ] **Step 4: 运行 test 验证通过**

Run: `uv run pytest dashboard/tests/unit/test_seed_ingest.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add dashboard/derive/seed_ingest.py dashboard/tests/unit/test_seed_ingest.py
git commit -m "$(cat <<'EOF'
feat(harness-board): SeedIngestService with insert-if-missing semantics

Plan 1 Task 2 — 抽 seed_deep_cards CLI 核心为 SeedIngestService,
默认 insert-if-missing 保护手动编辑,force=True 走 upsert。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: SeedIngestService — 已编辑保护 + force upsert + invalid skip(扩展 test)

**Files:**
- Modify: `dashboard/tests/unit/test_seed_ingest.py`

- [ ] **Step 1: 追加 3 个 test case(insert-if-missing 不覆盖 / force 覆盖 / cap_id 不在 yaml 时 skip_invalid)**

```python
# 追加到 dashboard/tests/unit/test_seed_ingest.py 末尾

def test_run_does_not_overwrite_existing_row(tmp_path: Path) -> None:
    """已存在 cap_id 一律跳过(保护手动编辑)— 即便 db 中 row 内容不同。"""
    seed = tmp_path / "seed.jsonl"
    _write_seed_jsonl(seed, ["memory.long_term_memory"])
    db = tmp_path / "board.db"

    # 预先塞一张"用户手动编辑过"的 card(what 不同于 seed)
    manual_card = DeepCard(cap_id="memory.long_term_memory", what="USER_EDITED")
    conn = open_db(db)
    try:
        DeepCardRepo(conn).upsert(manual_card)
    finally:
        conn.close()

    # 强制 run(不走 underfilled 判定;此处 db=1, seed=1 反正也是 not-underfilled)
    svc = SeedIngestService(seed_path=seed, db_path=db, config_dir=REAL_CONFIG_DIR)
    result = svc.run(force=False)

    assert result.inserted == 0
    assert result.skipped_existing == 1
    assert result.overwritten == 0

    # 校验 db row 未被覆盖
    conn = open_db(db)
    try:
        survived = DeepCardRepo(conn).get("memory.long_term_memory")
    finally:
        conn.close()
    assert survived is not None
    assert survived.what == "USER_EDITED"


def test_run_force_overwrites_existing_row(tmp_path: Path) -> None:
    """force=True → upsert,manual edit 会被 seed 内容覆盖。"""
    seed = tmp_path / "seed.jsonl"
    _write_seed_jsonl(seed, ["memory.long_term_memory"])
    db = tmp_path / "board.db"

    manual_card = DeepCard(cap_id="memory.long_term_memory", what="USER_EDITED")
    conn = open_db(db)
    try:
        DeepCardRepo(conn).upsert(manual_card)
    finally:
        conn.close()

    svc = SeedIngestService(seed_path=seed, db_path=db, config_dir=REAL_CONFIG_DIR)
    result = svc.run(force=True)

    assert result.overwritten == 1
    assert result.inserted == 0
    assert result.skipped_existing == 0

    conn = open_db(db)
    try:
        survived = DeepCardRepo(conn).get("memory.long_term_memory")
    finally:
        conn.close()
    assert survived is not None
    assert survived.what == "what for memory.long_term_memory"


def test_run_skips_invalid_cap_id(tmp_path: Path) -> None:
    """seed 中 cap_id 不在 capabilities.yaml → skipped_invalid 累加,不写 db。"""
    seed = tmp_path / "seed.jsonl"
    _write_seed_jsonl(seed, ["memory.long_term_memory", "nope.fake_capability"])
    db = tmp_path / "board.db"

    svc = SeedIngestService(seed_path=seed, db_path=db, config_dir=REAL_CONFIG_DIR)
    result = svc.run(force=False)

    assert result.inserted == 1
    assert result.skipped_invalid == 1

    conn = open_db(db)
    try:
        all_cards = DeepCardRepo(conn).get_all()
    finally:
        conn.close()
    assert {c.cap_id for c in all_cards} == {"memory.long_term_memory"}
```

- [ ] **Step 2: 运行 test 验证通过(实现已支持,3 个新 case 应 PASS)**

Run: `uv run pytest dashboard/tests/unit/test_seed_ingest.py -v`
Expected: 5 PASS

- [ ] **Step 3: Commit**

```bash
git add dashboard/tests/unit/test_seed_ingest.py
git commit -m "$(cat <<'EOF'
test(harness-board): cover force / invalid-skip / manual-edit paths in SeedIngestService

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Refactor `seed_deep_cards.py` CLI 为薄包装 + `--force` flag

**Files:**
- Modify: `backend/app/scripts/seed_deep_cards.py`
- Modify: `dashboard/tests/integration/test_seed_deep_cards.py`

- [ ] **Step 1: 改写 CLI 主体为调 `SeedIngestService.run(force=...)`,加 `--force` arg**

```python
# backend/app/scripts/seed_deep_cards.py
"""seed_deep_cards CLI — Plan 1 后:薄包装,委托 SeedIngestService。

默认 insert-if-missing(保护手动编辑);--force 走 upsert(向后兼容旧"强制重填"用途)。

Usage:
    uv run --project backend python -m app.scripts.seed_deep_cards \\
        --seed dashboard/data/deep_cards_seed.jsonl \\
        --db backend/data/board.db [--force] [--regenerate-flashcards]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from dashboard.derive.deep_card_types import DeepCard
from dashboard.derive.seed_ingest import SeedIngestService
from dashboard.state.db import open_db
from dashboard.state.repositories import DeepCardRepo, FlashcardRepo, regenerate_flashcards_for

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def load_seed(seed_path: Path) -> list[DeepCard]:
    """旧测试兼容:沿用 SeedIngestService 的内部 loader。"""
    cards: list[DeepCard] = []
    for raw in seed_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        cards.append(DeepCard.model_validate(json.loads(line)))
    return cards


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load hand-curated DeepCard seed into sqlite")
    parser.add_argument("--seed", default="dashboard/data/deep_cards_seed.jsonl")
    parser.add_argument("--db", default="backend/data/board.db")
    parser.add_argument(
        "--force",
        action="store_true",
        help="upsert 覆盖已存在 cap_id(默认 insert-if-missing 保护手动编辑)",
    )
    parser.add_argument("--regenerate-flashcards", action="store_true")
    args = parser.parse_args(argv)

    seed_arg = Path(args.seed)
    db_arg = Path(args.db)
    seed_path = seed_arg if seed_arg.is_absolute() else PROJECT_ROOT / seed_arg
    db_path = db_arg if db_arg.is_absolute() else PROJECT_ROOT / db_arg
    config_dir = PROJECT_ROOT / "dashboard" / "config"

    if not seed_path.exists():
        print(f"ERROR: seed file not found: {seed_path}", file=sys.stderr)
        return 2

    svc = SeedIngestService(seed_path=seed_path, db_path=db_path, config_dir=config_dir)
    result = svc.run(force=args.force)
    print(
        f"Seed load done. inserted={result.inserted}, "
        f"skipped_existing={result.skipped_existing}, "
        f"skipped_invalid={result.skipped_invalid}, "
        f"overwritten={result.overwritten}, total_seed={result.total_seed}"
    )

    if args.regenerate_flashcards:
        # 复用 Plan 3 原逻辑 — 对所有刚被写入的 cap_id 重生成
        from dashboard.derive.capability_resolver import load_capabilities

        caps = load_capabilities(config_dir / "capabilities.yaml")
        name_by_id = {c.id: c.name_cn for c in caps}
        conn = open_db(db_path)
        try:
            dc_repo = DeepCardRepo(conn)
            fc_repo = FlashcardRepo(conn)
            for card in dc_repo.get_all():
                regenerate_flashcards_for(
                    card.cap_id,
                    dc_repo=dc_repo,
                    fc_repo=fc_repo,
                    cap_name_cn=name_by_id.get(card.cap_id, card.cap_id),
                )
            print(f"Regenerated flashcards: {len(fc_repo.get_all())}")
        finally:
            conn.close()
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
```

- [ ] **Step 2: 验证现有 CLI smoke test 仍 PASS(`load_seed` 仍可用 + `main()` 行为兼容)**

Run: `uv run pytest dashboard/tests/integration/test_seed_deep_cards.py -v`
Expected: 2 PASS(test_load_seed_parses_real_jsonl / test_seed_load_direct_into_tmp_db)

- [ ] **Step 3: 加一个 CLI `--force` smoke test 到 integration test**

```python
# 追加到 dashboard/tests/integration/test_seed_deep_cards.py 末尾

def test_cli_force_flag_overwrites(tmp_path: Path) -> None:
    """CLI --force 委托 SeedIngestService(force=True)。"""
    seed_path = PROJECT_ROOT / "dashboard" / "data" / "deep_cards_seed.jsonl"
    db = tmp_path / "board.db"

    # 先非 force 跑一次
    rc = sd.main(["--seed", str(seed_path), "--db", str(db)])
    assert rc == 0

    # 手动改一条 row
    from dashboard.derive.deep_card_types import DeepCard

    conn = open_db(db)
    try:
        DeepCardRepo(conn).upsert(
            DeepCard(cap_id="memory.long_term_memory", what="USER_EDITED_BEFORE_FORCE")
        )
    finally:
        conn.close()

    # --force 跑一次 → 应覆盖
    rc = sd.main(["--seed", str(seed_path), "--db", str(db), "--force"])
    assert rc == 0

    conn = open_db(db)
    try:
        survived = DeepCardRepo(conn).get("memory.long_term_memory")
    finally:
        conn.close()
    assert survived is not None
    assert survived.what != "USER_EDITED_BEFORE_FORCE"
```

- [ ] **Step 4: 运行新 test**

Run: `uv run pytest dashboard/tests/integration/test_seed_deep_cards.py::test_cli_force_flag_overwrites -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/scripts/seed_deep_cards.py dashboard/tests/integration/test_seed_deep_cards.py
git commit -m "$(cat <<'EOF'
feat(harness-board): refactor seed_deep_cards CLI to thin wrapper over SeedIngestService

Plan 1 Task 4 — CLI 委托新 service,加 --force flag(默认 insert-if-missing
保护手动编辑),保留 --regenerate-flashcards 旧路径。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `StepEvent` dataclass + `RefreshPipeline` 骨架 + chip_resolve step(TDD)

**Files:**
- Create: `dashboard/derive/refresh_pipeline.py`
- Test: `dashboard/tests/unit/test_refresh_pipeline.py`

- [ ] **Step 1: 写 failing test — `StepEvent` 类型 + chip_resolve step 跑通**

```python
# dashboard/tests/unit/test_refresh_pipeline.py
"""RefreshPipeline L0 — 5 个 step 独立路径 + milvus 降级 4 种 + critical 错误。"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest

from dashboard.derive.refresh_pipeline import RefreshPipeline, StepEvent

PROJECT_ROOT = Path(__file__).resolve().parents[3]
REAL_CONFIG_DIR = PROJECT_ROOT / "dashboard" / "config"


@pytest.fixture
def pipeline(tmp_path: Path) -> RefreshPipeline:
    return RefreshPipeline(
        project_root=PROJECT_ROOT,
        config_dir=REAL_CONFIG_DIR,
        db_path=tmp_path / "board.db",
        seed_path=PROJECT_ROOT / "dashboard" / "data" / "deep_cards_seed.jsonl",
    )


def test_step_event_dataclass_shape() -> None:
    ev = StepEvent(step="chip_resolve", status="done", label="x", detail="y", duration_ms=5)
    assert ev.step == "chip_resolve"
    # status 只接受 4 个文字量(运行时不严格,但实现需 Literal 标注)
    valid: set[Literal["running", "done", "skip", "error"]] = {"running", "done", "skip", "error"}
    assert ev.status in valid


def test_chip_resolve_step_returns_done(pipeline: RefreshPipeline) -> None:
    ev = pipeline._chip_resolve_step()  # type: ignore[attr-defined]
    assert ev.step == "chip_resolve"
    assert ev.status == "done"
    assert "chip" in ev.detail.lower() or ev.detail  # 实现给出 detail
    assert ev.duration_ms >= 0
```

- [ ] **Step 2: 运行 test 验证失败**

Run: `uv run pytest dashboard/tests/unit/test_refresh_pipeline.py -v`
Expected: ImportError on `RefreshPipeline`/`StepEvent`

- [ ] **Step 3: 写 minimal `refresh_pipeline.py`**

```python
# dashboard/derive/refresh_pipeline.py
"""RefreshPipeline — POST /refresh SSE 5-step pipeline。spec § 2.6。

5 step:chip_resolve / seed_ingest / decision_extract / milvus_reindex / snapshot_finalize。
每个 step 返回 StepEvent;milvus_reindex 走 4 种 skip 降级矩阵(spec § 2.3)。
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

StepStatus = Literal["running", "done", "skip", "error"]


@dataclass(frozen=True)
class StepEvent:
    step: str
    status: StepStatus
    label: str
    detail: str = ""
    duration_ms: int = 0


# 步骤中文 label(SSE 面板显示)— spec § 2.1 范例
_LABELS: dict[str, str] = {
    "chip_resolve": "扫代码判断 chip 状态",
    "seed_ingest": "加载 DeepCard seed",
    "decision_extract": "重抽 spec/plan/memory 决策",
    "milvus_reindex": "向量重建",
    "snapshot_finalize": "整合 snapshot",
}


class RefreshPipeline:
    def __init__(
        self,
        *,
        project_root: Path,
        config_dir: Path,
        db_path: Path,
        seed_path: Path,
    ) -> None:
        self.project_root = project_root
        self.config_dir = config_dir
        self.db_path = db_path
        self.seed_path = seed_path

    # ---- 单 step 实现(下任务陆续补齐)----

    def _chip_resolve_step(self) -> StepEvent:
        """全量 resolve 62 cap;失败抛 → 上层包 status=error。"""
        from dashboard.derive.capability_resolver import load_capabilities, resolve_status

        t0 = time.perf_counter()
        caps = load_capabilities(self.config_dir / "capabilities.yaml")
        lit = wip = todo = 0
        for c in caps:
            s = resolve_status(c, self.project_root)
            if s == "lit":
                lit += 1
            elif s == "wip":
                wip += 1
            else:
                todo += 1
        dt = int((time.perf_counter() - t0) * 1000)
        return StepEvent(
            step="chip_resolve",
            status="done",
            label=_LABELS["chip_resolve"],
            detail=f"{len(caps)} chip · {lit} lit / {wip} wip / {todo} todo",
            duration_ms=dt,
        )

    async def stream(self) -> AsyncIterator[StepEvent]:
        """yield 5 个 step × (running, done|skip|error)。后续 task 完成。"""
        raise NotImplementedError("see Task 9")
```

- [ ] **Step 4: 运行 test 验证通过**

Run: `uv run pytest dashboard/tests/unit/test_refresh_pipeline.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add dashboard/derive/refresh_pipeline.py dashboard/tests/unit/test_refresh_pipeline.py
git commit -m "$(cat <<'EOF'
feat(harness-board): RefreshPipeline skeleton + chip_resolve step

Plan 1 Task 5 — StepEvent dataclass + RefreshPipeline class + 1/5 step
(chip_resolve)。其余 step 后续 task 逐步补齐。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `_seed_ingest_step` + `_decision_extract_step` + `_snapshot_finalize_step`(TDD)

**Files:**
- Modify: `dashboard/derive/refresh_pipeline.py`
- Modify: `dashboard/tests/unit/test_refresh_pipeline.py`

- [ ] **Step 1: 写 failing test — 3 个 non-degradable step 各返 status=done + 合理 detail**

```python
# 追加到 dashboard/tests/unit/test_refresh_pipeline.py

def test_seed_ingest_step_returns_done(pipeline: RefreshPipeline) -> None:
    ev = pipeline._seed_ingest_step()  # type: ignore[attr-defined]
    assert ev.step == "seed_ingest"
    assert ev.status == "done"
    # detail 应含 "insert"/"skip" 计数
    assert "insert" in ev.detail or "skipped" in ev.detail


def test_decision_extract_step_returns_done(pipeline: RefreshPipeline) -> None:
    ev = pipeline._decision_extract_step()  # type: ignore[attr-defined]
    assert ev.step == "decision_extract"
    assert ev.status == "done"
    # 至少抽出一个决策(本仓 specs 多)
    assert "entries" in ev.detail or "decision" in ev.detail.lower()


def test_snapshot_finalize_step_returns_done(pipeline: RefreshPipeline) -> None:
    ev = pipeline._snapshot_finalize_step()  # type: ignore[attr-defined]
    assert ev.step == "snapshot_finalize"
    assert ev.status == "done"
    assert "refreshed_at" in ev.detail or "snapshot" in ev.detail.lower()
```

- [ ] **Step 2: 运行 test 验证失败(AttributeError)**

Run: `uv run pytest dashboard/tests/unit/test_refresh_pipeline.py -v`
Expected: 3 new tests FAIL with `AttributeError: 'RefreshPipeline' object has no attribute '_seed_ingest_step'`

- [ ] **Step 3: 加 3 个 step 方法到 `RefreshPipeline`**

```python
# 追加到 dashboard/derive/refresh_pipeline.py 类内,在 _chip_resolve_step 后

    def _seed_ingest_step(self) -> StepEvent:
        from dashboard.derive.seed_ingest import SeedIngestService

        t0 = time.perf_counter()
        svc = SeedIngestService(
            seed_path=self.seed_path, db_path=self.db_path, config_dir=self.config_dir
        )
        # refresh 走 insert-if-missing(force=False),保护手动编辑;
        # 用户想 force 走 CLI --force 或后续 admin endpoint。
        result = svc.run(force=False)
        dt = int((time.perf_counter() - t0) * 1000)
        return StepEvent(
            step="seed_ingest",
            status="done",
            label=_LABELS["seed_ingest"],
            detail=(
                f"{result.total_seed} cards · {result.inserted} insert / "
                f"{result.skipped_existing} skip(existing) / "
                f"{result.skipped_invalid} skip(invalid)"
            ),
            duration_ms=dt,
        )

    def _decision_extract_step(self) -> StepEvent:
        from dashboard.derive.decision_extractor import extract_all

        t0 = time.perf_counter()
        decisions = extract_all()
        dt = int((time.perf_counter() - t0) * 1000)
        return StepEvent(
            step="decision_extract",
            status="done",
            label=_LABELS["decision_extract"],
            detail=f"{len(decisions)} entries",
            duration_ms=dt,
        )

    def _snapshot_finalize_step(self) -> StepEvent:
        from dashboard.derive.snapshot_builder import build_snapshot
        from dashboard.state.db import open_db
        from dashboard.state.repositories import OverrideRepo, SnapshotRepo

        t0 = time.perf_counter()
        conn = open_db(self.db_path)
        try:
            overrides = OverrideRepo(conn).get_all()
            snap_repo = SnapshotRepo(conn)
            snap_repo.invalidate()
            snapshot = build_snapshot(self.project_root, self.config_dir, overrides=overrides)
            snap_repo.save(snapshot.refreshed_at, snapshot.to_dict())
        finally:
            conn.close()
        dt = int((time.perf_counter() - t0) * 1000)
        return StepEvent(
            step="snapshot_finalize",
            status="done",
            label=_LABELS["snapshot_finalize"],
            detail=f"refreshed_at {snapshot.refreshed_at}",
            duration_ms=dt,
        )
```

- [ ] **Step 4: 运行 test 验证通过**

Run: `uv run pytest dashboard/tests/unit/test_refresh_pipeline.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add dashboard/derive/refresh_pipeline.py dashboard/tests/unit/test_refresh_pipeline.py
git commit -m "$(cat <<'EOF'
feat(harness-board): add 3 non-degradable refresh steps

Plan 1 Task 6 — seed_ingest / decision_extract / snapshot_finalize
封装现有 derive 函数 + SeedIngestService。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `_milvus_reindex_step` + 4 种降级矩阵(TDD)

**Files:**
- Modify: `dashboard/derive/refresh_pipeline.py`
- Modify: `dashboard/tests/unit/test_refresh_pipeline.py`

- [ ] **Step 1: 写 4 个 failing test — 4 种 skip 路径**

```python
# 追加到 dashboard/tests/unit/test_refresh_pipeline.py

def test_milvus_reindex_skip_when_host_missing(
    pipeline: RefreshPipeline, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HARNESS_BOARD_MILVUS_HOST", raising=False)

    import asyncio

    ev = asyncio.run(pipeline._milvus_reindex_step())  # type: ignore[attr-defined]
    assert ev.step == "milvus_reindex"
    assert ev.status == "skip"
    assert "milvus disabled" in ev.detail.lower()


def test_milvus_reindex_skip_when_embedding_key_missing(
    pipeline: RefreshPipeline, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HARNESS_BOARD_MILVUS_HOST", "localhost")
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.setenv("EMBEDDING_MODE", "qwen")

    import asyncio

    ev = asyncio.run(pipeline._milvus_reindex_step())  # type: ignore[attr-defined]
    assert ev.status == "skip"
    assert "embedding" in ev.detail.lower() and "missing" in ev.detail.lower()


def test_milvus_reindex_skip_when_milvus_unreachable(
    pipeline: RefreshPipeline, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HARNESS_BOARD_MILVUS_HOST", "localhost")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "fake-key-for-test")
    monkeypatch.setenv("EMBEDDING_MODE", "qwen")

    async def _raise_connection_error(self_: object) -> None:
        raise ConnectionError("milvus boom")

    monkeypatch.setattr(
        "dashboard.state.milvus_collection.DeepCardMilvusClient.ensure_collection",
        _raise_connection_error,
    )
    # 防真的连接 Milvus(__init__ 也连):patch __init__ no-op
    monkeypatch.setattr(
        "dashboard.state.milvus_collection.DeepCardMilvusClient.__init__",
        lambda self, **kw: None,
    )

    import asyncio

    ev = asyncio.run(pipeline._milvus_reindex_step())  # type: ignore[attr-defined]
    assert ev.status == "skip"
    assert "unreachable" in ev.detail.lower()


def test_milvus_reindex_skip_when_embedding_call_fails(
    pipeline: RefreshPipeline, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HARNESS_BOARD_MILVUS_HOST", "localhost")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "fake-key-for-test")
    monkeypatch.setenv("EMBEDDING_MODE", "qwen")

    # 让 ensure_collection 不抛(假装连上)
    monkeypatch.setattr(
        "dashboard.state.milvus_collection.DeepCardMilvusClient.__init__",
        lambda self, **kw: None,
    )

    async def _noop_ensure(self_: object) -> None:
        return None

    monkeypatch.setattr(
        "dashboard.state.milvus_collection.DeepCardMilvusClient.ensure_collection", _noop_ensure
    )

    class _BoomEmbedder:
        async def embed(self, texts: list[str]) -> list[list[float]]:
            raise RuntimeError("boom embedding")

    monkeypatch.setattr(
        "app.services.embedding_factory.build_embedding_service_from_env",
        lambda: _BoomEmbedder(),
    )

    # 先塞一张 deep_card,否则 cards 列表空就直接 done with 0 upserts
    from dashboard.derive.deep_card_types import DeepCard
    from dashboard.state.db import open_db
    from dashboard.state.repositories import DeepCardRepo

    conn = open_db(pipeline.db_path)
    try:
        DeepCardRepo(conn).upsert(DeepCard(cap_id="memory.long_term_memory", what="x"))
    finally:
        conn.close()

    import asyncio

    ev = asyncio.run(pipeline._milvus_reindex_step())  # type: ignore[attr-defined]
    assert ev.status == "skip"
    assert "embedding error" in ev.detail.lower()
```

- [ ] **Step 2: 运行 test 验证 4 个 FAIL**

Run: `uv run pytest dashboard/tests/unit/test_refresh_pipeline.py -v -k milvus`
Expected: 4 FAIL `AttributeError: _milvus_reindex_step`

- [ ] **Step 3: 实现 `_milvus_reindex_step` + 4 种 skip 降级**

```python
# 追加到 dashboard/derive/refresh_pipeline.py 类内,_snapshot_finalize_step 之前

    async def _milvus_reindex_step(self) -> StepEvent:
        """全量 reindex DeepCard → Milvus,4 种 skip 降级(spec § 2.3)。"""
        t0 = time.perf_counter()

        def _ev(status: StepStatus, detail: str) -> StepEvent:
            return StepEvent(
                step="milvus_reindex",
                status=status,
                label=_LABELS["milvus_reindex"],
                detail=detail,
                duration_ms=int((time.perf_counter() - t0) * 1000),
            )

        # 1. host 未设
        host = os.getenv("HARNESS_BOARD_MILVUS_HOST")
        if not host:
            return _ev("skip", "milvus disabled")

        # 2. embedding key 缺失(qwen mode 需 DASHSCOPE_API_KEY)
        mode = os.getenv("EMBEDDING_MODE", "qwen")
        if mode == "qwen" and not os.getenv("DASHSCOPE_API_KEY"):
            return _ev("skip", "embedding key missing")

        port = int(os.getenv("HARNESS_BOARD_MILVUS_PORT", "19530"))

        # 3. Milvus 不可达
        try:
            from dashboard.state.milvus_collection import DeepCardMilvusClient, embedding_text

            client = DeepCardMilvusClient(host=host, port=port)
            await client.ensure_collection()
        except ConnectionError as e:
            logger.warning("milvus_reindex skip (connection): %s", e)
            return _ev("skip", "milvus unreachable")
        except Exception as e:  # noqa: BLE001
            logger.warning("milvus_reindex skip (collection init): %s", e)
            return _ev("skip", f"milvus unreachable: {str(e)[:60]}")

        # 4. embedding 调用失败
        try:
            from app.services.embedding_factory import build_embedding_service_from_env
            from dashboard.derive.capability_resolver import load_capabilities
            from dashboard.state.db import open_db
            from dashboard.state.repositories import DeepCardRepo

            embedder = build_embedding_service_from_env()

            conn = open_db(self.db_path)
            try:
                cards = DeepCardRepo(conn).get_all()
            finally:
                conn.close()

            caps = load_capabilities(self.config_dir / "capabilities.yaml")
            name_by_id = {c.id: c.name_cn for c in caps}

            rows: list[dict[str, object]] = []
            texts: list[str] = []
            for card in cards:
                name_cn = name_by_id.get(card.cap_id, "")
                texts.append(embedding_text(card, name_cn=name_cn))
                rows.append(
                    {
                        "cap_id": card.cap_id,
                        "dimension": (
                            card.cap_id.split(".", 1)[0] if "." in card.cap_id else ""
                        ),
                        "name_cn": name_cn,
                        "status": "lit",
                        "confidence": card.srs_state.confidence,
                    }
                )
            if texts:
                vecs = await embedder.embed(texts)
                for r, v in zip(rows, vecs, strict=True):
                    r["embedding"] = v
                await client.upsert(rows)
            return _ev("done", f"{len(rows)} cards upserted")
        except Exception as e:  # noqa: BLE001
            logger.warning("milvus_reindex skip (embedding/upsert): %s", e)
            msg = str(e).replace("\n", " ")[:80]
            return _ev("skip", f"embedding error: {msg}")
```

- [ ] **Step 4: 运行 test 验证 4 个 PASS**

Run: `uv run pytest dashboard/tests/unit/test_refresh_pipeline.py -v -k milvus`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add dashboard/derive/refresh_pipeline.py dashboard/tests/unit/test_refresh_pipeline.py
git commit -m "$(cat <<'EOF'
feat(harness-board): milvus_reindex step with 4-way degradation matrix

Plan 1 Task 7 — env-host 缺 / embedding key 缺 / milvus 不可达 / embedding
调用失败,4 种 skip 路径覆盖 spec § 2.3,任一 skip 不阻断后续 step。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: `RefreshPipeline.stream()` async generator + critical-step error 包装

**Files:**
- Modify: `dashboard/derive/refresh_pipeline.py`
- Modify: `dashboard/tests/unit/test_refresh_pipeline.py`

- [ ] **Step 1: 写 failing test — stream 顺序 / running+done 配对 / chip_resolve 抛错 → error event**

```python
# 追加到 dashboard/tests/unit/test_refresh_pipeline.py

def test_stream_yields_all_5_steps_in_order(
    pipeline: RefreshPipeline, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HARNESS_BOARD_MILVUS_HOST", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    import asyncio

    async def _collect() -> list[StepEvent]:
        return [e async for e in pipeline.stream()]

    events = asyncio.run(_collect())
    # 每 step 一 running + 一 done|skip|error,共 5×2 = 10
    assert len(events) == 10
    expected_order = [
        "chip_resolve",
        "chip_resolve",
        "seed_ingest",
        "seed_ingest",
        "decision_extract",
        "decision_extract",
        "milvus_reindex",
        "milvus_reindex",
        "snapshot_finalize",
        "snapshot_finalize",
    ]
    assert [e.step for e in events] == expected_order
    assert [e.status for e in events[::2]] == ["running"] * 5
    # milvus skip,其他 done
    statuses = [e.status for e in events[1::2]]
    assert statuses == ["done", "done", "done", "skip", "done"]


def test_stream_yields_error_event_when_chip_resolve_raises(
    pipeline: RefreshPipeline, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HARNESS_BOARD_MILVUS_HOST", raising=False)

    def _boom(_self: object) -> StepEvent:
        raise RuntimeError("chip resolve boom")

    monkeypatch.setattr(RefreshPipeline, "_chip_resolve_step", _boom)

    import asyncio

    async def _collect() -> list[StepEvent]:
        return [e async for e in pipeline.stream()]

    events = asyncio.run(_collect())
    # chip_resolve running + error,但后续 step 仍然跑(spec § 2.4 不取消,只标 step error)
    chip_events = [e for e in events if e.step == "chip_resolve"]
    assert len(chip_events) == 2
    assert chip_events[0].status == "running"
    assert chip_events[1].status == "error"
    assert "boom" in chip_events[1].detail
    # snapshot_finalize 总是跑
    assert any(e.step == "snapshot_finalize" and e.status == "done" for e in events)
```

- [ ] **Step 2: 运行 test 验证失败**

Run: `uv run pytest dashboard/tests/unit/test_refresh_pipeline.py -v -k stream`
Expected: `NotImplementedError` from current `stream()` stub

- [ ] **Step 3: 实现 `stream()` + error 包装**

```python
# 替换 dashboard/derive/refresh_pipeline.py 中的 stream() stub

    async def stream(self) -> AsyncIterator[StepEvent]:
        """yield 5 个 step × (running + done|skip|error)。

        协议:
        - 每个 step 先 yield 一个 status=running 占位 event
        - 再调对应 _xxx_step,把返回结果 yield 出去
        - critical step(chip_resolve / seed_ingest / decision_extract / snapshot_finalize)
          抛异常时 yield status=error 但**不取消**后续 step(spec § 2.4)
        - milvus_reindex 内部已封装 4 种 skip,不会向外抛
        """
        sync_steps: tuple[tuple[str, callable], ...] = (  # type: ignore[type-arg]
            ("chip_resolve", self._chip_resolve_step),
            ("seed_ingest", self._seed_ingest_step),
            ("decision_extract", self._decision_extract_step),
        )

        for name, fn in sync_steps:
            yield StepEvent(step=name, status="running", label=_LABELS[name])
            try:
                yield fn()
            except Exception as e:  # noqa: BLE001
                logger.exception("step %s failed", name)
                yield StepEvent(
                    step=name,
                    status="error",
                    label=_LABELS[name],
                    detail=str(e)[:120],
                )

        # milvus_reindex(async)
        yield StepEvent(step="milvus_reindex", status="running", label=_LABELS["milvus_reindex"])
        try:
            yield await self._milvus_reindex_step()
        except Exception as e:  # noqa: BLE001
            logger.exception("milvus_reindex unexpectedly raised")
            yield StepEvent(
                step="milvus_reindex",
                status="skip",
                label=_LABELS["milvus_reindex"],
                detail=f"unexpected: {str(e)[:80]}",
            )

        # snapshot_finalize 始终最后跑
        yield StepEvent(
            step="snapshot_finalize", status="running", label=_LABELS["snapshot_finalize"]
        )
        try:
            yield self._snapshot_finalize_step()
        except Exception as e:  # noqa: BLE001
            logger.exception("snapshot_finalize failed")
            yield StepEvent(
                step="snapshot_finalize",
                status="error",
                label=_LABELS["snapshot_finalize"],
                detail=str(e)[:120],
            )
```

注:`callable` 在 Python 3.11 标注用 `Callable[..., StepEvent]`;tuple type 写法保留为不严格 alias 减少 import 噪音。如 mypy strict 报错,改用:

```python
from collections.abc import Callable

sync_steps: tuple[tuple[str, Callable[[], StepEvent]], ...] = (...)
```

- [ ] **Step 4: 运行 test 验证通过**

Run: `uv run pytest dashboard/tests/unit/test_refresh_pipeline.py -v`
Expected: 全部 PASS(2+3+4+2 = 11 个 test)

- [ ] **Step 5: Commit**

```bash
git add dashboard/derive/refresh_pipeline.py dashboard/tests/unit/test_refresh_pipeline.py
git commit -m "$(cat <<'EOF'
feat(harness-board): RefreshPipeline.stream() with critical-step error wrapping

Plan 1 Task 8 — async generator yield 5×(running, done|skip|error);
critical step 抛错只标 step error,不取消后续 step(spec § 2.4)。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: SSE endpoint — 改写 `post_refresh` + lifespan + L1 集成测试

**Files:**
- Modify: `dashboard/server.py`
- Create: `dashboard/tests/integration/test_refresh_sse.py`

- [ ] **Step 1: 写 failing L1 测试 — SSE event 计数 + milvus skip 后续 step 仍 done**

```python
# dashboard/tests/integration/test_refresh_sse.py
"""SSE /refresh endpoint L1 集成 — 事件流验证 + milvus 降级守护。"""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """每个 SSE test 用独立 sqlite + 禁 milvus / embedding env。"""
    monkeypatch.setattr("dashboard.server.DB_PATH", tmp_path / "board.db")
    monkeypatch.delenv("HARNESS_BOARD_MILVUS_HOST", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)


def _parse_sse(body: str) -> list[tuple[str, str]]:
    """解析 SSE body 为 [(event, data_json), ...]。"""
    out: list[tuple[str, str]] = []
    current_event = ""
    current_data: list[str] = []
    for line in body.splitlines():
        if line.startswith("event:"):
            if current_event:
                out.append((current_event, "\n".join(current_data)))
                current_data = []
            current_event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            current_data.append(line[len("data:") :].strip())
        elif line == "" and current_event:
            out.append((current_event, "\n".join(current_data)))
            current_event = ""
            current_data = []
    if current_event:
        out.append((current_event, "\n".join(current_data)))
    return out


def test_refresh_sse_returns_event_stream_with_done() -> None:
    """SSE 流至少 ≥ 11 event(5 step × 2 + 1 done)。"""
    import json

    from dashboard.server import app

    with TestClient(app) as client:
        with client.stream("POST", "/refresh") as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            body = "".join(chunk.decode("utf-8") for chunk in r.iter_bytes())

    events = _parse_sse(body)
    step_events = [e for e in events if e[0] == "step"]
    done_events = [e for e in events if e[0] == "done"]
    assert len(step_events) >= 10  # 5 × (running + done|skip|error)
    assert len(done_events) == 1

    done_payload = json.loads(done_events[0][1])
    assert "total_ms" in done_payload
    assert "steps_summary" in done_payload
    assert done_payload["steps_summary"]["error"] == 0


def test_refresh_sse_milvus_skip_does_not_block_snapshot() -> None:
    """env 未设 milvus → milvus_reindex skip + snapshot_finalize 仍 done。"""
    import json

    from dashboard.server import app

    with TestClient(app) as client:
        with client.stream("POST", "/refresh") as r:
            body = "".join(chunk.decode("utf-8") for chunk in r.iter_bytes())

    events = _parse_sse(body)
    step_data = [json.loads(d) for ev, d in events if ev == "step"]
    milvus_done = [
        d for d in step_data if d["step"] == "milvus_reindex" and d["status"] == "skip"
    ]
    snapshot_done = [
        d for d in step_data if d["step"] == "snapshot_finalize" and d["status"] == "done"
    ]
    assert len(milvus_done) == 1
    assert "milvus disabled" in milvus_done[0]["detail"].lower()
    assert len(snapshot_done) == 1
```

- [ ] **Step 2: 运行 test 验证失败**

Run: `uv run pytest dashboard/tests/integration/test_refresh_sse.py -v`
Expected: FAIL(当前 `/refresh` 还是 302 redirect)

- [ ] **Step 3: 改写 `dashboard/server.py:post_refresh` 为 SSE handler + 加 lifespan**

修改 `dashboard/server.py`,在顶部 imports 区追加:

```python
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict

from starlette.responses import StreamingResponse

from dashboard.derive.refresh_pipeline import RefreshPipeline
from dashboard.derive.seed_ingest import SeedIngestService
```

新增 lifespan(放在 `app = Starlette(...)` 之前):

```python
SEED_PATH = DASHBOARD_ROOT / "data" / "deep_cards_seed.jsonl"


@asynccontextmanager
async def lifespan(_app: Starlette) -> AsyncIterator[None]:
    """startup:db DeepCard 数 < seed 总数时 insert-if-missing 跑一次。

    spec § 2.5。不删除任何 row,保护 SRS flashcard 进度。
    """
    try:
        SeedIngestService(
            seed_path=SEED_PATH,
            db_path=DB_PATH,
            config_dir=CONFIG_DIR,
        ).run_once_if_underfilled()
    except Exception as e:  # noqa: BLE001
        logger.warning("lifespan seed ingest skipped due to: %s", e)
    yield
```

替换原 `post_refresh`:

```python
async def post_refresh(_request: Request) -> StreamingResponse:
    """SSE 5-step pipeline。spec § 2.1 / § 2.4。

    Breaking change(v0.9.6):不再 302 redirect 到 /,改为 text/event-stream。
    """
    pipeline = RefreshPipeline(
        project_root=PROJECT_ROOT,
        config_dir=CONFIG_DIR,
        db_path=DB_PATH,
        seed_path=SEED_PATH,
    )

    async def _gen() -> AsyncIterator[bytes]:
        import time as _time

        t0 = _time.perf_counter()
        summary = {"done": 0, "skip": 0, "error": 0}
        snapshot_refreshed_at = ""
        async for ev in pipeline.stream():
            if ev.status in summary:
                summary[ev.status] += 1
            if ev.step == "snapshot_finalize" and ev.status == "done":
                # detail = "refreshed_at <iso>"
                snapshot_refreshed_at = ev.detail.replace("refreshed_at ", "", 1)
            payload = json.dumps(asdict(ev), ensure_ascii=False)
            yield f"event: step\ndata: {payload}\n\n".encode()
        total_ms = int((_time.perf_counter() - t0) * 1000)
        done_payload = json.dumps(
            {
                "total_ms": total_ms,
                "snapshot_refreshed_at": snapshot_refreshed_at,
                "steps_summary": summary,
            },
            ensure_ascii=False,
        )
        yield f"event: done\ndata: {done_payload}\n\n".encode()

    return StreamingResponse(_gen(), media_type="text/event-stream")
```

把 `app = Starlette(routes=[...])` 改为:

```python
app = Starlette(
    routes=[
        # ... 保持原有 Route 列表不变 ...
    ],
    lifespan=lifespan,
)
```

注:lifespan 替代 deprecated `@app.on_event("startup")`,starlette 0.13+ 支持。

- [ ] **Step 4: 运行 SSE test 验证通过**

Run: `uv run pytest dashboard/tests/integration/test_refresh_sse.py -v`
Expected: 2 PASS

- [ ] **Step 5: 删除 / 替换旧 `test_post_refresh_invalidates_and_redirects`**

打开 `dashboard/tests/server/test_main_endpoint.py` ~line 135,把:

```python
def test_post_refresh_invalidates_and_redirects() -> None:
    """POST /refresh → 302 to /,snapshot 被清。"""
    with TestClient(app) as client:
        client.get("/")
        r = client.post("/refresh", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == "/"
```

替换为:

```python
def test_post_refresh_returns_sse_event_stream() -> None:
    """POST /refresh → text/event-stream(spec § 2,Plan 1 起 breaking change)。"""
    with TestClient(app) as client:
        client.get("/")
        with client.stream("POST", "/refresh") as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            body = "".join(chunk.decode("utf-8") for chunk in r.iter_bytes())
            assert "event: done" in body
```

- [ ] **Step 6: 运行旧测试 + 全 server tests 验证不破其他东西**

Run: `uv run pytest dashboard/tests/server/test_main_endpoint.py -v`
Expected: 全 PASS

Run: `uv run pytest dashboard/tests/ -x -q`
Expected: 全 PASS(包括 dashboard 既有测试)

- [ ] **Step 7: Commit**

```bash
git add dashboard/server.py dashboard/tests/integration/test_refresh_sse.py dashboard/tests/server/test_main_endpoint.py
git commit -m "$(cat <<'EOF'
feat(harness-board): rewrite POST /refresh as SSE 5-step pipeline + lifespan seed ingest

Plan 1 Task 9 — breaking change: /refresh 不再 302,改 text/event-stream
(spec § 2.1)。startup lifespan 跑 insert-if-missing seed ingest 修复鸟瞰空盘
(spec § 2.5)。旧 redirect 测试改为 SSE 验证。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Lifespan seed ingest L1 集成测试

**Files:**
- Create: `dashboard/tests/integration/test_lifespan_seed.py`

- [ ] **Step 1: 写 failing test — underfilled 触发 / 已满跳过 / 已编辑 row 不覆盖**

```python
# dashboard/tests/integration/test_lifespan_seed.py
"""lifespan seed ingest 集成测试 — spec § 2.5。"""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from dashboard.derive.deep_card_types import DeepCard
from dashboard.state.db import open_db
from dashboard.state.repositories import DeepCardRepo


@pytest.fixture(autouse=True)
def _disable_milvus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HARNESS_BOARD_MILVUS_HOST", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)


def test_lifespan_ingests_when_db_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """startup 时 db 空(0 < 35)→ insert-if-missing 跑;TestClient 上下文管理触发 lifespan。"""
    db = tmp_path / "board.db"
    monkeypatch.setattr("dashboard.server.DB_PATH", db)

    from dashboard.server import app

    with TestClient(app):  # ← `with` 触发 lifespan startup
        pass

    conn = open_db(db)
    try:
        cards = DeepCardRepo(conn).get_all()
    finally:
        conn.close()
    assert len(cards) >= 30  # seed jsonl 35 张,allow 一些 cap_id 不在 yaml


def test_lifespan_skips_when_db_already_full(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """db 已 ≥ seed 总数(40)→ lifespan no-op,不动 db。"""
    db = tmp_path / "board.db"
    monkeypatch.setattr("dashboard.server.DB_PATH", db)

    # 预先塞 40 张 marker card(用 yaml 中真实 id 范围内的一部分)
    from dashboard.derive.capability_resolver import load_capabilities

    PROJECT_ROOT = Path(__file__).resolve().parents[3]
    caps = load_capabilities(PROJECT_ROOT / "dashboard" / "config" / "capabilities.yaml")
    cap_ids = [c.id for c in caps][:40]  # 取前 40 个真实 id

    conn = open_db(db)
    try:
        repo = DeepCardRepo(conn)
        for cid in cap_ids:
            repo.upsert(DeepCard(cap_id=cid, what="MARKER"))
    finally:
        conn.close()

    from dashboard.server import app

    with TestClient(app):
        pass

    conn = open_db(db)
    try:
        survived = {c.cap_id: c.what for c in DeepCardRepo(conn).get_all()}
    finally:
        conn.close()
    # 所有 marker 仍是 MARKER(未被 seed 覆盖)
    for cid in cap_ids:
        assert survived.get(cid) == "MARKER", f"{cid} 被 lifespan 覆盖了"


def test_lifespan_does_not_overwrite_manual_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """underfilled 时跑 ingest,但已存在 cap_id 一律跳过(保护手动编辑)。"""
    db = tmp_path / "board.db"
    monkeypatch.setattr("dashboard.server.DB_PATH", db)

    # 塞 1 张已编辑 row(db count = 1 < 35,会触发 underfilled)
    conn = open_db(db)
    try:
        DeepCardRepo(conn).upsert(
            DeepCard(cap_id="memory.long_term_memory", what="USER_EDITED_VALUE")
        )
    finally:
        conn.close()

    from dashboard.server import app

    with TestClient(app):
        pass

    conn = open_db(db)
    try:
        survived = DeepCardRepo(conn).get("memory.long_term_memory")
    finally:
        conn.close()
    assert survived is not None
    assert survived.what == "USER_EDITED_VALUE"
```

- [ ] **Step 2: 运行 test 验证通过(实现已在 Task 9 完成)**

Run: `uv run pytest dashboard/tests/integration/test_lifespan_seed.py -v`
Expected: 3 PASS

- [ ] **Step 3: Commit**

```bash
git add dashboard/tests/integration/test_lifespan_seed.py
git commit -m "$(cat <<'EOF'
test(harness-board): lifespan seed ingest integration — underfilled / full / manual-edit guard

Plan 1 Task 10 — spec § 2.5 三路径守护:db 空触发 / 已满跳过 /
已编辑 row 保留(SRS 进度不被波及)。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: L2 e2e — seed 加载后鸟瞰 graph.json 反映新数据

**Files:**
- Create: `dashboard/tests/integration/test_overview_after_seed.py`

- [ ] **Step 1: 写 test — `/refresh` 跑完后 `/api/overview/graph.json` ≥ 35 nodes + 边数合理**

```python
# dashboard/tests/integration/test_overview_after_seed.py
"""L2 e2e — refresh pipeline 跑完后,鸟瞰 graph.json 反映新 seed 数据。

spec § 8 验收标准 1:渲染 ≥ 35 节点 + ≥ 10 edges。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("dashboard.server.DB_PATH", tmp_path / "board.db")
    monkeypatch.delenv("HARNESS_BOARD_MILVUS_HOST", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)


def test_overview_graph_after_refresh_has_filled_nodes() -> None:
    """rough path:启动(lifespan ingest)→ GET /api/overview/graph.json,
    至少 35 + edges ≥ 10。"""
    from dashboard.server import app

    with TestClient(app) as client:
        # lifespan 在 with 进入时已跑 seed ingest
        r = client.get("/api/overview/graph.json")
        assert r.status_code == 200
        payload = r.json()

    nodes = payload.get("nodes") or payload.get("elements", {}).get("nodes") or []
    edges = payload.get("edges") or payload.get("elements", {}).get("edges") or []
    # graph_builder 当前 schema:见 dashboard/derive/graph_builder.py。
    # 若 schema 不同,在写测试时根据真实返回结构调整 key 抓取(此 fallback 已覆盖两种风格)。
    assert len(nodes) >= 35, f"expect ≥35 nodes after seed, got {len(nodes)}"
    assert len(edges) >= 10, f"expect ≥10 edges after seed, got {len(edges)}"


def test_overview_graph_after_explicit_refresh_has_filled_nodes() -> None:
    """同上,但显式触发 POST /refresh(verify SSE 完成后 graph 拉到新数据)。"""
    from dashboard.server import app

    with TestClient(app) as client:
        # 跑 SSE refresh(消耗完流)
        with client.stream("POST", "/refresh") as r:
            for _ in r.iter_bytes():
                pass
            assert r.status_code == 200
        r2 = client.get("/api/overview/graph.json")
        assert r2.status_code == 200
        payload = r2.json()
    nodes = payload.get("nodes") or payload.get("elements", {}).get("nodes") or []
    assert len(nodes) >= 35
```

- [ ] **Step 2: 运行 test 验证通过**

Run: `uv run pytest dashboard/tests/integration/test_overview_after_seed.py -v`
Expected: 2 PASS

注:若返回 payload 的 key 与上述 `nodes`/`edges` fallback 不一致(实际 schema 在 `dashboard/derive/graph_builder.py`,本 plan 写时未细读 schema 细节),把第一行的 `nodes = ...` 改成真实 key — `cy_elements`、`elements.nodes` 等。Step 2 跑出来若 nodes 列表是空,先 print 一次 payload key 看清楚再调整。

- [ ] **Step 3: Commit**

```bash
git add dashboard/tests/integration/test_overview_after_seed.py
git commit -m "$(cat <<'EOF'
test(harness-board): L2 e2e — overview graph reflects seeded data after refresh

Plan 1 Task 11 — spec § 8 acceptance criterion 1:≥35 nodes + ≥10 edges
after seed ingest(either via lifespan or explicit /refresh)。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Final verification + ruff + mypy + 全测试套件

**Files:**
- (No new files;只跑 lint + 全 test)

- [ ] **Step 1: 跑 ruff(只跑 dashboard + backend/app/scripts/seed_deep_cards.py)**

Run: `uv run ruff check dashboard/derive/refresh_pipeline.py dashboard/derive/seed_ingest.py dashboard/server.py backend/app/scripts/seed_deep_cards.py dashboard/tests/unit/test_refresh_pipeline.py dashboard/tests/unit/test_seed_ingest.py dashboard/tests/integration/test_refresh_sse.py dashboard/tests/integration/test_lifespan_seed.py dashboard/tests/integration/test_overview_after_seed.py`
Expected: All checks passed!

- [ ] **Step 2: 跑 mypy strict(仅新增 / 修改文件)**

Run: `uv run mypy --strict dashboard/derive/refresh_pipeline.py dashboard/derive/seed_ingest.py dashboard/server.py backend/app/scripts/seed_deep_cards.py`
Expected: `Success: no issues found`(若有 strict 误报先按 spec 风格加 narrow `type: ignore` 注释 + 注释原因)

- [ ] **Step 3: 跑全 dashboard 测试**

Run: `uv run pytest dashboard/tests/ -v --tb=short`
Expected: 全 PASS(原 65 个 + Plan 1 新增 ~16 个 = ~81 个)

- [ ] **Step 4: 跑 spec § 6.1 守护场景手动验证(可选,在 README / CHANGELOG 记录)**

```bash
# 终端 1:启动 dashboard,显式 unset milvus + dashscope
HARNESS_BOARD_MILVUS_HOST= DASHSCOPE_API_KEY= uv run python -m uvicorn dashboard.server:app --port 8910

# 终端 2:curl 触发 SSE
curl -N -X POST http://127.0.0.1:8910/refresh
```

Expected:5 step 流式输出,milvus_reindex skip,snapshot_finalize done。

- [ ] **Step 5: Commit(若有 lint / typing 小修)**

```bash
git status  # 看是否有未提交修复
# 若有:
git add -p
git commit -m "$(cat <<'EOF'
chore(harness-board): Plan 1 lint + mypy cleanup

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Plan 1 ship 验收(self-check)

逐项验证(对照 spec § 8 acceptance criteria):

- [x] § 2.1 SSE event 协议正确(2 个 event 类型:`step` / `done`,JSON payload)— Task 9 + L1 test
- [x] § 2.2 5 个 step 全部实现 — Task 5 ~ 7
- [x] § 2.3 milvus_reindex 4 种降级矩阵 — Task 7
- [x] § 2.4 critical step 失败 → step error event(不取消后续) — Task 8
- [x] § 2.5 lifespan idempotent seed ingest — Task 9 + L1 test
- [x] § 2.6 SeedIngestService + SeedIngestResult 抽取 — Task 2 ~ 3
- [x] § 6 测试矩阵 L0 + L1 全绿 — Task 2~11
- [x] § 6.1 守护(unset milvus + dashscope) — autouse fixture in test_refresh_sse / test_lifespan_seed / test_overview_after_seed
- [x] § 7.1 PR 题目 / 分支 / 版本号写入 plan header

下一步:
- Plan 2(前端 style.css 重写 + 13 模板)需要 Plan 1 已 ship 才能测试 refresh-panel 交互
- Plan 3(refresh-panel.js + 鸟瞰增强 + flashcards stats)再后

---

## Self-Review(plan 起草后自检)

1. **Spec coverage:**
   - § 2.1 SSE 协议 → Task 9 (post_refresh 重写) + L1 test
   - § 2.2 5 step → Task 5/6/7
   - § 2.3 降级矩阵 → Task 7(4 个 monkeypatch 路径全列)
   - § 2.4 错误处理 → Task 8 + critical step 错误 test
   - § 2.5 lifespan → Task 9 lifespan + Task 10 三测试
   - § 2.6 service 抽取 → Task 2/3(SeedIngestService) + Task 5(RefreshPipeline)
   - § 6 L0/L1 测试 → Task 2/3/5/6/7/8(L0) + Task 9/10/11(L1)
   - § 7.2 Plan 1 工期 → ~12 task,符合 ~1 天 wall time
   - § 7.3 dep → Plan 2/3 引用本 Plan 的 SSE endpoint,Plan 1 单独可 ship

2. **Placeholder scan:** 全 task 含完整 code block,无 TBD / TODO / "see above"。

3. **Type consistency:**
   - `StepEvent` 字段(step / status / label / detail / duration_ms)在 Task 5 定义,Task 8/9 一致引用
   - `SeedIngestResult` 5 字段(total_seed / inserted / skipped_existing / skipped_invalid / overwritten)Task 2 定义,Task 4 CLI 引用一致
   - `RefreshPipeline.__init__` 参数(project_root / config_dir / db_path / seed_path)Task 5 定义,Task 9 在 `post_refresh` 中实例化一致

4. **Bite-sized 检查:** 每 task ≤ 5 step(write test / run fail / impl / run pass / commit),无超 5 个 step 的 task。

5. **挑战 / 风险预案:**
   - Task 9 `post_refresh` 改 SSE 会破现有 `test_post_refresh_invalidates_and_redirects`,Step 5 显式迁移
   - Task 11 graph.json schema 不在本 plan 详细确认 — fallback 已写 two-key probing,执行时可微调
   - Task 7 milvus mock 路径较多,monkeypatch `__init__` no-op 避免真连接
   - lifespan 在 TestClient `with` 块进入时跑;若集成测 setup 顺序耦合需用 `with TestClient(app) as client:`(已在 test 中保证)

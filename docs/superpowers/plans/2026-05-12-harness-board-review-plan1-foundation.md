# Harness Board Review Mode — Plan 1: Foundation + V2 模块深读

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** [`docs/superpowers/specs/2026-05-12-harness-board-review-mode-design.md`](../specs/2026-05-12-harness-board-review-mode-design.md)

**Goal:** 落地 DeepCard 统一底座 + V2 模块深读视图(chip 翻 modal),把 B(onboard 自己)+ C(模块化深读)两个核心复习场景一次性走通。

**Architecture:** 沿用 Harness Board 现有 Starlette + Jinja + htmx + sqlite 栈,新增 `deep_cards` / `flashcards` 表 + Milvus collection `harness_board_deepcards` + `prefill_deep_cards.py` batch CLI(constrained JSON schema + provenance fuzzy match 防幻觉)。V2 modal 用 htmx swap,inline 编辑沿用 OverrideRepo 模式。

**Tech Stack:** Python 3.11 / Starlette / Jinja2 / htmx / sqlite / Milvus(pymilvus 2.5+)/ qwen text-embedding-v3 / pytest / mypy strict / ruff

**Plan 1 ship checklist 摘要(完整版见 spec § 14):**
- sqlite schema migration 跑通
- `prefill_deep_cards.py` batch 跑通 ≥ 10 cap,provenance 命中率 ≥ 90%
- Milvus collection 创建 + DeepCard upsert path 工作(Milvus 不可用时 endpoint 不 500)
- V1 chip 角标 + confidence 显示正常
- V2 modal 翻面 + inline 编辑 + AI 草拟按钮 + provenance UI
- dashboard 现有 65 测试不破 + 新增 +30 L0 / +15 L1 / +5 cassette PASS
- mypy strict + ruff clean

---

## File Structure(Plan 1 范围)

**新建:**
- `dashboard/derive/deep_card_types.py` — DeepCard / Flashcard / Provenance Pydantic / dataclass 类型
- `dashboard/derive/provenance.py` — fuzzy substring match 校验
- `dashboard/derive/llm_prefill_prompt.py` — prompt builder + constrained schema
- `dashboard/derive/completion.py` — 完成度计算(用于 V1 chip 角标)
- `dashboard/state/milvus_collection.py` — Milvus collection schema + upsert + 相关推荐
- `dashboard/state/keyword_recommender.py` — 相关推荐 keyword fallback
- `dashboard/templates/_deep_card_modal.html` — V2 modal 主模板
- `dashboard/templates/_deep_card_field.html` — V2 modal 内单字段子模板(htmx target)
- `dashboard/templates/_ai_draft_button.html` — AI 草拟按钮子模板
- `backend/scripts/prefill_deep_cards.py` — batch CLI
- `dashboard/tests/unit/test_deep_card_types.py` / `test_provenance.py` / `test_llm_prefill_prompt.py` / `test_completion.py` / `test_keyword_recommender.py`
- `dashboard/tests/integration/test_deep_card_repo.py` / `test_milvus_collection.py` / `test_v2_modal_endpoint.py` / `test_ai_draft_endpoint.py`
- `dashboard/tests/e2e/cassettes/prefill_*.yaml`(5 cap × cassette)
- `dashboard/tests/e2e/test_prefill_cassette.py`

**修改:**
- `dashboard/state/db.py` — SCHEMA 加 deep_cards + flashcards CREATE TABLE
- `dashboard/state/repositories.py` — 加 `DeepCardRepo` / `FlashcardRepo`(skeleton)
- `dashboard/server.py` — 加 6 个 route(`GET /cap/{id}` / `POST /cap/{id}/field/{name}` / `POST /cap/{id}/ai_draft/{name}` / `GET /cap/{id}/related` / `POST /cap/{id}/prefill_all` / Milvus health)
- `dashboard/templates/_capability_chip.html` — 加 完成度角标 + confidence 数字 slot
- `dashboard/static/style.css` — 加 chip 角标 / modal 双栏 / provenance 边框 CSS
- `Makefile` — 加 `make prefill` target

---

## Task 1: DeepCard / Flashcard / Provenance 类型定义

**Files:**
- Create: `dashboard/derive/deep_card_types.py`
- Test: `dashboard/tests/unit/test_deep_card_types.py`

- [ ] **Step 1: Write the failing test**

```python
# dashboard/tests/unit/test_deep_card_types.py
"""DeepCard / Flashcard / Provenance 类型验证。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dashboard.derive.deep_card_types import (
    AlternativeItem,
    CodeAnchor,
    DeepCard,
    FieldProvenance,
    Flashcard,
    SrsState,
)


def test_deep_card_minimal_fields() -> None:
    """空 DeepCard 只需 cap_id;其他全部 optional。"""
    card = DeepCard(cap_id="01.constrained_schema")
    assert card.cap_id == "01.constrained_schema"
    assert card.what is None
    assert card.alternatives == []
    assert card.srs_state.confidence == 0
    assert card.prefill_source == "manual"


def test_deep_card_full_fields_roundtrip() -> None:
    card = DeepCard(
        cap_id="01.constrained_schema",
        what="LLM 输出强制走 JSON schema",
        why="避免自由生成导致下游解析失败",
        alternatives=[
            AlternativeItem(name="free-text + regex 后处理", brief_tradeoff="易碎"),
            AlternativeItem(name="constrained JSON schema", brief_tradeoff="model 端约束"),
        ],
        chosen_alternative="constrained JSON schema",
        tradeoff="选 schema 因为 OpenAI 兼容协议原生支持 response_format",
        code_anchors=[CodeAnchor(file="backend/app/services/llm_service.py", line=78, note="schema kwarg")],
        linked_decisions=["abc123def456"],
        linked_specs=["docs/superpowers/specs/2026-05-05-v0.8.5-constrained-router-design.md"],
        linked_capabilities=["02.tool_registry"],
        provenance={
            "what": FieldProvenance(quote="LLM 输出强制走", source="docs/.../design.md#§2"),
        },
        srs_state=SrsState(confidence=3, ef=2.5, interval=4, repetition=2),
        prefill_source="hybrid",
    )
    dumped = card.model_dump_json()
    loaded = DeepCard.model_validate_json(dumped)
    assert loaded == card


def test_alternatives_items_have_required_fields() -> None:
    with pytest.raises(ValidationError):
        AlternativeItem(name="x")  # type: ignore[call-arg]  # missing brief_tradeoff


def test_chosen_alternative_must_match_one_of_alternatives() -> None:
    """chosen_alternative 必须是 alternatives 中某 name(放宽:Pydantic 不强制,运行时校验)。"""
    card = DeepCard(
        cap_id="x",
        alternatives=[AlternativeItem(name="A", brief_tradeoff="a")],
        chosen_alternative="B",  # 不匹配 — Plan 1 仅 Pydantic 不报,Plan 3 闪卡生成时再校验
    )
    assert card.chosen_alternative == "B"


def test_srs_state_defaults() -> None:
    s = SrsState()
    assert s.confidence == 0
    assert s.ef == 2.5
    assert s.interval == 0
    assert s.repetition == 0
    assert s.last_reviewed_at is None
    assert s.next_review_at is None


def test_flashcard_minimal() -> None:
    f = Flashcard(
        id="01.constrained_schema::tradeoff",
        cap_id="01.constrained_schema",
        template_kind="tradeoff",
        question="什么 tradeoff?",
        answer="选 schema",
    )
    assert f.srs_state.confidence == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --project backend pytest dashboard/tests/unit/test_deep_card_types.py -v`
Expected: FAIL with `ModuleNotFoundError: dashboard.derive.deep_card_types`

- [ ] **Step 3: Implement types**

```python
# dashboard/derive/deep_card_types.py
"""DeepCard / Flashcard / Provenance 类型。spec § 4.1。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PrefillSource = Literal["llm", "manual", "hybrid"]
TemplateKind = Literal["alternatives", "tradeoff", "lessons"]


class AlternativeItem(BaseModel):
    """alternatives 数组单项。"""

    model_config = ConfigDict(extra="forbid")
    name: str
    brief_tradeoff: str


class CodeAnchor(BaseModel):
    """关键代码入口。"""

    model_config = ConfigDict(extra="forbid")
    file: str
    line: int
    note: str = ""


class FieldProvenance(BaseModel):
    """单字段 provenance — quote + source。spec § 7.3。"""

    model_config = ConfigDict(extra="forbid")
    quote: str = Field(..., max_length=200)  # 30 字硬限太严,留 200 兜底
    source: str  # file path + optional #section


class SrsState(BaseModel):
    """SM-2 状态。"""

    model_config = ConfigDict(extra="forbid")
    confidence: int = Field(default=0, ge=0, le=5)
    ef: float = Field(default=2.5, ge=1.3)  # ease factor
    interval: int = 0  # days
    repetition: int = 0
    last_reviewed_at: datetime | None = None
    next_review_at: datetime | None = None


class DeepCard(BaseModel):
    """每个 capability 的深读卡。spec § 4.1。"""

    model_config = ConfigDict(extra="forbid")
    cap_id: str
    # 内容核心
    what: str | None = None
    why: str | None = None
    alternatives: list[AlternativeItem] = Field(default_factory=list)
    chosen_alternative: str | None = None
    tradeoff: str | None = None
    lessons_learned: str | None = None
    metrics: dict[str, str | float | int] = Field(default_factory=dict)
    # 链接图
    code_anchors: list[CodeAnchor] = Field(default_factory=list)
    linked_decisions: list[str] = Field(default_factory=list)
    linked_specs: list[str] = Field(default_factory=list)
    linked_memories: list[str] = Field(default_factory=list)
    linked_capabilities: list[str] = Field(default_factory=list)
    # SRS
    srs_state: SrsState = Field(default_factory=SrsState)
    # 防幻觉
    provenance: dict[str, FieldProvenance] = Field(default_factory=dict)
    # 元
    prefill_source: PrefillSource = "manual"
    prefill_at: datetime | None = None
    last_edited_at: datetime | None = None


class Flashcard(BaseModel):
    """从 DeepCard 派生的闪卡。spec § 5.5。"""

    model_config = ConfigDict(extra="forbid")
    id: str  # f"{cap_id}::{template_kind}"
    cap_id: str
    template_kind: TemplateKind
    question: str
    answer: str
    srs_state: SrsState = Field(default_factory=SrsState)
    created_at: datetime | None = None
    last_reviewed_at: datetime | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --project backend pytest dashboard/tests/unit/test_deep_card_types.py -v`
Expected: 6 passed

- [ ] **Step 5: mypy strict 检查**

Run: `uv run --project backend mypy dashboard/derive/deep_card_types.py dashboard/tests/unit/test_deep_card_types.py --strict`
Expected: Success: no issues found

- [ ] **Step 6: Commit**

```bash
git add dashboard/derive/deep_card_types.py dashboard/tests/unit/test_deep_card_types.py
git commit -m "feat(harness-review-plan1): DeepCard / Flashcard / Provenance 类型"
```

---

## Task 2: sqlite migration — deep_cards + flashcards 表

**Files:**
- Modify: `dashboard/state/db.py` (extend SCHEMA)
- Test: `dashboard/tests/integration/test_db_schema_v2.py`

- [ ] **Step 1: Write the failing test**

```python
# dashboard/tests/integration/test_db_schema_v2.py
"""v2 schema migration — deep_cards + flashcards 表幂等创建。"""

from __future__ import annotations

from pathlib import Path

from dashboard.state.db import open_db


def test_deep_cards_table_created(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    conn = open_db(db)
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='deep_cards'"
    )
    assert cur.fetchone() is not None


def test_flashcards_table_created(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    conn = open_db(db)
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='flashcards'"
    )
    assert cur.fetchone() is not None


def test_flashcards_indexes_created(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    conn = open_db(db)
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND name IN ('idx_flashcards_cap_id', 'idx_flashcards_next_review')"
    )
    rows = cur.fetchall()
    assert len(rows) == 2


def test_schema_idempotent(tmp_path: Path) -> None:
    """open_db 跑两次不抛"""
    db = tmp_path / "test.db"
    open_db(db).close()
    conn = open_db(db)
    assert conn is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --project backend pytest dashboard/tests/integration/test_db_schema_v2.py -v`
Expected: 3 fails (table/index missing)

- [ ] **Step 3: Extend SCHEMA in `dashboard/state/db.py`**

```python
# dashboard/state/db.py — replace SCHEMA constant
SCHEMA = """
CREATE TABLE IF NOT EXISTS derived_snapshot (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  refreshed_at TEXT NOT NULL,
  payload TEXT NOT NULL
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

CREATE TABLE IF NOT EXISTS deep_cards (
  cap_id TEXT PRIMARY KEY,
  payload TEXT NOT NULL,           -- 全 DeepCard 序列化 JSON
  last_edited_at TEXT NOT NULL
);

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
"""
```

**注意**:DeepCard 用单 `payload` JSON 列(spec § 4.1 字段多,逐列存映射成本高;sqlite < 1M 数据 JSON 检索性能足够;PK 仍是 cap_id)。

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --project backend pytest dashboard/tests/integration/test_db_schema_v2.py -v`
Expected: 4 passed

- [ ] **Step 5: 现有 65 测试不破**

Run: `uv run --project backend pytest dashboard/tests/ -v`
Expected: 65 + 4 = 69 passed

- [ ] **Step 6: Commit**

```bash
git add dashboard/state/db.py dashboard/tests/integration/test_db_schema_v2.py
git commit -m "feat(harness-review-plan1): sqlite schema v2 — deep_cards + flashcards + prefill_log"
```

---

## Task 3: DeepCardRepo (CRUD)

**Files:**
- Modify: `dashboard/state/repositories.py`
- Test: `dashboard/tests/integration/test_deep_card_repo.py`

- [ ] **Step 1: Write the failing test**

```python
# dashboard/tests/integration/test_deep_card_repo.py
from __future__ import annotations

from pathlib import Path

from dashboard.derive.deep_card_types import (
    AlternativeItem,
    DeepCard,
    FieldProvenance,
)
from dashboard.state.db import open_db
from dashboard.state.repositories import DeepCardRepo


def test_upsert_and_get(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "t.db")
    repo = DeepCardRepo(conn)
    card = DeepCard(
        cap_id="01.constrained_schema",
        what="LLM JSON 强制",
        alternatives=[AlternativeItem(name="A", brief_tradeoff="a")],
        chosen_alternative="A",
        prefill_source="manual",
    )
    repo.upsert(card)
    got = repo.get("01.constrained_schema")
    assert got is not None
    assert got.cap_id == card.cap_id
    assert got.what == "LLM JSON 强制"
    assert got.alternatives[0].name == "A"


def test_get_missing_returns_none(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "t.db")
    repo = DeepCardRepo(conn)
    assert repo.get("nope") is None


def test_upsert_overwrites(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "t.db")
    repo = DeepCardRepo(conn)
    repo.upsert(DeepCard(cap_id="x", what="v1"))
    repo.upsert(DeepCard(cap_id="x", what="v2"))
    got = repo.get("x")
    assert got is not None and got.what == "v2"


def test_update_field_partial(tmp_path: Path) -> None:
    """update_field 只改一个字段,其他不动 + 自动转 prefill_source。"""
    conn = open_db(tmp_path / "t.db")
    repo = DeepCardRepo(conn)
    repo.upsert(DeepCard(cap_id="x", what="seed", prefill_source="llm"))
    repo.update_field("x", "what", "edited")
    got = repo.get("x")
    assert got is not None
    assert got.what == "edited"
    assert got.prefill_source == "hybrid"  # llm 后人改 → hybrid


def test_update_field_manual_to_manual(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "t.db")
    repo = DeepCardRepo(conn)
    repo.upsert(DeepCard(cap_id="x", prefill_source="manual"))  # what=None
    repo.update_field("x", "what", "first manual fill")
    got = repo.get("x")
    assert got is not None and got.prefill_source == "manual"


def test_get_all_returns_all(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "t.db")
    repo = DeepCardRepo(conn)
    repo.upsert(DeepCard(cap_id="a"))
    repo.upsert(DeepCard(cap_id="b"))
    cards = repo.get_all()
    assert {c.cap_id for c in cards} == {"a", "b"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --project backend pytest dashboard/tests/integration/test_deep_card_repo.py -v`
Expected: ImportError DeepCardRepo

- [ ] **Step 3: Implement DeepCardRepo**

```python
# dashboard/state/repositories.py — append at bottom

from __future__ import annotations

# ... existing imports + classes ...

from dashboard.derive.deep_card_types import DeepCard, PrefillSource


class DeepCardRepo:
    """sqlite CRUD for deep_cards。spec § 6.1。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get(self, cap_id: str) -> DeepCard | None:
        cur = self.conn.execute(
            "SELECT payload FROM deep_cards WHERE cap_id = ?", (cap_id,)
        )
        row = cur.fetchone()
        if not row:
            return None
        return DeepCard.model_validate_json(row["payload"])

    def get_all(self) -> list[DeepCard]:
        cur = self.conn.execute("SELECT payload FROM deep_cards ORDER BY cap_id")
        return [DeepCard.model_validate_json(r["payload"]) for r in cur.fetchall()]

    def upsert(self, card: DeepCard) -> None:
        now = datetime.now(UTC).isoformat()
        payload = card.model_dump_json()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO deep_cards (cap_id, payload, last_edited_at)
                VALUES (?, ?, ?)
                ON CONFLICT(cap_id) DO UPDATE SET
                  payload = excluded.payload,
                  last_edited_at = excluded.last_edited_at
                """,
                (card.cap_id, payload, now),
            )

    def update_field(self, cap_id: str, field_name: str, value: object) -> None:
        """改单个字段。自动转 prefill_source:
        llm + 人改 → hybrid
        manual + 人改 → manual
        hybrid + 人改 → hybrid (no-op)
        """
        card = self.get(cap_id) or DeepCard(cap_id=cap_id)
        if not hasattr(card, field_name):
            raise KeyError(f"DeepCard has no field {field_name}")
        new_data = card.model_dump()
        new_data[field_name] = value
        new_data["last_edited_at"] = datetime.now(UTC).isoformat()
        if card.prefill_source == "llm":
            new_data["prefill_source"] = "hybrid"
        updated = DeepCard.model_validate(new_data)
        self.upsert(updated)

    def mark_ai_drafted(self, cap_id: str, field_name: str) -> None:
        """AI 草拟单字段成功后调:prefill_source = llm (覆盖 manual)"""
        card = self.get(cap_id) or DeepCard(cap_id=cap_id)
        new_data = card.model_dump()
        new_data["prefill_source"] = "llm"
        new_data["prefill_at"] = datetime.now(UTC).isoformat()
        self.upsert(DeepCard.model_validate(new_data))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --project backend pytest dashboard/tests/integration/test_deep_card_repo.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add dashboard/state/repositories.py dashboard/tests/integration/test_deep_card_repo.py
git commit -m "feat(harness-review-plan1): DeepCardRepo CRUD + prefill_source 转换"
```

---

## Task 4: FlashcardRepo (skeleton — Plan 3 完善 SRS 逻辑)

**Files:**
- Modify: `dashboard/state/repositories.py`
- Test: `dashboard/tests/integration/test_flashcard_repo.py`

- [ ] **Step 1: Write the failing test**

```python
# dashboard/tests/integration/test_flashcard_repo.py
from __future__ import annotations

from pathlib import Path

from dashboard.derive.deep_card_types import Flashcard, SrsState
from dashboard.state.db import open_db
from dashboard.state.repositories import FlashcardRepo


def test_upsert_and_get(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "t.db")
    repo = FlashcardRepo(conn)
    fc = Flashcard(
        id="x::tradeoff",
        cap_id="x",
        template_kind="tradeoff",
        question="q?",
        answer="a",
    )
    repo.upsert(fc)
    got = repo.get("x::tradeoff")
    assert got is not None and got.question == "q?"


def test_get_by_cap_id(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "t.db")
    repo = FlashcardRepo(conn)
    repo.upsert(Flashcard(id="x::tradeoff", cap_id="x", template_kind="tradeoff",
                          question="q1", answer="a1"))
    repo.upsert(Flashcard(id="x::lessons", cap_id="x", template_kind="lessons",
                          question="q2", answer="a2"))
    cards = repo.get_by_cap_id("x")
    assert len(cards) == 2


def test_delete_by_cap_id(tmp_path: Path) -> None:
    """DeepCard 重生成闪卡时,需要先删旧的(template kind 没了)"""
    conn = open_db(tmp_path / "t.db")
    repo = FlashcardRepo(conn)
    repo.upsert(Flashcard(id="x::tradeoff", cap_id="x", template_kind="tradeoff",
                          question="q", answer="a"))
    repo.delete_by_cap_id("x")
    assert repo.get_by_cap_id("x") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --project backend pytest dashboard/tests/integration/test_flashcard_repo.py -v`
Expected: ImportError FlashcardRepo

- [ ] **Step 3: Implement FlashcardRepo**

```python
# dashboard/state/repositories.py — append

from dashboard.derive.deep_card_types import Flashcard


class FlashcardRepo:
    """sqlite CRUD for flashcards. Plan 1 仅 CRUD;SRS 算法在 Plan 3。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get(self, flashcard_id: str) -> Flashcard | None:
        cur = self.conn.execute(
            "SELECT id, cap_id, template_kind, question, answer, srs_state, "
            "created_at, last_reviewed_at FROM flashcards WHERE id = ?",
            (flashcard_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return self._row_to_fc(row)

    def get_by_cap_id(self, cap_id: str) -> list[Flashcard]:
        cur = self.conn.execute(
            "SELECT id, cap_id, template_kind, question, answer, srs_state, "
            "created_at, last_reviewed_at FROM flashcards WHERE cap_id = ?",
            (cap_id,),
        )
        return [self._row_to_fc(r) for r in cur.fetchall()]

    def upsert(self, fc: Flashcard) -> None:
        now = datetime.now(UTC).isoformat()
        created_at = fc.created_at.isoformat() if fc.created_at else now
        last = fc.last_reviewed_at.isoformat() if fc.last_reviewed_at else None
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO flashcards
                  (id, cap_id, template_kind, question, answer, srs_state,
                   created_at, last_reviewed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  question = excluded.question,
                  answer = excluded.answer,
                  srs_state = excluded.srs_state,
                  last_reviewed_at = excluded.last_reviewed_at
                """,
                (
                    fc.id, fc.cap_id, fc.template_kind, fc.question, fc.answer,
                    fc.srs_state.model_dump_json(), created_at, last,
                ),
            )

    def delete_by_cap_id(self, cap_id: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM flashcards WHERE cap_id = ?", (cap_id,))

    @staticmethod
    def _row_to_fc(row: sqlite3.Row) -> Flashcard:
        return Flashcard(
            id=row["id"],
            cap_id=row["cap_id"],
            template_kind=row["template_kind"],
            question=row["question"],
            answer=row["answer"],
            srs_state=SrsState.model_validate_json(row["srs_state"]),
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
            last_reviewed_at=datetime.fromisoformat(row["last_reviewed_at"]) if row["last_reviewed_at"] else None,
        )
```

注意:`SrsState` 需在 file 顶部 import。

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --project backend pytest dashboard/tests/integration/test_flashcard_repo.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add dashboard/state/repositories.py dashboard/tests/integration/test_flashcard_repo.py
git commit -m "feat(harness-review-plan1): FlashcardRepo CRUD skeleton (SRS 在 Plan 3)"
```

---

## Task 5: provenance fuzzy match 校验

**Files:**
- Create: `dashboard/derive/provenance.py`
- Test: `dashboard/tests/unit/test_provenance.py`

- [ ] **Step 1: Write the failing test**

```python
# dashboard/tests/unit/test_provenance.py
"""provenance fuzzy match — spec § 7.3。"""

from __future__ import annotations

from pathlib import Path

import pytest

from dashboard.derive.provenance import (
    ProvenanceCheckResult,
    normalize_text,
    verify_quote_in_source,
)


def test_normalize_strips_whitespace() -> None:
    assert normalize_text("  hello  world\n") == "hello world"


def test_normalize_removes_markdown_emphasis() -> None:
    assert normalize_text("**bold**") == "bold"
    assert normalize_text("_italic_") == "italic"
    assert normalize_text("`code`") == "code"


def test_normalize_collapses_internal_whitespace() -> None:
    assert normalize_text("a   b\t\nc") == "a b c"


def test_verify_exact_match(tmp_path: Path) -> None:
    src = tmp_path / "spec.md"
    src.write_text("LLM 输出强制走 JSON schema。", encoding="utf-8")
    result = verify_quote_in_source("LLM 输出强制走 JSON schema", src, base_dir=tmp_path)
    assert result.ok is True


def test_verify_markdown_in_source_match(tmp_path: Path) -> None:
    """source 含 markdown,quote 不含,normalize 后命中"""
    src = tmp_path / "spec.md"
    src.write_text("**LLM** 输出 *强制* 走 JSON `schema`", encoding="utf-8")
    result = verify_quote_in_source("LLM 输出 强制 走 JSON schema", src, base_dir=tmp_path)
    assert result.ok is True


def test_verify_quote_in_markdown_match(tmp_path: Path) -> None:
    """quote 含 markdown,source 不含,normalize 后也命中"""
    src = tmp_path / "spec.md"
    src.write_text("LLM 输出强制走 JSON schema", encoding="utf-8")
    result = verify_quote_in_source("**LLM** 输出强制走 JSON `schema`", src, base_dir=tmp_path)
    assert result.ok is True


def test_verify_fabricated_quote_rejected(tmp_path: Path) -> None:
    src = tmp_path / "spec.md"
    src.write_text("LLM 输出强制走 JSON schema。", encoding="utf-8")
    result = verify_quote_in_source("LLM 必须用 tools call", src, base_dir=tmp_path)
    assert result.ok is False
    assert "not found" in result.reason.lower()


def test_verify_source_file_missing(tmp_path: Path) -> None:
    result = verify_quote_in_source("x", Path("nonexistent.md"), base_dir=tmp_path)
    assert result.ok is False
    assert "not exist" in result.reason.lower()


def test_verify_source_with_anchor(tmp_path: Path) -> None:
    """source 含 #anchor 段(spec § 7.3 source 可附 #section),anchor 忽略,只 verify file"""
    src = tmp_path / "spec.md"
    src.write_text("hello", encoding="utf-8")
    result = verify_quote_in_source("hello", Path("spec.md#§2"), base_dir=tmp_path)
    assert result.ok is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --project backend pytest dashboard/tests/unit/test_provenance.py -v`
Expected: ImportError dashboard.derive.provenance

- [ ] **Step 3: Implement provenance.py**

```python
# dashboard/derive/provenance.py
"""provenance quote → source fuzzy match。spec § 7.3。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

MARKDOWN_EMPHASIS_RE = re.compile(r"[*_`]+")
WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class ProvenanceCheckResult:
    ok: bool
    reason: str = ""


def normalize_text(text: str) -> str:
    """strip markdown emphasis + collapse whitespace。"""
    text = MARKDOWN_EMPHASIS_RE.sub("", text)
    text = WHITESPACE_RE.sub(" ", text)
    return text.strip()


def verify_quote_in_source(
    quote: str,
    source: Path | str,
    *,
    base_dir: Path,
) -> ProvenanceCheckResult:
    """检查 normalize(quote) 是否在 normalize(source 文件内容)中。

    source 可附 #anchor(spec § 7.3),verify 时剥离。
    """
    src_str = str(source)
    if "#" in src_str:
        src_str = src_str.split("#", 1)[0]
    src_path = (base_dir / src_str).resolve()
    if not src_path.exists():
        return ProvenanceCheckResult(ok=False, reason=f"source does not exist: {src_str}")
    try:
        content = src_path.read_text(encoding="utf-8")
    except OSError as e:
        return ProvenanceCheckResult(ok=False, reason=f"source read error: {e}")
    norm_quote = normalize_text(quote)
    norm_content = normalize_text(content)
    if norm_quote in norm_content:
        return ProvenanceCheckResult(ok=True)
    return ProvenanceCheckResult(ok=False, reason="quote not found in source (normalized)")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --project backend pytest dashboard/tests/unit/test_provenance.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add dashboard/derive/provenance.py dashboard/tests/unit/test_provenance.py
git commit -m "feat(harness-review-plan1): provenance fuzzy match (markdown-aware)"
```

---

## Task 6: LLM prefill prompt builder + constrained Pydantic schema

**Files:**
- Create: `dashboard/derive/llm_prefill_prompt.py`
- Test: `dashboard/tests/unit/test_llm_prefill_prompt.py`

- [ ] **Step 1: Write the failing test**

```python
# dashboard/tests/unit/test_llm_prefill_prompt.py
from __future__ import annotations

from pydantic import BaseModel

from dashboard.derive.llm_prefill_prompt import (
    PrefillRequest,
    PrefillResponse,
    SingleFieldPrefillResponse,
    build_full_prefill_prompt,
    build_single_field_prefill_prompt,
)


def test_prefill_response_schema_has_provenance() -> None:
    """Pydantic schema 必须含 each-field provenance(spec § 7.3)。"""
    schema = PrefillResponse.model_json_schema()
    props = schema["properties"]
    for f in ("what", "why", "alternatives", "tradeoff", "lessons_learned"):
        assert f in props
        assert f"{f}_provenance" in props


def test_full_prompt_includes_cap_name_and_sources() -> None:
    req = PrefillRequest(
        cap_id="01.constrained_schema",
        cap_name_cn="输出 Schema 约束",
        linked_spec_paths=["docs/superpowers/specs/2026-05-05-v0.8.5-constrained-router-design.md"],
        linked_memory_paths=["memory/feedback_design_doc_format.md"],
        decisions_summary=[("abc12", "Constrained Router 4 选 1")],
    )
    prompt = build_full_prefill_prompt(req)
    assert "01.constrained_schema" in prompt
    assert "输出 Schema 约束" in prompt
    assert "2026-05-05-v0.8.5" in prompt
    assert "feedback_design_doc_format" in prompt
    assert "Constrained Router 4 选 1" in prompt
    # 要求 LLM 输出 schema
    assert "provenance" in prompt.lower()
    assert "quote" in prompt.lower()


def test_single_field_prompt_specifies_field() -> None:
    req = PrefillRequest(
        cap_id="x",
        cap_name_cn="x",
        linked_spec_paths=["a.md"],
        linked_memory_paths=[],
        decisions_summary=[],
    )
    prompt = build_single_field_prefill_prompt(req, field_name="why")
    assert "why" in prompt
    assert "single field" in prompt.lower() or "仅生成" in prompt or "only generate" in prompt.lower()


def test_single_field_response_schema_is_pydantic() -> None:
    assert issubclass(SingleFieldPrefillResponse, BaseModel)
    schema = SingleFieldPrefillResponse.model_json_schema()
    assert "value" in schema["properties"]
    assert "provenance" in schema["properties"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --project backend pytest dashboard/tests/unit/test_llm_prefill_prompt.py -v`
Expected: ImportError dashboard.derive.llm_prefill_prompt

- [ ] **Step 3: Implement**

```python
# dashboard/derive/llm_prefill_prompt.py
"""LLM prefill prompt + constrained schema。spec § 7.3。"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from dashboard.derive.deep_card_types import AlternativeItem, FieldProvenance


@dataclass(frozen=True)
class PrefillRequest:
    """单个 cap 的 prefill 上下文 — 装配 prompt 用。"""

    cap_id: str
    cap_name_cn: str
    linked_spec_paths: list[str]
    linked_memory_paths: list[str]
    decisions_summary: list[tuple[str, str]]  # [(decision_id, title), ...]


class PrefillResponse(BaseModel):
    """LLM 输出 schema — 全字段 + per-field provenance。"""

    model_config = ConfigDict(extra="forbid")
    what: str | None = None
    what_provenance: FieldProvenance | None = None
    why: str | None = None
    why_provenance: FieldProvenance | None = None
    alternatives: list[AlternativeItem] = Field(default_factory=list)
    alternatives_provenance: FieldProvenance | None = None
    chosen_alternative: str | None = None
    chosen_alternative_provenance: FieldProvenance | None = None
    tradeoff: str | None = None
    tradeoff_provenance: FieldProvenance | None = None
    lessons_learned: str | None = None
    lessons_learned_provenance: FieldProvenance | None = None


class SingleFieldPrefillResponse(BaseModel):
    """AI 草拟单字段 — POST /cap/{id}/ai_draft/{name} 用。"""

    model_config = ConfigDict(extra="forbid")
    value: str
    provenance: FieldProvenance


SYSTEM_RULES = """\
你是金融研投助手项目的复习卡片助手。任务:基于给定的 spec/memory/decision 来源,
为某个 capability 生成 DeepCard 字段内容(中文,精炼)。

严格规则(违反将被拒绝入库):
1. 每个生成字段必须配 `*_provenance` 含 `quote`(≤30 字,从 source 原文截取)
   和 `source`(具体文件 path,允许 #section anchor)。
2. `quote` 必须是 source 文件中 substring 真实存在的文字(允许 markdown 标点差异)。
3. 如果某字段从 source 中找不到根据,请置该字段为 null + provenance 也为 null,
   不要凭空编造。
4. `what` <= 2 句话;`why` <= 200 字;`tradeoff` <= 200 字;
   `alternatives` 3-5 项 + brief_tradeoff <= 30 字;
   `chosen_alternative` 必须是 alternatives 列表中某 name 的精确字符串。
5. 输出 JSON 严格遵守提供的 schema。
"""


def _format_sources(req: PrefillRequest) -> str:
    lines: list[str] = []
    lines.append("**Linked specs (优先来源):**")
    for s in req.linked_spec_paths:
        lines.append(f"- {s}")
    lines.append("")
    if req.linked_memory_paths:
        lines.append("**Linked memory (经验/教训来源):**")
        for m in req.linked_memory_paths:
            lines.append(f"- {m}")
        lines.append("")
    if req.decisions_summary:
        lines.append("**已抽取决策卡 (linked decisions):**")
        for did, title in req.decisions_summary:
            lines.append(f"- [{did}] {title}")
        lines.append("")
    return "\n".join(lines)


def build_full_prefill_prompt(req: PrefillRequest) -> str:
    return (
        f"{SYSTEM_RULES}\n\n"
        f"# Capability\n\n"
        f"- id: `{req.cap_id}`\n"
        f"- 名称: {req.cap_name_cn}\n\n"
        f"# 来源材料\n\n"
        f"{_format_sources(req)}\n"
        f"# 任务\n\n"
        f"基于上述来源,生成 DeepCard 字段:what / why / alternatives / chosen_alternative / "
        f"tradeoff / lessons_learned,以及每个字段的 provenance(quote + source)。\n"
        f"对找不到根据的字段,**置 null 不要编造**。"
    )


def build_single_field_prefill_prompt(req: PrefillRequest, *, field_name: str) -> str:
    field_hints = {
        "what": "做了什么(1-2 句事实陈述)",
        "why": "为什么这么选(动机 + 主要约束,<200 字)",
        "alternatives": "业界 alternatives 数组(3-5 项,每项 name + brief_tradeoff)",
        "chosen_alternative": "alternatives 中我们选的 name(必须精确匹配)",
        "tradeoff": "我们的最终取舍(<200 字)",
        "lessons_learned": "事后撞坑教训(从 memory feedback_*.md 抽)",
    }
    hint = field_hints.get(field_name, field_name)
    return (
        f"{SYSTEM_RULES}\n\n"
        f"# Capability\n\n"
        f"- id: `{req.cap_id}`\n"
        f"- 名称: {req.cap_name_cn}\n\n"
        f"# 来源材料\n\n"
        f"{_format_sources(req)}\n"
        f"# 任务\n\n"
        f"仅生成单字段 `{field_name}`({hint})及其 provenance。输出 schema:\n"
        f"`{{value: str, provenance: {{quote, source}}}}`。\n"
        f"找不到根据时,**置 value = ''** + provenance.quote = '' 表示放弃。"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --project backend pytest dashboard/tests/unit/test_llm_prefill_prompt.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add dashboard/derive/llm_prefill_prompt.py dashboard/tests/unit/test_llm_prefill_prompt.py
git commit -m "feat(harness-review-plan1): LLM prefill prompt + constrained Pydantic schema"
```

---

## Task 7: prefill_deep_cards.py batch CLI

**Files:**
- Create: `backend/scripts/prefill_deep_cards.py`
- Test L1: `dashboard/tests/integration/test_prefill_batch.py`
- Test L2: `dashboard/tests/e2e/test_prefill_cassette.py`(cassette,Task 7b)

- [ ] **Step 1: Write L1 integration test (mock LLMService)**

```python
# dashboard/tests/integration/test_prefill_batch.py
"""prefill batch CLI 集成测试 — mock LLMService 验证流程。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from dashboard.derive.deep_card_types import AlternativeItem, FieldProvenance
from dashboard.derive.llm_prefill_prompt import PrefillResponse
from dashboard.state.db import open_db
from dashboard.state.repositories import DeepCardRepo

# 通过 sys.path 模拟脚本调用
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "backend" / "scripts"))
import prefill_deep_cards as pf


def _mock_llm_returns(text: str, parsed: PrefillResponse) -> MagicMock:
    m = MagicMock()
    m.content = text
    m.parsed = parsed
    m.cost_cny = 0.001
    return m


def test_prefill_one_cap_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 准备假 spec 文件让 provenance 命中
    src_dir = tmp_path / "docs" / "specs"
    src_dir.mkdir(parents=True)
    (src_dir / "fake.md").write_text(
        "LLM 输出强制走 JSON schema,避免下游解析失败", encoding="utf-8"
    )
    db = tmp_path / "board.db"
    conn = open_db(db)
    repo = DeepCardRepo(conn)

    # mock LLMService.chat 返回结构化 response
    fake_parsed = PrefillResponse(
        what="LLM 输出强制走 JSON schema",
        what_provenance=FieldProvenance(quote="LLM 输出强制走", source="docs/specs/fake.md"),
        alternatives=[AlternativeItem(name="A", brief_tradeoff="a")],
        chosen_alternative="A",
    )
    fake_llm = MagicMock()
    fake_llm.chat.return_value = _mock_llm_returns(fake_parsed.model_dump_json(), fake_parsed)

    cap_ctx = pf.CapPrefillContext(
        cap_id="01.constrained_schema",
        cap_name_cn="输出 Schema 约束",
        linked_specs=["docs/specs/fake.md"],
        linked_memories=[],
        decisions_summary=[],
    )
    result = pf.prefill_one_cap(
        ctx=cap_ctx,
        llm_service=fake_llm,
        repo=repo,
        base_dir=tmp_path,
    )
    assert result.success_fields >= 1
    assert result.rejected_fields == 0
    card = repo.get("01.constrained_schema")
    assert card is not None
    assert card.what == "LLM 输出强制走 JSON schema"
    assert card.prefill_source == "llm"


def test_prefill_rejects_fabricated_quote(tmp_path: Path) -> None:
    src_dir = tmp_path / "docs" / "specs"
    src_dir.mkdir(parents=True)
    (src_dir / "fake.md").write_text("Real content unrelated", encoding="utf-8")
    db = tmp_path / "board.db"
    conn = open_db(db)
    repo = DeepCardRepo(conn)

    # LLM 编造的 quote 不在 source 中
    fake_parsed = PrefillResponse(
        what="编造内容",
        what_provenance=FieldProvenance(quote="完全编造的引用", source="docs/specs/fake.md"),
    )
    fake_llm = MagicMock()
    fake_llm.chat.return_value = _mock_llm_returns(fake_parsed.model_dump_json(), fake_parsed)

    cap_ctx = pf.CapPrefillContext(
        cap_id="x", cap_name_cn="x",
        linked_specs=["docs/specs/fake.md"],
        linked_memories=[], decisions_summary=[],
    )
    result = pf.prefill_one_cap(
        ctx=cap_ctx, llm_service=fake_llm, repo=repo, base_dir=tmp_path,
    )
    # what 字段因 quote 校验失败被 reject
    assert result.rejected_fields >= 1
    card = repo.get("x")
    # what 应该是 None (reject) 而非编造值
    assert card is None or card.what is None


def test_prefill_log_records_status(tmp_path: Path) -> None:
    # 验证 prefill_log 表有写入
    src_dir = tmp_path / "docs" / "specs"
    src_dir.mkdir(parents=True)
    (src_dir / "fake.md").write_text("LLM 输出 schema", encoding="utf-8")
    db = tmp_path / "board.db"
    conn = open_db(db)
    repo = DeepCardRepo(conn)

    fake_parsed = PrefillResponse(
        what="LLM 输出 schema",
        what_provenance=FieldProvenance(quote="LLM 输出 schema", source="docs/specs/fake.md"),
    )
    fake_llm = MagicMock()
    fake_llm.chat.return_value = _mock_llm_returns(fake_parsed.model_dump_json(), fake_parsed)

    cap_ctx = pf.CapPrefillContext(
        cap_id="z", cap_name_cn="z",
        linked_specs=["docs/specs/fake.md"],
        linked_memories=[], decisions_summary=[],
    )
    pf.prefill_one_cap(
        ctx=cap_ctx, llm_service=fake_llm, repo=repo, base_dir=tmp_path,
    )
    cur = conn.execute("SELECT field_name, status FROM prefill_log WHERE cap_id = 'z'")
    rows = cur.fetchall()
    assert len(rows) >= 1
```

补 import:`import pytest` in test file.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --project backend pytest dashboard/tests/integration/test_prefill_batch.py -v`
Expected: ImportError prefill_deep_cards

- [ ] **Step 3: Implement CLI**

```python
# backend/scripts/prefill_deep_cards.py
"""DeepCard LLM prefill batch CLI。spec § 7.3。

Usage:
    uv run python -m backend.scripts.prefill_deep_cards \\
        --caps 01.constrained_schema,02.tool_registry \\
        --db backend/data/board.db
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from dashboard.derive.deep_card_types import DeepCard, FieldProvenance, PrefillSource
from dashboard.derive.llm_prefill_prompt import (
    PrefillRequest,
    PrefillResponse,
    build_full_prefill_prompt,
)
from dashboard.derive.provenance import verify_quote_in_source
from dashboard.state.db import open_db
from dashboard.state.repositories import DeepCardRepo

if TYPE_CHECKING:
    from app.services.llm_service import LLMService

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).parent.parent.parent

CONTENT_FIELDS = ("what", "why", "alternatives", "chosen_alternative", "tradeoff", "lessons_learned")


@dataclass(frozen=True)
class CapPrefillContext:
    cap_id: str
    cap_name_cn: str
    linked_specs: list[str]
    linked_memories: list[str]
    decisions_summary: list[tuple[str, str]]


@dataclass(frozen=True)
class PrefillResult:
    cap_id: str
    success_fields: int
    rejected_fields: int
    error: str | None = None


def _log_prefill(conn, cap_id: str, field_name: str, status: str, detail: str = "") -> None:
    """写 prefill_log。"""
    with conn:
        conn.execute(
            "INSERT INTO prefill_log (cap_id, field_name, status, detail, ran_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (cap_id, field_name, status, detail, datetime.now(UTC).isoformat()),
        )


def prefill_one_cap(
    *,
    ctx: CapPrefillContext,
    llm_service: "LLMService",
    repo: DeepCardRepo,
    base_dir: Path,
) -> PrefillResult:
    """单个 cap 的 prefill — 调 LLM + provenance 校验 + 落库。"""
    req = PrefillRequest(
        cap_id=ctx.cap_id,
        cap_name_cn=ctx.cap_name_cn,
        linked_spec_paths=ctx.linked_specs,
        linked_memory_paths=ctx.linked_memories,
        decisions_summary=ctx.decisions_summary,
    )
    prompt = build_full_prefill_prompt(req)
    try:
        resp = llm_service.chat(prompt=prompt, tier="balanced", schema=PrefillResponse)
    except Exception as e:
        logger.exception("LLM prefill failed for %s", ctx.cap_id)
        _log_prefill(repo.conn, ctx.cap_id, "*", "llm_error", str(e))
        return PrefillResult(cap_id=ctx.cap_id, success_fields=0, rejected_fields=0, error=str(e))

    parsed: PrefillResponse | None = resp.parsed if hasattr(resp, "parsed") else None
    if parsed is None:
        # fallback: try parse content
        parsed = PrefillResponse.model_validate_json(resp.content)

    success, rejected = _apply_response_to_card(
        parsed=parsed,
        ctx=ctx,
        repo=repo,
        base_dir=base_dir,
    )
    return PrefillResult(cap_id=ctx.cap_id, success_fields=success, rejected_fields=rejected)


def _apply_response_to_card(
    *,
    parsed: PrefillResponse,
    ctx: CapPrefillContext,
    repo: DeepCardRepo,
    base_dir: Path,
) -> tuple[int, int]:
    """逐字段 provenance 校验 → 失败 reject → 通过的字段写入新 DeepCard。"""
    existing = repo.get(ctx.cap_id) or DeepCard(cap_id=ctx.cap_id)
    new_data = existing.model_dump()
    success = 0
    rejected = 0

    for field_name in CONTENT_FIELDS:
        value = getattr(parsed, field_name)
        prov: FieldProvenance | None = getattr(parsed, f"{field_name}_provenance", None)
        if value is None or (isinstance(value, list) and not value):
            _log_prefill(repo.conn, ctx.cap_id, field_name, "skipped", "LLM returned null")
            continue
        if prov is None or not prov.quote:
            rejected += 1
            _log_prefill(repo.conn, ctx.cap_id, field_name, "rejected_quote", "missing provenance")
            continue
        check = verify_quote_in_source(prov.quote, prov.source, base_dir=base_dir)
        if not check.ok:
            rejected += 1
            _log_prefill(repo.conn, ctx.cap_id, field_name, "rejected_quote", check.reason)
            continue
        new_data[field_name] = (
            [a.model_dump() for a in value] if isinstance(value, list) else value
        )
        # provenance 累计写入
        prov_dict = new_data.get("provenance") or {}
        prov_dict[field_name] = prov.model_dump()
        new_data["provenance"] = prov_dict
        success += 1
        _log_prefill(repo.conn, ctx.cap_id, field_name, "success", "")

    new_data["prefill_source"] = "llm" if success > 0 else existing.prefill_source
    new_data["prefill_at"] = datetime.now(UTC).isoformat() if success > 0 else new_data.get("prefill_at")
    # linked_specs / linked_memories 自动 dedupe(spec § 4.2)— provenance 内 value 是 dict
    prov_values = (new_data.get("provenance") or {}).values()
    spec_sources = {
        v["source"].split("#")[0]
        for v in prov_values
        if isinstance(v, dict) and isinstance(v.get("source"), str)
    }
    spec_paths = sorted(s for s in spec_sources if s.startswith("docs/"))
    memory_paths = sorted(
        s for s in spec_sources
        if "memory" in s.lower() or s.startswith("backend/data/memory")
    )
    new_data["linked_specs"] = spec_paths if spec_paths else new_data.get("linked_specs", [])
    new_data["linked_memories"] = memory_paths if memory_paths else new_data.get("linked_memories", [])

    if success > 0 or rejected > 0:
        repo.upsert(DeepCard.model_validate(new_data))

    return success, rejected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DeepCard LLM prefill batch")
    parser.add_argument("--caps", required=True, help="逗号分隔 cap_id list")
    parser.add_argument("--db", default="backend/data/board.db", help="sqlite path")
    parser.add_argument("--base-dir", default=str(PROJECT_ROOT), help="project root for provenance")
    args = parser.parse_args(argv)

    # lazy import 避免 dashboard/derive/* L0 跑不动
    from app.services.openai_client import build_llm_service_from_env
    from dashboard.derive.capability_resolver import load_capabilities

    llm = build_llm_service_from_env()
    base_dir = Path(args.base_dir)
    conn = open_db(base_dir / args.db)
    repo = DeepCardRepo(conn)

    caps_cfg = load_capabilities(base_dir / "dashboard" / "config" / "capabilities.yaml")
    cap_by_id = {c.id: c for c in caps_cfg}

    cap_ids = [c.strip() for c in args.caps.split(",") if c.strip()]
    total_success, total_rejected = 0, 0
    for cap_id in cap_ids:
        cfg = cap_by_id.get(cap_id)
        if not cfg:
            logger.warning("cap %s not in capabilities.yaml — skipping", cap_id)
            continue
        # 简单 linked 推断 — 通过 keyword match 找 specs/memories(完善归 Task 后续)
        ctx = CapPrefillContext(
            cap_id=cap_id,
            cap_name_cn=cfg.name_cn,
            linked_specs=[],  # CLI 模式下空,人工填或后续 enrich
            linked_memories=[],
            decisions_summary=[],
        )
        result = prefill_one_cap(ctx=ctx, llm_service=llm, repo=repo, base_dir=base_dir)
        logger.info("cap=%s success=%d rejected=%d", cap_id, result.success_fields, result.rejected_fields)
        total_success += result.success_fields
        total_rejected += result.rejected_fields

    print(f"Prefill done. fields written: {total_success}, rejected: {total_rejected}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --project backend pytest dashboard/tests/integration/test_prefill_batch.py -v`
Expected: 3 passed

- [ ] **Step 5: mypy strict**

Run: `uv run --project backend mypy backend/scripts/prefill_deep_cards.py --strict`
Expected: Success

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/prefill_deep_cards.py dashboard/tests/integration/test_prefill_batch.py
git commit -m "feat(harness-review-plan1): prefill_deep_cards batch CLI + provenance 校验"
```

---

## Task 7b: prefill L2 cassette(真 LLM replay)

**Files:**
- Test: `dashboard/tests/e2e/test_prefill_cassette.py`
- Cassette: `dashboard/tests/fixtures/cassettes/prefill_*.yaml`

- [ ] **Step 1: 准备 5 cap 真实输入 + spec 引用**

挑 5 cap 录 cassette(目标:Plan 1 ship 时有 cassette replay):
1. `01.constrained_schema` → spec `2026-05-05-v0.8.5-constrained-router-design.md`
2. `01.skills_bundle` → spec `2026-05-05-v0.8.5-constrained-router-design.md`(同 spec)
3. `03.langgraph_supervisor`(若 cap 存在;否则 `03.research_5agent` etc)→ spec `2026-05-09-v0.9-chat-mode-c1c2-design.md`
4. `04.bi_temporal_memory` → spec `2026-05-10-c5-cross-session-memory-design.md`
5. `05.milvus_3_collections` → spec `2026-05-02-v0.7-kb-search-milvus-design.md`

(确认 cap_id 在 `dashboard/config/capabilities.yaml` 中存在;若名称不同,实施时按实际命名)

- [ ] **Step 2: Write cassette test**

```python
# dashboard/tests/e2e/test_prefill_cassette.py
"""L2 cassette — 真 LLM replay prefill 5 cap。"""

from __future__ import annotations

from pathlib import Path

import pytest

# 沿用项目 cassette 配置(已有 conftest 注入 vcr 配置)
pytestmark = pytest.mark.vcr

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent


@pytest.mark.parametrize("cap_id,name_cn,spec_path", [
    ("01.constrained_schema", "输出 Schema 约束",
     "docs/superpowers/specs/2026-05-05-v0.8.5-constrained-router-design.md"),
    ("01.skills_bundle", "Skills bundle (17-component)",
     "docs/superpowers/specs/2026-05-05-v0.8.5-constrained-router-design.md"),
    ("04.bi_temporal_memory", "Bi-temporal memory",
     "docs/superpowers/specs/2026-05-10-c5-cross-session-memory-design.md"),
    ("05.milvus_3_collections", "Milvus 3 collection",
     "docs/superpowers/specs/2026-05-02-v0.7-kb-search-milvus-design.md"),
    ("03.langgraph_supervisor", "LangGraph supervisor",
     "docs/superpowers/specs/2026-05-09-v0.9-chat-mode-c1c2-design.md"),
])
def test_prefill_cap_real_llm(
    cap_id: str, name_cn: str, spec_path: str, tmp_path: Path,
) -> None:
    """每个 cap × 1 cassette。 - 第一次录:删 cassette 文件,uv run pytest --record-mode=once
    - replay:正常 pytest"""
    from app.services.openai_client import build_llm_service_from_env
    from dashboard.state.db import open_db
    from dashboard.state.repositories import DeepCardRepo
    import sys
    sys.path.insert(0, str(PROJECT_ROOT / "backend" / "scripts"))
    import prefill_deep_cards as pf

    llm = build_llm_service_from_env()
    db = tmp_path / "t.db"
    conn = open_db(db)
    repo = DeepCardRepo(conn)
    ctx = pf.CapPrefillContext(
        cap_id=cap_id, cap_name_cn=name_cn,
        linked_specs=[spec_path],
        linked_memories=[], decisions_summary=[],
    )
    result = pf.prefill_one_cap(
        ctx=ctx, llm_service=llm, repo=repo, base_dir=PROJECT_ROOT,
    )
    assert result.success_fields + result.rejected_fields >= 1
    card = repo.get(cap_id)
    assert card is not None
```

注意:cassette dir 沿用 `backend/tests/fixtures/cassettes/`(项目 pytest-recording 已配置)。

- [ ] **Step 3: 第一次录 cassette(需要真 LLM,有 .env)**

```bash
unset all_proxy https_proxy http_proxy
uv run --project backend pytest dashboard/tests/e2e/test_prefill_cassette.py -v --record-mode=once
```

预期:产出 5 个 cassette yaml,5 测试 PASS。

- [ ] **Step 4: replay 验证**

```bash
uv run --project backend pytest dashboard/tests/e2e/test_prefill_cassette.py -v
```

预期:5 测试 PASS,无网络调用。

- [ ] **Step 5: 校验 cassette 安全**

```bash
uv run python scripts/check_cassette_sanitize.py
```

预期:无敏感信息泄露。

- [ ] **Step 6: Commit**

```bash
git add dashboard/tests/e2e/test_prefill_cassette.py backend/tests/fixtures/cassettes/test_prefill_*.yaml
git commit -m "test(harness-review-plan1): prefill L2 cassette (5 cap × real LLM replay)"
```

---

## Task 8: Milvus collection 设计 + upsert + 相关推荐(with fallback)

**Files:**
- Create: `dashboard/state/milvus_collection.py`
- Create: `dashboard/state/keyword_recommender.py`
- Test: `dashboard/tests/unit/test_keyword_recommender.py`
- Test: `dashboard/tests/integration/test_milvus_collection.py`

- [ ] **Step 1: Write keyword recommender unit test(fallback 路径)**

```python
# dashboard/tests/unit/test_keyword_recommender.py
"""keyword 相关推荐 fallback — spec § 6.3。"""

from __future__ import annotations

from dashboard.derive.deep_card_types import DeepCard
from dashboard.state.keyword_recommender import recommend_by_keyword


def test_recommend_returns_top_k() -> None:
    cards = [
        DeepCard(cap_id="01.a", what="LangGraph supervisor + planner"),
        DeepCard(cap_id="01.b", what="Constrained Router for plan"),
        DeepCard(cap_id="01.c", what="Unrelated content"),
        DeepCard(cap_id="01.d", what="LangGraph subgraph + Critic"),
    ]
    pivot = cards[0]
    result = recommend_by_keyword(pivot, cards, k=2)
    # d 含 LangGraph 关键词,排第一;c 不相关排最末
    ids = [r.cap_id for r in result]
    assert "01.d" in ids
    assert "01.c" not in ids
    assert len(ids) == 2


def test_recommend_excludes_self() -> None:
    cards = [DeepCard(cap_id="a", what="LangGraph"), DeepCard(cap_id="b", what="LangGraph")]
    result = recommend_by_keyword(cards[0], cards, k=5)
    assert all(r.cap_id != "a" for r in result)


def test_recommend_empty_pivot() -> None:
    """pivot DeepCard 内容全空 — 返回 empty list"""
    pivot = DeepCard(cap_id="x")
    cards = [pivot, DeepCard(cap_id="y", what="something")]
    result = recommend_by_keyword(pivot, cards, k=3)
    assert result == []
```

- [ ] **Step 2: Run + fails**

Run: `uv run --project backend pytest dashboard/tests/unit/test_keyword_recommender.py -v`
Expected: ImportError keyword_recommender

- [ ] **Step 3: Implement keyword recommender**

```python
# dashboard/state/keyword_recommender.py
"""相关推荐 keyword fallback — sum-of-keyword-length 评分(沿用 classify_layer 逻辑)。

spec § 6.3:Milvus 不可用时退化路径。
"""

from __future__ import annotations

import re
from collections import Counter

from dashboard.derive.deep_card_types import DeepCard

TOKEN_RE = re.compile(r"[A-Za-z][\w-]+|[一-龥]+")


def _tokens(card: DeepCard) -> list[str]:
    """从 DeepCard 文本字段抽 keyword token(简单切词,中英文混合)。"""
    parts: list[str] = []
    for f in ("what", "why", "tradeoff", "lessons_learned"):
        v = getattr(card, f, None)
        if isinstance(v, str):
            parts.append(v)
    for a in card.alternatives:
        parts.append(a.name)
        parts.append(a.brief_tradeoff)
    if card.chosen_alternative:
        parts.append(card.chosen_alternative)
    text = " ".join(parts)
    return [t for t in TOKEN_RE.findall(text) if len(t) >= 2]


def recommend_by_keyword(
    pivot: DeepCard, all_cards: list[DeepCard], *, k: int = 5
) -> list[DeepCard]:
    """对 pivot 与每张 card 算 keyword 命中得分,返回 top-k(排除 self)。

    评分:Σ len(token) for token in (pivot_tokens ∩ card_tokens).
    """
    pivot_tokens = set(_tokens(pivot))
    if not pivot_tokens:
        return []
    scored: list[tuple[DeepCard, int]] = []
    for c in all_cards:
        if c.cap_id == pivot.cap_id:
            continue
        c_tokens = set(_tokens(c))
        common = pivot_tokens & c_tokens
        if not common:
            continue
        score = sum(len(t) for t in common)
        scored.append((c, score))
    scored.sort(key=lambda kv: kv[1], reverse=True)
    return [c for c, _ in scored[:k]]
```

- [ ] **Step 4: Run + passes**

Run: `uv run --project backend pytest dashboard/tests/unit/test_keyword_recommender.py -v`
Expected: 3 passed

- [ ] **Step 5: Write Milvus collection integration test**

```python
# dashboard/tests/integration/test_milvus_collection.py
"""Milvus collection — 真 Milvus fixture(若起 docker compose milvus)。"""

from __future__ import annotations

import os

import pytest

from dashboard.derive.deep_card_types import DeepCard
from dashboard.state.milvus_collection import (
    COLLECTION_NAME,
    DeepCardMilvusClient,
    embedding_text,
)

milvus_skip = pytest.mark.skipif(
    os.getenv("MILVUS_HOST") is None,
    reason="real Milvus integration; set MILVUS_HOST=localhost MILVUS_PORT=19530"
)


def test_embedding_text_combines_fields() -> None:
    c = DeepCard(
        cap_id="x",
        what="LLM 输出 schema",
        why="避免下游解析失败",
        tradeoff="选 schema 因为兼容协议支持",
    )
    text = embedding_text(c, name_cn="输出 Schema 约束")
    assert "输出 Schema 约束" in text
    assert "LLM 输出 schema" in text
    assert "避免下游解析失败" in text
    assert "选 schema" in text


def test_embedding_text_skips_empty_fields() -> None:
    c = DeepCard(cap_id="x", what="only what")
    text = embedding_text(c, name_cn="N")
    assert "only what" in text
    # 不应有连续 \n\n\n(空段被跳)
    assert "\n\n\n" not in text


@milvus_skip
@pytest.mark.asyncio
async def test_milvus_upsert_and_search() -> None:
    from app.services.embedding_factory import build_embedding_service_from_env
    client = DeepCardMilvusClient(
        host=os.environ["MILVUS_HOST"],
        port=int(os.getenv("MILVUS_PORT", "19530")),
    )
    embedder = build_embedding_service_from_env()
    await client.ensure_collection()
    c = DeepCard(cap_id="test.1", what="LangGraph supervisor")
    vec = (await embedder.embed([embedding_text(c, name_cn="T")]))[0]
    await client.upsert([dict(cap_id=c.cap_id, embedding=vec,
                              dimension="03", name_cn="T", status="lit", confidence=0)])
    results = await client.search(vec, top_k=1)
    assert len(results) >= 1
    assert results[0]["cap_id"] == "test.1"
    await client.delete("test.1")
```

- [ ] **Step 6: Run + fails**

Run: `uv run --project backend pytest dashboard/tests/integration/test_milvus_collection.py -v`
Expected: ImportError milvus_collection

- [ ] **Step 7: Implement Milvus collection**

```python
# dashboard/state/milvus_collection.py
"""Harness Board DeepCard Milvus collection — spec § 6.2。

跟 KB collection (kb_research/financial/policy) 不复用,新 schema。
"""

from __future__ import annotations

import logging
from typing import Any

from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    connections,
    utility,
)

from dashboard.derive.deep_card_types import DeepCard

logger = logging.getLogger(__name__)

COLLECTION_NAME = "harness_board_deepcards"
EMBEDDING_DIM = 1024  # qwen text-embedding-v3


def embedding_text(card: DeepCard, *, name_cn: str) -> str:
    """组合 name + what + why + tradeoff 作为 embedding source。spec § 6.2。

    空字段跳过(不产生连续空行)。
    """
    parts = [name_cn]
    for f in ("what", "why", "tradeoff"):
        v = getattr(card, f, None)
        if v:
            parts.append(v)
    return "\n\n".join(parts)


def _schema() -> CollectionSchema:
    return CollectionSchema(
        fields=[
            FieldSchema(name="cap_id", dtype=DataType.VARCHAR, max_length=64, is_primary=True),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM),
            FieldSchema(name="dimension", dtype=DataType.VARCHAR, max_length=32),
            FieldSchema(name="name_cn", dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name="status", dtype=DataType.VARCHAR, max_length=16),
            FieldSchema(name="confidence", dtype=DataType.INT8),
        ],
        description="Harness Board DeepCard embeddings",
    )


class DeepCardMilvusClient:
    """Wrap pymilvus 操作。fallback 行为在调用层处理。"""

    def __init__(self, *, host: str, port: int) -> None:
        self._alias = "harness_board"
        connections.connect(alias=self._alias, host=host, port=port)

    async def ensure_collection(self) -> None:
        if utility.has_collection(COLLECTION_NAME, using=self._alias):
            coll = Collection(COLLECTION_NAME, using=self._alias)
            coll.load()
            return
        coll = Collection(name=COLLECTION_NAME, schema=_schema(), using=self._alias)
        coll.create_index(
            field_name="embedding",
            index_params={"index_type": "AUTOINDEX", "metric_type": "COSINE"},
        )
        coll.load()

    async def upsert(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        coll = Collection(COLLECTION_NAME, using=self._alias)
        coll.upsert(data=[
            [r["cap_id"] for r in rows],
            [r["embedding"] for r in rows],
            [r["dimension"] for r in rows],
            [r["name_cn"] for r in rows],
            [r["status"] for r in rows],
            [r["confidence"] for r in rows],
        ])
        coll.flush()

    async def search(self, vec: list[float], *, top_k: int = 5) -> list[dict[str, Any]]:
        coll = Collection(COLLECTION_NAME, using=self._alias)
        res = coll.search(
            data=[vec],
            anns_field="embedding",
            param={"metric_type": "COSINE", "params": {"ef": 64}},
            limit=top_k,
            output_fields=["cap_id", "dimension", "name_cn", "status", "confidence"],
        )
        out: list[dict[str, Any]] = []
        for hits in res:
            for hit in hits:
                out.append({
                    "cap_id": hit.entity.get("cap_id"),
                    "dimension": hit.entity.get("dimension"),
                    "name_cn": hit.entity.get("name_cn"),
                    "status": hit.entity.get("status"),
                    "confidence": hit.entity.get("confidence"),
                    "score": hit.score,
                })
        return out

    async def delete(self, cap_id: str) -> None:
        coll = Collection(COLLECTION_NAME, using=self._alias)
        coll.delete(expr=f'cap_id == "{cap_id}"')
```

- [ ] **Step 8: Run integration test(skip if no Milvus)**

Run: `uv run --project backend pytest dashboard/tests/integration/test_milvus_collection.py -v`
Expected: 2 passed + 1 skipped(若 MILVUS_HOST 未 set);若 docker compose 跑 Milvus,3 passed

- [ ] **Step 9: Commit**

```bash
git add dashboard/state/milvus_collection.py dashboard/state/keyword_recommender.py \
        dashboard/tests/unit/test_keyword_recommender.py \
        dashboard/tests/integration/test_milvus_collection.py
git commit -m "feat(harness-review-plan1): Milvus collection + keyword fallback"
```

---

## Task 9: 相关推荐 endpoint(with Milvus + fallback)

**Files:**
- Modify: `dashboard/server.py`
- Test: `dashboard/tests/integration/test_related_endpoint.py`

- [ ] **Step 1: Write the failing test**

```python
# dashboard/tests/integration/test_related_endpoint.py
from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    db = tmp_path / "board.db"
    monkeypatch.setenv("HARNESS_BOARD_DB", str(db))
    # 让 server import 时用 tmp db
    from dashboard import server
    monkeypatch.setattr(server, "DB_PATH", db)
    monkeypatch.setattr(server, "MILVUS_HOST", None)  # 强制 fallback
    return TestClient(server.app)


def test_related_returns_keyword_fallback(client: TestClient) -> None:
    from dashboard.derive.deep_card_types import DeepCard
    from dashboard.state.db import open_db
    from dashboard.state.repositories import DeepCardRepo
    # seed 3 DeepCard
    conn = open_db(client.app.state.db_path)  # type: ignore[attr-defined]
    repo = DeepCardRepo(conn)
    repo.upsert(DeepCard(cap_id="01.a", what="LangGraph supervisor"))
    repo.upsert(DeepCard(cap_id="01.b", what="LangGraph subgraph"))
    repo.upsert(DeepCard(cap_id="03.c", what="Constrained Router"))

    resp = client.get("/cap/01.a/related?k=2")
    assert resp.status_code == 200
    body = resp.json()
    assert any(r["cap_id"] == "01.b" for r in body)


def test_related_missing_cap_returns_404(client: TestClient) -> None:
    resp = client.get("/cap/nope/related?k=5")
    assert resp.status_code == 404


def test_related_milvus_unavailable_falls_back_with_banner(client: TestClient) -> None:
    """Milvus 不通时,response 头部应含 'X-Milvus-Status: fallback'。"""
    from dashboard.derive.deep_card_types import DeepCard
    from dashboard.state.db import open_db
    from dashboard.state.repositories import DeepCardRepo
    conn = open_db(client.app.state.db_path)  # type: ignore[attr-defined]
    repo = DeepCardRepo(conn)
    repo.upsert(DeepCard(cap_id="x", what="t"))
    repo.upsert(DeepCard(cap_id="y", what="t"))
    resp = client.get("/cap/x/related?k=5")
    assert resp.status_code == 200
    assert resp.headers.get("X-Milvus-Status") == "fallback"
```

- [ ] **Step 2: Run + fails**

Run: `uv run --project backend pytest dashboard/tests/integration/test_related_endpoint.py -v`
Expected: 404 / endpoint missing

- [ ] **Step 3: Implement endpoint in `dashboard/server.py`**

```python
# dashboard/server.py — 在 routes 列表前加 import,在 routes append

# top of file imports (additions):
import os
from dashboard.state.keyword_recommender import recommend_by_keyword
from dashboard.state.repositories import DeepCardRepo

MILVUS_HOST = os.getenv("HARNESS_BOARD_MILVUS_HOST")
MILVUS_PORT = int(os.getenv("HARNESS_BOARD_MILVUS_PORT", "19530"))


def _try_milvus_related(cap_id: str, k: int) -> tuple[list[dict[str, object]] | None, str]:
    """尝试 Milvus 查询,失败返回 (None, reason)。"""
    if MILVUS_HOST is None:
        return None, "milvus_disabled"
    try:
        # lazy import 避免无 milvus 环境启动失败
        from dashboard.state.milvus_collection import DeepCardMilvusClient
        # ... 实际查询省略(完整路径需要 embed pivot 文本 → search)
        # Plan 1 阶段简化:只支持 fallback,Plan 2 完整接 Milvus 查询路径
        return None, "milvus_search_not_wired_plan1"
    except Exception as e:
        return None, f"milvus_error: {e}"


async def related_capabilities(request: Request) -> JSONResponse:
    cap_id = request.path_params["cap_id"]
    k = int(request.query_params.get("k", "5"))
    conn = open_db(DB_PATH)
    try:
        repo = DeepCardRepo(conn)
        pivot = repo.get(cap_id)
        if pivot is None:
            return JSONResponse({"error": "cap not found"}, status_code=404)
        all_cards = repo.get_all()
    finally:
        conn.close()

    milvus_result, reason = _try_milvus_related(cap_id, k)
    if milvus_result is not None:
        return JSONResponse(milvus_result, headers={"X-Milvus-Status": "ok"})
    # fallback
    recs = recommend_by_keyword(pivot, all_cards, k=k)
    payload = [{"cap_id": r.cap_id, "name_cn": "", "score": 0.0} for r in recs]
    # 注:Plan 2 / 3 时 fill name_cn from capabilities.yaml
    return JSONResponse(payload, headers={"X-Milvus-Status": "fallback"})


# 在 routes 列表 append:
#   Route("/cap/{cap_id}/related", related_capabilities, methods=["GET"]),
```

注意 server.py 现有结构:`MILVUS_HOST` 顶层 env 读取(monkeypatch 友好)。`app.state.db_path` 注入到 Starlette state(在 app 构造时 set)。

- [ ] **Step 4: Run + passes**

Run: `uv run --project backend pytest dashboard/tests/integration/test_related_endpoint.py -v`
Expected: 3 passed

- [ ] **Step 5: 65 测试不破**

Run: `uv run --project backend pytest dashboard/tests/ -v`
Expected: 65 + 新增 全 PASS

- [ ] **Step 6: Commit**

```bash
git add dashboard/server.py dashboard/tests/integration/test_related_endpoint.py
git commit -m "feat(harness-review-plan1): GET /cap/{id}/related (Milvus + keyword fallback)"
```

---

## Task 10: V1 chip 完成度角标 + confidence 数字

**Files:**
- Create: `dashboard/derive/completion.py`
- Modify: `dashboard/templates/_capability_chip.html`
- Modify: `dashboard/static/style.css`
- Test: `dashboard/tests/unit/test_completion.py`

- [ ] **Step 1: Write completion calc unit test**

```python
# dashboard/tests/unit/test_completion.py
from __future__ import annotations

from dashboard.derive.completion import completion_level, completion_ratio
from dashboard.derive.deep_card_types import AlternativeItem, DeepCard


def test_empty_card_ratio_zero() -> None:
    assert completion_ratio(DeepCard(cap_id="x")) == 0.0
    assert completion_level(DeepCard(cap_id="x")) == "empty"


def test_partial_one_field() -> None:
    c = DeepCard(cap_id="x", what="something")
    assert 0 < completion_ratio(c) < 1
    assert completion_level(c) == "partial"


def test_full_card() -> None:
    c = DeepCard(
        cap_id="x",
        what="w",
        why="why",
        alternatives=[AlternativeItem(name="A", brief_tradeoff="a")],
        tradeoff="t",
    )
    assert completion_ratio(c) == 1.0
    assert completion_level(c) == "full"


def test_optional_fields_not_counted() -> None:
    """lessons_learned 和 metrics 不计入"""
    c = DeepCard(cap_id="x", lessons_learned="L", metrics={"k": "v"})
    assert completion_level(c) == "empty"


def test_no_deep_card_returns_none() -> None:
    """Helper to compute level when DeepCard missing"""
    from dashboard.derive.completion import completion_level_or_none
    assert completion_level_or_none(None) is None
```

- [ ] **Step 2: Run + fails**

Run: `uv run --project backend pytest dashboard/tests/unit/test_completion.py -v`
Expected: ImportError completion

- [ ] **Step 3: Implement**

```python
# dashboard/derive/completion.py
"""DeepCard 完成度计算 — spec § 5.1。"""

from __future__ import annotations

from typing import Literal

from dashboard.derive.deep_card_types import DeepCard

CompletionLevel = Literal["empty", "partial", "full"]

REQUIRED_FIELDS = ("what", "why", "alternatives", "tradeoff")  # 4 字段必填,spec § 5.1


def completion_ratio(card: DeepCard) -> float:
    """填充字段数 / 4。alternatives 非空列表算填,空列表算未填。"""
    filled = 0
    for f in REQUIRED_FIELDS:
        v = getattr(card, f, None)
        if v is None:
            continue
        if isinstance(v, list) and not v:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        filled += 1
    return filled / len(REQUIRED_FIELDS)


def completion_level(card: DeepCard) -> CompletionLevel:
    r = completion_ratio(card)
    if r == 0.0:
        return "empty"
    if r >= 1.0:
        return "full"
    return "partial"


def completion_level_or_none(card: DeepCard | None) -> CompletionLevel | None:
    if card is None:
        return None
    return completion_level(card)
```

- [ ] **Step 4: Run + passes**

Run: `uv run --project backend pytest dashboard/tests/unit/test_completion.py -v`
Expected: 5 passed

- [ ] **Step 5: 修改 _capability_chip.html 模板**

Read 模板,然后加入完成度角标 + confidence 数字 slot。模板需新增 2 个变量:`completion_level`(empty / partial / full / null)和 `confidence`(int 0-5 / null)。

```html
{# dashboard/templates/_capability_chip.html — 在现有 chip div 内末尾加 #}
{% if completion_level %}
  <span class="chip-completion chip-completion--{{ completion_level }}"
        title="DeepCard 完成度:{{ completion_level }}"></span>
{% endif %}
{% if confidence is not none %}
  <span class="chip-confidence" title="SRS confidence">{{ confidence }}</span>
{% endif %}
```

- [ ] **Step 6: 修改 server.py index() 注入 chip 变量**

在 `index()` ctx 装配处,从 `DeepCardRepo` 拉所有 card,按 cap_id index 后,把 `completion_level` / `confidence` 注入到每个 chip 渲染 context。

```python
# dashboard/server.py — index() 内
from dashboard.derive.completion import completion_level_or_none

# 在 ctx 装配前
conn = open_db(DB_PATH)
try:
    dc_repo = DeepCardRepo(conn)
    deep_cards_by_id = {c.cap_id: c for c in dc_repo.get_all()}
finally:
    conn.close()

# 注入到每个 cap chip(在 layer 循环时)
for layer in snap["layers"]:
    for c in layer["capabilities"]:
        dc = deep_cards_by_id.get(c["id"])
        c["completion_level"] = completion_level_or_none(dc)
        c["confidence"] = dc.srs_state.confidence if dc else None
```

(注意:CapabilityDict 是 TypedDict — 添加新字段需 update types.py 的 TypedDict;或 ctx 用 plain dict 包装。简单做:用 plain dict 包装。)

- [ ] **Step 7: 加 CSS**

```css
/* dashboard/static/style.css — append */

.chip-completion {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  position: absolute;
  top: 4px;
  right: 4px;
}
.chip-completion--empty { background: #ccc; }
.chip-completion--partial { background: #f5c518; }
.chip-completion--full { background: #2da44e; }

.chip-confidence {
  position: absolute;
  bottom: 2px;
  right: 4px;
  font-size: 9px;
  color: #666;
  font-weight: bold;
}
.capability-chip {
  position: relative; /* 确保现有 chip 是 anchor */
}
```

- [ ] **Step 8: smoke test 现有 dashboard 测试**

Run: `uv run --project backend pytest dashboard/tests/ -v`
Expected: PASS,无 regression

- [ ] **Step 9: 手动验证**

```bash
make board
# 浏览器看 chip 是否有角标
make board-stop
```

- [ ] **Step 10: Commit**

```bash
git add dashboard/derive/completion.py dashboard/tests/unit/test_completion.py \
        dashboard/templates/_capability_chip.html dashboard/static/style.css \
        dashboard/server.py
git commit -m "feat(harness-review-plan1): V1 chip 完成度角标 + confidence 数字"
```

---

## Task 11: V2 modal route + 主模板

**Files:**
- Create: `dashboard/templates/_deep_card_modal.html`
- Create: `dashboard/templates/_deep_card_field.html`
- Modify: `dashboard/server.py` (add `GET /cap/{cap_id}` route)
- Test: `dashboard/tests/integration/test_v2_modal_endpoint.py`

- [ ] **Step 1: Write modal endpoint test**

```python
# dashboard/tests/integration/test_v2_modal_endpoint.py
from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    from dashboard import server
    db = tmp_path / "board.db"
    monkeypatch.setattr(server, "DB_PATH", db)
    return TestClient(server.app)


def test_modal_returns_html(client: TestClient) -> None:
    from dashboard.derive.deep_card_types import DeepCard
    from dashboard.state.db import open_db
    from dashboard.state.repositories import DeepCardRepo
    conn = open_db(client.app.state.db_path)  # type: ignore[attr-defined]
    DeepCardRepo(conn).upsert(DeepCard(
        cap_id="01.skills_bundle",
        what="Anthropic Skills bundle 17 件",
        why="progressive disclosure",
    ))

    resp = client.get("/cap/01.skills_bundle")
    assert resp.status_code == 200
    body = resp.text
    assert "Anthropic Skills bundle" in body
    assert "progressive disclosure" in body
    assert "deep-card-modal" in body  # 模板 class 验证


def test_modal_unknown_cap_returns_empty_template(client: TestClient) -> None:
    """cap 不在 yaml 中 — 404"""
    resp = client.get("/cap/nonexistent.cap")
    assert resp.status_code == 404


def test_modal_known_cap_no_deep_card(client: TestClient) -> None:
    """cap 在 yaml 但无 DeepCard — 显示 'AI 草拟 / 手填' 引导"""
    # 假设 capabilities.yaml 中存在 01.constrained_schema
    resp = client.get("/cap/01.constrained_schema")
    assert resp.status_code == 200
    body = resp.text
    assert "AI 草拟" in body or "未填" in body
```

- [ ] **Step 2: Run + fails**

Run: `uv run --project backend pytest dashboard/tests/integration/test_v2_modal_endpoint.py -v`
Expected: 404

- [ ] **Step 3: 实现 _deep_card_modal.html**

```html
{# dashboard/templates/_deep_card_modal.html
   spec § 5.2 — 左右两栏,内容核心 + 链接图 #}
<div class="deep-card-modal" id="modal-{{ cap.id }}">
  <div class="modal-header">
    <h2>{{ cap.name_cn }}</h2>
    <span class="cap-id">{{ cap.id }}</span>
    <span class="status status--{{ cap.status }}">{{ cap.status }}</span>
    <button class="modal-close" hx-on="click: this.closest('.modal-overlay').remove()">×</button>
  </div>
  <div class="modal-body">
    <div class="modal-left">
      {% for field in content_fields %}
        {% include "_deep_card_field.html" with context %}
      {% endfor %}
    </div>
    <div class="modal-right">
      <h3>code anchors</h3>
      <ul>
        {% for ca in deep_card.code_anchors if deep_card %}
          <li><a href="vscode://file/{{ ca.file }}:{{ ca.line }}">{{ ca.file }}:{{ ca.line }}</a> {{ ca.note }}</li>
        {% else %}
          <li>(无)</li>
        {% endfor %}
      </ul>
      <h3>linked decisions</h3>
      <ul>
        {% for did in deep_card.linked_decisions if deep_card %}
          <li><a href="/decisions#dec_{{ did }}">{{ did }}</a></li>
        {% else %}
          <li>(无)</li>
        {% endfor %}
      </ul>
      <h3>linked specs</h3>
      <ul>
        {% for sp in deep_card.linked_specs if deep_card %}
          <li>{{ sp }}</li>
        {% else %}
          <li>(无)</li>
        {% endfor %}
      </ul>
      <h3>相关 capability</h3>
      <div hx-get="/cap/{{ cap.id }}/related?k=5"
           hx-trigger="load"
           hx-swap="innerHTML">载入...</div>
    </div>
  </div>
</div>
```

- [ ] **Step 4: 实现 _deep_card_field.html**

```html
{# dashboard/templates/_deep_card_field.html
   field, value, provenance, source 由 context 传入 #}
<div class="dc-field dc-field--{{ source }}" data-field="{{ field }}">
  <div class="dc-field-header">
    <span class="dc-field-label">{{ field }}</span>
    {% if value is none or (value == '' or value == []) %}
      <button class="ai-draft-btn"
              hx-post="/cap/{{ cap.id }}/ai_draft/{{ field }}"
              hx-target="closest .dc-field"
              hx-swap="outerHTML">AI 草拟</button>
    {% endif %}
  </div>
  {% if value is none or value == '' or value == [] %}
    <div class="dc-field-empty">(未填)</div>
  {% elif value is iterable and value is not string %}
    <ul>
      {% for item in value %}
        <li>{{ item.name }} — {{ item.brief_tradeoff }}</li>
      {% endfor %}
    </ul>
  {% else %}
    <div class="dc-field-value" contenteditable="true"
         hx-trigger="blur"
         hx-post="/cap/{{ cap.id }}/field/{{ field }}"
         hx-vals='js:{value: event.target.innerText}'
         hx-swap="outerHTML">{{ value }}</div>
  {% endif %}
  {% if provenance %}
    <div class="dc-field-provenance">
      <a href="{{ provenance.source }}" target="_blank">
        "{{ provenance.quote }}" — {{ provenance.source }}
      </a>
    </div>
  {% endif %}
</div>
```

- [ ] **Step 5: 实现 modal endpoint in server.py**

```python
# dashboard/server.py — 加 import + handler + route

async def deep_card_modal(request: Request) -> HTMLResponse:
    cap_id = request.path_params["cap_id"]
    caps_cfg = load_capabilities(CONFIG_DIR / "capabilities.yaml")
    cfg = next((c for c in caps_cfg if c.id == cap_id), None)
    if cfg is None:
        return HTMLResponse("<div class='error'>cap not found</div>", status_code=404)

    conn = open_db(DB_PATH)
    try:
        repo = DeepCardRepo(conn)
        card = repo.get(cap_id)
    finally:
        conn.close()

    # 装配 status(沿用 resolve_status)
    derived = resolve_status(cfg, PROJECT_ROOT)

    cap = {
        "id": cfg.id,
        "name_cn": cfg.name_cn,
        "status": derived,
    }
    content_fields = []
    for f in ("what", "why", "alternatives", "chosen_alternative", "tradeoff", "lessons_learned"):
        value = getattr(card, f, None) if card else None
        prov = (card.provenance.get(f) if card and card.provenance else None)
        content_fields.append({
            "field": f,
            "value": value,
            "provenance": prov,
            "source": card.prefill_source if card else "manual",
        })
    template = templates.get_template("_deep_card_modal.html")
    html = template.render(cap=cap, deep_card=card, content_fields=content_fields)
    return HTMLResponse(html)


# routes append:
#   Route("/cap/{cap_id}", deep_card_modal),
```

- [ ] **Step 6: Run + passes**

Run: `uv run --project backend pytest dashboard/tests/integration/test_v2_modal_endpoint.py -v`
Expected: 3 passed

- [ ] **Step 7: 65 + 新增 全 PASS**

Run: `uv run --project backend pytest dashboard/tests/ -v`

- [ ] **Step 8: Commit**

```bash
git add dashboard/templates/_deep_card_modal.html dashboard/templates/_deep_card_field.html \
        dashboard/server.py dashboard/tests/integration/test_v2_modal_endpoint.py
git commit -m "feat(harness-review-plan1): V2 modal GET endpoint + 模板"
```

---

## Task 12: V2 inline 编辑 POST + prefill_source 自动转换

**Files:**
- Modify: `dashboard/server.py`(加 POST `/cap/{cap_id}/field/{field}`)
- Test: `dashboard/tests/integration/test_v2_modal_endpoint.py`(extend)

- [ ] **Step 1: Add test cases to existing test file**

```python
# dashboard/tests/integration/test_v2_modal_endpoint.py — append

def test_post_field_updates_deep_card(client: TestClient) -> None:
    from dashboard.derive.deep_card_types import DeepCard
    from dashboard.state.db import open_db
    from dashboard.state.repositories import DeepCardRepo
    conn = open_db(client.app.state.db_path)  # type: ignore[attr-defined]
    repo = DeepCardRepo(conn)
    repo.upsert(DeepCard(cap_id="x", prefill_source="manual"))
    resp = client.post("/cap/x/field/what", data={"value": "edited content"})
    assert resp.status_code == 200
    assert "edited content" in resp.text

    conn2 = open_db(client.app.state.db_path)  # type: ignore[attr-defined]
    repo2 = DeepCardRepo(conn2)
    card = repo2.get("x")
    assert card is not None and card.what == "edited content"
    assert card.prefill_source == "manual"  # 第一次手填


def test_post_field_llm_to_hybrid(client: TestClient) -> None:
    from dashboard.derive.deep_card_types import DeepCard
    from dashboard.state.db import open_db
    from dashboard.state.repositories import DeepCardRepo
    conn = open_db(client.app.state.db_path)  # type: ignore[attr-defined]
    repo = DeepCardRepo(conn)
    repo.upsert(DeepCard(cap_id="y", what="llm wrote this", prefill_source="llm"))
    client.post("/cap/y/field/what", data={"value": "I edited it"})

    conn2 = open_db(client.app.state.db_path)  # type: ignore[attr-defined]
    card = DeepCardRepo(conn2).get("y")
    assert card is not None
    assert card.what == "I edited it"
    assert card.prefill_source == "hybrid"


def test_post_field_unknown_field_400(client: TestClient) -> None:
    resp = client.post("/cap/x/field/bogus_field", data={"value": "x"})
    assert resp.status_code == 400
```

- [ ] **Step 2: Run + fails**

Run: `uv run --project backend pytest dashboard/tests/integration/test_v2_modal_endpoint.py -v`
Expected: 3 fail (POST 路由不存在)

- [ ] **Step 3: Implement POST handler**

```python
# dashboard/server.py — add

ALLOWED_EDITABLE_FIELDS = {
    "what", "why", "tradeoff", "lessons_learned", "chosen_alternative",
}  # alternatives 是 list,单独 endpoint;metrics 也单独


async def post_field_update(request: Request) -> HTMLResponse:
    cap_id = request.path_params["cap_id"]
    field = request.path_params["field"]
    if field not in ALLOWED_EDITABLE_FIELDS:
        return HTMLResponse(f"<div class='error'>field not editable: {field}</div>", status_code=400)

    form = await request.form()
    value = form.get("value", "")
    if not isinstance(value, str):
        return HTMLResponse("<div class='error'>value must be str</div>", status_code=400)

    conn = open_db(DB_PATH)
    try:
        repo = DeepCardRepo(conn)
        repo.update_field(cap_id, field, value.strip())
        card = repo.get(cap_id)
    finally:
        conn.close()
    assert card is not None
    # 重 render 单字段
    prov = card.provenance.get(field)
    template = templates.get_template("_deep_card_field.html")
    html = template.render(
        cap={"id": cap_id},
        field=field,
        value=getattr(card, field),
        provenance=prov,
        source=card.prefill_source,
    )
    return HTMLResponse(html)


# route:
#   Route("/cap/{cap_id}/field/{field}", post_field_update, methods=["POST"]),
```

- [ ] **Step 4: Run + passes**

Run: `uv run --project backend pytest dashboard/tests/integration/test_v2_modal_endpoint.py -v`
Expected: 6 passed (3 modal + 3 POST)

- [ ] **Step 5: Commit**

```bash
git add dashboard/server.py dashboard/tests/integration/test_v2_modal_endpoint.py
git commit -m "feat(harness-review-plan1): V2 inline 编辑 POST + prefill_source 转换"
```

---

## Task 13: V2 AI 草拟按钮 POST + 单字段 LLM 生成

**Files:**
- Modify: `dashboard/server.py`(加 POST `/cap/{cap_id}/ai_draft/{field}`)
- Test: `dashboard/tests/integration/test_ai_draft_endpoint.py`

- [ ] **Step 1: Write test (with mocked LLMService)**

```python
# dashboard/tests/integration/test_ai_draft_endpoint.py
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from dashboard.derive.deep_card_types import FieldProvenance
from dashboard.derive.llm_prefill_prompt import SingleFieldPrefillResponse


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    from dashboard import server
    db = tmp_path / "board.db"
    monkeypatch.setattr(server, "DB_PATH", db)
    return TestClient(server.app)


def test_ai_draft_success_writes_field(client: TestClient, tmp_path: Path) -> None:
    spec_file = tmp_path / "docs" / "fake.md"
    spec_file.parent.mkdir(parents=True)
    spec_file.write_text("LLM 输出强制走 JSON schema 来避免编造", encoding="utf-8")

    fake_resp = SingleFieldPrefillResponse(
        value="LLM 输出强制走 JSON schema",
        provenance=FieldProvenance(quote="LLM 输出强制走 JSON schema", source="docs/fake.md"),
    )
    fake_llm_resp = MagicMock()
    fake_llm_resp.parsed = fake_resp
    fake_llm_resp.content = fake_resp.model_dump_json()
    fake_llm = MagicMock()
    fake_llm.chat.return_value = fake_llm_resp

    with patch("dashboard.server.PROJECT_ROOT", tmp_path):
        with patch("dashboard.server._get_llm_service", return_value=fake_llm):
            resp = client.post("/cap/01.constrained_schema/ai_draft/what")
    assert resp.status_code == 200
    assert "LLM 输出强制走" in resp.text


def test_ai_draft_rejects_fabricated_quote(client: TestClient, tmp_path: Path) -> None:
    spec_file = tmp_path / "docs" / "fake.md"
    spec_file.parent.mkdir(parents=True)
    spec_file.write_text("Only this text", encoding="utf-8")

    bad_resp = SingleFieldPrefillResponse(
        value="编造内容",
        provenance=FieldProvenance(quote="编造引用", source="docs/fake.md"),
    )
    fake_llm_resp = MagicMock()
    fake_llm_resp.parsed = bad_resp
    fake_llm = MagicMock()
    fake_llm.chat.return_value = fake_llm_resp

    with patch("dashboard.server.PROJECT_ROOT", tmp_path):
        with patch("dashboard.server._get_llm_service", return_value=fake_llm):
            resp = client.post("/cap/01.constrained_schema/ai_draft/what")
    # provenance 失败 → 422,字段未写
    assert resp.status_code == 422
    assert "not found" in resp.text.lower() or "provenance" in resp.text.lower()


def test_ai_draft_llm_unavailable_503(client: TestClient) -> None:
    with patch("dashboard.server._get_llm_service", side_effect=RuntimeError("no llm")):
        resp = client.post("/cap/01.constrained_schema/ai_draft/what")
    assert resp.status_code == 503
```

- [ ] **Step 2: Run + fails**

Run: `uv run --project backend pytest dashboard/tests/integration/test_ai_draft_endpoint.py -v`
Expected: 404

- [ ] **Step 3: Implement POST handler**

```python
# dashboard/server.py — add

def _get_llm_service():
    """lazy build LLMService — 测试可 patch。"""
    from app.services.openai_client import build_llm_service_from_env
    return build_llm_service_from_env()


def _resolve_linked_sources(cap_id: str, base_dir: Path) -> tuple[list[str], list[str]]:
    """从 DeepCard 已有 linked_specs / memories 取;空时 fallback 空 list(Plan 2 enrich)。"""
    conn = open_db(DB_PATH)
    try:
        card = DeepCardRepo(conn).get(cap_id)
    finally:
        conn.close()
    if card:
        return list(card.linked_specs), list(card.linked_memories)
    return [], []


async def post_ai_draft(request: Request) -> HTMLResponse:
    from dashboard.derive.llm_prefill_prompt import (
        PrefillRequest,
        SingleFieldPrefillResponse,
        build_single_field_prefill_prompt,
    )
    from dashboard.derive.provenance import verify_quote_in_source

    cap_id = request.path_params["cap_id"]
    field = request.path_params["field"]
    if field not in {"what", "why", "alternatives", "chosen_alternative",
                     "tradeoff", "lessons_learned"}:
        return HTMLResponse(f"field not draftable: {field}", status_code=400)

    caps_cfg = load_capabilities(CONFIG_DIR / "capabilities.yaml")
    cfg = next((c for c in caps_cfg if c.id == cap_id), None)
    if cfg is None:
        return HTMLResponse("cap not found", status_code=404)

    try:
        llm = _get_llm_service()
    except Exception as e:
        return HTMLResponse(f"LLM unavailable: {e}", status_code=503)

    linked_specs, linked_memories = _resolve_linked_sources(cap_id, PROJECT_ROOT)
    req = PrefillRequest(
        cap_id=cap_id, cap_name_cn=cfg.name_cn,
        linked_spec_paths=linked_specs,
        linked_memory_paths=linked_memories,
        decisions_summary=[],
    )
    prompt = build_single_field_prefill_prompt(req, field_name=field)
    try:
        resp = llm.chat(prompt=prompt, tier="balanced", schema=SingleFieldPrefillResponse)
    except Exception as e:
        return HTMLResponse(f"LLM error: {e}", status_code=502)
    parsed: SingleFieldPrefillResponse = resp.parsed or \
        SingleFieldPrefillResponse.model_validate_json(resp.content)

    # provenance 校验
    if not parsed.provenance.quote:
        return HTMLResponse("LLM gave up (no quote)", status_code=422)
    check = verify_quote_in_source(parsed.provenance.quote, parsed.provenance.source,
                                    base_dir=PROJECT_ROOT)
    if not check.ok:
        return HTMLResponse(f"provenance 校验失败:{check.reason}", status_code=422)

    # 写入字段 + 标 prefill_source=llm
    conn = open_db(DB_PATH)
    try:
        repo = DeepCardRepo(conn)
        repo.update_field(cap_id, field, parsed.value)
        # 把 provenance 也存进去
        card = repo.get(cap_id)
        assert card is not None
        new_prov = dict(card.provenance)
        new_prov[field] = parsed.provenance.model_dump()
        card_data = card.model_dump()
        card_data["provenance"] = new_prov
        card_data["prefill_source"] = "llm"
        repo.upsert(DeepCard.model_validate(card_data))
        card = repo.get(cap_id)
    finally:
        conn.close()

    assert card is not None
    template = templates.get_template("_deep_card_field.html")
    html = template.render(
        cap={"id": cap_id}, field=field,
        value=getattr(card, field), provenance=card.provenance.get(field),
        source="llm",
    )
    return HTMLResponse(html)


# route:
#   Route("/cap/{cap_id}/ai_draft/{field}", post_ai_draft, methods=["POST"]),
```

- [ ] **Step 4: Run + passes**

Run: `uv run --project backend pytest dashboard/tests/integration/test_ai_draft_endpoint.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add dashboard/server.py dashboard/tests/integration/test_ai_draft_endpoint.py
git commit -m "feat(harness-review-plan1): V2 AI 草拟 POST + provenance 校验 + 503/422 边界"
```

---

## Task 14: V2 provenance UI(边框着色 + quote 显示)

**Files:**
- Modify: `dashboard/static/style.css`
- Modify: `dashboard/templates/_deep_card_field.html`(已含 provenance render,确认 class hooks)

- [ ] **Step 1: 添加 CSS**

```css
/* dashboard/static/style.css — append */

.deep-card-modal {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
}
.deep-card-modal > .modal-body {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 24px;
  background: white;
  width: 1200px;
  max-width: 95vw;
  max-height: 90vh;
  padding: 24px;
  border-radius: 8px;
  overflow: auto;
}
.dc-field {
  margin-bottom: 16px;
  padding: 12px;
  border-left: 4px solid #999;
  background: #fafafa;
}
.dc-field--llm {
  border-left-color: #f59e0b;
  background: #fffbeb;
}
.dc-field--hybrid {
  border-left-color: #3b82f6;
  background: #eff6ff;
}
.dc-field--manual {
  border-left-color: #10b981;
  background: #f0fdf4;
}
.dc-field-empty {
  color: #999;
  font-style: italic;
}
.dc-field-provenance {
  margin-top: 6px;
  font-size: 11px;
  color: #666;
  font-style: italic;
}
.dc-field-provenance a { color: #3b82f6; }
.ai-draft-btn {
  font-size: 11px;
  padding: 2px 8px;
  background: #f59e0b;
  color: white;
  border: none;
  border-radius: 3px;
  cursor: pointer;
}
.ai-draft-btn:hover { background: #d97706; }
```

- [ ] **Step 2: 视觉手动验证**

```bash
make board-refresh && open http://localhost:8910
```

点 chip,验证 modal 弹出 + 3 种边框色(llm 橙 / hybrid 蓝 / manual 绿)。

- [ ] **Step 3: Commit**

```bash
git add dashboard/static/style.css
git commit -m "feat(harness-review-plan1): V2 provenance UI 着色边框 + AI 草拟按钮"
```

---

## Task 15: 10 张样本 cap 手动 prefill + review

**Files:** (无 code 改动,内容生成 + review)

候选 10 cap(基于 spec § 16 推荐,实施时按 capabilities.yaml 实际 id 微调):

| # | cap_id | dim | spec/memory 关键来源 |
|---|---|---|---|
| 1 | `01.constrained_schema` | 01 | `2026-05-05-v0.8.5-constrained-router-design.md` |
| 2 | `01.skills_bundle` | 01 | 同上 |
| 3 | `02.tool_registry` | 02 | `2026-05-09-v0.9-chat-mode-c1c2-design.md` |
| 4 | `03.langgraph_supervisor` | 03 | `2026-05-09-v0.9-chat-mode-c1c2-design.md` |
| 5 | `03.research_5agent` | 03 | `2026-05-04-v0.8.4-b1-single-deep-design.md` |
| 6 | `04.bi_temporal_memory` | 04 | `2026-05-10-c5-cross-session-memory-design.md` |
| 7 | `05.milvus_3_collections` | 05 | `2026-05-02-v0.7-kb-search-milvus-design.md` |
| 8 | `06.monitoring_engine` | 06 | `2026-05-08-v1.0-portfolio-monitoring-engine-design.md` |
| 9 | `07.escalation_protocol` | 03(或 07)| `2026-05-09-v0.9-chat-mode-c1c2-design.md` |
| 10 | `08.tier_router` | 08 | `2026-04-30-v0-architecture-design.md`(or B/C plan) |

- [ ] **Step 1: 实际 cap_id 校对**

Run:
```bash
uv run python -c "
from pathlib import Path
from dashboard.derive.capability_resolver import load_capabilities
caps = load_capabilities(Path('dashboard/config/capabilities.yaml'))
for c in caps:
    print(c.id, '|', c.dimension, '|', c.name_cn)
"
```

挑出实际存在的 10 cap_id。若上表 cap_id 不存在,选邻近的(同 dim 内)。

- [ ] **Step 2: 跑 prefill batch**

```bash
unset all_proxy https_proxy http_proxy
uv run python -m backend.scripts.prefill_deep_cards \
    --caps "01.constrained_schema,01.skills_bundle,..." \
    --db backend/data/board.db
```

Expected:输出 `fields written: N, rejected: M`,期望 N/(N+M) ≥ 0.9

- [ ] **Step 3: 通过 V2 modal review 这 10 张**

逐张打开,人工 review LLM 输出:
- 内容准确?
- 不准确字段 → 编辑(自动转 hybrid)
- 字段拒绝入库的 → 看 prefill_log,手动补

```bash
make board
# 浏览器中逐 cap 点开 modal 检查
```

- [ ] **Step 4: 验证 prefill_log**

```bash
uv run python -c "
import sqlite3
conn = sqlite3.connect('backend/data/board.db')
for row in conn.execute('SELECT cap_id, field_name, status FROM prefill_log'):
    print(row)
"
```

期望:每个 cap × 6 field = 60 行,success 比例 ≥ 70%(允许 lessons_learned 等 optional 字段空)

- [ ] **Step 5: Commit 数据 baseline**

```bash
# board.db 是 gitignored 的,不入 git
# 把 10 cap 的 prefill 结果导出为 yaml seed(留 reproducibility)
uv run python -c "
import json
from dashboard.state.db import open_db
from dashboard.state.repositories import DeepCardRepo
conn = open_db('backend/data/board.db')
cards = DeepCardRepo(conn).get_all()
with open('dashboard/data/deep_cards_seed.jsonl', 'w') as f:
    for c in cards:
        f.write(c.model_dump_json() + '\n')
"
git add dashboard/data/deep_cards_seed.jsonl
git commit -m "data(harness-review-plan1): 10 cap 样本 prefill + review seed"
```

(注:`dashboard/data/` 需新建 + 加入 .gitignore 排除 board.db 但保留 jsonl)

---

## Task 16: Plan 1 ship checklist 收尾

**Files:** (整体检查,无新 code)

- [ ] **Step 1: 跑完整测试**

```bash
uv run --project backend pytest dashboard/tests/ -v
```

Expected:65(原)+ 30+(L0)+ 15+(L1)+ 5(L2 cassette)= 115+ passed

- [ ] **Step 2: mypy strict**

```bash
uv run --project backend mypy dashboard/ backend/scripts/prefill_deep_cards.py --strict
```

Expected:Success

- [ ] **Step 3: ruff**

```bash
uv run --project backend ruff format --check dashboard/ backend/scripts/
uv run --project backend ruff check dashboard/ backend/scripts/
```

Expected:All clean

- [ ] **Step 4: board startup + refresh + 手动 5 chip 点开**

```bash
make board
make board-refresh
# 浏览器逐 chip 点开 modal,验证:
#  - 完成度角标颜色对
#  - confidence 数字显示
#  - modal 双栏布局
#  - inline 编辑 work
#  - AI 草拟按钮 work
#  - 相关推荐区显示(可能是 keyword fallback)
make board-stop
```

- [ ] **Step 5: 添加 claude-context 知识卡**

```bash
# 创建 docs/claude-context/harness-board-review-plan1-done.md
cat > docs/claude-context/harness-board-review-plan1-done.md <<'EOF'
---
name: harness-board-review-plan1-done
description: Plan 1 ship — DeepCard 底座 + V2 模块深读 modal + LLM L2 prefill + Milvus collection
type: project
---

Plan 1 ship 内容:
- sqlite v2 schema(deep_cards / flashcards / prefill_log)
- `prefill_deep_cards.py` batch CLI + constrained schema + provenance fuzzy match 校验
- Milvus collection `harness_board_deepcards` + keyword fallback
- V1 chip 完成度角标 + confidence 数字
- V2 modal(双栏 + inline 编辑 + AI 草拟按钮 + provenance UI 边框 3 色)
- 10 张样本 cap prefill + review,seed jsonl 入 git

**Why**:覆盖复习场景 B(onboard)+ C(模块化),作为 Plan 2/3 的内容地基。

**How to apply**:
- 下次问"这个 capability 的 why 是什么" → 直接看 V2 modal
- 修代码后改 DeepCard 需手动改(暂无自动同步,Plan 4 再说)
- 新 cap 加到 capabilities.yaml 后,跑 prefill batch 拉一张
EOF

# 更新 CLAUDE.md 索引
# 加一行到 c5 子系统下面 / 或新增 "Harness Board Review Mode" 段
git add docs/claude-context/harness-board-review-plan1-done.md CLAUDE.md
git commit -m "docs(harness-review-plan1): 知识卡 + CLAUDE.md 索引"
```

- [ ] **Step 6: 创建 PR**

```bash
git push -u origin feat/c5-implementation  # 当前 branch 已包含,或创建新 branch
# gh pr create ...(按 README 习惯)
```

---

## Plan 1 总结

**交付内容:**
- 11 个新 Python module + 2 个新 template + CSS 扩展
- 16 个 task,每 task TDD step 完整
- 测试覆盖:+30 L0 / +15 L1 / +5 L2 cassette
- 10 张样本 DeepCard 入 jsonl seed
- 知识卡片 + CLAUDE.md 索引

**用户价值:**
- 复习场景 B + C 走通(模块深读形态)
- 后续 Plan 2/3(V3 鸟瞰 / V4 故事 / V5 闪卡)的内容底座已就绪

**待 Plan 2 / 3 接续:**
- 相关推荐 Milvus 真路径(Task 9 简化为 fallback,Plan 2 完整 wire)
- V3 / V4 / V5 视图实现
- 全量 ~50 cap prefill

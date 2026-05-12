# Harness Board Review Mode — Plan 3: V5 闪卡 SRS + 全量 prefill + 收尾

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans`. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** [`docs/superpowers/specs/2026-05-12-harness-board-review-mode-design.md`](../specs/2026-05-12-harness-board-review-mode-design.md)

**前置依赖:** Plan 1 + Plan 2 已 ship(DeepCard 底座 + V2 modal + V3 鸟瞰 + V4 故事 + Milvus + 跨视图联动)

**Goal:** 落地 V5 闪卡 SRS(D 主动召回场景),把所有 DeepCard 内容机械派生成可复习的闪卡;完成全量 ~50 张 cap 的 prefill 工作,把复合型工具从 demo 推到日常可用。

**Architecture:** SM-2 算法 50 行 Python(`derive/srs.py`),纯函数 + Protocol 接口预留 FSRS。闪卡 3 类模板(alternatives / tradeoff / lessons)机械派生自 DeepCard,DeepCard 编辑时触发 `regenerate_flashcards(cap_id)` — 保留旧 srs_state,overwrite Q/A 文本。`/flashcards/today` 主入口拉新卡 ≤5 + 到期卡 ≤20,翻面 + 0-5 自评 POST → SM-2 算 next_review_at 落库。

**Tech Stack:** Python 3.11 / SM-2 算法 / Starlette + Jinja / htmx / sqlite

**Plan 3 ship checklist:**
- SM-2 算法 + Protocol 接口
- 闪卡 3 模板派生 + DeepCard 编辑 hook
- `/flashcards/today` 主入口 + 翻面 + 0-5 自评
- 闪卡历史/统计页(可选)
- 全量 ~50 cap prefill 完成(或 ≥30 张 / 涵盖所有 8 维)
- dashboard 全测试 PASS + +20 L0 / +5 L1 / +2 L2 cassette
- mypy strict + ruff clean
- README 更新 + CLAUDE.md 索引 + 整体 review mode 总卡

---

## File Structure(Plan 3 范围)

**新建:**
- `dashboard/derive/srs.py` — SM-2 算法 + SrsAlgo Protocol
- `dashboard/derive/flashcard_generator.py` — 3 类模板派生
- `dashboard/templates/flashcards.html` — `/flashcards/today` 主入口
- `dashboard/templates/_flashcard_review.html` — 单卡翻面 UI
- `dashboard/templates/flashcards_stats.html` — 学习统计页(简版)
- `dashboard/tests/unit/test_srs.py`
- `dashboard/tests/unit/test_flashcard_generator.py`
- `dashboard/tests/integration/test_flashcards_endpoint.py`
- `dashboard/tests/integration/test_flashcard_regenerate_hook.py`

**修改:**
- `dashboard/state/repositories.py` — DeepCardRepo.upsert 触发 flashcard regenerate
- `dashboard/server.py` — `GET /flashcards/today` + `POST /flashcards/{id}/review` + `GET /flashcards/stats`
- `dashboard/templates/main.html` — nav 加 "🎴 闪卡"
- `README.md` — 当前版本段更新
- `CLAUDE.md` — Harness Board Review Mode 段索引

---

## Task 1: SM-2 SRS 算法 + Protocol

**Files:**
- Create: `dashboard/derive/srs.py`
- Test: `dashboard/tests/unit/test_srs.py`

- [ ] **Step 1: Write test**

```python
# dashboard/tests/unit/test_srs.py
from __future__ import annotations

from datetime import datetime, timedelta, UTC

from dashboard.derive.deep_card_types import SrsState
from dashboard.derive.srs import SM2Algo, schedule_next_review


def test_first_review_grade_5_advances_to_interval_1() -> None:
    """新卡(repetition=0)第一次得 5 → repetition=1, interval=1, ef 微升"""
    s = SrsState()
    new = SM2Algo().apply(s, grade=5, now=datetime(2026, 5, 12, tzinfo=UTC))
    assert new.repetition == 1
    assert new.interval == 1
    assert new.ef > 2.5  # 高分 ef 上升
    assert new.next_review_at == datetime(2026, 5, 13, tzinfo=UTC)


def test_second_review_grade_4_advances_to_interval_6() -> None:
    """repetition=1, interval=1 → 得 4 → repetition=2, interval=6"""
    s = SrsState(repetition=1, interval=1, ef=2.5,
                 last_reviewed_at=datetime(2026, 5, 11, tzinfo=UTC))
    new = SM2Algo().apply(s, grade=4, now=datetime(2026, 5, 12, tzinfo=UTC))
    assert new.repetition == 2
    assert new.interval == 6
    assert new.next_review_at == datetime(2026, 5, 18, tzinfo=UTC)


def test_third_review_uses_ef_multiplication() -> None:
    """repetition>=2 时 interval = prev_interval * ef"""
    s = SrsState(repetition=2, interval=6, ef=2.5,
                 last_reviewed_at=datetime(2026, 5, 1, tzinfo=UTC))
    new = SM2Algo().apply(s, grade=4, now=datetime(2026, 5, 7, tzinfo=UTC))
    assert new.repetition == 3
    assert new.interval == 15  # 6 * 2.5 = 15
    expected = datetime(2026, 5, 7, tzinfo=UTC) + timedelta(days=15)
    assert new.next_review_at == expected


def test_low_grade_resets_repetition() -> None:
    """grade < 3 → repetition=0, interval=1, ef 下降"""
    s = SrsState(repetition=5, interval=30, ef=2.8,
                 last_reviewed_at=datetime(2026, 5, 1, tzinfo=UTC))
    new = SM2Algo().apply(s, grade=1, now=datetime(2026, 5, 31, tzinfo=UTC))
    assert new.repetition == 0
    assert new.interval == 1
    assert new.ef < 2.8


def test_ef_lower_bound() -> None:
    """ef 不能低于 1.3"""
    s = SrsState(ef=1.3)
    new = SM2Algo().apply(s, grade=0, now=datetime(2026, 5, 12, tzinfo=UTC))
    assert new.ef == 1.3


def test_confidence_field_set_from_grade() -> None:
    """confidence 反映上次自评(用于 V3 节点边框 / V1 chip)"""
    s = SrsState()
    new = SM2Algo().apply(s, grade=4, now=datetime(2026, 5, 12, tzinfo=UTC))
    assert new.confidence == 4


def test_schedule_next_review_convenience() -> None:
    """top-level helper:输入 state + grade,返回 new state"""
    s = SrsState()
    new = schedule_next_review(s, grade=5)
    assert new.repetition == 1
```

- [ ] **Step 2: Run + fails**

Run: `uv run --project backend pytest dashboard/tests/unit/test_srs.py -v`
Expected: ImportError

- [ ] **Step 3: Implement**

```python
# dashboard/derive/srs.py
"""SM-2 SRS 算法 + Protocol 接口(为 FSRS v1.x 升级预留)。spec § 5.5。

参考 Wozniak (1990)。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol

from dashboard.derive.deep_card_types import SrsState


class SrsAlgo(Protocol):
    """SRS 算法接口 — Plan 3 SM-2,v1.x 可换 FSRS。"""

    def apply(self, state: SrsState, *, grade: int, now: datetime) -> SrsState:
        """输入当前 state + 自评 grade ∈ [0, 5],输出新 state。"""


class SM2Algo:
    """SM-2 算法 — Anki 经典。"""

    EF_MIN = 1.3

    def apply(self, state: SrsState, *, grade: int, now: datetime) -> SrsState:
        if not 0 <= grade <= 5:
            raise ValueError(f"grade must be 0..5, got {grade}")
        # ef 更新公式(Wozniak)
        new_ef = state.ef + (0.1 - (5 - grade) * (0.08 + (5 - grade) * 0.02))
        new_ef = max(new_ef, self.EF_MIN)

        if grade < 3:
            # 答错 — 重置
            new_repetition = 0
            new_interval = 1
        else:
            new_repetition = state.repetition + 1
            if new_repetition == 1:
                new_interval = 1
            elif new_repetition == 2:
                new_interval = 6
            else:
                new_interval = int(round(state.interval * state.ef))

        next_at = now + timedelta(days=new_interval)
        return SrsState(
            confidence=grade,
            ef=new_ef,
            interval=new_interval,
            repetition=new_repetition,
            last_reviewed_at=now,
            next_review_at=next_at,
        )


def schedule_next_review(state: SrsState, *, grade: int) -> SrsState:
    """Convenience wrapper — 用 SM-2 + now()。"""
    return SM2Algo().apply(state, grade=grade, now=datetime.now(UTC))
```

- [ ] **Step 4: Run + passes**

Run: `uv run --project backend pytest dashboard/tests/unit/test_srs.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add dashboard/derive/srs.py dashboard/tests/unit/test_srs.py
git commit -m "feat(harness-review-plan3): SM-2 SRS 算法 + SrsAlgo Protocol"
```

---

## Task 2: 闪卡 3 类模板派生

**Files:**
- Create: `dashboard/derive/flashcard_generator.py`
- Test: `dashboard/tests/unit/test_flashcard_generator.py`

- [ ] **Step 1: Write test**

```python
# dashboard/tests/unit/test_flashcard_generator.py
from __future__ import annotations

from dashboard.derive.deep_card_types import AlternativeItem, DeepCard
from dashboard.derive.flashcard_generator import generate_flashcards


def test_generates_tradeoff_card() -> None:
    card = DeepCard(cap_id="x.a", tradeoff="选 schema 因为协议支持")
    cards = generate_flashcards(card, cap_name_cn="X.A")
    kinds = {c.template_kind for c in cards}
    assert "tradeoff" in kinds
    tc = next(c for c in cards if c.template_kind == "tradeoff")
    assert "X.A" in tc.question
    assert tc.answer == "选 schema 因为协议支持"


def test_generates_alternatives_card_with_chosen() -> None:
    card = DeepCard(
        cap_id="x", chosen_alternative="constrained JSON schema",
        alternatives=[
            AlternativeItem(name="free-text + regex", brief_tradeoff="易碎"),
            AlternativeItem(name="constrained JSON schema", brief_tradeoff="model 端约束"),
        ],
    )
    cards = generate_flashcards(card, cap_name_cn="X")
    ac = next(c for c in cards if c.template_kind == "alternatives")
    assert "constrained JSON schema" in ac.answer
    assert "model 端约束" in ac.answer


def test_skip_alternatives_card_if_no_chosen() -> None:
    """chosen_alternative 缺 → 不生成 alternatives 闪卡"""
    card = DeepCard(cap_id="x", alternatives=[AlternativeItem(name="A", brief_tradeoff="a")])
    cards = generate_flashcards(card, cap_name_cn="X")
    assert all(c.template_kind != "alternatives" for c in cards)


def test_generates_lessons_card_if_non_empty() -> None:
    card = DeepCard(cap_id="x", lessons_learned="撞过 ruff 行宽")
    cards = generate_flashcards(card, cap_name_cn="X")
    lc = next(c for c in cards if c.template_kind == "lessons")
    assert lc.answer == "撞过 ruff 行宽"


def test_skip_lessons_card_if_empty() -> None:
    card = DeepCard(cap_id="x", tradeoff="t")  # no lessons_learned
    cards = generate_flashcards(card, cap_name_cn="X")
    assert all(c.template_kind != "lessons" for c in cards)


def test_no_content_no_cards() -> None:
    """DeepCard 全空 → 不生成"""
    card = DeepCard(cap_id="x")
    cards = generate_flashcards(card, cap_name_cn="X")
    assert cards == []


def test_flashcard_id_format() -> None:
    card = DeepCard(cap_id="x", tradeoff="t")
    cards = generate_flashcards(card, cap_name_cn="X")
    assert any(c.id == "x::tradeoff" for c in cards)


def test_chosen_not_in_alternatives_skipped() -> None:
    """chosen_alternative 不在 alternatives 名字中 → 不生成 alternatives 闪卡(spec § 4.1 提到的运行时校验)"""
    card = DeepCard(cap_id="x", chosen_alternative="bogus",
                    alternatives=[AlternativeItem(name="A", brief_tradeoff="a")])
    cards = generate_flashcards(card, cap_name_cn="X")
    assert all(c.template_kind != "alternatives" for c in cards)
```

- [ ] **Step 2: Run + fails**

Run: `uv run --project backend pytest dashboard/tests/unit/test_flashcard_generator.py -v`
Expected: ImportError

- [ ] **Step 3: Implement**

```python
# dashboard/derive/flashcard_generator.py
"""DeepCard → Flashcard 机械模板派生(无 LLM)。spec § 5.5。"""

from __future__ import annotations

from datetime import UTC, datetime

from dashboard.derive.deep_card_types import DeepCard, Flashcard, SrsState


def generate_flashcards(card: DeepCard, *, cap_name_cn: str) -> list[Flashcard]:
    """生成 0-3 张闪卡。

    模板:
    - tradeoff:Q="Capability {name} 的关键 tradeoff 是什么?" A=tradeoff 字段
    - alternatives:Q="Capability {name} 在业界 alternatives 中我们选了哪个?为什么?"
      A=chosen + brief_tradeoff(仅 chosen_alternative 在 alternatives 名字中时)
    - lessons:Q="Capability {name} 撞过什么坑?" A=lessons_learned(仅非空)
    """
    out: list[Flashcard] = []
    now = datetime.now(UTC)

    if card.tradeoff:
        out.append(Flashcard(
            id=f"{card.cap_id}::tradeoff",
            cap_id=card.cap_id,
            template_kind="tradeoff",
            question=f"Capability「{cap_name_cn}」的关键 tradeoff 是什么?",
            answer=card.tradeoff,
            srs_state=SrsState(),
            created_at=now,
        ))

    if card.chosen_alternative and card.alternatives:
        alt_match = next(
            (a for a in card.alternatives if a.name == card.chosen_alternative), None
        )
        if alt_match is not None:
            out.append(Flashcard(
                id=f"{card.cap_id}::alternatives",
                cap_id=card.cap_id,
                template_kind="alternatives",
                question=f"Capability「{cap_name_cn}」在业界 alternatives 中我们选了哪个?为什么?",
                answer=f"{card.chosen_alternative} — {alt_match.brief_tradeoff}",
                srs_state=SrsState(),
                created_at=now,
            ))

    if card.lessons_learned:
        out.append(Flashcard(
            id=f"{card.cap_id}::lessons",
            cap_id=card.cap_id,
            template_kind="lessons",
            question=f"Capability「{cap_name_cn}」撞过什么坑?",
            answer=card.lessons_learned,
            srs_state=SrsState(),
            created_at=now,
        ))

    return out
```

- [ ] **Step 4: Run + passes**

Run: `uv run --project backend pytest dashboard/tests/unit/test_flashcard_generator.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add dashboard/derive/flashcard_generator.py dashboard/tests/unit/test_flashcard_generator.py
git commit -m "feat(harness-review-plan3): 闪卡 3 类模板派生 (tradeoff/alternatives/lessons)"
```

---

## Task 3: DeepCard upsert hook → regenerate flashcards

**Files:**
- Modify: `dashboard/state/repositories.py`
- Test: `dashboard/tests/integration/test_flashcard_regenerate_hook.py`

- [ ] **Step 1: Write test**

```python
# dashboard/tests/integration/test_flashcard_regenerate_hook.py
from __future__ import annotations

from pathlib import Path

from dashboard.derive.deep_card_types import DeepCard, SrsState
from dashboard.state.db import open_db
from dashboard.state.repositories import DeepCardRepo, FlashcardRepo, regenerate_flashcards_for


def test_upsert_first_time_generates_flashcards(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "t.db")
    dc_repo = DeepCardRepo(conn)
    fc_repo = FlashcardRepo(conn)
    dc_repo.upsert(DeepCard(cap_id="x.a", tradeoff="选 schema",
                            lessons_learned="撞过 escape"))
    regenerate_flashcards_for("x.a", dc_repo=dc_repo, fc_repo=fc_repo,
                              cap_name_cn="X.A")
    fcs = fc_repo.get_by_cap_id("x.a")
    assert len(fcs) == 2  # tradeoff + lessons


def test_regenerate_preserves_srs_state(tmp_path: Path) -> None:
    """DeepCard 编辑后重生成 — 保留旧闪卡的 srs_state,只 overwrite Q/A 文本"""
    conn = open_db(tmp_path / "t.db")
    dc_repo = DeepCardRepo(conn)
    fc_repo = FlashcardRepo(conn)
    dc_repo.upsert(DeepCard(cap_id="x.a", tradeoff="V1 tradeoff"))
    regenerate_flashcards_for("x.a", dc_repo=dc_repo, fc_repo=fc_repo,
                              cap_name_cn="X.A")
    # 模拟用户复习过 → srs_state 有积累
    fc = fc_repo.get("x.a::tradeoff")
    assert fc is not None
    fc_with_state = fc.model_copy(update={
        "srs_state": SrsState(repetition=3, interval=10, ef=2.6, confidence=4)
    })
    fc_repo.upsert(fc_with_state)

    # DeepCard 改 tradeoff,re-generate
    dc_repo.upsert(DeepCard(cap_id="x.a", tradeoff="V2 改写后的 tradeoff"))
    regenerate_flashcards_for("x.a", dc_repo=dc_repo, fc_repo=fc_repo,
                              cap_name_cn="X.A")
    fc_after = fc_repo.get("x.a::tradeoff")
    assert fc_after is not None
    assert fc_after.answer == "V2 改写后的 tradeoff"  # 文本变
    assert fc_after.srs_state.repetition == 3  # SRS 保留
    assert fc_after.srs_state.ef == 2.6


def test_regenerate_deletes_obsolete_kinds(tmp_path: Path) -> None:
    """DeepCard 删掉 lessons_learned → 对应闪卡应该消失"""
    conn = open_db(tmp_path / "t.db")
    dc_repo = DeepCardRepo(conn)
    fc_repo = FlashcardRepo(conn)
    dc_repo.upsert(DeepCard(cap_id="x", tradeoff="t", lessons_learned="l"))
    regenerate_flashcards_for("x", dc_repo=dc_repo, fc_repo=fc_repo, cap_name_cn="X")
    assert len(fc_repo.get_by_cap_id("x")) == 2

    # 删 lessons
    dc_repo.upsert(DeepCard(cap_id="x", tradeoff="t"))
    regenerate_flashcards_for("x", dc_repo=dc_repo, fc_repo=fc_repo, cap_name_cn="X")
    fcs = fc_repo.get_by_cap_id("x")
    assert len(fcs) == 1
    assert fcs[0].template_kind == "tradeoff"
```

- [ ] **Step 2: Run + fails**

Run: `uv run --project backend pytest dashboard/tests/integration/test_flashcard_regenerate_hook.py -v`
Expected: ImportError regenerate_flashcards_for

- [ ] **Step 3: Implement helper in repositories.py**

```python
# dashboard/state/repositories.py — append

def regenerate_flashcards_for(
    cap_id: str,
    *,
    dc_repo: DeepCardRepo,
    fc_repo: FlashcardRepo,
    cap_name_cn: str,
) -> None:
    """DeepCard 编辑后调:重生成 flashcard 集合,保留 srs_state。

    流程:
    1. 取当前 DeepCard
    2. 派生新 flashcard 集合(generate_flashcards)
    3. 取旧 flashcard srs_state 按 (cap_id, kind) 索引
    4. 新集合每张:若 (cap_id, kind) 已有 srs_state,用旧的;否则用默认
    5. delete_by_cap_id 然后 upsert 新集合
    """
    from dashboard.derive.flashcard_generator import generate_flashcards

    card = dc_repo.get(cap_id)
    if card is None:
        fc_repo.delete_by_cap_id(cap_id)
        return

    new_cards = generate_flashcards(card, cap_name_cn=cap_name_cn)

    old_cards = {f.template_kind: f for f in fc_repo.get_by_cap_id(cap_id)}
    fc_repo.delete_by_cap_id(cap_id)
    for nc in new_cards:
        old = old_cards.get(nc.template_kind)
        if old:
            preserved = nc.model_copy(update={
                "srs_state": old.srs_state,
                "created_at": old.created_at,
                "last_reviewed_at": old.last_reviewed_at,
            })
            fc_repo.upsert(preserved)
        else:
            fc_repo.upsert(nc)
```

- [ ] **Step 4: Run + passes**

Run: `uv run --project backend pytest dashboard/tests/integration/test_flashcard_regenerate_hook.py -v`
Expected: 3 passed

- [ ] **Step 5: Wire to V2 edit endpoints**

Modify Plan 1 Task 12 / 13 的 `post_field_update` 和 `post_ai_draft`,在 `repo.update_field` / `repo.upsert` 之后追加:

```python
# dashboard/server.py — in post_field_update + post_ai_draft 末尾(update 之后)
caps_cfg = load_capabilities(CONFIG_DIR / "capabilities.yaml")
cfg = next((c for c in caps_cfg if c.id == cap_id), None)
if cfg is not None:
    fc_repo = FlashcardRepo(conn)
    regenerate_flashcards_for(cap_id, dc_repo=repo, fc_repo=fc_repo,
                               cap_name_cn=cfg.name_cn)
```

Add `from dashboard.state.repositories import FlashcardRepo, regenerate_flashcards_for` to imports.

- [ ] **Step 6: Run all dashboard tests**

```bash
uv run --project backend pytest dashboard/tests/ -v
```

Expected: 新增 3 PASS,Plan 1+2 既有不破

- [ ] **Step 7: Commit**

```bash
git add dashboard/state/repositories.py dashboard/server.py \
        dashboard/tests/integration/test_flashcard_regenerate_hook.py
git commit -m "feat(harness-review-plan3): DeepCard 编辑 hook → flashcard 重生成 (保留 srs_state)"
```

---

## Task 4: GET /flashcards/today 主入口

**Files:**
- Modify: `dashboard/server.py`
- Create: `dashboard/templates/flashcards.html`
- Create: `dashboard/templates/_flashcard_review.html`
- Test: `dashboard/tests/integration/test_flashcards_endpoint.py`

- [ ] **Step 1: Write test**

```python
# dashboard/tests/integration/test_flashcards_endpoint.py
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from starlette.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    from dashboard import server
    monkeypatch.setattr(server, "DB_PATH", tmp_path / "board.db")
    return TestClient(server.app)


def _seed_flashcards(db_path: Path, cards_def: list[dict]) -> None:
    from dashboard.derive.deep_card_types import Flashcard, SrsState
    from dashboard.state.db import open_db
    from dashboard.state.repositories import FlashcardRepo
    conn = open_db(db_path)
    repo = FlashcardRepo(conn)
    for d in cards_def:
        repo.upsert(Flashcard(**d))


def test_today_empty_show_message(client: TestClient) -> None:
    resp = client.get("/flashcards/today")
    assert resp.status_code == 200
    assert "暂无" in resp.text or "无可复习" in resp.text


def test_today_lists_new_cards(client: TestClient) -> None:
    from dashboard.derive.deep_card_types import Flashcard, SrsState
    _seed_flashcards(client.app.state.db_path, [  # type: ignore[attr-defined]
        {"id": "x.a::tradeoff", "cap_id": "x.a", "template_kind": "tradeoff",
         "question": "Q1?", "answer": "A1", "srs_state": SrsState()},
        {"id": "x.b::tradeoff", "cap_id": "x.b", "template_kind": "tradeoff",
         "question": "Q2?", "answer": "A2", "srs_state": SrsState()},
    ])
    resp = client.get("/flashcards/today")
    body = resp.text
    assert "Q1?" in body or "Q2?" in body  # 起码 1 张展示


def test_today_due_cards_appear(client: TestClient) -> None:
    """next_review_at 过去时 → 入今日复习"""
    from dashboard.derive.deep_card_types import Flashcard, SrsState
    past = datetime.now(UTC) - timedelta(days=1)
    _seed_flashcards(client.app.state.db_path, [  # type: ignore[attr-defined]
        {"id": "x::tradeoff", "cap_id": "x", "template_kind": "tradeoff",
         "question": "Due?", "answer": "A",
         "srs_state": SrsState(repetition=2, interval=6, ef=2.5,
                               last_reviewed_at=past - timedelta(days=6),
                               next_review_at=past)},
    ])
    resp = client.get("/flashcards/today")
    assert "Due?" in resp.text


def test_today_caps_new_cards_5_due_20(client: TestClient) -> None:
    from dashboard.derive.deep_card_types import Flashcard, SrsState
    # 10 张新卡
    defs = [
        {"id": f"x.{i}::tradeoff", "cap_id": f"x.{i}", "template_kind": "tradeoff",
         "question": f"Q{i}?", "answer": "A", "srs_state": SrsState()}
        for i in range(10)
    ]
    _seed_flashcards(client.app.state.db_path, defs)  # type: ignore[attr-defined]
    resp = client.get("/flashcards/today")
    # 模板渲染中包含的 question 数 应 = 5(新卡上限)
    count = sum(1 for i in range(10) if f"Q{i}?" in resp.text)
    assert count == 5
```

- [ ] **Step 2: Run + fails**

Run: `uv run --project backend pytest dashboard/tests/integration/test_flashcards_endpoint.py -v`
Expected: 404

- [ ] **Step 3: Implement templates**

```html
{# dashboard/templates/flashcards.html #}
{% extends "base.html" %}
{% block content %}
<div class="flashcards-page">
  <div class="flashcards-toolbar">
    <a href="/">← 返回网格</a>
    <span>🎴 今日复习 ({{ today_cards | length }} 张)</span>
    <a href="/flashcards/stats">📊 学习统计</a>
  </div>

  {% if today_cards %}
    <div class="flashcards-progress">
      已完成 <span id="reviewed-count">0</span> / {{ today_cards | length }}
    </div>
    <div class="flashcards-deck">
      {% for fc in today_cards %}
        <div class="flashcard" data-fc-id="{{ fc.id }}"
             data-fc-index="{{ loop.index0 }}"
             {% if not loop.first %}style="display:none;"{% endif %}>
          {% include "_flashcard_review.html" %}
        </div>
      {% endfor %}
    </div>
  {% else %}
    <div class="flashcards-empty">
      📭 今日无可复习卡 — 先到 <a href="/">网格</a> 给一些 cap 填 DeepCard
    </div>
  {% endif %}
</div>
<script src="/static/htmx.min.js"></script>
<script src="/static/flashcards.js"></script>
{% endblock %}
```

```html
{# dashboard/templates/_flashcard_review.html #}
<div class="flashcard-card" id="card-{{ fc.id }}">
  <div class="flashcard-meta">
    <a href="/cap/{{ fc.cap_id }}" target="_blank">{{ fc.cap_id }}</a> ·
    {{ fc.template_kind }} ·
    confidence: {{ fc.srs_state.confidence }} ·
    {% if fc.srs_state.next_review_at %}
      next: {{ fc.srs_state.next_review_at.isoformat()[:10] }}
    {% else %}
      新卡
    {% endif %}
  </div>
  <div class="flashcard-question">
    {{ fc.question }}
  </div>
  <button class="reveal-btn" onclick="this.parentElement.querySelector('.flashcard-answer').style.display='block'; this.parentElement.querySelector('.grade-row').style.display='flex'; this.style.display='none';">
    看答案
  </button>
  <div class="flashcard-answer" style="display:none;">
    {{ fc.answer }}
  </div>
  <div class="grade-row" style="display:none;">
    <button hx-post="/flashcards/{{ fc.id }}/review" hx-vals='{"grade":"0"}' hx-target="#card-{{ fc.id }}" hx-swap="outerHTML">0 完全忘</button>
    <button hx-post="/flashcards/{{ fc.id }}/review" hx-vals='{"grade":"1"}' hx-target="#card-{{ fc.id }}" hx-swap="outerHTML">1</button>
    <button hx-post="/flashcards/{{ fc.id }}/review" hx-vals='{"grade":"2"}' hx-target="#card-{{ fc.id }}" hx-swap="outerHTML">2</button>
    <button hx-post="/flashcards/{{ fc.id }}/review" hx-vals='{"grade":"3"}' hx-target="#card-{{ fc.id }}" hx-swap="outerHTML">3 一半</button>
    <button hx-post="/flashcards/{{ fc.id }}/review" hx-vals='{"grade":"4"}' hx-target="#card-{{ fc.id }}" hx-swap="outerHTML">4</button>
    <button hx-post="/flashcards/{{ fc.id }}/review" hx-vals='{"grade":"5"}' hx-target="#card-{{ fc.id }}" hx-swap="outerHTML">5 完美</button>
  </div>
</div>
```

```javascript
// dashboard/static/flashcards.js — 简化:HX-Trigger response 推进卡片
document.body.addEventListener('htmx:afterOnLoad', (evt) => {
  if (!evt.detail.xhr.getResponseHeader('X-Reviewed')) return;
  // 当前卡片已 swap 成 "✅ 已复习",下一张显示
  const reviewed = document.querySelectorAll('.flashcard[data-fc-reviewed]');
  document.getElementById('reviewed-count').textContent = reviewed.length;
  const next = document.querySelector('.flashcard:not([data-fc-reviewed])');
  if (next) next.style.display = '';
});
```

- [ ] **Step 4: Implement endpoint**

```python
# dashboard/server.py
async def flashcards_today(request: Request) -> HTMLResponse:
    """每日复习入口 — 新卡 ≤5 + 到期 ≤20。"""
    from datetime import datetime, UTC

    conn = open_db(DB_PATH)
    try:
        cur = conn.execute(
            "SELECT id, cap_id, template_kind, question, answer, srs_state, "
            "created_at, last_reviewed_at FROM flashcards"
        )
        all_fcs = [FlashcardRepo._row_to_fc(r) for r in cur.fetchall()]
    finally:
        conn.close()

    now = datetime.now(UTC)
    new_cards = [f for f in all_fcs if f.srs_state.repetition == 0][:5]
    due = [
        f for f in all_fcs
        if f.srs_state.repetition > 0 and f.srs_state.next_review_at
        and f.srs_state.next_review_at <= now
    ][:20]

    today_cards = new_cards + due
    template = templates.get_template("flashcards.html")
    return HTMLResponse(template.render(today_cards=today_cards))


# Route: Route("/flashcards/today", flashcards_today),
```

- [ ] **Step 5: Run + passes**

Run: `uv run --project backend pytest dashboard/tests/integration/test_flashcards_endpoint.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add dashboard/server.py dashboard/templates/flashcards.html \
        dashboard/templates/_flashcard_review.html dashboard/static/flashcards.js \
        dashboard/tests/integration/test_flashcards_endpoint.py
git commit -m "feat(harness-review-plan3): V5 /flashcards/today + 翻面 UI"
```

---

## Task 5: 单卡复习 POST + SRS 状态更新

**Files:**
- Modify: `dashboard/server.py`
- Test: 加 to test_flashcards_endpoint.py

- [ ] **Step 1: Add test**

```python
# test_flashcards_endpoint.py — append
def test_review_updates_srs_state(client: TestClient) -> None:
    from dashboard.derive.deep_card_types import Flashcard, SrsState
    _seed_flashcards(client.app.state.db_path, [  # type: ignore[attr-defined]
        {"id": "x::tradeoff", "cap_id": "x", "template_kind": "tradeoff",
         "question": "Q?", "answer": "A", "srs_state": SrsState()},
    ])
    resp = client.post("/flashcards/x::tradeoff/review", data={"grade": "5"})
    assert resp.status_code == 200
    assert resp.headers.get("X-Reviewed") == "1"

    # 校验落库
    from dashboard.state.db import open_db
    from dashboard.state.repositories import FlashcardRepo
    conn = open_db(client.app.state.db_path)  # type: ignore[attr-defined]
    fc = FlashcardRepo(conn).get("x::tradeoff")
    assert fc is not None
    assert fc.srs_state.repetition == 1
    assert fc.srs_state.interval == 1
    assert fc.srs_state.confidence == 5


def test_review_invalid_grade_returns_400(client: TestClient) -> None:
    from dashboard.derive.deep_card_types import Flashcard, SrsState
    _seed_flashcards(client.app.state.db_path, [  # type: ignore[attr-defined]
        {"id": "x::tradeoff", "cap_id": "x", "template_kind": "tradeoff",
         "question": "Q?", "answer": "A", "srs_state": SrsState()},
    ])
    resp = client.post("/flashcards/x::tradeoff/review", data={"grade": "7"})
    assert resp.status_code == 400


def test_review_404_unknown_flashcard(client: TestClient) -> None:
    resp = client.post("/flashcards/bogus::tradeoff/review", data={"grade": "3"})
    assert resp.status_code == 404
```

- [ ] **Step 2: Run + fails**

Run: `uv run --project backend pytest dashboard/tests/integration/test_flashcards_endpoint.py -v`
Expected: 404

- [ ] **Step 3: Implement POST endpoint**

```python
# dashboard/server.py
async def post_flashcard_review(request: Request) -> HTMLResponse:
    from dashboard.derive.srs import schedule_next_review

    flashcard_id = request.path_params["flashcard_id"]
    form = await request.form()
    try:
        grade = int(form.get("grade", "-1"))
    except (TypeError, ValueError):
        return HTMLResponse("invalid grade", status_code=400)
    if not 0 <= grade <= 5:
        return HTMLResponse("grade must be 0..5", status_code=400)

    conn = open_db(DB_PATH)
    try:
        repo = FlashcardRepo(conn)
        fc = repo.get(flashcard_id)
        if fc is None:
            return HTMLResponse("flashcard not found", status_code=404)
        new_state = schedule_next_review(fc.srs_state, grade=grade)
        updated = fc.model_copy(update={
            "srs_state": new_state,
            "last_reviewed_at": new_state.last_reviewed_at,
        })
        repo.upsert(updated)
    finally:
        conn.close()

    return HTMLResponse(
        f"<div class='flashcard-reviewed' data-fc-reviewed='1'>"
        f"✅ 已复习 → 下次:{new_state.next_review_at.date()} (conf={grade})"
        f"</div>",
        headers={"X-Reviewed": "1"},
    )


# Route: Route("/flashcards/{flashcard_id:path}/review", post_flashcard_review, methods=["POST"]),
# 注意:flashcard_id 包含 `::` 冒号,starlette 默认 path 类型需要 :path 转换器
```

- [ ] **Step 4: Run + passes**

Run: `uv run --project backend pytest dashboard/tests/integration/test_flashcards_endpoint.py -v`
Expected: 7 passed(原 4 + 新 3)

- [ ] **Step 5: 手动验证**

```bash
make board
# 浏览器 /flashcards/today 翻几张卡,验证:
#   - 看答案按钮显示答案
#   - 0-5 按钮提交后 X-Reviewed 触发下一张
#   - sqlite flashcards 表 srs_state JSON 字段更新
```

- [ ] **Step 6: Commit**

```bash
git add dashboard/server.py dashboard/tests/integration/test_flashcards_endpoint.py
git commit -m "feat(harness-review-plan3): POST /flashcards/{id}/review + SM-2 SRS 状态更新"
```

---

## Task 6: 学习统计页(简版)

**Files:**
- Modify: `dashboard/server.py`
- Create: `dashboard/templates/flashcards_stats.html`

- [ ] **Step 1: Implement stats endpoint**

```python
# dashboard/server.py
async def flashcards_stats(request: Request) -> HTMLResponse:
    conn = open_db(DB_PATH)
    try:
        cur = conn.execute(
            "SELECT COUNT(*) as total, "
            "SUM(CASE WHEN json_extract(srs_state, '$.repetition') = 0 THEN 1 ELSE 0 END) as new, "
            "SUM(CASE WHEN json_extract(srs_state, '$.confidence') >= 4 THEN 1 ELSE 0 END) as mastered, "
            "AVG(json_extract(srs_state, '$.confidence')) as avg_conf "
            "FROM flashcards"
        )
        row = cur.fetchone()
        # 维度分布(基于 cap_id 前缀,粗略)
        dim_cur = conn.execute(
            "SELECT substr(cap_id, 1, 2) as dim, COUNT(*) as n "
            "FROM flashcards GROUP BY dim ORDER BY n DESC"
        )
        dim_dist = [(r["dim"], r["n"]) for r in dim_cur.fetchall()]
    finally:
        conn.close()

    template = templates.get_template("flashcards_stats.html")
    return HTMLResponse(template.render(
        total=row["total"] or 0,
        new=row["new"] or 0,
        mastered=row["mastered"] or 0,
        avg_conf=round(row["avg_conf"] or 0.0, 2),
        dim_dist=dim_dist,
    ))


# Route: Route("/flashcards/stats", flashcards_stats),
```

```html
{# dashboard/templates/flashcards_stats.html #}
{% extends "base.html" %}
{% block content %}
<div class="stats-page">
  <a href="/flashcards/today">← 回到今日复习</a>
  <h2>📊 学习统计</h2>
  <div class="stats-grid">
    <div class="stat-card"><div class="stat-label">总闪卡</div><div class="stat-value">{{ total }}</div></div>
    <div class="stat-card"><div class="stat-label">新卡</div><div class="stat-value">{{ new }}</div></div>
    <div class="stat-card"><div class="stat-label">已掌握 (conf≥4)</div><div class="stat-value">{{ mastered }}</div></div>
    <div class="stat-card"><div class="stat-label">平均 confidence</div><div class="stat-value">{{ avg_conf }}</div></div>
  </div>
  <h3>维度分布(基于 cap_id 前缀)</h3>
  <ul>
    {% for dim, n in dim_dist %}
      <li>{{ dim }}: {{ n }} 张</li>
    {% endfor %}
  </ul>
</div>
{% endblock %}
```

- [ ] **Step 2: CSS**

```css
.stats-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin: 16px 0; }
.stat-card { background: #f9fafb; padding: 16px; border-radius: 4px; }
.stat-label { font-size: 11px; color: #666; }
.stat-value { font-size: 32px; font-weight: bold; color: #1f2937; }
```

- [ ] **Step 3: Commit**

```bash
git add dashboard/server.py dashboard/templates/flashcards_stats.html dashboard/static/style.css
git commit -m "feat(harness-review-plan3): /flashcards/stats 学习统计简版"
```

---

## Task 7: 顶部 nav 加 "🎴 闪卡"

**Files:** Modify `dashboard/templates/main.html`

- [ ] **Step 1: Add nav link**

```html
{# dashboard/templates/main.html nav #}
<nav class="board-nav">
  <a href="/" class="nav-link">📊 网格</a>
  <a href="/overview" class="nav-link">🌐 鸟瞰</a>
  <a href="/story" class="nav-link">📖 故事</a>
  <a href="/flashcards/today" class="nav-link">🎴 闪卡</a>
  <a href="/decisions" class="nav-link">⚖ 决策</a>
</nav>
```

- [ ] **Step 2: Commit**

```bash
git add dashboard/templates/main.html
git commit -m "feat(harness-review-plan3): nav 加 V5 闪卡入口"
```

---

## Task 8: 全量 prefill ~50 cap

**Files:** 数据生成 + review,无 code 改动

- [ ] **Step 1: 列剩余待 prefill cap**

Plan 1 已 prefill 10 张;剩余约 52 张。按维度优先级:

- 01 Prompt & Context:8 项剩 6
- 02 Tools:8 项剩 7
- 03 Orchestration:剩 ~5
- 04 Memory:剩 ~4
- 05 RAG / Knowledge:剩 ~4
- 06 Guardrails / Reliability:剩 ~7
- 07 Eval / Observability:剩 ~6
- 08 Cost / Routing:剩 ~5

- [ ] **Step 2: 批量 prefill**

```bash
unset all_proxy https_proxy http_proxy

# 把 cap_id 列举一次拉
uv run python -c "
from pathlib import Path
from dashboard.derive.capability_resolver import load_capabilities
from dashboard.state.db import open_db
from dashboard.state.repositories import DeepCardRepo
caps = load_capabilities(Path('dashboard/config/capabilities.yaml'))
conn = open_db(Path('backend/data/board.db'))
existing = {c.cap_id for c in DeepCardRepo(conn).get_all()}
todo = [c.id for c in caps if c.id not in existing]
print(','.join(todo))
" > /tmp/cap_todo.txt

# 分 5 批跑,每批 ~10 张
uv run python -m backend.scripts.prefill_deep_cards --caps "$(cat /tmp/cap_todo.txt | cut -d, -f1-10)" --db backend/data/board.db
# 重复 5-6 次,每次 10 张
```

- [ ] **Step 3: 人工 review 全量**

`make board` → 每个 cap chip 点开 V2 modal,validate:
- 完成度角标颜色合理
- LLM 草拟的内容准确(橙色边框)→ 不准的 edit → hybrid 蓝色
- 拒绝入库的字段(prefill_log 显示)→ 手动补 → manual 绿色

目标:**≥ 50 张 cap 至少 4 必填字段全填**(`completion_level=full`)

- [ ] **Step 4: 导出 seed jsonl**

```bash
uv run python -c "
from dashboard.state.db import open_db
from dashboard.state.repositories import DeepCardRepo
conn = open_db('backend/data/board.db')
cards = DeepCardRepo(conn).get_all()
with open('dashboard/data/deep_cards_seed.jsonl', 'w') as f:
    for c in cards:
        f.write(c.model_dump_json() + '\n')
print(f'Exported {len(cards)} deep cards')
"
git add dashboard/data/deep_cards_seed.jsonl
git commit -m "data(harness-review-plan3): 全量 50+ cap prefill seed"
```

- [ ] **Step 5: 全量 reindex Milvus**

```bash
curl -X POST http://localhost:8910/admin/milvus/reindex
# 期望:upserted: 50+
```

- [ ] **Step 6: 闪卡全量重生成**

```bash
uv run python -c "
from pathlib import Path
from dashboard.derive.capability_resolver import load_capabilities
from dashboard.state.db import open_db
from dashboard.state.repositories import DeepCardRepo, FlashcardRepo, regenerate_flashcards_for
caps = load_capabilities(Path('dashboard/config/capabilities.yaml'))
name_by_id = {c.id: c.name_cn for c in caps}
conn = open_db('backend/data/board.db')
dc_repo = DeepCardRepo(conn)
fc_repo = FlashcardRepo(conn)
n = 0
for card in dc_repo.get_all():
    regenerate_flashcards_for(card.cap_id, dc_repo=dc_repo, fc_repo=fc_repo,
                              cap_name_cn=name_by_id.get(card.cap_id, card.cap_id))
    n += 1
print(f'Regenerated flashcards for {n} cap')
"
```

期望:50+ cap × avg 2 张闪卡 = ~100 张闪卡入库

---

## Task 9: 整体测试 + lint 收尾

**Files:** 全量验证

- [ ] **Step 1: 全部测试**

```bash
uv run --project backend pytest dashboard/tests/ -v
```

Expected: Plan 1 + 2 + 3 累计 ≥ 160 PASS,无 regression

- [ ] **Step 2: mypy strict**

```bash
uv run --project backend mypy dashboard/ backend/scripts/prefill_deep_cards.py --strict
```

- [ ] **Step 3: ruff**

```bash
uv run --project backend ruff format --check dashboard/ backend/scripts/
uv run --project backend ruff check dashboard/ backend/scripts/
```

- [ ] **Step 4: 5 view smoke test**

```bash
make board
# 浏览器逐 view 验证:
#   - / 网格 chip + 完成度 + confidence(≥50 张应为绿)
#   - /overview 鸟瞰图 cytoscape 渲染 + 节点点击 modal
#   - /story 故事时间线 ≥50 张三段卡片
#   - /flashcards/today 翻面 + 0-5 自评
#   - /flashcards/stats 总数 + 维度分布
#   - /decisions 不退化
make board-stop
```

- [ ] **Step 5: poe ci(整体项目不破)**

```bash
uv run poe ci
```

Expected: 整个项目 lint + test 全 PASS,dashboard / backend 都不破

---

## Task 10: README + CLAUDE.md + 总结知识卡

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Create: `docs/claude-context/harness-board-review-mode-done.md`(总卡)
- Create: `docs/claude-context/harness-board-review-plan3-done.md`(Plan 3 卡)

- [ ] **Step 1: 写总知识卡 review-mode-done.md**

```bash
cat > docs/claude-context/harness-board-review-mode-done.md <<'EOF'
---
name: harness-board-review-mode-done
description: Harness Board Review Mode 复合型工具 ship 完 — 底座 + 5 视图 + 全量内容
type: project
---

Harness Board Review Mode ship 内容 (2026-05-12, 3 plan / ~27.5h wall time):

**底座** (sqlite + Milvus):
- DeepCard 字段:what / why / alternatives / chosen_alternative / tradeoff / lessons_learned / metrics / code_anchors / linked_* / srs_state / provenance / prefill_source
- Flashcard 表:每 DeepCard 派生 0-3 张(tradeoff / alternatives / lessons)
- Milvus collection `harness_board_deepcards`(qwen v3 1024d)+ keyword fallback

**5 视图**:
- V1 网格:chip 加完成度角标 + confidence 数字
- V2 模块深读:chip→modal 双栏 + inline 编辑 + AI 草拟按钮 + provenance UI(3 色边框)
- V3 系统鸟瞰:cytoscape cose-bilkent + 8 维染色 + 节点大小 = code_anchors + 过滤工具栏
- V4 故事时间线:git commit-time + 三段式(难题/决策/收获)+ 维度 + 时间窗过滤
- V5 闪卡 SRS:SM-2 + 模板派生 + 新卡 5/日 + 到期 20/日

**LLM 边界 = L2**:
- 一次性 prefill batch(50+ cap)+ AI 草拟按钮(按需)
- constrained JSON schema + provenance fuzzy match 校验,幻觉率 < 10%
- 不做在线对话(去 /chat)+ 不做闪卡 LLM 评分(SM-2 自评足够)

**跨视图联动** 5 条全确定性:V1→V2 / V3→V2 / V4→V2 / V2 linked_decision→/decisions / V2 linked_capability→V3 anchor

**Why**:
- B(onboard 自己)+ C(系统化+模块化)+ A(面试讲项目)+ D(主动召回)四场景共享底座
- story.md 不再过期 — 从 DeepCard 集合 render
- 复习内容长期增量填,不一晚填满

**How to apply**:
- 复习模块深度 → V2 modal
- 复习全局架构 → V3 鸟瞰
- 准备面试讲项目 → V4 故事时间线
- 主动召回知识 → V5 闪卡
- 新加 capability → capabilities.yaml + 跑 prefill batch
- 改代码 → 改 DeepCard → 闪卡自动 regenerate (保留 srs_state)
- LLM unavailable → 隐藏 AI 草拟按钮,功能退化为纯手编(不阻塞)
- Milvus unavailable → 相关推荐降级 keyword scorer + banner 提示
EOF

# Plan 3 卡
cat > docs/claude-context/harness-board-review-plan3-done.md <<'EOF'
---
name: harness-board-review-plan3-done
description: Plan 3 ship — V5 闪卡 SRS + 全量 50+ cap prefill + Review Mode 收尾
type: project
---

Plan 3 ship 内容:
- SM-2 算法(50 行 Python)+ SrsAlgo Protocol(v1.x 升级 FSRS 留口)
- 闪卡 3 类模板派生(tradeoff / alternatives / lessons)— 无 LLM 机械模板
- DeepCard 编辑 → regenerate hook(保留 srs_state)
- `/flashcards/today` 主入口:新卡 ≤5 + 到期 ≤20,翻面 + 0-5 自评
- `/flashcards/stats` 学习统计页(总数 / 已掌握 / 维度分布)
- 全量 50+ cap prefill + review + Milvus reindex + 闪卡 regenerate
- seed jsonl 入 git(`dashboard/data/deep_cards_seed.jsonl`)
- README "当前版本" 段 + CLAUDE.md 索引更新

**Why**:Plan 1+2 已 ship B+C+A 三场景,Plan 3 闭合 D 主动召回 + 把内容铺满,把 demo 推到日常可用。
EOF

git add docs/claude-context/harness-board-review-mode-done.md \
        docs/claude-context/harness-board-review-plan3-done.md
git commit -m "docs(harness-review-plan3): 总知识卡 + Plan 3 知识卡"
```

- [ ] **Step 2: 更新 README.md 当前版本段**

修改 `README.md` 第 5 行附近"当前版本"段:

```markdown
**当前版本**:v1.0(...原内容...) + **Harness Board Review Mode**(复合型项目知识工具 — 底座 DeepCard + 5 视图 V1 网格 / V2 模块深读 / V3 系统鸟瞰 / V4 故事时间线 / V5 闪卡 SRS + Milvus 相关推荐 + LLM L2 一次性 prefill + AI 草拟按钮)
```

并在"常用命令"段补:

```markdown
| `make board` | 起 Harness Board(localhost:8910)+ 5 view |
| `uv run python -m backend.scripts.prefill_deep_cards --caps <ids>` | LLM batch prefill DeepCard |
| 浏览器 `/flashcards/today` | 每日复习 |
```

- [ ] **Step 3: 更新 CLAUDE.md 索引**

在 CLAUDE.md "v1.0 ship" 段(或同级)加新段:

```markdown
### Harness Board Review Mode (2026-05-12 ship)
- [Harness Board Review Mode ship 完](docs/claude-context/harness-board-review-mode-done.md) — 底座 DeepCard + 5 视图 + 50+ cap 内容 + LLM L2 + Milvus
- [Plan 1 底座 + V2](docs/claude-context/harness-board-review-plan1-done.md)
- [Plan 2 V3 + V4](docs/claude-context/harness-board-review-plan2-done.md)
- [Plan 3 V5 + 收尾](docs/claude-context/harness-board-review-plan3-done.md)
```

- [ ] **Step 4: Commit README + CLAUDE.md**

```bash
git add README.md CLAUDE.md
git commit -m "docs(harness-review-plan3): README 当前版本 + CLAUDE.md Review Mode 索引"
```

- [ ] **Step 5: Push + PR**

```bash
git push
# gh pr create --title "feat(harness-board): Review Mode 复合型工具 (Plan 1+2+3)" --body "..."
```

PR body 重点:
- spec link
- 3 plan link
- 5 视图截图(/, /overview, /story, /flashcards/today, modal)
- before/after:旧 board (D/B/决策 3 tab) → 新 board(+5 view + DeepCard 50+ 张)
- ship checklist 全 ✅

---

## Plan 3 总结

**交付内容:**
- 4 个新 Python module + 5 个新 template + 1 新 JS + CSS 扩展
- 10 task,TDD step 完整
- 测试覆盖:+20 L0 / +5 L1 / +2 L2(可选)
- 全量 50+ DeepCard + ~100 张闪卡入库
- README + CLAUDE.md + 3 plan 知识卡 + 1 总卡

**用户价值:**
- D 主动召回场景闭合
- 4 类复习场景 A+B+C+D 全可用,复合型工具 ship 完
- 后续维护:写代码 → 改 DeepCard → 闪卡 / 故事自动更新

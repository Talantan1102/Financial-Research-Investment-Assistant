"""seed_deep_cards CLI smoke test — Plan 3 Task 8 hand-curated 路径守护。"""

from __future__ import annotations

import sys
from pathlib import Path

# backend/ 是 source root,test 跑在项目根,需要把 backend/ 加进 sys.path
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.scripts import seed_deep_cards as sd  # noqa: E402

from dashboard.state.db import open_db  # noqa: E402
from dashboard.state.repositories import (  # noqa: E402
    DeepCardRepo,
    FlashcardRepo,
    regenerate_flashcards_for,
)


def test_load_seed_parses_real_jsonl() -> None:
    """读真实 seed jsonl,validate 全部为 DeepCard。"""
    seed_path = PROJECT_ROOT / "dashboard" / "data" / "deep_cards_seed.jsonl"
    cards = sd.load_seed(seed_path)
    assert len(cards) >= 30, f"Expect ≥30 seed cards, got {len(cards)}"
    # ETCLOVG 7 维 — execution 暂无 seed card (E 层是 Plan 1 新增);其余 6 维应有 ≥1 card
    dims = {c.cap_id.split(".")[0] for c in cards if "." in c.cap_id}
    expected_subset = {
        "context",
        "tool",
        "lifecycle",
        "observability",
        "verification",
        "governance",
    }
    assert expected_subset.issubset(dims), f"Missing dims: {expected_subset - dims}"


def test_seed_load_direct_into_tmp_db(tmp_path: Path) -> None:
    """走 load_seed + upsert + regenerate(绕开 CLI 路径处理)。"""
    seed_path = PROJECT_ROOT / "dashboard" / "data" / "deep_cards_seed.jsonl"
    db = tmp_path / "board.db"
    cards = sd.load_seed(seed_path)
    conn = open_db(db)
    dc_repo = DeepCardRepo(conn)
    fc_repo = FlashcardRepo(conn)
    for card in cards:
        dc_repo.upsert(card)
        regenerate_flashcards_for(
            card.cap_id, dc_repo=dc_repo, fc_repo=fc_repo, cap_name_cn=card.cap_id
        )

    # 校验 DeepCard 数 ≥ 30
    all_cards = dc_repo.get_all()
    assert len(all_cards) >= 30

    # 校验闪卡数 — 每 card 至少 tradeoff 必填,所以 ≥ 30
    all_fcs = fc_repo.get_all()
    assert len(all_fcs) >= 30


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
            DeepCard(cap_id="context.long_term_memory", what="USER_EDITED_BEFORE_FORCE")
        )
    finally:
        conn.close()

    # --force 跑一次 → 应覆盖
    rc = sd.main(["--seed", str(seed_path), "--db", str(db), "--force"])
    assert rc == 0

    conn = open_db(db)
    try:
        survived = DeepCardRepo(conn).get("context.long_term_memory")
    finally:
        conn.close()
    assert survived is not None
    assert survived.what != "USER_EDITED_BEFORE_FORCE"

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
    # 覆盖 8 维
    dims = {c.cap_id.split(".")[0] for c in cards if "." in c.cap_id}
    expected_dims = {
        "prompt_context",
        "tools_function",
        "orchestration",
        "memory",
        "rag_knowledge",
        "guardrails",
        "eval_observability",
        "cost_routing",
    }
    assert dims == expected_dims, f"Missing dims: {expected_dims - dims}"


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

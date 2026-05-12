"""seed_deep_cards CLI — 从 dashboard/data/deep_cards_seed.jsonl 加载手写 DeepCard 入 sqlite。

Plan 3 Task 8 备用路径:LLM 不可达时(本机无 OPENAI_API_KEY)用此 CLI 把
hand-curated 35 张 cap 一次性写入 board.db,并触发 flashcard 重生成。

Usage:
    uv run --project backend python -m app.scripts.seed_deep_cards \\
        --seed dashboard/data/deep_cards_seed.jsonl \\
        --db backend/data/board.db
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from dashboard.derive.capability_resolver import load_capabilities
from dashboard.derive.deep_card_types import DeepCard
from dashboard.state.db import open_db
from dashboard.state.repositories import DeepCardRepo, FlashcardRepo, regenerate_flashcards_for

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def load_seed(seed_path: Path) -> list[DeepCard]:
    """读 jsonl,validate 每行为 DeepCard。"""
    cards: list[DeepCard] = []
    for line in seed_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        data = json.loads(line)
        cards.append(DeepCard.model_validate(data))
    return cards


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load hand-curated DeepCard seed into sqlite")
    parser.add_argument(
        "--seed",
        default="dashboard/data/deep_cards_seed.jsonl",
        help="seed jsonl path (relative to project root)",
    )
    parser.add_argument(
        "--db", default="backend/data/board.db", help="sqlite path (relative to project root)"
    )
    parser.add_argument(
        "--regenerate-flashcards",
        action="store_true",
        help="完成后触发 flashcard 重生成 (Plan 3 Task 8 Step 6)",
    )
    args = parser.parse_args(argv)

    base_dir = PROJECT_ROOT
    seed_arg = Path(args.seed)
    db_arg = Path(args.db)
    seed_path = seed_arg if seed_arg.is_absolute() else base_dir / seed_arg
    db_path = db_arg if db_arg.is_absolute() else base_dir / db_arg

    if not seed_path.exists():
        print(f"ERROR: seed file not found: {seed_path}", file=sys.stderr)
        return 2

    caps = load_capabilities(base_dir / "dashboard" / "config" / "capabilities.yaml")
    valid_ids = {c.id for c in caps}
    name_by_id = {c.id: c.name_cn for c in caps}

    cards = load_seed(seed_path)
    skipped: list[str] = []
    upserted: list[str] = []

    conn = open_db(db_path)
    dc_repo = DeepCardRepo(conn)
    fc_repo = FlashcardRepo(conn)
    for card in cards:
        if card.cap_id not in valid_ids:
            logger.warning("cap %s not in capabilities.yaml — skipping", card.cap_id)
            skipped.append(card.cap_id)
            continue
        dc_repo.upsert(card)
        upserted.append(card.cap_id)
        if args.regenerate_flashcards:
            regenerate_flashcards_for(
                card.cap_id,
                dc_repo=dc_repo,
                fc_repo=fc_repo,
                cap_name_cn=name_by_id.get(card.cap_id, card.cap_id),
            )

    print(
        f"Seed load done. Upserted: {len(upserted)}, skipped (cap_id not in yaml): {len(skipped)}"
    )
    if skipped:
        print(f"Skipped cap_ids: {skipped}")
    if args.regenerate_flashcards:
        all_fcs = fc_repo.get_all()
        print(f"Regenerated flashcards: {len(all_fcs)}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())

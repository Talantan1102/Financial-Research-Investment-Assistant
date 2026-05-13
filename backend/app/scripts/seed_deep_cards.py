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

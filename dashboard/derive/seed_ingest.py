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
    total_seed: int  # jsonl 行数(no-op 时为 0)
    inserted: int  # 新插入
    skipped_existing: int  # cap_id 已存在跳过(保护手动编辑)
    skipped_invalid: int  # cap_id 不在 capabilities.yaml 跳过
    overwritten: int  # 仅 force=True 时 > 0


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
            logger.info("SeedIngest: skip (db=%d ≥ seed=%d or seed missing)", db_total, seed_total)
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

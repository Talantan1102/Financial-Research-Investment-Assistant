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

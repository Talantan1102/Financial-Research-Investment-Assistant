"""一次性脚本:DeepCard payload v1 → v2 migration(Plan 2)。

Usage:
    uv run python -m dashboard.scripts.migrate_deepcard_v2 [/path/to/db]

幂等:已是 v2 的 payload 跳过。
"""

from __future__ import annotations

import json
import logging
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


V2_BLANK_FIELDS: dict[str, object] = {
    "scenario": None,
    "design": None,
    "tradeoff": None,
    "review": None,
    "decisions_extracted_ids": [],
    "decisions_user_notes": [],
    "evidence": None,
    "screenshots": [],
}


def migrate_payloads(db_path: Path) -> int:
    """迁移 deep_cards.payload from v1 to v2。返回迁移行数。"""
    if not db_path.exists():
        logger.info("db not found at %s — skip", db_path)
        return 0
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    migrated = 0
    try:
        rows = conn.execute("SELECT cap_id, payload FROM deep_cards").fetchall()
        for row in rows:
            payload = json.loads(row["payload"])
            if payload.get("schema_version") == 2:
                continue
            new_payload = {
                "cap_id": payload.get("cap_id", row["cap_id"]),
                "schema_version": 2,
                "legacy_payload": payload,
                **V2_BLANK_FIELDS,
            }
            with conn:
                conn.execute(
                    "UPDATE deep_cards SET payload = ?, last_edited_at = ? WHERE cap_id = ?",
                    (
                        json.dumps(new_payload),
                        datetime.now(UTC).isoformat(),
                        row["cap_id"],
                    ),
                )
            migrated += 1
        logger.info("migrated %d deep_cards payloads to v2", migrated)
    finally:
        conn.close()
    return migrated


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(sys.argv) > 1:
        db_path = Path(sys.argv[1])
    else:
        db_path = Path(__file__).resolve().parents[1] / "data" / "harness_board.db"
    n = migrate_payloads(db_path)
    print(f"migrated {n} payloads")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""sqlite CRUD。M1 仅 SnapshotRepo;M2 增 OverrideRepo / DecisionRepo。"""

from __future__ import annotations

import json
import sqlite3
from typing import Any


class SnapshotRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def save(self, refreshed_at: str, payload: dict[str, Any]) -> None:
        """全量替换 — 仅保留最新一行(M1 简单语义)。"""
        with self.conn:
            self.conn.execute("DELETE FROM derived_snapshot")
            self.conn.execute(
                "INSERT INTO derived_snapshot (refreshed_at, payload) VALUES (?, ?)",
                (refreshed_at, json.dumps(payload)),
            )

    def get_latest(self) -> dict[str, Any] | None:
        cur = self.conn.execute(
            "SELECT refreshed_at, payload FROM derived_snapshot ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()
        if not row:
            return None
        d: dict[str, Any] = json.loads(row["payload"])
        d["refreshed_at"] = row["refreshed_at"]
        return d

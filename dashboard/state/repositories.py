"""sqlite CRUD。M1 仅 SnapshotRepo;M2 增 OverrideRepo / DecisionRepo。"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from dashboard.derive.types import CapabilityStatus


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


class OverrideRepo:
    """sqlite CRUD for capability_override。single row per capability(spec § 3)。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get_all(self) -> dict[str, CapabilityStatus]:
        """返回 {capability_id: status},喂给 build_snapshot(overrides=...)。"""
        cur = self.conn.execute("SELECT capability_id, status FROM capability_override")
        out: dict[str, CapabilityStatus] = {}
        for row in cur.fetchall():
            status: CapabilityStatus = row["status"]
            out[row["capability_id"]] = status
        return out

    def upsert(
        self,
        capability_id: str,
        status: CapabilityStatus,
        reason: str = "",
        set_at: str | None = None,
    ) -> None:
        """upsert per capability_id (PRIMARY KEY conflict 时覆盖)。"""
        set_at = set_at or datetime.now(UTC).isoformat()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO capability_override (capability_id, status, reason, set_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(capability_id) DO UPDATE SET
                  status = excluded.status,
                  reason = excluded.reason,
                  set_at = excluded.set_at
                """,
                (capability_id, status, reason, set_at),
            )

    def delete(self, capability_id: str) -> None:
        with self.conn:
            self.conn.execute(
                "DELETE FROM capability_override WHERE capability_id = ?",
                (capability_id,),
            )

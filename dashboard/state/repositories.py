"""sqlite CRUD。M1 仅 SnapshotRepo;M2 增 OverrideRepo;M3 增 DecisionNoteRepo;
Review Mode v2 增 DeepCardRepo。FlashcardRepo Plan 1 退役。"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from dashboard.derive.deep_card_types import DeepCard
from dashboard.derive.types import CapabilityStatus, SnapshotDict


class SnapshotRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def save(self, refreshed_at: str, payload: SnapshotDict) -> None:
        """全量替换 — 仅保留最新一行(M1 简单语义)。"""
        with self.conn:
            self.conn.execute("DELETE FROM derived_snapshot")
            self.conn.execute(
                "INSERT INTO derived_snapshot (refreshed_at, payload) VALUES (?, ?)",
                (refreshed_at, json.dumps(payload)),
            )

    def get_latest(self) -> SnapshotDict | None:
        cur = self.conn.execute(
            "SELECT refreshed_at, payload FROM derived_snapshot ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()
        if not row:
            return None
        d: SnapshotDict = json.loads(row["payload"])
        d["refreshed_at"] = row["refreshed_at"]
        return d

    def invalidate(self) -> None:
        """清空 derived_snapshot,下次 GET / 触发 lazy rebuild。"""
        with self.conn:
            self.conn.execute("DELETE FROM derived_snapshot")


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


class DecisionNoteRepo:
    """sqlite CRUD for decision_note。single row per decision(spec § 4)。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get_all(self) -> dict[str, str]:
        """返回 {decision_id: note}"""
        cur = self.conn.execute("SELECT decision_id, note FROM decision_note")
        return {row["decision_id"]: row["note"] for row in cur.fetchall()}

    def upsert(
        self,
        decision_id: str,
        note: str,
        set_at: str | None = None,
    ) -> None:
        """upsert per decision_id (PRIMARY KEY conflict 时覆盖)。"""
        set_at = set_at or datetime.now(UTC).isoformat()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO decision_note (decision_id, note, set_at)
                VALUES (?, ?, ?)
                ON CONFLICT(decision_id) DO UPDATE SET
                  note = excluded.note,
                  set_at = excluded.set_at
                """,
                (decision_id, note, set_at),
            )

    def delete(self, decision_id: str) -> None:
        with self.conn:
            self.conn.execute(
                "DELETE FROM decision_note WHERE decision_id = ?",
                (decision_id,),
            )


class DeepCardRepo:
    """sqlite CRUD for deep_cards。spec § 6.1。

    实施时:为简化 Pydantic roundtrip,DeepCard 用单 `payload` JSON 列(非分列)。
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get(self, cap_id: str) -> DeepCard | None:
        cur = self.conn.execute("SELECT payload FROM deep_cards WHERE cap_id = ?", (cap_id,))
        row = cur.fetchone()
        if not row:
            return None
        result: DeepCard = DeepCard.model_validate_json(row["payload"])
        return result

    def get_all(self) -> list[DeepCard]:
        cur = self.conn.execute("SELECT payload FROM deep_cards ORDER BY cap_id")
        return [DeepCard.model_validate_json(r["payload"]) for r in cur.fetchall()]

    def upsert(self, card: DeepCard) -> None:
        now = datetime.now(UTC).isoformat()
        payload = card.model_dump_json()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO deep_cards (cap_id, payload, last_edited_at)
                VALUES (?, ?, ?)
                ON CONFLICT(cap_id) DO UPDATE SET
                  payload = excluded.payload,
                  last_edited_at = excluded.last_edited_at
                """,
                (card.cap_id, payload, now),
            )

    def update_field(self, cap_id: str, field_name: str, value: object) -> None:
        """改单个字段。自动转 prefill_source(spec § 5.2):
        llm + 人改 → hybrid;manual + 人改 → manual;hybrid + 人改 → hybrid。
        """
        card = self.get(cap_id) or DeepCard(cap_id=cap_id)
        if field_name not in DeepCard.model_fields:
            raise KeyError(f"DeepCard has no field {field_name}")
        new_data = card.model_dump()
        new_data[field_name] = value
        new_data["last_edited_at"] = datetime.now(UTC).isoformat()
        if card.prefill_source == "llm":
            new_data["prefill_source"] = "hybrid"
        updated = DeepCard.model_validate(new_data)
        self.upsert(updated)

    def mark_ai_drafted(self, cap_id: str, field_name: str) -> None:  # noqa: ARG002
        """AI 草拟单字段成功后调:prefill_source = llm (覆盖 manual)。field_name 留作未来 per-field 状态扩展。"""
        card = self.get(cap_id) or DeepCard(cap_id=cap_id)
        new_data = card.model_dump()
        new_data["prefill_source"] = "llm"
        new_data["prefill_at"] = datetime.now(UTC).isoformat()
        self.upsert(DeepCard.model_validate(new_data))

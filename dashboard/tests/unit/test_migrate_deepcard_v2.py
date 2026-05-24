"""Plan 2 Task 2 — DeepCard payload v1 → v2 migration 幂等测试。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from dashboard.scripts.migrate_deepcard_v2 import migrate_payloads


@pytest.fixture
def db_with_v1_cards(tmp_path: Path) -> Path:
    db_path = tmp_path / "board.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE deep_cards (
            cap_id TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            last_edited_at TEXT NOT NULL
        );
        """
    )
    v1_payload = json.dumps({"cap_id": "a", "spec": "old spec", "how": "old how"})
    v2_payload = json.dumps(
        {
            "cap_id": "b",
            "schema_version": 2,
            "scenario": "already v2",
            "screenshots": [],
        }
    )
    conn.execute("INSERT INTO deep_cards VALUES (?, ?, ?)", ("a", v1_payload, "2026-01-01"))
    conn.execute("INSERT INTO deep_cards VALUES (?, ?, ?)", ("b", v2_payload, "2026-01-01"))
    conn.commit()
    conn.close()
    return db_path


def _load_payload(db_path: Path, cap_id: str) -> dict[str, object]:
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT payload FROM deep_cards WHERE cap_id = ?", (cap_id,)).fetchone()
    conn.close()
    return json.loads(row[0])


def test_migrate_v1_becomes_v2(db_with_v1_cards: Path) -> None:
    n = migrate_payloads(db_with_v1_cards)
    assert n == 1
    payload_a = _load_payload(db_with_v1_cards, "a")
    assert payload_a["schema_version"] == 2
    assert payload_a["scenario"] is None
    assert "legacy_payload" in payload_a
    assert payload_a["legacy_payload"]["spec"] == "old spec"  # type: ignore[index]


def test_migrate_v2_unchanged(db_with_v1_cards: Path) -> None:
    migrate_payloads(db_with_v1_cards)
    payload_b = _load_payload(db_with_v1_cards, "b")
    assert payload_b["schema_version"] == 2
    assert payload_b["scenario"] == "already v2"
    assert "legacy_payload" not in payload_b


def test_migrate_idempotent(db_with_v1_cards: Path) -> None:
    n1 = migrate_payloads(db_with_v1_cards)
    n2 = migrate_payloads(db_with_v1_cards)
    assert n1 == 1
    assert n2 == 0


def test_migrate_on_empty_table(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE deep_cards (
            cap_id TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            last_edited_at TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()
    n = migrate_payloads(db_path)
    assert n == 0

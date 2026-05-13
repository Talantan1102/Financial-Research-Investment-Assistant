from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from dashboard.derive.deep_card_types import Flashcard, SrsState


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    from dashboard import server
    from dashboard.state.db import open_db

    db_path = tmp_path / "board.db"
    monkeypatch.setattr(server, "DB_PATH", db_path)
    # open_db 自动建 schema
    conn = open_db(db_path)
    conn.close()
    return TestClient(server.app)


def test_stats_json_empty_db(client: TestClient) -> None:
    resp = client.get("/api/flashcards/stats.json")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["today"] == 0
    assert body["avg_confidence"] == 0.0
    assert body["streak_days"] == 0
    assert body["timeline"] == []
    assert body["scatter"] == []


def test_stats_json_with_seed_flashcards(client: TestClient, tmp_path: Path) -> None:
    """种 5 flashcards (3 reviewed) → 校验各 metric。"""
    from dashboard.state.db import open_db
    from dashboard.state.repositories import FlashcardRepo

    now = datetime.now(UTC)
    conn = open_db(tmp_path / "board.db")
    try:
        repo = FlashcardRepo(conn)
        # 3 张今天复习过 (grade 4,5,3) + 2 张未复习
        for i, grade in enumerate([4, 5, 3]):
            repo.upsert(
                Flashcard(
                    id=f"01.a::tradeoff::{i}",
                    cap_id="01.a",
                    template_kind="tradeoff",
                    question="Q",
                    answer="A",
                    srs_state=SrsState(
                        confidence=grade,
                        repetition=1,
                        interval=1,
                        last_reviewed_at=now,
                        next_review_at=now + timedelta(days=1),
                    ),
                )
            )
        for i in range(2):
            repo.upsert(
                Flashcard(
                    id=f"04.b::lessons::{i}",
                    cap_id="04.b",
                    template_kind="lessons",
                    question="Q",
                    answer="A",
                    srs_state=SrsState(),  # repetition=0,新卡
                )
            )
    finally:
        conn.close()

    resp = client.get("/api/flashcards/stats.json")
    body = resp.json()
    assert body["total"] == 5
    assert body["today"] == 3  # 今天复习的 3 张
    assert 3.0 <= body["avg_confidence"] <= 4.5  # (4+5+3)/3 = 4.0
    dims = [s["dim"] for s in body["scatter"]]
    assert "prompt_context" in dims or "memory" in dims or len(dims) > 0
    # timeline 含 3 个 reviewed 点
    assert len(body["timeline"]) == 3
    for t in body["timeline"]:
        assert "date" in t and "grade" in t


def test_stats_html_hydrates_via_js(client: TestClient) -> None:
    """flashcards_stats.html 应只返静态壳 + 引用 /api/flashcards/stats.json。"""
    resp = client.get("/flashcards/stats")
    assert resp.status_code == 200
    assert "/api/flashcards/stats.json" in resp.text
    assert 'id="stats-ring"' in resp.text  # SVG mount 点

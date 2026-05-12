"""GET /flashcards/today + POST /flashcards/{id}/review。Plan 3 Task 4-5。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient


@pytest.fixture()
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from dashboard import server

    p = tmp_path / "board.db"
    monkeypatch.setattr(server, "DB_PATH", p)
    return p


@pytest.fixture()
def client(db_path: Path) -> TestClient:
    from dashboard import server

    return TestClient(server.app)


def _seed_flashcards(db_path: Path, cards_def: list[dict[str, Any]]) -> None:
    from dashboard.derive.deep_card_types import Flashcard
    from dashboard.state.db import open_db
    from dashboard.state.repositories import FlashcardRepo

    conn = open_db(db_path)
    repo = FlashcardRepo(conn)
    for d in cards_def:
        repo.upsert(Flashcard(**d))


def test_today_empty_show_message(client: TestClient) -> None:
    resp = client.get("/flashcards/today")
    assert resp.status_code == 200
    assert "暂无" in resp.text or "无可复习" in resp.text


def test_today_lists_new_cards(client: TestClient, db_path: Path) -> None:
    from dashboard.derive.deep_card_types import SrsState

    _seed_flashcards(
        db_path,
        [
            {
                "id": "x.a::tradeoff",
                "cap_id": "x.a",
                "template_kind": "tradeoff",
                "question": "Q1?",
                "answer": "A1",
                "srs_state": SrsState(),
            },
            {
                "id": "x.b::tradeoff",
                "cap_id": "x.b",
                "template_kind": "tradeoff",
                "question": "Q2?",
                "answer": "A2",
                "srs_state": SrsState(),
            },
        ],
    )
    resp = client.get("/flashcards/today")
    body = resp.text
    assert "Q1?" in body or "Q2?" in body  # 起码 1 张展示


def test_today_due_cards_appear(client: TestClient, db_path: Path) -> None:
    """next_review_at 过去时 → 入今日复习。"""
    from dashboard.derive.deep_card_types import SrsState

    past = datetime.now(UTC) - timedelta(days=1)
    _seed_flashcards(
        db_path,
        [
            {
                "id": "x::tradeoff",
                "cap_id": "x",
                "template_kind": "tradeoff",
                "question": "Due?",
                "answer": "A",
                "srs_state": SrsState(
                    repetition=2,
                    interval=6,
                    ef=2.5,
                    last_reviewed_at=past - timedelta(days=6),
                    next_review_at=past,
                ),
            },
        ],
    )
    resp = client.get("/flashcards/today")
    assert "Due?" in resp.text


def test_today_caps_new_cards_5_due_20(client: TestClient, db_path: Path) -> None:
    from dashboard.derive.deep_card_types import SrsState

    # 10 张新卡
    defs: list[dict[str, Any]] = [
        {
            "id": f"x.{i}::tradeoff",
            "cap_id": f"x.{i}",
            "template_kind": "tradeoff",
            "question": f"Q{i}?",
            "answer": "A",
            "srs_state": SrsState(),
        }
        for i in range(10)
    ]
    _seed_flashcards(db_path, defs)
    resp = client.get("/flashcards/today")
    # 模板渲染中包含的 question 数 应 = 5(新卡上限)
    count = sum(1 for i in range(10) if f"Q{i}?" in resp.text)
    assert count == 5


def test_review_updates_srs_state(client: TestClient, db_path: Path) -> None:
    from dashboard.derive.deep_card_types import SrsState

    _seed_flashcards(
        db_path,
        [
            {
                "id": "x::tradeoff",
                "cap_id": "x",
                "template_kind": "tradeoff",
                "question": "Q?",
                "answer": "A",
                "srs_state": SrsState(),
            },
        ],
    )
    resp = client.post("/flashcards/x::tradeoff/review", data={"grade": "5"})
    assert resp.status_code == 200
    assert resp.headers.get("X-Reviewed") == "1"

    # 校验落库
    from dashboard.state.db import open_db
    from dashboard.state.repositories import FlashcardRepo

    conn = open_db(db_path)
    fc = FlashcardRepo(conn).get("x::tradeoff")
    assert fc is not None
    assert fc.srs_state.repetition == 1
    assert fc.srs_state.interval == 1
    assert fc.srs_state.confidence == 5


def test_review_invalid_grade_returns_400(client: TestClient, db_path: Path) -> None:
    from dashboard.derive.deep_card_types import SrsState

    _seed_flashcards(
        db_path,
        [
            {
                "id": "x::tradeoff",
                "cap_id": "x",
                "template_kind": "tradeoff",
                "question": "Q?",
                "answer": "A",
                "srs_state": SrsState(),
            },
        ],
    )
    resp = client.post("/flashcards/x::tradeoff/review", data={"grade": "7"})
    assert resp.status_code == 400


def test_review_404_unknown_flashcard(client: TestClient) -> None:
    resp = client.post("/flashcards/bogus::tradeoff/review", data={"grade": "3"})
    assert resp.status_code == 404

"""GET /cap/{id}/related endpoint。Plan 1 Task 9。"""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from dashboard import server
from dashboard.derive.deep_card_types import DeepCard
from dashboard.state.db import open_db
from dashboard.state.repositories import DeepCardRepo


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    db = tmp_path / "board.db"
    monkeypatch.setattr(server, "DB_PATH", db)
    monkeypatch.setattr(server, "MILVUS_HOST", None)  # 强制 fallback
    return TestClient(server.app)


def _seed(monkeypatch_db: Path, cards: list[DeepCard]) -> None:
    conn = open_db(monkeypatch_db)
    repo = DeepCardRepo(conn)
    for c in cards:
        repo.upsert(c)


def test_related_returns_keyword_fallback(client: TestClient, tmp_path: Path) -> None:
    db = tmp_path / "board.db"
    _seed(
        db,
        [
            DeepCard(cap_id="01.a", what="LangGraph supervisor planner"),
            DeepCard(cap_id="01.b", what="LangGraph subgraph"),
            DeepCard(cap_id="03.c", what="Unrelated content fully"),
        ],
    )
    resp = client.get("/cap/01.a/related?k=2")
    assert resp.status_code == 200
    body = resp.json()
    ids = [r["cap_id"] for r in body]
    assert "01.b" in ids
    assert "03.c" not in ids
    assert resp.headers.get("X-Milvus-Status") == "fallback"


def test_related_missing_cap_returns_404(client: TestClient) -> None:
    resp = client.get("/cap/nope/related?k=5")
    assert resp.status_code == 404


def test_related_milvus_disabled_falls_back_with_banner(client: TestClient, tmp_path: Path) -> None:
    """Milvus 不通时,response 头部应含 X-Milvus-Status: fallback。"""
    db = tmp_path / "board.db"
    _seed(
        db,
        [
            DeepCard(cap_id="x", what="同款内容 contents"),
            DeepCard(cap_id="y", what="同款内容 contents"),
        ],
    )
    resp = client.get("/cap/x/related?k=5")
    assert resp.status_code == 200
    assert resp.headers.get("X-Milvus-Status") == "fallback"

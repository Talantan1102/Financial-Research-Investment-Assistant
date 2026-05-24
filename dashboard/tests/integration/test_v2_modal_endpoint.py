"""V2 cap expand endpoint (GET /cap/{id}/expand)。Plan 1 Task 11 → Plan 2 Task 7 route rename。"""

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
    return TestClient(server.app)


def test_modal_returns_html(client: TestClient, tmp_path: Path) -> None:
    db = tmp_path / "board.db"
    conn = open_db(db)
    DeepCardRepo(conn).upsert(
        DeepCard(
            cap_id="context.skills_bundle",
            scenario="this is the scenario",
        )
    )
    resp = client.get("/cap/context.skills_bundle/expand")
    assert resp.status_code == 200
    body = resp.text
    assert "this is the scenario" in body
    assert "cap-detail-inner" in body


def test_modal_unknown_cap_returns_404(client: TestClient) -> None:
    resp = client.get("/cap/nonexistent.cap/expand")
    assert resp.status_code == 404


def test_modal_known_cap_no_deep_card(client: TestClient) -> None:
    """cap 在 yaml 但无 DeepCard → 显示 6 字段空框架。"""
    resp = client.get("/cap/context.constrained_schema/expand")
    assert resp.status_code == 200
    body = resp.text
    assert "需求场景" in body
    assert "设计方案" in body
    assert "(待填)" in body


def test_post_field_updates_deep_card(client: TestClient, tmp_path: Path) -> None:
    db = tmp_path / "board.db"
    conn = open_db(db)
    repo = DeepCardRepo(conn)
    repo.upsert(DeepCard(cap_id="x", prefill_source="manual"))
    resp = client.post("/cap/x/field/what", data={"value": "edited content"})
    assert resp.status_code == 200
    assert "edited content" in resp.text

    conn2 = open_db(db)
    card = DeepCardRepo(conn2).get("x")
    assert card is not None and card.what == "edited content"
    assert card.prefill_source == "manual"  # 第一次手填


def test_post_field_llm_to_hybrid(client: TestClient, tmp_path: Path) -> None:
    db = tmp_path / "board.db"
    conn = open_db(db)
    DeepCardRepo(conn).upsert(DeepCard(cap_id="y", what="llm wrote this", prefill_source="llm"))
    client.post("/cap/y/field/what", data={"value": "I edited it"})
    card = DeepCardRepo(open_db(db)).get("y")
    assert card is not None
    assert card.what == "I edited it"
    assert card.prefill_source == "hybrid"


def test_post_field_unknown_field_400(client: TestClient) -> None:
    resp = client.post("/cap/x/field/bogus_field", data={"value": "x"})
    assert resp.status_code == 400


def test_expand_shows_6_fields(client: TestClient) -> None:
    """Plan 2 Task 7: expand fragment contains all 6 field sections."""
    resp = client.get("/cap/context.skills_bundle/expand")
    assert resp.status_code == 200
    body = resp.text
    assert "需求场景" in body
    assert "设计方案" in body
    assert "Tradeoff" in body
    assert "方案点评" in body
    assert "实现效果" in body
    assert "决策记录" in body

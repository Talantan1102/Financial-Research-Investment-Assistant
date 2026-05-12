"""V2 modal endpoint (GET /cap/{id})。Plan 1 Task 11。"""

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
            cap_id="prompt_context.skills_bundle",
            what="Anthropic Skills bundle 17 件",
            why="progressive disclosure",
        )
    )
    resp = client.get("/cap/prompt_context.skills_bundle")
    assert resp.status_code == 200
    body = resp.text
    assert "Anthropic Skills bundle" in body
    assert "progressive disclosure" in body
    assert "deep-card-modal" in body


def test_modal_unknown_cap_returns_404(client: TestClient) -> None:
    resp = client.get("/cap/nonexistent.cap")
    assert resp.status_code == 404


def test_modal_known_cap_no_deep_card(client: TestClient) -> None:
    """cap 在 yaml 但无 DeepCard → 显示 'AI 草拟' 按钮 / '(未填)' 引导。"""
    resp = client.get("/cap/prompt_context.constrained_schema")
    assert resp.status_code == 200
    body = resp.text
    assert "AI 草拟" in body
    assert "(未填)" in body


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


def test_ai_draft_llm_unavailable_503(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        server, "_get_llm_service", lambda: (_ for _ in ()).throw(RuntimeError("no llm"))
    )
    resp = client.post("/cap/prompt_context.constrained_schema/ai_draft/what")
    assert resp.status_code == 503


def test_modal_linked_capability_renders_overview_anchor(
    client: TestClient, tmp_path: Path
) -> None:
    """Plan 2 Task 10:linked_capabilities 渲染为 /overview#cap_{id} 跳转链接。"""
    db = tmp_path / "board.db"
    conn = open_db(db)
    DeepCardRepo(conn).upsert(
        DeepCard(
            cap_id="prompt_context.skills_bundle",
            what="Anthropic Skills bundle 17 件",
            linked_capabilities=["memory.cross_session", "orchestration.supervisor"],
        )
    )
    resp = client.get("/cap/prompt_context.skills_bundle")
    assert resp.status_code == 200
    body = resp.text
    assert "/overview#cap_memory.cross_session" in body
    assert "/overview#cap_orchestration.supervisor" in body

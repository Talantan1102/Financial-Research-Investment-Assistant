"""Plan 2 Task 7 — GET /cap/{id}/expand inline expand fragment 测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from dashboard import server


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    db = tmp_path / "test.db"
    monkeypatch.setattr(server, "DB_PATH", db)
    return TestClient(server.app)


def test_expand_returns_fragment(client: TestClient) -> None:
    resp = client.get("/cap/execution.docker_compose/expand")
    assert resp.status_code == 200
    body = resp.text
    assert "cap-detail-inner" in body
    assert "需求场景" in body
    assert "设计方案" in body
    assert "Tradeoff" in body
    assert "方案点评" in body
    assert "实现效果" in body
    assert "决策记录" in body


def test_expand_unknown_cap_404(client: TestClient) -> None:
    resp = client.get("/cap/not_a_cap/expand")
    assert resp.status_code == 404


def test_expand_lit_status_shows_evidence_enabled(client: TestClient) -> None:
    resp = client.get("/cap/execution.docker_compose/expand")
    assert "field-evidence" in resp.text


def test_expand_with_existing_card_shows_content(client: TestClient, tmp_path: Path) -> None:
    from dashboard.derive.deep_card_types import DeepCard
    from dashboard.state.db import open_db
    from dashboard.state.repositories import DeepCardRepo

    db = tmp_path / "test.db"
    conn = open_db(db)
    DeepCardRepo(conn).upsert(
        DeepCard(
            cap_id="execution.docker_compose",
            schema_version=2,
            scenario="this is the scenario text for testing",
        )
    )
    conn.close()

    resp = client.get("/cap/execution.docker_compose/expand")
    assert resp.status_code == 200
    assert "this is the scenario text for testing" in resp.text

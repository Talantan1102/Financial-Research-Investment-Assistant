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
    # 渲染真实 v1 字段(早期模板误读 v2 空字段导致全显"(待填)",已修)
    assert "这是什么" in body
    assert "为什么需要" in body
    assert "取舍" in body
    assert "踩坑沉淀" in body
    assert "决策记录" in body


def test_expand_unknown_cap_404(client: TestClient) -> None:
    resp = client.get("/cap/not_a_cap/expand")
    assert resp.status_code == 404


def test_expand_renders_editable_text_fields(client: TestClient) -> None:
    # 文本字段(what/why/tradeoff/lessons)以可编辑 field-block 渲染
    body = client.get("/cap/execution.docker_compose/expand").text
    assert "field-what" in body
    assert "field-edit-btn" in body


def test_expand_with_existing_card_shows_content(client: TestClient, tmp_path: Path) -> None:
    from dashboard.derive.deep_card_types import DeepCard
    from dashboard.state.db import open_db
    from dashboard.state.repositories import DeepCardRepo

    db = tmp_path / "test.db"
    conn = open_db(db)
    DeepCardRepo(conn).upsert(
        DeepCard(
            cap_id="execution.docker_compose",
            what="this is the what text for testing",
        )
    )
    conn.close()

    resp = client.get("/cap/execution.docker_compose/expand")
    assert resp.status_code == 200
    assert "this is the what text for testing" in resp.text

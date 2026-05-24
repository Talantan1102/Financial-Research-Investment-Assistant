"""Plan 4 Task 4 — /story 新页面渲染测试(textarea + render area)。"""

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


def test_story_page_returns_200(client: TestClient) -> None:
    resp = client.get("/story")
    assert resp.status_code == 200


def test_story_page_renders_textarea(client: TestClient) -> None:
    resp = client.get("/story")
    body = resp.text
    assert 'id="story-input"' in body
    assert "textarea" in body
    assert 'class="story-input"' in body


def test_story_page_renders_output_area(client: TestClient) -> None:
    resp = client.get("/story")
    body = resp.text
    assert 'id="story-out"' in body
    assert "story-render" in body
    assert "markdown-body" in body


def test_story_page_includes_story_js(client: TestClient) -> None:
    resp = client.get("/story")
    assert "story.js" in resp.text


def test_story_page_loads_marked_and_mermaid_cdn(client: TestClient) -> None:
    resp = client.get("/story")
    body = resp.text
    assert "marked" in body
    assert "mermaid" in body


def test_story_page_no_old_card_artifact(client: TestClient) -> None:
    resp = client.get("/story")
    body = resp.text
    assert "story-card" not in body
    assert "drop-cap" not in body
    assert "三段式时间线" not in body

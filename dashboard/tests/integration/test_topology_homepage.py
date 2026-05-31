"""Plan 3 Task 2 — 首页 Topology 渲染测试。"""

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


def test_homepage_returns_200(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200


def test_homepage_renders_topology_svg(client: TestClient) -> None:
    resp = client.get("/")
    body = resp.text
    assert "topology-svg" in body
    assert 'viewBox="0 0 600 320"' in body


def test_homepage_shows_all_7_modules(client: TestClient) -> None:
    resp = client.get("/")
    body = resp.text
    for letter in ["E", "T", "C", "L", "O", "V", "G"]:
        assert f">{letter}</text>" in body, f"missing letter {letter}"
    for dim_id in [
        "execution",
        "tool",
        "context",
        "lifecycle",
        "observability",
        "verification",
        "governance",
    ]:
        assert f'href="/m/{dim_id}"' in body, f"missing link for {dim_id}"


def test_homepage_shows_paper_anchors(client: TestClient) -> None:
    resp = client.get("/")
    body = resp.text
    for sec in ["§ 3", "§ 4", "§ 5", "§ 6", "§ 7", "§ 8", "§ 9"]:
        assert sec in body


def test_homepage_includes_status_bars(client: TestClient) -> None:
    resp = client.get("/")
    body = resp.text
    assert "#34C759" in body
    assert "#FF9F0A" in body
    assert "#AEAEB2" in body  # todo 段提深(原 #C7C7CC 太浅,"未开发"视觉隐身)


def test_homepage_no_old_views(client: TestClient) -> None:
    """旧 D-view / B-view / view-toggle / app-shell-row 已退役。"""
    resp = client.get("/")
    body = resp.text
    assert "view-toggle" not in body
    assert "layer-stack" not in body
    assert "kanban" not in body
    assert "app-shell-row" not in body

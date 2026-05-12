"""Plan 2 Task 3 — V3 /overview + /api/overview/graph.json endpoint tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    from dashboard import server

    monkeypatch.setattr(server, "DB_PATH", tmp_path / "board.db")
    return TestClient(server.app)


def test_overview_html_contains_cytoscape_init(client: TestClient) -> None:
    resp = client.get("/overview")
    assert resp.status_code == 200
    assert "cytoscape" in resp.text.lower()
    assert "overview-canvas" in resp.text


def test_graph_json_returns_nodes_edges(client: TestClient) -> None:
    resp = client.get("/api/overview/graph.json")
    assert resp.status_code == 200
    body = resp.json()
    assert "nodes" in body and "edges" in body
    # 至少应有 capabilities.yaml 的 ≥60 cap (无过滤)
    assert len(body["nodes"]) >= 60


def test_graph_json_filter_by_dim(client: TestClient) -> None:
    resp = client.get("/api/overview/graph.json?dim=memory")
    body = resp.json()
    for n in body["nodes"]:
        assert n["data"]["dimension"] == "memory"


def test_graph_json_only_low_confidence(client: TestClient) -> None:
    resp = client.get("/api/overview/graph.json?low_conf=1")
    body = resp.json()
    # 当前所有 cap 无 DeepCard → confidence=0 → 都应入(全部 low conf)
    assert len(body["nodes"]) >= 10


def test_overview_fallback_renders_cards(client: TestClient) -> None:
    resp = client.get("/overview/fallback")
    assert resp.status_code == 200
    assert "overview-fallback-grid" in resp.text
    # 至少含某个 /cap/ 链接
    assert '<a href="/cap/' in resp.text

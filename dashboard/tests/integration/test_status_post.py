"""Plan 2 Task 6 — POST /cap/{id}/status 三色切换测试。"""

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


def test_status_post_sets_lit(client: TestClient) -> None:
    resp = client.post("/cap/execution.docker_compose/status", data={"status": "lit"})
    assert resp.status_code == 200
    assert "cap-chip--lit" in resp.text


def test_status_post_sets_wip(client: TestClient) -> None:
    resp = client.post("/cap/execution.docker_compose/status", data={"status": "wip"})
    assert resp.status_code == 200
    assert "cap-chip--wip" in resp.text


def test_status_post_invalid_status_400(client: TestClient) -> None:
    resp = client.post("/cap/execution.docker_compose/status", data={"status": "invalid"})
    assert resp.status_code == 400


def test_status_post_unknown_cap_404(client: TestClient) -> None:
    resp = client.post("/cap/not_a_cap/status", data={"status": "lit"})
    assert resp.status_code == 404


def test_status_post_persists_in_override(client: TestClient, tmp_path: Path) -> None:
    from dashboard.state.db import open_db
    from dashboard.state.repositories import OverrideRepo

    client.post("/cap/execution.docker_compose/status", data={"status": "lit"})
    conn = open_db(tmp_path / "test.db")
    overrides = OverrideRepo(conn).get_all()
    conn.close()
    assert overrides.get("execution.docker_compose") == "lit"

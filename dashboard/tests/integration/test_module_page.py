"""Plan 2 Task 4 — 模块页 /m/{dim_id} 渲染测试。"""

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


def test_module_page_execution(client: TestClient) -> None:
    resp = client.get("/m/execution")
    assert resp.status_code == 200
    body = resp.text
    assert "module-page" in body
    assert 'data-dim-id="execution"' in body
    assert "执行环境" in body


def test_module_page_all_7_dims(client: TestClient) -> None:
    for dim_id in [
        "execution",
        "tool",
        "context",
        "lifecycle",
        "observability",
        "verification",
        "governance",
    ]:
        resp = client.get(f"/m/{dim_id}")
        assert resp.status_code == 200, f"failed for {dim_id}"
        assert f'data-dim-id="{dim_id}"' in resp.text


def test_module_page_unknown_dim_404(client: TestClient) -> None:
    resp = client.get("/m/totally_invalid")
    assert resp.status_code == 404


def test_module_page_shows_capability_chips(client: TestClient) -> None:
    resp = client.get("/m/execution")
    body = resp.text
    assert body.count('class="cap-item"') >= 5

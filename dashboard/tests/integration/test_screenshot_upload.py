"""Plan 2 Task 9 — POST /cap/{id}/screenshot endpoint 测试。"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from dashboard import server


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(server, "DASHBOARD_ROOT", tmp_path)
    return TestClient(server.app)


def _png_bytes(size: int = 200) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"x" * size


def test_upload_screenshot_success(client: TestClient, tmp_path: Path) -> None:
    files = {"file": ("arch.png", io.BytesIO(_png_bytes()), "image/png")}
    resp = client.post("/cap/execution.docker_compose/screenshot", files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert data["path"].startswith("screenshots/execution.docker_compose/")
    assert data["path"].endswith("-arch.png")
    assert "git add dashboard/screenshots/" in data["git_hint"]
    assert (tmp_path / data["path"]).exists()


def test_upload_screenshot_rejects_unsupported_type(client: TestClient) -> None:
    files = {"file": ("doc.pdf", io.BytesIO(b"%PDF-1.4\n"), "application/pdf")}
    resp = client.post("/cap/x.y/screenshot", files=files)
    assert resp.status_code == 400
    assert "unsupported" in resp.json()["error"]


def test_upload_screenshot_rejects_too_large(client: TestClient) -> None:
    big = b"\x89PNG\r\n\x1a\n" + b"x" * 600_000
    files = {"file": ("big.png", io.BytesIO(big), "image/png")}
    resp = client.post("/cap/x.y/screenshot", files=files)
    assert resp.status_code == 400
    assert "size" in resp.json()["error"]


def test_upload_screenshot_no_file(client: TestClient) -> None:
    resp = client.post("/cap/x.y/screenshot")
    assert resp.status_code == 400

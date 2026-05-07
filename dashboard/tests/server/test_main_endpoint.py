from starlette.testclient import TestClient

from dashboard.server import app


def test_healthz() -> None:
    with TestClient(app) as client:
        r = client.get("/healthz")
        assert r.status_code == 200
        assert r.json() == {"ok": True}


def test_index_renders() -> None:
    with TestClient(app) as client:
        r = client.get("/")
        assert r.status_code == 200
        body = r.text
        # Hero
        assert "📅" in body
        # 8 layer 卡片
        assert body.count("layer-card") >= 8
        # 三态 chip
        assert "lit" in body and "todo" in body
        # 计数
        assert "/62" in body or "62" in body  # total appears somewhere

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


def test_view_d_default() -> None:
    """无 query 默认 D 视图,有 layer-card 和 Tab nav。"""
    with TestClient(app) as client:
        r = client.get("/")
        assert r.status_code == 200
        body = r.text
        assert 'class="layer-card"' in body
        assert "B Kanban" in body  # tab nav
        assert "D 维度" in body


def test_view_b_renders_kanban() -> None:
    """?view=b 渲染 Kanban 三列。"""
    with TestClient(app) as client:
        r = client.get("/?view=b")
        assert r.status_code == 200
        body = r.text
        assert 'class="layer-card"' not in body  # 不显 D 视图
        assert 'class="kanban"' in body
        assert "Todo (" in body  # todo 列 header
        assert "Doing (" in body
        assert "Done (" in body
        assert "<details>" in body  # Done 列折叠

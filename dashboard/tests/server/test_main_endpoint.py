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
        # Hero (Plan 3 Task 2 — Topology homepage)
        assert "hero-title" in body
        # Topology SVG present
        assert "topology-svg" in body
        assert 'viewBox="0 0 600 320"' in body
        # 7 module links
        for dim_id in [
            "execution",
            "tool",
            "context",
            "lifecycle",
            "observability",
            "verification",
            "governance",
        ]:
            assert f'href="/m/{dim_id}"' in body
        # 计数
        assert "87" in body  # total appears somewhere


def test_view_d_default() -> None:
    """Plan 3 Task 2 — 首页默认渲染 Topology SVG(D/B 视图切换已退役)。"""
    with TestClient(app) as client:
        r = client.get("/")
        assert r.status_code == 200
        body = r.text
        assert "topology-svg" in body
        assert "topology-box" in body
        # old D-view layer-stack / Kanban tab 已退役
        assert 'class="layer-stack"' not in body
        assert 'class="kanban"' not in body


def test_view_b_renders_kanban() -> None:
    """Plan 3 Task 2 — ?view=b 不再渲染 Kanban;首页统一 Topology。"""
    with TestClient(app) as client:
        r = client.get("/?view=b")
        assert r.status_code == 200
        body = r.text
        # Topology 始终渲染
        assert "topology-svg" in body
        # 旧 kanban 已退役
        assert 'class="kanban"' not in body


def test_get_refresh_returns_sse_event_stream() -> None:
    """GET /refresh → text/event-stream(SSE 标准 = GET;EventSource 强制 GET)。"""
    with TestClient(app) as client:
        client.get("/")
        with client.stream("GET", "/refresh") as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            body = "".join(chunk.decode("utf-8") for chunk in r.iter_bytes())
            assert "event: done" in body


def test_index_shows_app_shell_row() -> None:
    """Plan 3 Task 2 — 首页含 Topology hero 和 7 模块链接(App Shell 行已退役至模块页)。"""
    with TestClient(app) as client:
        r = client.get("/")
        body = r.text
        assert "hero-title" in body
        assert "topology-svg" in body
        # All 7 paper section anchors rendered
        for sec in ["§ 3", "§ 4", "§ 5", "§ 6", "§ 7", "§ 8", "§ 9"]:
            assert sec in body

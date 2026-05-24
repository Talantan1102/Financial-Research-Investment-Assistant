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


def test_get_edit_returns_select() -> None:
    """点击 chip 触发的 GET /capability/{id}/edit 返回 select form。"""
    with TestClient(app) as client:
        r = client.get("/capability/context.long_term_memory/edit")
        assert r.status_code == 200
        body = r.text
        assert "<select" in body
        assert "force-lit" in body
        assert "set-wip" in body
        assert "force-todo" in body
        assert "clear override" in body
        assert "hx-post" in body
        assert "/capability/context.long_term_memory/override" in body


def test_get_edit_404_unknown_id() -> None:
    """未知 capability id 返 404。"""
    with TestClient(app) as client:
        r = client.get("/capability/nope.fake/edit")
        assert r.status_code == 404


def test_post_override_invalidates_and_swaps() -> None:
    """POST override → 写 override 表 + invalidate snapshot + 返回新 chip HTML。"""
    with TestClient(app) as client:
        # 先 GET / 触发 build_snapshot,确保表有 row
        client.get("/")
        # POST set wip
        r = client.post(
            "/capability/context.long_term_memory/override",
            data={"status": "wip"},
        )
        assert r.status_code == 200
        body = r.text
        assert "cap-chip--wip" in body
        # invalidate 验证:再 GET /,snapshot 含新 wip
        r2 = client.get("/")
        assert "context.long_term_memory" in r2.text  # capability 出现在页面


def test_post_override_clear_sentinel() -> None:
    """POST status=__clear__ 删除 override row。"""
    with TestClient(app) as client:
        # 先种一个 override
        client.post("/capability/context.long_term_memory/override", data={"status": "wip"})
        # 清掉
        r = client.post(
            "/capability/context.long_term_memory/override",
            data={"status": "__clear__"},
        )
        assert r.status_code == 200
        body = r.text
        # clear 后回到 derived 状态(context.long_term_memory derive 是 todo,因 derive_rule type=manual)
        assert "cap-chip--todo" in body
        # new chip template has no stale-mark


def test_post_override_unknown_cap_id_returns_404_no_write() -> None:
    """POST 未知 cap_id 返 404 且不写 override 表(防 orphan row)。"""
    from dashboard import server as dashboard_server
    from dashboard.state.db import open_db
    from dashboard.state.repositories import OverrideRepo

    with TestClient(app) as client:
        # POST with unknown cap_id and valid status
        r = client.post(
            "/capability/nope.fake/override",
            data={"status": "wip"},
        )
        assert r.status_code == 404
        assert "not found" in r.text
        # Verify NO row written to capability_override table for nope.fake
        # (use isolated DB_PATH from autouse fixture, not prod path)
        conn = open_db(dashboard_server.DB_PATH)
        try:
            overrides = OverrideRepo(conn).get_all()
        finally:
            conn.close()
        assert "nope.fake" not in overrides


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

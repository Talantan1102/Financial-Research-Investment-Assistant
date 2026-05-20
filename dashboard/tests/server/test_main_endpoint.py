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
        assert "hero-title" in body
        # 7 layer 卡片(ETCLOVG 新结构使用 class="layer")
        assert body.count('class="layer"') >= 7
        # 三态 chip
        assert "lit" in body and "todo" in body
        # 计数
        assert "/87" in body or "87" in body  # total appears somewhere


def test_view_d_default() -> None:
    """无 query 默认 D 视图,有 layer-stack 和 Tab nav。"""
    with TestClient(app) as client:
        r = client.get("/")
        assert r.status_code == 200
        body = r.text
        assert 'class="layer-stack"' in body
        assert "Kanban" in body  # tab nav B view
        assert "维度" in body  # tab nav D view


def test_view_b_renders_kanban() -> None:
    """?view=b 渲染 Kanban 三列。"""
    with TestClient(app) as client:
        r = client.get("/?view=b")
        assert r.status_code == 200
        body = r.text
        assert 'class="layer-stack"' not in body  # 不显 D 视图
        assert 'class="kanban"' in body
        assert "kanban-todo" in body  # todo 列
        assert "kanban-doing" in body
        assert "kanban-done" in body


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
        assert 'class="chip wip"' in body
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
        assert 'class="chip todo"' in body
        assert "stale-mark" not in body  # 派生 == status,无 stale


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
    """主视图含 App Shell 第 9 行。"""
    with TestClient(app) as client:
        r = client.get("/")
        body = r.text
        assert 'class="app-shell-row"' in body
        assert "09" in body  # app shell number
        assert "App Shell" in body
        # 6 项至少出现一项(具体名称随 dimensions.yaml,只验"前端"在 yaml 默认配置中)
        assert "前端" in body

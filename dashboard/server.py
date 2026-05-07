"""Starlette app + 路由。M1:GET / + GET /healthz。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from dashboard.derive.capability_resolver import load_capabilities
from dashboard.derive.snapshot_builder import build_snapshot
from dashboard.derive.types import SnapshotDict
from dashboard.state.db import open_db
from dashboard.state.repositories import OverrideRepo, SnapshotRepo

DASHBOARD_ROOT = Path(__file__).parent
PROJECT_ROOT = DASHBOARD_ROOT.parent
CONFIG_DIR = DASHBOARD_ROOT / "config"
DB_PATH = PROJECT_ROOT / "backend" / "data" / "board.db"

templates = Jinja2Templates(directory=str(DASHBOARD_ROOT / "templates"))


def _today_label() -> str:
    """e.g. '2026-05-07 周三'(中文星期)。"""
    weekdays_cn = ["一", "二", "三", "四", "五", "六", "日"]
    now = datetime.now()
    return f"{now.strftime('%Y-%m-%d')} 周{weekdays_cn[now.weekday()]}"


def _get_or_build_snapshot() -> SnapshotDict:
    """Lazy 派生:若 sqlite 无 snapshot,跑一次 build(把 override 喂进去)。"""
    conn = open_db(DB_PATH)
    try:
        snap_repo = SnapshotRepo(conn)
        snap = snap_repo.get_latest()
        if snap is None:
            override_repo = OverrideRepo(conn)
            overrides = override_repo.get_all()
            snapshot = build_snapshot(PROJECT_ROOT, CONFIG_DIR, overrides=overrides)
            snap_repo.save(snapshot.refreshed_at, snapshot.to_dict())
            snap = snap_repo.get_latest()
            assert snap is not None  # just saved
        return snap
    finally:
        conn.close()


async def index(request: Request) -> HTMLResponse:
    view_mode = request.query_params.get("view", "d")
    if view_mode not in ("d", "b"):
        view_mode = "d"
    snap = _get_or_build_snapshot()
    wips = [c for layer in snap["layers"] for c in layer["capabilities"] if c["status"] == "wip"]
    ctx: dict[str, object] = {
        "today": _today_label(),
        "snap": snap,
        "wips": wips,
        "view_mode": view_mode,
    }
    if view_mode == "b":
        # Pre-compute Kanban lists (Risk 5 mitigation: avoid jinja list.append)
        ctx["todo_caps"] = [
            c for layer in snap["layers"] for c in layer["capabilities"] if c["status"] == "todo"
        ]
        ctx["wip_caps"] = wips
        ctx["lit_caps"] = [
            c for layer in snap["layers"] for c in layer["capabilities"] if c["status"] == "lit"
        ]
    return templates.TemplateResponse(request, "main.html", ctx)


async def healthz(_request: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


async def edit_capability(request: Request) -> HTMLResponse:
    """返回 chip 替换为 edit select 的 HTML 片段(htmx swap source)。"""
    cap_id = request.path_params["cap_id"]
    # 从 capabilities.yaml 拿到这个 capability 的元数据(name_cn 用于 select 头)
    caps = load_capabilities(CONFIG_DIR / "capabilities.yaml")
    target = next((c for c in caps if c.id == cap_id), None)
    if target is None:
        return HTMLResponse(f"capability {cap_id} not found", status_code=404)
    template = templates.get_template("_edit_select.html")
    html = template.render(c=target)
    return HTMLResponse(html)


app = Starlette(
    routes=[
        Route("/", index),
        Route("/healthz", healthz),
        Route("/capability/{cap_id}/edit", edit_capability),
        Mount(
            "/static",
            StaticFiles(directory=str(DASHBOARD_ROOT / "static")),
            name="static",
        ),
    ],
)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8910, log_level="info")

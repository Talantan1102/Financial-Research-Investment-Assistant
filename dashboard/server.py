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
    return templates.TemplateResponse(
        request,
        "main.html",
        {
            "today": _today_label(),
            "snap": snap,
            "wips": wips,
            "view_mode": view_mode,
        },
    )


async def healthz(_request: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


app = Starlette(
    routes=[
        Route("/", index),
        Route("/healthz", healthz),
        Mount(
            "/static",
            StaticFiles(directory=str(DASHBOARD_ROOT / "static")),
            name="static",
        ),
    ],
)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8910, log_level="info")

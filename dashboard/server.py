"""Starlette app + 路由。M1:GET / + GET /healthz。"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import cast

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

logger = logging.getLogger(__name__)
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from dashboard.derive.app_shell_stat import compute_app_shell_stat
from dashboard.derive.capability_resolver import load_capabilities, resolve_status
from dashboard.derive.decision_extractor import extract_all, resolve_memory_path
from dashboard.derive.path_router import load_dimensions
from dashboard.derive.snapshot_builder import build_snapshot
from dashboard.derive.types import Capability, CapabilityStatus, SnapshotDict
from dashboard.state.db import open_db
from dashboard.state.keyword_recommender import recommend_by_keyword
from dashboard.state.repositories import (
    DecisionNoteRepo,
    DeepCardRepo,
    OverrideRepo,
    SnapshotRepo,
)

MILVUS_HOST = os.getenv("HARNESS_BOARD_MILVUS_HOST")
MILVUS_PORT = int(os.getenv("HARNESS_BOARD_MILVUS_PORT", "19530"))

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

    # DeepCard 完成度 + SRS confidence 注入到每个 chip(Review Mode Task 10)
    from dashboard.derive.completion import completion_level_or_none

    conn = open_db(DB_PATH)
    try:
        deep_cards_by_id = {c.cap_id: c for c in DeepCardRepo(conn).get_all()}
    finally:
        conn.close()
    for layer in snap["layers"]:
        for c in layer["capabilities"]:
            dc = deep_cards_by_id.get(c["id"])
            # TypedDict 不支持动态 key,但 chip 模板用 dict access 兼容
            c["completion_level"] = completion_level_or_none(dc)  # type: ignore[typeddict-unknown-key]
            c["confidence"] = dc.srs_state.confidence if dc else 0  # type: ignore[typeddict-unknown-key]

    wips = [c for layer in snap["layers"] for c in layer["capabilities"] if c["status"] == "wip"]
    # App Shell 第 9 行 mini stat
    _main_dims, app_shell_dims = load_dimensions(CONFIG_DIR / "dimensions.yaml")
    app_shell = compute_app_shell_stat(PROJECT_ROOT, app_shell_dims)
    ctx: dict[str, object] = {
        "today": _today_label(),
        "snap": snap,
        "wips": wips,
        "view_mode": view_mode,
        "active_view": view_mode,  # M3:同 view_mode("d" 或 "b"),decisions 用独立 route 不走这
        "app_shell": app_shell,
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


async def decisions_view(request: Request) -> HTMLResponse:
    """GET /decisions — render 全部决策卡 + filter UI(client JS)。"""
    decisions = extract_all()
    memory_path = resolve_memory_path()
    # snap + wips 复用(base.html / _hero.html 需要)
    snap = _get_or_build_snapshot()
    wips = [c for layer in snap["layers"] for c in layer["capabilities"] if c["status"] == "wip"]
    # 读 note 持久化
    conn = open_db(DB_PATH)
    try:
        note_repo = DecisionNoteRepo(conn)
        note_lookup = note_repo.get_all()
    finally:
        conn.close()
    # 加载 main_dims for filter chip(layer 列)
    main_dims, _ = load_dimensions(CONFIG_DIR / "dimensions.yaml")
    return templates.TemplateResponse(
        request,
        "decisions.html",
        {
            "today": _today_label(),
            "snap": snap,
            "wips": wips,
            "decisions": decisions,
            "note_lookup": note_lookup,
            "main_dims": main_dims,
            "active_view": "decisions",
            "memory_path_warning": memory_path is None,
        },
    )


async def post_decision_note(request: Request) -> HTMLResponse:
    """upsert decision note + 返回新 form HTML(htmx swap)。"""
    decision_id = request.path_params["decision_id"]
    form = await request.form()
    note_raw = form.get("note", "")
    if not isinstance(note_raw, str):
        return HTMLResponse("invalid form", status_code=400)
    conn = open_db(DB_PATH)
    try:
        DecisionNoteRepo(conn).upsert(decision_id, note_raw)
    finally:
        conn.close()
    return _render_decision_note_form(decision_id, note_raw)


async def delete_decision_note(request: Request) -> HTMLResponse:
    """clear decision note + 返回空 form HTML。"""
    decision_id = request.path_params["decision_id"]
    conn = open_db(DB_PATH)
    try:
        DecisionNoteRepo(conn).delete(decision_id)
    finally:
        conn.close()
    return _render_decision_note_form(decision_id, "")


def _render_decision_note_form(decision_id: str, note: str) -> HTMLResponse:
    """Render decision-note form HTML(用于 POST/DELETE htmx swap response)。

    模板内容跟 _decision_card.html 内的 form 部分一致 — 共享单一 source of truth
    在 _decision_note_form.html partial 里。
    """
    template = templates.get_template("_decision_note_form.html")
    html = template.render(decision_id=decision_id, note=note)
    return HTMLResponse(html)


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


async def post_override(request: Request) -> HTMLResponse:
    """upsert override 或 clear (sentinel __clear__) + invalidate snapshot + 返回新 chip HTML。"""
    cap_id = request.path_params["cap_id"]
    form = await request.form()
    status_raw = form.get("status", "")
    if not isinstance(status_raw, str):
        return HTMLResponse("invalid form", status_code=400)
    if status_raw != "__clear__" and status_raw not in ("lit", "wip", "todo"):
        return HTMLResponse(f"invalid status: {status_raw}", status_code=400)

    # Validate cap_id BEFORE touching DB (fix: write-before-validate orphan row bug)
    caps = load_capabilities(CONFIG_DIR / "capabilities.yaml")
    target_cfg = next((c for c in caps if c.id == cap_id), None)
    if target_cfg is None:
        return HTMLResponse(f"capability {cap_id} not found", status_code=404)

    conn = open_db(DB_PATH)
    try:
        override_repo = OverrideRepo(conn)
        if status_raw == "__clear__":
            override_repo.delete(cap_id)
        else:
            override_repo.upsert(cap_id, cast(CapabilityStatus, status_raw), reason="via UI")
        # invalidate snapshot,下次 GET / 重 build
        SnapshotRepo(conn).invalidate()
        # 重新读 override(可能刚 delete)
        overrides = override_repo.get_all()
    finally:
        conn.close()

    # 重 resolve 这一个 capability,渲染新 chip
    derived = resolve_status(target_cfg, PROJECT_ROOT)
    final_status = overrides.get(cap_id, derived)
    cap = Capability(
        id=target_cfg.id,
        dimension=target_cfg.dimension,
        name_cn=target_cfg.name_cn,
        name_en=target_cfg.name_en,
        status=final_status,
        derived_status=derived,
    )
    template = templates.get_template("_capability_chip.html")
    html = template.render(c=cap)
    return HTMLResponse(html)


async def post_refresh(_request: Request) -> Response:
    """显式 invalidate snapshot,302 redirect 到 /。"""
    conn = open_db(DB_PATH)
    try:
        SnapshotRepo(conn).invalidate()
    finally:
        conn.close()
    return RedirectResponse("/", status_code=302)


def _try_milvus_related(_cap_id: str, _k: int) -> tuple[list[dict[str, object]] | None, str]:
    """尝试 Milvus 查询;Plan 1 简化为只支持 fallback,Plan 2 Task 6 wire 完整路径。"""
    if MILVUS_HOST is None:
        return None, "milvus_disabled"
    # Plan 2 wire 时替换,当前直接 fallback
    return None, "milvus_search_not_wired_plan1"


async def related_capabilities(request: Request) -> JSONResponse:
    """GET /cap/{cap_id}/related?k=5 — 相关 cap 推荐 (Milvus 真路径 / keyword fallback)。"""
    cap_id = request.path_params["cap_id"]
    try:
        k = int(request.query_params.get("k", "5"))
    except ValueError:
        k = 5

    conn = open_db(DB_PATH)
    try:
        repo = DeepCardRepo(conn)
        pivot = repo.get(cap_id)
        if pivot is None:
            return JSONResponse({"error": "cap not found"}, status_code=404)
        all_cards = repo.get_all()
    finally:
        conn.close()

    milvus_result, _reason = _try_milvus_related(cap_id, k)
    if milvus_result is not None:
        return JSONResponse(milvus_result, headers={"X-Milvus-Status": "ok"})
    # fallback to keyword
    recs = recommend_by_keyword(pivot, all_cards, k=k)
    # name_cn 从 capabilities.yaml 取(简化:不每次重读;若性能瓶颈再 cache)
    caps_cfg = load_capabilities(CONFIG_DIR / "capabilities.yaml")
    name_by_id = {c.id: c.name_cn for c in caps_cfg}
    payload = [
        {"cap_id": r.cap_id, "name_cn": name_by_id.get(r.cap_id, ""), "score": 0.0} for r in recs
    ]
    return JSONResponse(payload, headers={"X-Milvus-Status": "fallback"})


app = Starlette(
    routes=[
        Route("/", index),
        Route("/healthz", healthz),
        Route("/decisions", decisions_view),
        Route("/decisions/{decision_id}/note", post_decision_note, methods=["POST"]),
        Route("/decisions/{decision_id}/note", delete_decision_note, methods=["DELETE"]),
        Route("/capability/{cap_id}/edit", edit_capability),
        Route("/capability/{cap_id}/override", post_override, methods=["POST"]),
        Route("/refresh", post_refresh, methods=["POST"]),
        Route("/cap/{cap_id}/related", related_capabilities, methods=["GET"]),
        Mount(
            "/static",
            StaticFiles(directory=str(DASHBOARD_ROOT / "static")),
            name="static",
        ),
    ],
)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8910, log_level="info")

"""Starlette app + 路由。M1:GET / + GET /healthz。"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import cast

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

logger = logging.getLogger(__name__)

from dashboard.derive.app_shell_stat import compute_app_shell_stat
from dashboard.derive.capability_resolver import load_capabilities, resolve_status
from dashboard.derive.decision_extractor import extract_all, resolve_memory_path
from dashboard.derive.path_router import load_dimensions
from dashboard.derive.refresh_pipeline import RefreshPipeline
from dashboard.derive.seed_ingest import SeedIngestService
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
SEED_PATH = DASHBOARD_ROOT / "data" / "deep_cards_seed.jsonl"

templates = Jinja2Templates(directory=str(DASHBOARD_ROOT / "templates"))
# 静态资源 cache buster — 用 static/ 目录所有 .js/.css 的最大 mtime,server 启动时算一次。
# 资源文件改动后下次启动 hash 变化,浏览器(尤其 Safari)被迫重新拉取,绕开本地缓存。
_STATIC_DIR = DASHBOARD_ROOT / "static"
_asset_mtime = max(
    (p.stat().st_mtime for p in _STATIC_DIR.glob("*") if p.suffix in {".js", ".css"}),
    default=0.0,
)
ASSET_VERSION = f"{int(_asset_mtime):x}"
templates.env.globals["asset_v"] = ASSET_VERSION


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

    wips = [c for layer in snap["layers"] for c in layer["capabilities"] if c["status"] == "wip"]
    # App Shell 第 9 行 mini stat
    _main_dims, catch_all_dims = load_dimensions(CONFIG_DIR / "dimensions.yaml")
    app_shell = compute_app_shell_stat(PROJECT_ROOT, catch_all_dims)
    ctx: dict[str, object] = {
        "today": _today_label(),
        "snap": snap,
        "wips": wips,
        "view_mode": view_mode,
        "active_view": view_mode,  # M3:同 view_mode("d" 或 "b"),decisions 用独立 route 不走这
        "active_nav": "grid",
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


async def module_page_view(request: Request) -> HTMLResponse:
    """模块页 — 单维度 capability 列表。Plan 2 Task 4。"""
    dim_id = request.path_params["dim_id"]
    main_dims, _ = load_dimensions(CONFIG_DIR / "dimensions.yaml")
    dim = next((d for d in main_dims if d.id == dim_id), None)
    if dim is None:
        return HTMLResponse(f"unknown dim_id: {dim_id}", status_code=404)

    conn = open_db(DB_PATH)
    try:
        snap_repo = SnapshotRepo(conn)
        snap = snap_repo.get_latest()
        if snap is None:
            override_repo = OverrideRepo(conn)
            overrides = override_repo.get_all()
            snapshot = build_snapshot(PROJECT_ROOT, CONFIG_DIR, overrides=overrides)
            snap = snapshot.to_dict()
            snap_repo.save(snap["refreshed_at"], snap)
    finally:
        conn.close()

    layer = next((L for L in snap["layers"] if L["id"] == dim_id), None)
    if layer is None:
        return HTMLResponse(f"no layer data for dim_id: {dim_id}", status_code=404)

    ctx = {
        "request": request,
        "dim": dim,
        "layer": layer,
        "asset_v": ASSET_VERSION,
    }
    return cast(HTMLResponse, templates.TemplateResponse("_module_page.html", ctx))


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
            "active_nav": "decisions",
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


async def post_status(request: Request) -> HTMLResponse:
    """右键菜单切状态。Plan 2 Task 6;原 /capability/{id}/override 简化版。"""
    cap_id = request.path_params["cap_id"]
    form = await request.form()
    status = form.get("status", "")
    if status not in {"lit", "wip", "todo"}:
        return HTMLResponse(f"invalid status: {status}", status_code=400)

    conn = open_db(DB_PATH)
    try:
        OverrideRepo(conn).upsert(cap_id, cast(CapabilityStatus, status), reason="right-click")
        SnapshotRepo(conn).invalidate()
    finally:
        conn.close()

    cfg = next(
        (c for c in load_capabilities(CONFIG_DIR / "capabilities.yaml") if c.id == cap_id),
        None,
    )
    if cfg is None:
        return HTMLResponse(f"unknown cap: {cap_id}", status_code=404)
    chip_ctx = {
        "request": request,
        "c": {
            "id": cfg.id,
            "name_cn": cfg.name_cn,
            "name_en": cfg.name_en,
            "status": status,
        },
    }
    return cast(HTMLResponse, templates.TemplateResponse("_capability_chip.html", chip_ctx))


async def post_refresh(_request: Request) -> StreamingResponse:
    """SSE 5-step pipeline。spec § 2.1 / § 2.4。

    Breaking change(v0.9.6):不再 302 redirect 到 /,改为 text/event-stream。
    """
    pipeline = RefreshPipeline(
        project_root=PROJECT_ROOT,
        config_dir=CONFIG_DIR,
        db_path=DB_PATH,
        seed_path=SEED_PATH,
    )

    async def _gen() -> AsyncIterator[bytes]:
        import time as _time

        t0 = _time.perf_counter()
        summary = {"done": 0, "skip": 0, "error": 0}
        snapshot_refreshed_at = ""
        async for ev in pipeline.stream():
            if ev.status in summary:
                summary[ev.status] += 1
            if ev.step == "snapshot_finalize" and ev.status == "done":
                # detail = "refreshed_at <iso>"
                snapshot_refreshed_at = ev.detail.replace("refreshed_at ", "", 1)
            payload = json.dumps(asdict(ev), ensure_ascii=False)
            yield f"event: step\ndata: {payload}\n\n".encode()
        total_ms = int((_time.perf_counter() - t0) * 1000)
        done_payload = json.dumps(
            {
                "total_ms": total_ms,
                "snapshot_refreshed_at": snapshot_refreshed_at,
                "steps_summary": summary,
            },
            ensure_ascii=False,
        )
        yield f"event: done\ndata: {done_payload}\n\n".encode()

    return StreamingResponse(_gen(), media_type="text/event-stream")


async def _build_milvus_client() -> object:
    """lazy Milvus init,失败抛 ConnectionError。"""
    if not MILVUS_HOST:
        raise ConnectionError("MILVUS_HOST not set")
    from dashboard.state.milvus_collection import DeepCardMilvusClient

    client = DeepCardMilvusClient(host=MILVUS_HOST, port=MILVUS_PORT)
    await client.ensure_collection()
    return client


async def _build_embedder() -> object:
    from app.services.embedding_factory import build_embedding_service_from_env

    return build_embedding_service_from_env()


async def _try_milvus_related(cap_id: str, k: int) -> tuple[list[dict[str, object]] | None, str]:
    """尝试 Milvus 查询 → top_k 相关 cap。失败返回 (None, reason) 让调用者 fallback。"""
    if MILVUS_HOST is None:
        return None, "milvus_disabled"
    try:
        from dashboard.state.milvus_collection import embedding_text

        client = await _build_milvus_client()
        embedder = await _build_embedder()

        conn = open_db(DB_PATH)
        try:
            pivot = DeepCardRepo(conn).get(cap_id)
        finally:
            conn.close()
        if pivot is None:
            return None, "no_pivot_card"

        caps_cfg = load_capabilities(CONFIG_DIR / "capabilities.yaml")
        name_cn = next((c.name_cn for c in caps_cfg if c.id == cap_id), "")
        text = embedding_text(pivot, name_cn=name_cn)
        vec = (await embedder.embed([text]))[0]  # type: ignore[attr-defined]
        hits = await client.search(vec, top_k=k + 1)  # type: ignore[attr-defined]
        # filter self
        hits = [h for h in hits if h["cap_id"] != cap_id][:k]
        return hits, "ok"
    except Exception as e:  # noqa: BLE001
        logger.warning("Milvus related fallback: %s", e)
        return None, f"milvus_error:{e}"


async def post_admin_milvus_reindex(_request: Request) -> JSONResponse:
    """全量 reindex — 显式触发 DeepCard → Milvus embedding 同步。"""
    if MILVUS_HOST is None:
        return JSONResponse({"error": "milvus disabled"}, status_code=503)
    from dashboard.state.milvus_collection import embedding_text

    client = await _build_milvus_client()
    embedder = await _build_embedder()

    conn = open_db(DB_PATH)
    try:
        cards = DeepCardRepo(conn).get_all()
    finally:
        conn.close()

    caps_cfg = load_capabilities(CONFIG_DIR / "capabilities.yaml")
    name_by_id = {c.id: c.name_cn for c in caps_cfg}

    rows: list[dict[str, object]] = []
    texts: list[str] = []
    for card in cards:
        name_cn = name_by_id.get(card.cap_id, "")
        text = embedding_text(card, name_cn=name_cn)
        texts.append(text)
        rows.append(
            {
                "cap_id": card.cap_id,
                "dimension": (card.cap_id.split(".", 1)[0] if "." in card.cap_id else ""),
                "name_cn": name_cn,
                "status": "lit",
            }
        )
    if texts:
        vecs = await embedder.embed(texts)  # type: ignore[attr-defined]
        for r, v in zip(rows, vecs, strict=True):
            r["embedding"] = v
        await client.upsert(rows)  # type: ignore[attr-defined]
    return JSONResponse({"upserted": len(rows)})


ALLOWED_EDITABLE_FIELDS = {
    "what",
    "why",
    "tradeoff",
    "lessons_learned",
    "chosen_alternative",
}


def _get_llm_service() -> object:
    """lazy build LLMService — 测试可 patch。返回 LLMService(避免顶层 import)。"""
    from app.services.openai_client import build_llm_service_from_env

    return build_llm_service_from_env()


def _render_deep_card_field(cap_id: str, field_name: str) -> HTMLResponse:
    """重 render 单字段 partial(POST 后 htmx swap)。"""
    conn = open_db(DB_PATH)
    try:
        card = DeepCardRepo(conn).get(cap_id)
    finally:
        conn.close()
    if card is None:
        return HTMLResponse("<div class='error'>card lost</div>", status_code=500)
    prov = card.provenance.get(field_name)
    template = templates.get_template("_deep_card_field.html")
    html = template.render(
        cap={"id": cap_id},
        field={
            "field": field_name,
            "value": getattr(card, field_name),
            "provenance": prov,
            "source": card.prefill_source,
        },
    )
    return HTMLResponse(html)


async def post_field_update(request: Request) -> HTMLResponse:
    """POST /cap/{cap_id}/field/{field} — V2 inline 编辑保存。"""
    cap_id = request.path_params["cap_id"]
    field = request.path_params["field"]
    if field not in ALLOWED_EDITABLE_FIELDS:
        return HTMLResponse(
            f"<div class='error'>field not editable: {field}</div>", status_code=400
        )
    form = await request.form()
    value_raw = form.get("value", "")
    if not isinstance(value_raw, str):
        return HTMLResponse("value must be str", status_code=400)
    conn = open_db(DB_PATH)
    try:
        DeepCardRepo(conn).update_field(cap_id, field, value_raw.strip())
    finally:
        conn.close()
    return _render_deep_card_field(cap_id, field)


async def deep_card_modal(request: Request) -> HTMLResponse:
    """GET /cap/{cap_id} — V2 模块深读 modal HTML 片段(htmx swap into overlay)。"""
    cap_id = request.path_params["cap_id"]
    caps_cfg = load_capabilities(CONFIG_DIR / "capabilities.yaml")
    cfg = next((c for c in caps_cfg if c.id == cap_id), None)
    if cfg is None:
        return HTMLResponse(f"<div class='error'>cap not found: {cap_id}</div>", status_code=404)

    conn = open_db(DB_PATH)
    try:
        card = DeepCardRepo(conn).get(cap_id)
    finally:
        conn.close()

    derived_status = resolve_status(cfg, PROJECT_ROOT)
    cap = {
        "id": cfg.id,
        "name_cn": cfg.name_cn,
        "status": derived_status,
        "dimension": cfg.dimension,
    }

    content_fields: list[dict[str, object]] = []
    for f in (
        "what",
        "why",
        "alternatives",
        "chosen_alternative",
        "tradeoff",
        "lessons_learned",
    ):
        value = getattr(card, f, None) if card else None
        prov = card.provenance.get(f) if (card and card.provenance) else None
        content_fields.append(
            {
                "field": f,
                "value": value,
                "provenance": prov,
                "source": card.prefill_source if card else "manual",
            }
        )
    template = templates.get_template("_deep_card_modal.html")
    html = template.render(cap=cap, deep_card=card, content_fields=content_fields)
    return HTMLResponse(html)


def _extract_commit_times_for_caps(caps_cfg: list[object]) -> dict[str, str]:
    """对所有 cap 抽 git log 首个 commit time。

    spec § 5.4 fallback chain;Plan 3 改为后台 job + cache。
    单独函数以便测试 monkeypatch 跳过。
    """
    from dashboard.derive.commit_time_extractor import extract_cap_commit_time

    out: dict[str, str] = {}
    for cap_cfg in caps_cfg:
        # duck-typed:caps_cfg 是 CapabilityConfig list
        cap_id = getattr(cap_cfg, "id", None)
        rule = getattr(cap_cfg, "derive_rule", None)
        if cap_id is None or rule is None:
            continue
        ts = extract_cap_commit_time(rule, cwd=PROJECT_ROOT)
        if ts:
            out[cap_id] = ts
    return out


async def story_view(request: Request) -> HTMLResponse:
    """V4 故事时间线主页 — 三段式卡片流。spec § 5.4。"""
    from dashboard.derive.story_builder import build_story_cards

    qp = request.query_params
    dims = qp.getlist("dim")
    selected_dims: set[str] | None = set(dims) if dims else None
    time_after = qp.get("after") or None
    time_before = qp.get("before") or None
    order = qp.get("order", "asc")

    main_dims, _ = load_dimensions(CONFIG_DIR / "dimensions.yaml")
    caps_cfg = load_capabilities(CONFIG_DIR / "capabilities.yaml")

    # 抽 commit_time(可缓存,Plan 3 改为后台 job;Plan 2 每次现抽)
    commit_times = _extract_commit_times_for_caps(list(caps_cfg))

    snap = _get_or_build_snapshot()
    all_caps: list[Capability] = []
    for layer in snap["layers"]:
        for cd in layer["capabilities"]:
            all_caps.append(
                Capability(
                    id=cd["id"],
                    dimension=cd["dimension"],
                    name_cn=cd["name_cn"],
                    name_en=cd["name_en"],
                    status=cd["status"],
                    derived_status=cd["derived_status"],
                )
            )

    conn = open_db(DB_PATH)
    try:
        cards = DeepCardRepo(conn).get_all()
    finally:
        conn.close()

    stories = build_story_cards(
        all_caps,
        cards,
        commit_times=commit_times,
        filter_dimensions=selected_dims,
        time_after=time_after,
        time_before=time_before,
        order=order,
    )
    template = templates.get_template("story.html")
    return HTMLResponse(
        template.render(
            stories=stories,
            dimensions=main_dims,
            selected_dims=selected_dims or set(),
            time_after=time_after,
            time_before=time_before,
            order=order,
            active_nav="story",
        )
    )


async def survey_view(request: Request) -> HTMLResponse:
    """§ 06 Survey — 5 个外部 agent 项目的 harness trick 调研结果,按 8 维度分组。

    数据源 dashboard/data/external_agent_survey.jsonl,server 启动时 lru_cache 一次。
    """
    from dashboard.derive.survey_loader import group_by_dimension, load_survey, repo_summary

    survey_path = DASHBOARD_ROOT / "data" / "external_agent_survey.jsonl"
    tricks = load_survey(str(survey_path))
    main_dims, _ = load_dimensions(CONFIG_DIR / "dimensions.yaml")
    template = templates.get_template("survey.html")
    return HTMLResponse(
        template.render(
            dimensions=main_dims,
            tricks_by_dim=group_by_dimension(tricks),
            repos=repo_summary(tricks),
            active_nav="survey",
        )
    )


async def overview_view(request: Request) -> HTMLResponse:
    """V3 鸟瞰主页 — 渲染含 cytoscape 容器,数据由 /api/overview/graph.json 拉。"""
    main_dims, _ = load_dimensions(CONFIG_DIR / "dimensions.yaml")
    caps_cfg = load_capabilities(CONFIG_DIR / "capabilities.yaml")
    template = templates.get_template("overview.html")
    html = template.render(
        dimensions=main_dims,
        total_nodes=len(caps_cfg),
        active_nav="overview",
    )
    return HTMLResponse(html)


async def overview_graph_json(request: Request) -> JSONResponse:
    """V3 cytoscape 数据源。支持 ?dim=memory,prompt_context / ?status=lit / ?low_conf=1。"""
    from dashboard.derive.graph_builder import build_graph_payload

    qp = request.query_params
    filter_dims: set[str] | None = (
        {x for x in qp.get("dim", "").split(",") if x} if qp.get("dim") else None
    )
    filter_statuses: set[str] | None = (
        {x for x in qp.get("status", "").split(",") if x} if qp.get("status") else None
    )
    only_low_conf = qp.get("low_conf") == "1"

    snap = _get_or_build_snapshot()
    all_caps: list[Capability] = []
    for layer in snap["layers"]:
        for c_dict in layer["capabilities"]:
            all_caps.append(
                Capability(
                    id=c_dict["id"],
                    dimension=c_dict["dimension"],
                    name_cn=c_dict["name_cn"],
                    name_en=c_dict["name_en"],
                    status=c_dict["status"],
                    derived_status=c_dict["derived_status"],
                )
            )

    conn = open_db(DB_PATH)
    try:
        cards = DeepCardRepo(conn).get_all()
    finally:
        conn.close()

    payload = build_graph_payload(
        all_caps,
        cards,
        filter_dimensions=filter_dims,
        filter_statuses=filter_statuses,
        only_low_confidence=only_low_conf,
    )
    return JSONResponse(payload)


async def overview_fallback(request: Request) -> HTMLResponse:
    """V3 cytoscape 加载失败兜底 — 维度卡片墙。"""
    main_dims, _ = load_dimensions(CONFIG_DIR / "dimensions.yaml")
    caps_cfg = load_capabilities(CONFIG_DIR / "capabilities.yaml")
    by_dim: dict[str, list[dict[str, str]]] = {d.id: [] for d in main_dims}
    for c in caps_cfg:
        by_dim.setdefault(c.dimension, []).append({"id": c.id, "name_cn": c.name_cn})
    dims_with_caps = [
        {
            "id": d.id,
            "number": d.number,
            "name_cn": d.name_cn,
            "capabilities": by_dim.get(d.id, []),
        }
        for d in main_dims
    ]
    template = templates.get_template("overview_fallback.html")
    return HTMLResponse(template.render(dimensions_with_caps=dims_with_caps, active_nav="overview"))


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

    milvus_result, _reason = await _try_milvus_related(cap_id, k)
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


@asynccontextmanager
async def lifespan(_app: Starlette) -> AsyncIterator[None]:
    """startup:db DeepCard 数 < seed 总数时 insert-if-missing 跑一次。spec § 2.5。"""
    try:
        SeedIngestService(
            seed_path=SEED_PATH,
            db_path=DB_PATH,
            config_dir=CONFIG_DIR,
        ).run_once_if_underfilled()
    except Exception as e:  # noqa: BLE001
        logger.warning("lifespan seed ingest skipped due to: %s", e)
    yield


app = Starlette(
    routes=[
        Route("/", index),
        Route("/m/{dim_id}", module_page_view),
        Route("/healthz", healthz),
        Route("/decisions", decisions_view),
        Route("/decisions/{decision_id}/note", post_decision_note, methods=["POST"]),
        Route("/decisions/{decision_id}/note", delete_decision_note, methods=["DELETE"]),
        Route("/capability/{cap_id}/edit", edit_capability),
        Route("/capability/{cap_id}/override", post_override, methods=["POST"]),
        Route("/refresh", post_refresh, methods=["GET"]),
        Route("/overview", overview_view),
        Route("/overview/fallback", overview_fallback),
        Route("/api/overview/graph.json", overview_graph_json),
        Route("/story", story_view),
        Route("/survey", survey_view),
        Route("/cap/{cap_id}", deep_card_modal, methods=["GET"]),
        Route("/cap/{cap_id}/status", post_status, methods=["POST"]),
        Route("/cap/{cap_id}/related", related_capabilities, methods=["GET"]),
        Route("/cap/{cap_id}/field/{field}", post_field_update, methods=["POST"]),
        Route(
            "/admin/milvus/reindex",
            post_admin_milvus_reindex,
            methods=["POST"],
        ),
        Mount(
            "/static",
            StaticFiles(directory=str(DASHBOARD_ROOT / "static")),
            name="static",
        ),
    ],
    lifespan=lifespan,
)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8910, log_level="info")

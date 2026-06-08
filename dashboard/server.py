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

from dashboard.derive.capability_resolver import load_capabilities, resolve_status
from dashboard.derive.path_router import load_dimensions
from dashboard.derive.refresh_pipeline import RefreshPipeline
from dashboard.derive.seed_ingest import SeedIngestService
from dashboard.derive.snapshot_builder import build_snapshot
from dashboard.derive.types import Capability, CapabilityStatus, SnapshotDict
from dashboard.state.db import open_db
from dashboard.state.keyword_recommender import recommend_by_keyword
from dashboard.state.repositories import (
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

# 维度页 → 挂在该 ETCLOVG 维度下的深度调研报告。
# 「调研/综述」体裁(讲某件事*怎么做*)归到它论述的维度页,而非 /eval(那是评估方法论)。
# 报告本体仍由 report_view 在 /eval/report/<slug> 渲染(genre-neutral),这里只是入口归位。
DIMENSION_REPORTS: dict[str, tuple[dict[str, str], ...]] = {
    "tool": (
        {
            "slug": "subagent-dispatch-survey",
            "title": "子 agent 派发 · 怎么做",
            "sub": "7 个派发设计决策,每个配真实场景 · 三大派系 + 学术理论,对照本项目编排 · 40+ 系统/论文调研 + 事实核查",
        },
        {
            "slug": "periphery-wiring-survey",
            "title": "Agent Loop 周边接线 · 怎么做",
            "sub": "7 个接线设计决策,每个配真实场景 · 万物皆工具的判据与例外 / 工具数量治理 / 信号工具 / 记忆双轨 / 技能渐进披露,对照本项目 chat 重设计草案 · 12 路调研 + 40+ 条事实核查",
        },
        {
            "slug": "post-training-rl-survey",
            "title": "LLM 后训练 · 什么时候必须上 RL,怎么落地",
            "sub": "7 个后训练设计决策,每个配真实场景 · 提示词/SFT/DPO/RL 判别标准 / 数据集构造 / 奖励设计与 reward hacking 攻防 / 五层评估 / verl+sglang 工程落地,5 张图例 + 对照本项目 LLM 调用面三档路线 · 两轮调研 + 19 条承重结论逐条复核",
        },
    ),
    "context": (
        {
            "slug": "context-engineering-survey",
            "title": "Agent Loop 上下文工程 · 怎么做",
            "sub": "7 个上下文工程设计决策,每个配真实场景 · KV-cache 前缀经济学 / 压缩与可回取 / 检索式记忆 / 中文 token 计数,对照本项目 chat 重设计草案 · 8 路调研 + 21 条事实核查",
        },
    ),
    "lifecycle": (
        {
            "slug": "chat-agent-loop-survey",
            "title": "Chat 模式 Agent Loop · 怎么做",
            "sub": "7 个 chat-loop 设计决策,每个配真实场景 · 原生工具调用循环 / plan-execute / workflow-vs-agent 主轴,对照本项目 chat 子图循环 · 9 路调研 + 63 条事实核查",
        },
    ),
}

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

    # 下一步 ›:按成熟度(lit/total)升序排维度,各取首个 todo cap → "最该补的方向"。J1 前瞻。
    next_gaps: list[dict[str, object]] = []
    for layer in snap["layers"]:
        todos = [c for c in layer["capabilities"] if c["status"] == "todo"]
        if todos:
            next_gaps.append(
                {
                    "dim_id": layer["id"],
                    "name_cn": layer["name_cn"],
                    "lit": layer["lit"],
                    "total": layer["total"],
                    "cap": todos[0],
                }
            )
    next_gaps.sort(key=lambda g: (g["lit"] / g["total"]) if g["total"] else 0.0)  # type: ignore[operator]
    next_gaps = next_gaps[:4]

    # Plan 3 Task 2 — Topology data
    from dashboard.derive.topology_layout import (
        connection_endpoints,
        layout_with_progress,
    )

    topology_modules = layout_with_progress(snap["layers"])
    topology_endpoints = connection_endpoints({m.dim_id: m for m in topology_modules})

    ctx: dict[str, object] = {
        "today": _today_label(),
        "snap": snap,
        "wips": wips,
        "next_gaps": next_gaps,
        "view_mode": view_mode,
        "active_view": view_mode,  # M3:同 view_mode("d" 或 "b"),decisions 用独立 route 不走这
        "active_nav": "grid",
        "topology_modules": topology_modules,
        "topology_endpoints": topology_endpoints,
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
        "reports": DIMENSION_REPORTS.get(dim_id, ()),
        "asset_v": ASSET_VERSION,
    }
    return cast(HTMLResponse, templates.TemplateResponse("_module_page.html", ctx))


async def healthz(_request: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


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


async def post_screenshot(request: Request) -> JSONResponse:
    """图上传 endpoint。Plan 2 Task 9。"""
    from starlette.datastructures import UploadFile as StarletteUploadFile

    from dashboard.derive.screenshot_repo import UploadError, save_screenshot

    cap_id = request.path_params["cap_id"]
    form = await request.form()
    upload_raw = form.get("file")
    if not isinstance(upload_raw, StarletteUploadFile):
        return JSONResponse({"error": "no file uploaded"}, status_code=400)
    upload: StarletteUploadFile = upload_raw

    try:
        content = await upload.read()
        result = save_screenshot(
            DASHBOARD_ROOT,
            cap_id,
            content,
            upload.content_type or "",
            upload.filename or "image.png",
        )
    except UploadError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    return JSONResponse(
        {
            "path": result.rel_path,
            "markdown": result.markdown,
            "git_hint": result.git_hint,
        }
    )


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


async def cap_expand(request: Request) -> HTMLResponse:
    """单击 capability chip — 返回 6 字段 inline fragment。Plan 2 Task 7。"""
    cap_id = request.path_params["cap_id"]
    cfg = next(
        (c for c in load_capabilities(CONFIG_DIR / "capabilities.yaml") if c.id == cap_id),
        None,
    )
    if cfg is None:
        return HTMLResponse(f"unknown cap: {cap_id}", status_code=404)

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

    ctx = {"request": request, "cap": cap, "card": card}
    return cast(HTMLResponse, templates.TemplateResponse("_deep_card_inline.html", ctx))


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


EVAL_SYSTEM_PATH = CONFIG_DIR / "eval_system.yaml"
REPORTS_DIR = DASHBOARD_ROOT / "data" / "reports"
# slug 白名单:小写字母 / 数字 / 连字符 —— 挡路径穿越。
_SLUG_OK: frozenset[str] = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-")


async def eval_view(request: Request) -> HTMLResponse:
    """GET /eval — 子系统 × 评估层级 覆盖矩阵。数据驱动自 eval_system.yaml。

    论文 §8 Verification & Evaluation;"没有评估就没有优化"。
    纯渲染:不依赖 DB / snapshot,只读 yaml(SSOT)。
    """
    from dashboard.derive.eval_matrix import load_eval_matrix, matrix_summary

    matrix = load_eval_matrix(EVAL_SYSTEM_PATH)
    summary = matrix_summary(matrix)
    template = templates.get_template("eval.html")
    return HTMLResponse(
        template.render(
            matrix=matrix,
            summary=summary,
            active_nav="eval",
        )
    )


async def report_view(request: Request) -> HTMLResponse:
    """GET /eval/report/{slug} — 长文研究报告。数据驱动自 data/reports/<slug>.yaml。

    纯渲染:不依赖 DB / snapshot,只读 yaml(SSOT)。slug 走白名单挡路径穿越。
    """
    from dashboard.derive.report import load_report

    slug = request.path_params["slug"]
    if not slug or set(slug) - _SLUG_OK:
        return HTMLResponse(f"bad report slug: {slug!r}", status_code=400)
    path = REPORTS_DIR / f"{slug}.yaml"
    if not path.is_file():
        return HTMLResponse(f"report not found: {slug}", status_code=404)

    report = load_report(path)
    template = templates.get_template("report.html")
    return HTMLResponse(template.render(report=report, active_nav="eval"))


async def eval_cell_expand(request: Request) -> HTMLResponse:
    """GET /eval/cell/{subsystem}/{layer} — 单格展开 fragment(htmx swap)。"""
    from dashboard.derive.eval_matrix import load_eval_matrix

    subsystem_id = request.path_params["subsystem"]
    layer_id = request.path_params["layer"]

    matrix = load_eval_matrix(EVAL_SYSTEM_PATH)
    layer = next((layer for layer in matrix.layers if layer.id == layer_id), None)
    if layer is None:
        return HTMLResponse(f"unknown layer: {layer_id}", status_code=404)
    subsystem = next((s for s in matrix.subsystems if s.id == subsystem_id), None)
    if subsystem is None:
        return HTMLResponse(f"unknown subsystem: {subsystem_id}", status_code=404)
    cell = subsystem.cells.get(layer_id)
    if cell is None:
        return HTMLResponse(f"no cell for {subsystem_id}/{layer_id}", status_code=404)

    template = templates.get_template("_eval_cell_detail.html")
    return HTMLResponse(
        template.render(
            subsystem=subsystem,
            layer=layer,
            cell=cell,
            methods_detail=matrix.resolve_methods(cell),
        )
    )


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
        Route("/refresh", post_refresh, methods=["GET"]),
        Route("/story", story_view),
        Route("/eval", eval_view),
        Route("/eval/report/{slug}", report_view, methods=["GET"]),
        Route("/eval/cell/{subsystem}/{layer}", eval_cell_expand, methods=["GET"]),
        Route("/cap/{cap_id}/expand", cap_expand, methods=["GET"]),
        Route("/cap/{cap_id}/status", post_status, methods=["POST"]),
        Route("/cap/{cap_id}/screenshot", post_screenshot, methods=["POST"]),
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
        # 只读暴露 docs/(让 DeepCard 的 linked_specs 可点开)+ screenshots/(让上传图可显示)
        Mount(
            "/docs",
            StaticFiles(directory=str(PROJECT_ROOT / "docs")),
            name="docs",
        ),
        Mount(
            "/screenshots",
            StaticFiles(directory=str(DASHBOARD_ROOT / "screenshots")),
            name="screenshots",
        ),
    ],
    lifespan=lifespan,
)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8910, log_level="info")

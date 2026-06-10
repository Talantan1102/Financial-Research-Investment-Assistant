"""POST/GET/DELETE /reports — 研报 CRUD + SSE stream endpoints (v0.9.x).

设计 ref: docs/superpowers/specs/2026-05-06-v0.9.x-frontend-rebuild-design.md § 7.2

Endpoints (router prefix = "/reports", frontend proxies via /api → /reports):

  POST   /reports                  — 启动新研报,创建 placeholder (status=streaming),返回 id
  GET    /reports?page=1&page_size=20 — 当前 user 的历史列表 (paginated)
  GET    /reports/{report_id}      — 单条研报详情 (404/403 隔离 enforcement)
  GET    /reports/{report_id}/stream — SSE 订阅 (Task 9 — 7 events + db 写回)
  DELETE /reports/{report_id}      — 硬删 (204)

Auth:
  使用 get_current_user_required (JWT-based) 而非 v0 stub auth_helpers.get_current_user。
  原因:本 endpoint 强 user-isolation,需要真 user.id (UUID) 而非 'anonymous' 通配。
  v0 stub 仍由 chat/research v0 路径继续使用,本 router 不影响。
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agents.schemas import ResearchRequest
from app.core.database import SessionLocal, get_db
from app.models.research_report import ResearchReport
from app.models.user import User
from app.router.auth_helpers import _AnonUser
from app.router.auth_router import get_current_user_required
from app.router.research import _stream_research, get_research_graph

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["reports-v0.9"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class ReportListItem(BaseModel):
    """list endpoint 返回的精简条目 — 不含完整 report_json,只挑最常显示的字段."""

    id: str
    target_name: str
    target_ts_code: str | None
    status: str
    cost: float
    created_at: datetime
    investment_recommendation: str | None  # legacy 评级;去推荐后新报告恒为 None(仅历史报告有值)


class ReportListResponse(BaseModel):
    items: list[ReportListItem]
    total: int
    page: int
    page_size: int


class ReportDetailResponse(BaseModel):
    """get-by-id endpoint 返回的完整数据."""

    id: str
    target_name: str
    target_ts_code: str | None
    status: str
    cost: float
    created_at: datetime
    updated_at: datetime
    request_id: str | None
    report_json: dict[str, Any]


class ReportStartRequest(BaseModel):
    target_name: str = Field(..., min_length=1, max_length=128)
    target_ts_code: str | None = Field(None, max_length=16)
    research_style: str = Field("comprehensive", max_length=32)


class ReportStartResponse(BaseModel):
    id: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_recommendation(report_json: Any) -> str | None:
    """从 report_json 里挖 investment_recommendation.recommendation 字段(legacy).

    去推荐改造(2026-06-04)后,新报告 § 6 为 investment_synthesis(无评级字段),
    此处对新报告将返回 None;仅历史报告(去推荐前生成)仍能挖出旧评级。
    streaming 中 report_json 可能空 dict 或缺 key, 同样返回 None.
    """
    if not isinstance(report_json, dict):
        return None
    rec_block = report_json.get("investment_recommendation")
    if not isinstance(rec_block, dict):
        return None
    rec = rec_block.get("recommendation")
    return rec if isinstance(rec, str) else None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=ReportListResponse)
async def list_reports(
    user: Annotated[User, Depends(get_current_user_required)],
    db: Annotated[Session, Depends(get_db)],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> ReportListResponse:
    """当前 user 的历史研报, 倒序 paginated."""
    q = db.query(ResearchReport).filter(ResearchReport.user_id == user.id)
    total = q.count()
    rows = (
        q.order_by(ResearchReport.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [
        ReportListItem(
            id=str(r.id),
            target_name=r.target_name,
            target_ts_code=r.target_ts_code,
            status=r.status,
            cost=float(r.cost) if r.cost is not None else 0.0,
            created_at=r.created_at,
            investment_recommendation=_extract_recommendation(r.report_json),
        )
        for r in rows
    ]
    return ReportListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/{report_id}", response_model=ReportDetailResponse)
async def get_report(
    report_id: str,
    user: Annotated[User, Depends(get_current_user_required)],
    db: Annotated[Session, Depends(get_db)],
) -> ReportDetailResponse:
    """单条研报详情 — 404 if not found, 403 if 不属于当前 user."""
    r = db.query(ResearchReport).filter(ResearchReport.id == report_id).first()
    if r is None:
        raise HTTPException(status_code=404, detail="Report not found")
    if r.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your report")
    return ReportDetailResponse(
        id=str(r.id),
        target_name=r.target_name,
        target_ts_code=r.target_ts_code,
        status=r.status,
        cost=float(r.cost) if r.cost is not None else 0.0,
        created_at=r.created_at,
        updated_at=r.updated_at,
        request_id=r.request_id,
        report_json=r.report_json or {},
    )


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_report(
    report_id: str,
    user: Annotated[User, Depends(get_current_user_required)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """硬删研报 — 简化, 不做软删. 204 on success."""
    r = db.query(ResearchReport).filter(ResearchReport.id == report_id).first()
    if r is None:
        raise HTTPException(status_code=404, detail="Report not found")
    if r.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your report")
    db.delete(r)
    db.commit()


@router.post(
    "",
    response_model=ReportStartResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_report(
    payload: ReportStartRequest,
    user: Annotated[User, Depends(get_current_user_required)],
    db: Annotated[Session, Depends(get_db)],
) -> ReportStartResponse:
    """启动新研报 — 创建 placeholder row (status='streaming'), 返回 id 给前端订阅 SSE.

    SSE stream 的实际生成 + report_json 写回在 Task 9 实现.
    本 endpoint 只创建 row, 不调用 LLM / orchestration.
    """
    report_id = str(uuid4())
    # SQLAlchemy + PG-only: user.id 是 UUID 实例.
    # 直接传给 column 即可.
    user_id_val: UUID | str | None = user.id
    r = ResearchReport(
        id=report_id,
        user_id=user_id_val,
        target_name=payload.target_name,
        target_ts_code=payload.target_ts_code,
        status="streaming",
        report_json={},
    )
    db.add(r)
    db.commit()
    return ReportStartResponse(id=report_id)


# ---------------------------------------------------------------------------
# GET /reports/{id}/stream — SSE 订阅 + db 写回 (Task 9)
# ---------------------------------------------------------------------------


# v0.8.4 ResearchRequest 默认值 — 当 ReportStartRequest 未带完整投资上下文时用.
# Best-effort: streaming 启动需要 6 个结构化字段, 但 ReportStartRequest 只收 target_name +
# target_ts_code. 这里给中性默认 (balanced / medium_term / moderate),后续 v0.9.y 应:
#   1. ReportStartRequest 扩展接收完整 ResearchRequest 字段
#   2. ResearchReport 表增加列存这些字段
#   3. /stream 启动时从 row 还原, 而非用默认值
# 见 DONE_WITH_CONCERNS.
_DEFAULT_AUM = 50_000_000.0  # 5000 万 — 中等机构客户
_DEFAULT_OBJECTIVE = "balanced"
_DEFAULT_HORIZON = "medium_term"
_DEFAULT_RISK = "moderate"


@router.get("/{report_id}/stream")
async def stream_report(
    report_id: str,
    user: Annotated[User, Depends(get_current_user_required)],
    db: Annotated[Session, Depends(get_db)],
    graph: Annotated[Any, Depends(get_research_graph)],
) -> StreamingResponse:
    """订阅指定研报的 SSE 流;完成时把 report_json + cost 写回 db.

    流程:
      1. find ResearchReport by id (404 if not exists)
      2. verify user_id 隔离 (403 if not yours)
      3. 复用 v0.5 _stream_research async generator (mock or real graph)
      4. wrap with _stream_research_with_persist:并行 yield SSE + 累积 final_report
      5. on `done` event:写回 db (status='completed', cost, request_id)
      6. on `error` event 或异常:status='failed' + report_json={'error': ...}

    Best-effort 决策:
      - ResearchRequest 6 字段中 target_name → target_ts_code (用 row 上的或 row.target_name)
        + 4 字段用 _DEFAULT_* 中性值;v0.9.y 扩展存储完整 context 后取消默认.
      - 7 event types 与 v0.8.4 兼容 (plan/data_progress/insight/report_chunk/critic_score/done/error).
    """
    r = db.query(ResearchReport).filter(ResearchReport.id == report_id).first()
    if r is None:
        raise HTTPException(status_code=404, detail="Report not found")
    if r.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your report")

    # ResearchRequest 需要 target_ts_code (required) — fallback 到 target_name
    # 当 row 没有 ts_code 时(虽然实际 frontend 总传 ts_code).
    ts_code: str = r.target_ts_code or r.target_name
    req = ResearchRequest(
        target_ts_code=ts_code,
        client_total_aum=_DEFAULT_AUM,
        investment_objective=_DEFAULT_OBJECTIVE,
        investment_horizon=_DEFAULT_HORIZON,
        risk_tolerance=_DEFAULT_RISK,
        user_message=f"研究 {r.target_name}",
    )

    # _stream_research 期望 _AnonUser 类型, 但 user.id 是 UUID; 包成 _AnonUser-like
    # (它只用 .id 字段). 直接传 user 也可,因为 _AnonUser 是 duck-typed.
    return StreamingResponse(
        _stream_research_with_persist(req, user, graph, r, db),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _stream_research_with_persist(
    req: ResearchRequest,
    user: User | _AnonUser,
    graph: Any,
    report: ResearchReport,
    db: Session,
) -> AsyncIterator[str]:
    """Wrap _stream_research,完成时把 final report_json + cost + status 写 db.

    Event 解析约定:
      - SSE line format: ``data: <json>\\n\\n`` (与 _stream_research 输出一致)
      - report_chunk event: data.chunk = full markdown — 累积进 report_json["report_markdown"]
      - critic_score event (scorer=aggregate): data.scores + data.overall — 存入 report_json
      - done event: data.request_id — 写 status='completed' + final report_json
      - error event 或异常: status='failed' + report_json={'error': ...}

    cost 累计:_stream_research 当前 event payload 不含 cost (LLM cost 在 TraceService 里).
    v0.9.y 接入 TraceService 后从 trace 表 SELECT SUM(cost) WHERE request_id = ... 算.
    本 task 把 cost 留 0; 见 DONE_WITH_CONCERNS.
    """
    # _AnonUser 风格(只读 .id)— _stream_research 期望它能拿 .id.
    # User (sqlalchemy) 也有 .id, duck-type 兼容.
    final_report: dict[str, Any] = {}
    request_id: str | None = None
    stream_failed = False

    try:
        async for sse_line in _stream_research(req, user, graph):  # type: ignore[arg-type]
            yield sse_line

            # 解析 event 用于 累积 final_report / 抓 done event
            try:
                # SSE line: 'data: {...}\n\n' — 取 data: 后到第一个 \n
                stripped = sse_line.strip()
                if not stripped.startswith("data: "):
                    continue
                json_part = stripped[len("data: ") :]
                event = json.loads(json_part)
            except (json.JSONDecodeError, ValueError):
                continue

            event_type = event.get("type")
            event_data = event.get("data", {}) or {}

            if event_type == "report_chunk":
                # report_chunk.data.chunk 是 full markdown
                chunk = event_data.get("chunk")
                if isinstance(chunk, str) and chunk:
                    final_report["report_markdown"] = chunk

            elif event_type == "critic_score":
                # 仅 aggregate scorer 带 final scores
                if event_data.get("scorer") == "aggregate":
                    final_report["critic_scores"] = event_data.get("scores") or {}
                    final_report["critic_overall"] = event_data.get("overall") or 0.0

            elif event_type == "done":
                request_id = event_data.get("request_id") or request_id
                # v0.9.x fix: SSE event 累积只能拿到 markdown 字符串和 critic 评分,
                # 6 节结构化 InvestmentDueDiligenceReport 在 _RUN_RESULTS_CACHE 里
                # (writer_node 完成时由 research.py 写入). merge 进 final_report
                # 让前端 ReportCanvas + EvidenceSidebar 能拿到 target_overview /
                # financial_analysis 等 6 节字段渲染.
                if request_id:
                    from app.router.research import _RUN_RESULTS_CACHE

                    structured = _RUN_RESULTS_CACHE.get(request_id)
                    if isinstance(structured, dict):
                        final_report = {**structured, **final_report}

            elif event_type == "error":
                # error event 来自 _stream_research 的 except 分支
                stream_failed = True
                final_report = {"error": str(event_data.get("message", ""))}
                break

    except Exception as e:
        # 流被未捕获异常中断 — 也算 failed
        logger.exception("stream_report inner generator raised")
        stream_failed = True
        final_report = {"error": str(e)}
        # 不重 raise, 把 status 写 db 后正常返回(SSE response 已经 yield 出去了)

    # 完成时回写 db.  best-effort: 即使 final_report 为空, 至少把 status 写对.
    try:
        if stream_failed:
            report.status = "failed"  # type: ignore[assignment]
            report.report_json = final_report  # type: ignore[assignment]
        else:
            report.status = "completed"  # type: ignore[assignment]
            report.report_json = final_report  # type: ignore[assignment]
            if request_id:
                report.request_id = request_id  # type: ignore[assignment]
            # cost 累计待 v0.9.y TraceService 接入;此处保持 row 默认 0.
            report.cost = report.cost or Decimal("0")  # type: ignore[assignment]
        db.commit()
    except Exception:
        # C70: db.commit() failed; rollback the tainted session first, then
        # rescue the row via a *fresh* SessionLocal so it does not stay
        # status='streaming' forever (no stale-scanner covers research_reports).
        logger.exception("Failed to persist research report %s after stream", report.id)
        db.rollback()
        try:
            rescue_db = SessionLocal()
            try:
                rescue_db.execute(
                    text(
                        "UPDATE research_reports"
                        " SET status = 'failed'"
                        " WHERE id = :id AND status = 'streaming'"
                    ),
                    {"id": report.id},
                )
                rescue_db.commit()
            finally:
                rescue_db.close()
        except Exception:
            logger.exception(
                "Rescue UPDATE also failed for research report %s; row may be stuck 'streaming'",
                report.id,
            )

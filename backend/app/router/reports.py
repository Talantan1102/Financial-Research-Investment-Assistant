"""POST/GET/DELETE /reports — 研报 CRUD endpoints (v0.9.x).

设计 ref: docs/superpowers/specs/2026-05-06-v0.9.x-frontend-rebuild-design.md § 7.2

Endpoints (router prefix = "/reports", frontend proxies via /api → /reports):

  POST   /reports                — 启动新研报,创建 placeholder (status=streaming),返回 id
  GET    /reports?page=1&page_size=20 — 当前 user 的历史列表 (paginated)
  GET    /reports/{report_id}    — 单条研报详情 (404/403 隔离 enforcement)
  DELETE /reports/{report_id}    — 硬删 (204)

Auth:
  使用 get_current_user_required (JWT-based) 而非 v0 stub auth_helpers.get_current_user。
  原因:本 endpoint 强 user-isolation,需要真 user.id (UUID) 而非 'anonymous' 通配。
  v0 stub 仍由 chat/research v0 路径继续使用,本 router 不影响。

SSE stream endpoint 在 Task 9 写,此处只负责 CRUD。
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.research_report import ResearchReport
from app.models.user import User
from app.router.auth_router import get_current_user_required

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
    investment_recommendation: str | None  # 从 report_json 提取(可能 None — streaming 中)


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
    """从 report_json 里挖 investment_recommendation.recommendation 字段.

    InvestmentDueDiligenceReport schema 形如:
      {"investment_recommendation": {"recommendation": "Buy/Hold/Sell", ...}, ...}
    streaming 中 report_json 可能空 dict 或缺 key, 返回 None.
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
    # SQLAlchemy + SQLite/with_variant: user.id 是 UUID 实例 (PG) 或 str (SQLite via with_variant).
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

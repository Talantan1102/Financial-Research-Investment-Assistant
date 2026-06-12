"""Portfolio router — v1.0 持仓监控 REST API(Trade CRUD + Position read + Onboarding)。

Endpoints:
  POST   /portfolio/trades        — 单笔 trade 录入(initial / buy / sell)
  DELETE /portfolio/trades/{id}   — 24h 内删除(spec § 3.3)
  PATCH  /portfolio/trades/{id}   — initial trade 字段更新
  GET    /portfolio/positions     — 当前 user 的全部 positions(Task 11)
  POST   /portfolio/onboarding    — 批量录入 initial trades(Task 11)

Auth: get_current_user_required(JWT,跟 reports.py 同模式)。
错误:PortfolioError 子类映射到 409 Conflict。

注意:使用 async def 避免 anyio 将 sync 端点放入 threadpool,
保证测试 / 生产中 SQLAlchemy Session 的 same-thread 约束不被违反。
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.trade import Trade, TradeType
from app.models.user import User
from app.router.auth_router import get_current_user_required
from app.schemas.portfolio import (
    OnboardingRequest,
    OnboardingResponse,
    OverviewRead,
    PositionRead,
    TradeCreate,
    TradeRead,
    TradeUpdate,
    TrendRead,
)
from app.services.portfolio_analytics import DailySnap, compute_twr
from app.services.portfolio_exceptions import (
    ExpiredDeletionError,
    ImmutableTradeError,
    PortfolioError,
)
from app.services.portfolio_narrator import narrate_today
from app.services.portfolio_overview_service import build_overview
from app.services.position_service import PositionService
from app.services.position_snapshot_repo import PositionSnapshotRepo
from app.services.trade_service import TradeService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/portfolio", tags=["portfolio-v1.0"])


@router.post(
    "/trades",
    response_model=TradeRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_trade(
    payload: TradeCreate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
) -> TradeRead:
    svc = TradeService(db)
    try:
        trade = svc.create(
            user_id=str(user.id),  # type: ignore[arg-type]
            ts_code=payload.ts_code,
            name=payload.name,
            ttype=TradeType(payload.type),
            quantity=payload.quantity,
            price=payload.price,
            trade_date=payload.trade_date,
            note=payload.note,
        )
        db.commit()
        db.refresh(trade)
        return TradeRead.model_validate(trade)
    except PortfolioError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete(
    "/trades/{trade_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_trade(
    trade_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
) -> None:
    svc = TradeService(db)
    try:
        svc.delete(trade_id, user_id=str(user.id))  # type: ignore[arg-type]
        db.commit()
    except NoResultFound:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trade not found")
    except ExpiredDeletionError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.patch("/trades/{trade_id}", response_model=TradeRead)
async def update_trade(
    trade_id: str,
    payload: TradeUpdate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
) -> TradeRead:
    svc = TradeService(db)
    fields = payload.model_dump(exclude_unset=True)
    try:
        trade = svc.update(trade_id, user_id=str(user.id), **fields)  # type: ignore[arg-type]
        db.commit()
        db.refresh(trade)
        return TradeRead.model_validate(trade)
    except NoResultFound:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trade not found")
    except ImmutableTradeError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/positions", response_model=list[PositionRead])
async def list_positions(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
) -> list[PositionRead]:
    svc = PositionService(db)
    positions = svc.list_for_user(str(user.id))  # type: ignore[arg-type]
    return [PositionRead.model_validate(p) for p in positions]


@router.post(
    "/onboarding",
    response_model=OnboardingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def onboarding(
    payload: OnboardingRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
) -> OnboardingResponse:
    """雪球做法:批量录入 INITIAL trade,all-or-nothing 单事务。"""
    # 严格只接受 initial type(雪球语义)
    for tc in payload.trades:
        if tc.type != "initial":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="onboarding 仅接受 type='initial' trades",
            )

    trade_svc = TradeService(db)
    pos_svc = PositionService(db)
    created_trades: list[Trade] = []
    try:
        for tc in payload.trades:
            trade = trade_svc.create(
                user_id=str(user.id),  # type: ignore[arg-type]
                ts_code=tc.ts_code,
                name=tc.name,
                ttype=TradeType(tc.type),
                quantity=tc.quantity,
                price=tc.price,
                trade_date=tc.trade_date,
                note=tc.note,
            )
            created_trades.append(trade)
            # 透传 asset_class → Position(默认 "stock",保持老调用零变化)
            pos = pos_svc.get(user_id=str(user.id), ts_code=tc.ts_code)  # type: ignore[arg-type]
            if pos is not None:
                pos.asset_class = tc.asset_class  # type: ignore[assignment]
        db.commit()
    except PortfolioError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    for t in created_trades:
        db.refresh(t)

    positions = pos_svc.list_for_user(str(user.id))  # type: ignore[arg-type]
    return OnboardingResponse(
        trades=[TradeRead.model_validate(t) for t in created_trades],
        positions=[PositionRead.model_validate(p) for p in positions],
    )


# ---------------------------------------------------------------------------
# Portfolio overview endpoints (Task 1 — 持仓总览聚合层)
# ---------------------------------------------------------------------------

_RANGE_DAYS: dict[str, int] = {"1m": 30, "3m": 90, "6m": 182, "1y": 365, "3y": 1095}


def _uid(user: User) -> object:
    """Return user.id, or None for the anonymous stub user."""
    return None if str(user.id) == "anonymous" else user.id


@router.get("/overview", response_model=OverviewRead)
async def get_overview(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
) -> OverviewRead:
    """聚合今日快照:总市值 / 今日涨跌 / 年初至今 / 拆账 / 看结构 / AI 叙事。"""
    import datetime as dt

    uid = _uid(user)
    ov = await build_overview(db, user_id=uid)
    ov["narrative"] = await narrate_today(ov["attribution"], persona_note=None)

    # ytd_pct: 取今年第一个交易日快照(若无,best-effort 0.0)
    ytd_pct = 0.0
    try:
        year_start = dt.date(dt.date.today().year, 1, 1)
        today = dt.date.today()
        if uid is not None:
            snaps_ytd = PositionSnapshotRepo(db).list_range(
                user_id=uid, start_date=year_start, end_date=today
            )
            by_date_ytd: dict[str, dict] = {}
            for row in snaps_ytd:
                by_date_ytd.setdefault(str(row.snapshot_date), {})[row.ts_code] = (
                    int(row.quantity),
                    float(row.market_price),
                )
            snaps_list = [DailySnap(date=d, holdings=h) for d, h in sorted(by_date_ytd.items())]
            if len(snaps_list) >= 2:
                twr_ytd = compute_twr(snaps_list)
                ytd_pct = round(twr_ytd["cumulative"] * 100, 4)
    except Exception:
        ytd_pct = 0.0

    ov["ytd_pct"] = ytd_pct
    return OverviewRead(**ov)


@router.get("/overview/trend", response_model=TrendRead)
async def get_trend(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
    range: str = "1m",
) -> TrendRead:
    """时间加权收益曲线 vs 沪深300 基准,按区间返回。"""
    import datetime as dt

    days = _RANGE_DAYS.get(range, 30)
    end = dt.date.today()
    start = end - dt.timedelta(days=days)
    uid = _uid(user)

    # --- 组合收益曲线 ---
    rows = PositionSnapshotRepo(db).list_range(user_id=uid, start_date=start, end_date=end)
    by_date: dict[str, dict] = {}
    for row in rows:
        by_date.setdefault(str(row.snapshot_date), {})[row.ts_code] = (
            int(row.quantity),
            float(row.market_price),
        )
    snaps = [DailySnap(date=d, holdings=h) for d, h in sorted(by_date.items())]
    twr = compute_twr(snaps) if len(snaps) >= 2 else {"daily": [], "cumulative": 0.0}

    dates = [s.date for s in snaps]

    # --- 沪深300 基准(同窗口累计,real get_index_daily) ---
    benchmark: list[float] = []
    try:
        from app.services.tushare_factory import build_tushare_service

        tushare = build_tushare_service()
        start_str = start.strftime("%Y%m%d")
        end_str = end.strftime("%Y%m%d")
        df = await tushare.get_index_daily(
            ts_code="000300.SH", start_date=start_str, end_date=end_str
        )
        if df is not None and not getattr(df, "empty", True):
            df = df.sort_values("trade_date")
            # 按日期过滤,只保留在 dates 集合内的交易日(近似对齐);
            # 若 dates 为空则返回全部沪深300交易日序列
            bench_dates = [str(d) for d in df["trade_date"].tolist()]
            pct_series = [float(x) for x in df["pct_chg"].tolist()]

            if dates:
                # 对齐:只取与组合 dates 重叠的交易日
                date_set = set(dates)
                bench_filtered = [(d, p) for d, p in zip(bench_dates, pct_series) if d in date_set]
                # 若没有重叠(如快照间隔与交易日不匹配),则用完整序列
                if not bench_filtered:
                    bench_filtered = list(zip(bench_dates, pct_series))
                pct_series = [p for _, p in bench_filtered]

            # 把涨跌幅百分点转成累计收益率序列(chain-linked)
            cum = 1.0
            for pct in pct_series:
                cum *= 1.0 + pct / 100.0
                benchmark.append(round(cum - 1.0, 10))
    except Exception:
        benchmark = []

    return TrendRead(
        dates=dates,
        portfolio=twr["daily"],
        cumulative=twr["cumulative"],
        benchmark=benchmark,
        range=range,
    )

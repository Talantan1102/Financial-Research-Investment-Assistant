from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User
from app.router.auth_router import get_current_user_required
from app.schemas.watchlist import WatchlistCreate, WatchlistRead, WatchlistUpdate
from app.services.watchlist_service import ChangeSource, WatchlistService

router = APIRouter(prefix="/api/v0/watchlist", tags=["watchlist"])


@router.get("", response_model=list[WatchlistRead])
def list_watchlist(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
) -> list[WatchlistRead]:
    return [
        WatchlistRead.model_validate(item) for item in WatchlistService(db).list(user_id=user.id)
    ]


@router.post("", response_model=WatchlistRead)
def add_watchlist(
    payload: WatchlistCreate,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
) -> WatchlistRead:
    try:
        result = WatchlistService(db).add(
            user_id=user.id,
            ts_code=payload.ts_code,
            name=payload.name,
            note=payload.note,
            monitoring_enabled=payload.monitoring_enabled,
            source=ChangeSource(),
        )
        db.commit()
        db.refresh(result.item)
        response.status_code = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
        return WatchlistRead.model_validate(result.item)
    except Exception:
        db.rollback()
        raise


@router.patch("/{ts_code}", response_model=WatchlistRead)
def update_watchlist(
    ts_code: str,
    payload: WatchlistUpdate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
) -> WatchlistRead:
    try:
        item = WatchlistService(db).update(
            user_id=user.id,
            ts_code=ts_code,
            changes=payload.model_dump(exclude_unset=True),
            source=ChangeSource(),
        )
        db.commit()
        db.refresh(item)
        return WatchlistRead.model_validate(item)
    except NoResultFound as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail="Watchlist item not found") from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/{ts_code}", status_code=status.HTTP_204_NO_CONTENT)
def remove_watchlist(
    ts_code: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
) -> None:
    try:
        WatchlistService(db).remove(user_id=user.id, ts_code=ts_code, source=ChangeSource())
        db.commit()
    except NoResultFound as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail="Watchlist item not found") from exc

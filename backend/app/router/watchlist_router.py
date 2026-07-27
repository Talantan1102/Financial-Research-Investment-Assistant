"""Authenticated direct CRUD endpoints for the current user's watchlist."""

from __future__ import annotations

import uuid
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User
from app.router.auth_router import get_current_user_required
from app.schemas.watchlist import (
    WatchlistCreate,
    WatchlistRead,
    WatchlistRemoveResponse,
    WatchlistUpdate,
)
from app.services.watchlist_service import ChangeSource, WatchlistService

router = APIRouter(prefix="/api/v0/watchlist", tags=["watchlist"])


def _user_id(user: User) -> uuid.UUID:
    return cast(uuid.UUID, user.id)


@router.get("", response_model=list[WatchlistRead])
def list_watchlist(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
) -> list[WatchlistRead]:
    return [
        WatchlistRead.model_validate(item)
        for item in WatchlistService(db).list(user_id=_user_id(user))
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
            user_id=_user_id(user),
            ts_code=payload.ts_code,
            name=payload.name,
            note=payload.note,
            monitoring_enabled=payload.monitoring_enabled,
            source=ChangeSource(),
        )
        db.commit()
        db.refresh(result.item)
    except Exception:
        db.rollback()
        raise
    response.status_code = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
    return WatchlistRead.model_validate(result.item)


@router.patch("/{ts_code}", response_model=WatchlistRead)
def update_watchlist(
    ts_code: str,
    payload: WatchlistUpdate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
) -> WatchlistRead:
    try:
        item = WatchlistService(db).update(
            user_id=_user_id(user),
            ts_code=ts_code,
            changes=payload.model_dump(exclude_unset=True),
            source=ChangeSource(),
        )
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Watchlist item not found",
            )
        db.commit()
        db.refresh(item)
    except HTTPException:
        db.rollback()
        raise
    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except Exception:
        db.rollback()
        raise
    return WatchlistRead.model_validate(item)


@router.delete("/{ts_code}", response_model=WatchlistRemoveResponse)
def remove_watchlist(
    ts_code: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
) -> WatchlistRemoveResponse:
    try:
        result = WatchlistService(db).remove(
            user_id=_user_id(user),
            ts_code=ts_code,
            source=ChangeSource(),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return WatchlistRemoveResponse(removed=result.removed)

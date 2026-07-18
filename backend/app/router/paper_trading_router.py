from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User
from app.router.auth_router import get_current_user_required
from app.schemas.paper_trading import InitialCashUpdate, PaperAccountRead
from app.services.paper_trading.account_service import PaperAccountService
from app.services.paper_trading.errors import PaperTradingError

router = APIRouter(prefix="/api/v0/paper-trading", tags=["paper-trading"])


def _business_error(exc: PaperTradingError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": exc.code, "message": str(exc)},
    )


@router.get("/account", response_model=PaperAccountRead)
def get_account(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
) -> PaperAccountRead:
    try:
        account = PaperAccountService(db).get_or_create(user_id=user.id)
        snapshot = PaperAccountRead.model_validate(account)
        db.commit()
    except PaperTradingError as exc:
        db.rollback()
        raise _business_error(exc) from exc
    except Exception:
        db.rollback()
        raise
    return snapshot


@router.patch("/account/initial-cash", response_model=PaperAccountRead)
def update_initial_cash(
    payload: InitialCashUpdate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
) -> PaperAccountRead:
    try:
        service = PaperAccountService(db)
        service.get_or_create(user_id=user.id)
        account = service.edit_initial_cash_once(
            user_id=user.id,
            initial_cash=payload.initial_cash,
        )
        snapshot = PaperAccountRead.model_validate(account)
        db.commit()
    except PaperTradingError as exc:
        db.rollback()
        raise _business_error(exc) from exc
    except Exception:
        db.rollback()
        raise
    return snapshot

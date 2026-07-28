"""Authenticated REST endpoints for the non-Agent market-permission workflow."""

from __future__ import annotations

import uuid
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.investor_suitability import Market
from app.models.user import User
from app.router.auth_router import get_current_user_required
from app.schemas.investor_suitability import (
    ApplicationRead,
    AssessmentRead,
    ConfirmApplicationRequest,
    MarketEntitlementRead,
    StartApplicationRequest,
    SubmitProfileRequest,
)
from app.services.investor_suitability.service import (
    SuitabilityApplicationError,
    SuitabilityApplicationService,
)
from app.services.paper_trading.account_service import PaperAccountService

router = APIRouter(prefix="/api/v0/market-permissions", tags=["market-permissions"])

_NOT_FOUND_CODES = {"application_not_found", "stale_account_generation"}
_INVALID_CODES = {"invalid_input", "profile_required", "application_not_open"}


def _user_id(user: User) -> uuid.UUID:
    return cast(uuid.UUID, user.id)


def _active_account_id(db: Session, user: User) -> uuid.UUID:
    return cast(uuid.UUID, PaperAccountService(db).get_or_create(user_id=_user_id(user)).id)


def _raise_application_error(exc: SuitabilityApplicationError) -> None:
    if exc.code in _NOT_FOUND_CODES:
        status_code = status.HTTP_404_NOT_FOUND
        message = "未找到该权限申请。"
    elif exc.code in _INVALID_CODES:
        status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
        message = "提交的信息不完整或不符合要求。"
    else:
        status_code = status.HTTP_409_CONFLICT
        message = "当前申请状态不允许此操作，请刷新后重试。"
    raise HTTPException(
        status_code=status_code, detail={"code": exc.code, "message": message}
    ) from exc


@router.get("", response_model=list[MarketEntitlementRead])
def list_market_permissions(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
) -> list[MarketEntitlementRead]:
    try:
        account_id = _active_account_id(db, user)
        result = SuitabilityApplicationService(db).list_entitlements(
            user_id=_user_id(user), account_id=account_id
        )
        db.commit()
        return [MarketEntitlementRead.model_validate(item) for item in result]
    except SuitabilityApplicationError as exc:
        db.rollback()
        _raise_application_error(exc)


@router.post("/{market}/applications", response_model=ApplicationRead)
def start_application(
    market: Market,
    payload: StartApplicationRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
) -> ApplicationRead:
    try:
        application = SuitabilityApplicationService(db).start(
            user_id=_user_id(user),
            account_id=_active_account_id(db, user),
            market=market,
            idempotency_key=payload.idempotency_key,
        )
        db.commit()
        db.refresh(application)
        return ApplicationRead.model_validate(application)
    except SuitabilityApplicationError as exc:
        db.rollback()
        _raise_application_error(exc)


@router.put("/applications/{application_id}/profile", response_model=AssessmentRead)
def submit_profile(
    application_id: uuid.UUID,
    payload: SubmitProfileRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
) -> AssessmentRead:
    try:
        assessment = SuitabilityApplicationService(db).submit_profile(
            user_id=_user_id(user),
            application_id=application_id,
            average_assets_20d=payload.declared_average_assets_20d,
            experience_months=payload.securities_experience_months,
            risk_level=payload.risk_level,
        )
        db.commit()
        db.refresh(assessment)
        return AssessmentRead.model_validate(assessment)
    except SuitabilityApplicationError as exc:
        db.rollback()
        _raise_application_error(exc)


@router.post("/applications/{application_id}/confirm", response_model=MarketEntitlementRead)
def confirm_application(
    application_id: uuid.UUID,
    payload: ConfirmApplicationRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
) -> MarketEntitlementRead:
    try:
        entitlement = SuitabilityApplicationService(db).confirm(
            user_id=_user_id(user),
            application_id=application_id,
            disclosure_version=payload.disclosure_version,
            idempotency_key=payload.idempotency_key,
        )
        db.commit()
        db.refresh(entitlement)
        return MarketEntitlementRead.model_validate(entitlement)
    except SuitabilityApplicationError as exc:
        db.rollback()
        _raise_application_error(exc)


@router.post("/applications/{application_id}/cancel", response_model=ApplicationRead)
def cancel_application(
    application_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
) -> ApplicationRead:
    try:
        application = SuitabilityApplicationService(db).cancel(
            user_id=_user_id(user), application_id=application_id
        )
        db.commit()
        db.refresh(application)
        return ApplicationRead.model_validate(application)
    except SuitabilityApplicationError as exc:
        db.rollback()
        _raise_application_error(exc)

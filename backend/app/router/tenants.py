"""Minimal tenant and membership management endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.tenant import Tenant
from app.models.user import User
from app.router.auth_router import get_current_user_required
from app.run_control.types import TenantRole
from app.schemas.tenant import MemberAdd, MemberResponse, TenantCreate, TenantResponse
from app.services.tenant_service import TenantService

router = APIRouter(prefix="/api/v1/tenants", tags=["tenants-v1"])


def _tenant_response(tenant: Tenant, role: TenantRole) -> TenantResponse:
    return TenantResponse.model_validate(
        {
            "id": tenant.id,
            "name": tenant.name,
            "slug": tenant.slug,
            "is_personal": tenant.is_personal,
            "max_running_runs": tenant.max_running_runs,
            "max_queued_runs": tenant.max_queued_runs,
            "role": role,
        }
    )


def _member_response(user: User, role: str) -> MemberResponse:
    return MemberResponse.model_validate(
        {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "role": role,
        }
    )


@router.get("", response_model=list[TenantResponse])
def list_tenants(
    current_user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db),
) -> list[TenantResponse]:
    service = TenantService(db)
    tenants = service.list_for_user(current_user.id)
    return [
        _tenant_response(tenant, TenantRole(service.require_role(tenant.id, current_user.id).role))
        for tenant in tenants
    ]


@router.post("", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
def create_tenant(
    body: TenantCreate,
    current_user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db),
) -> TenantResponse:
    tenant = TenantService(db).create_with_owner(name=body.name, owner=current_user)
    db.commit()
    return _tenant_response(tenant, TenantRole.OWNER)


@router.get("/{tenant_id}/members", response_model=list[MemberResponse])
def list_members(
    tenant_id: uuid.UUID,
    current_user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db),
) -> list[MemberResponse]:
    try:
        memberships = TenantService(db).list_members(tenant_id, current_user.id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    users_by_id = {
        user.id: user
        for user in db.query(User).filter(User.id.in_([row.user_id for row in memberships])).all()
    }
    return [_member_response(users_by_id[row.user_id], row.role) for row in memberships]


@router.post(
    "/{tenant_id}/members",
    response_model=MemberResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_member(
    tenant_id: uuid.UUID,
    body: MemberAdd,
    current_user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db),
) -> MemberResponse:
    try:
        membership = TenantService(db).add_member(
            tenant_id,
            current_user.id,
            body.email,
            TenantRole(body.role),
        )
        target = db.query(User).filter_by(id=membership.user_id).one()
        db.commit()
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="user is already a tenant member",
        )
    return _member_response(target, membership.role)


@router.delete("/{tenant_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db),
) -> Response:
    try:
        TenantService(db).remove_member(tenant_id, current_user.id, user_id)
        db.commit()
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except PermissionError as exc:
        code = status.HTTP_409_CONFLICT if "final owner" in str(exc) else status.HTTP_403_FORBIDDEN
        raise HTTPException(status_code=code, detail=str(exc))
    return Response(status_code=status.HTTP_204_NO_CONTENT)

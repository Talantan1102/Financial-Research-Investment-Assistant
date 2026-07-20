"""Tenant-scoped, read-only Run control-plane observability endpoint."""

from __future__ import annotations

from datetime import timedelta
from typing import cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.tenant import TenantMembership
from app.models.user import User
from app.router.auth_router import get_current_user_required
from app.services.run_metrics import RunMetricsService

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/observability", tags=["run-observability-v1"]
)


async def _factory(request: Request) -> async_sessionmaker[AsyncSession]:
    return cast(async_sessionmaker[AsyncSession], request.app.state.async_session_factory)


@router.get("/runs")
@router.get("/metrics")
async def run_metrics(
    tenant_id: UUID,
    request: Request,
    window_minutes: int = 15,
    current_user: User = Depends(get_current_user_required),
) -> dict[str, object]:
    factory = await _factory(request)
    async with factory() as session:
        member = await session.scalar(
            select(TenantMembership).where(
                TenantMembership.tenant_id == tenant_id,
                TenantMembership.user_id == cast(UUID, current_user.id),
            )
        )
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tenant not found")
    if not 1 <= window_minutes <= 24 * 60:
        raise HTTPException(status_code=400, detail="window_minutes must be between 1 and 1440")
    return await RunMetricsService(factory).snapshot(
        tenant_id, window=timedelta(minutes=window_minutes)
    )

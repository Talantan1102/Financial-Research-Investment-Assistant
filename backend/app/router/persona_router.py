"""persona_router — Plan Task 8 — REST endpoints for Tier 1 persona items.

spec § 7 (路径调整为 /api/v0/persona 对齐项目 router 前缀风格).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.memory.models import ChatMemoryPersonaItem
from app.memory.persona_service import PersonaService
from app.models.user import User
from app.router._persona_schemas import (
    PersonaItemOut,
    PersonaListResponse,
    PersonaPatchRequest,
    PersonaPostRequest,
)
from app.router.auth_router import get_current_user_required

router = APIRouter(prefix="/api/v0/persona", tags=["persona-ui"])


# ---------------------------------------------------------------------------
# Auth dependency — wraps project's existing get_current_user_required
# ---------------------------------------------------------------------------


def _get_current_user_id(
    current_user: Annotated[User, Depends(get_current_user_required)],
) -> UUID:
    """Extract UUID from current authenticated user.

    User.id 是 UUID(as_uuid=True).with_variant(String(36), "sqlite") — PG 下是
    typed UUID, SQLite 下是 str. 这里统一 cast 为 UUID 给下游 PersonaService 用,
    避免 4 个 endpoint 重复散布 cast 知识.

    test fixture 通过 app.dependency_overrides 替换此 dep。
    """
    return UUID(str(current_user.id))


# ---------------------------------------------------------------------------
# Session factory & service dependency
# ---------------------------------------------------------------------------


def get_persona_session_factory() -> Callable[[], Session]:
    return SessionLocal  # type: ignore[return-value]


def get_persona_service(
    session_factory: Annotated[Callable[[], Session], Depends(get_persona_session_factory)],
) -> PersonaService:
    return PersonaService(pg_session_factory=session_factory)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _to_out(item: ChatMemoryPersonaItem) -> PersonaItemOut:
    return PersonaItemOut(
        id=item.item_id,
        text=item.text,
        source=item.source,  # type: ignore[arg-type]
        position=item.position,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=PersonaListResponse)
def list_persona(
    user_id: Annotated[UUID, Depends(_get_current_user_id)],
    service: Annotated[PersonaService, Depends(get_persona_service)],
) -> PersonaListResponse:
    result = service.list_items(user_id=user_id)
    return PersonaListResponse(
        user_declared=[_to_out(i) for i in result["user_declared"]],
        agent_inferred=[_to_out(i) for i in result["agent_inferred"]],
    )


@router.post(
    "/items",
    response_model=PersonaItemOut,
    status_code=status.HTTP_201_CREATED,
)
def add_persona_item(
    body: PersonaPostRequest,
    user_id: Annotated[UUID, Depends(_get_current_user_id)],
    service: Annotated[PersonaService, Depends(get_persona_service)],
) -> PersonaItemOut:
    item = service.add_item(user_id=user_id, text=body.text, target_section=body.target_section)
    return _to_out(item)


@router.patch("/items/{item_id}", response_model=PersonaItemOut)
def update_persona_item(
    item_id: UUID,
    body: PersonaPatchRequest,
    user_id: Annotated[UUID, Depends(_get_current_user_id)],
    service: Annotated[PersonaService, Depends(get_persona_service)],
) -> PersonaItemOut:
    try:
        item = service.update_item(user_id=user_id, item_id=item_id, text=body.text)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_out(item)


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_persona_item(
    item_id: UUID,
    user_id: Annotated[UUID, Depends(_get_current_user_id)],
    service: Annotated[PersonaService, Depends(get_persona_service)],
) -> Response:
    try:
        service.delete_item(user_id=user_id, item_id=item_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)

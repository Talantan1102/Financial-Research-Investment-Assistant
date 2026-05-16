"""persona_router Pydantic schema + 路由行为测试 (Plan Tasks 7-8)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from app.router._persona_schemas import (
    PersonaItemOut,
    PersonaListResponse,
    PersonaPatchRequest,
    PersonaPostRequest,
)
from pydantic import ValidationError


@pytest.mark.unit
def test_post_request_strips_text() -> None:
    req = PersonaPostRequest(text="  保守稳健  ", target_section="user")
    assert req.text == "保守稳健"


@pytest.mark.unit
def test_post_request_rejects_empty() -> None:
    with pytest.raises(ValidationError):
        PersonaPostRequest(text="   ", target_section="user")


@pytest.mark.unit
def test_post_request_rejects_too_long() -> None:
    with pytest.raises(ValidationError):
        PersonaPostRequest(text="a" * 501, target_section="user")


@pytest.mark.unit
def test_post_request_target_section_enum() -> None:
    with pytest.raises(ValidationError):
        PersonaPostRequest(text="x", target_section="other")  # type: ignore[arg-type]


@pytest.mark.unit
def test_patch_request_validates_text() -> None:
    PersonaPatchRequest(text="updated")
    with pytest.raises(ValidationError):
        PersonaPatchRequest(text="")
    with pytest.raises(ValidationError):
        PersonaPatchRequest(text="a" * 501)


@pytest.mark.unit
def test_list_response_serializes() -> None:
    resp = PersonaListResponse(user_declared=[], agent_inferred=[])
    assert resp.model_dump() == {"user_declared": [], "agent_inferred": []}


@pytest.mark.unit
def test_item_out_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        PersonaItemOut(  # type: ignore[call-arg]
            id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
            text="x",
            source="user",
            position=0,
            created_at=datetime(2026, 5, 17, tzinfo=UTC),
            updated_at=datetime(2026, 5, 17, tzinfo=UTC),
            extra_field="boom",
        )

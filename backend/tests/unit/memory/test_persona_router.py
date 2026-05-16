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


# ---------------------------------------------------------------------------
# Task 8: Router behaviour tests
# ---------------------------------------------------------------------------

from unittest.mock import MagicMock
from uuid import uuid4

from app.memory.models import ChatMemoryPersonaItem
from app.router.persona_router import get_persona_service
from app.router.persona_router import router as persona_router
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _fake_item(**overrides: object) -> ChatMemoryPersonaItem:
    item = ChatMemoryPersonaItem(
        item_id=uuid4(),
        user_id=uuid4(),
        source="user",
        text="测试",
        position=0,
    )
    item.created_at = datetime.now(UTC)  # type: ignore[assignment]
    item.updated_at = datetime.now(UTC)  # type: ignore[assignment]
    for k, v in overrides.items():
        setattr(item, k, v)
    return item


def _client(service: MagicMock, user_id: object | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(persona_router)
    app.dependency_overrides[get_persona_service] = lambda: service
    # 假装 current_user dependency 已注入 — 实际 endpoint 用 get_current_user_required
    from app.router.persona_router import _get_current_user_id

    app.dependency_overrides[_get_current_user_id] = lambda: user_id or uuid4()
    return TestClient(app)


@pytest.mark.unit
def test_get_persona_returns_two_sections() -> None:
    service = MagicMock()
    user_item = _fake_item(source="user", text="A")
    agent_item = _fake_item(source="agent", text="B")
    service.list_items.return_value = {
        "user_declared": [user_item],
        "agent_inferred": [agent_item],
    }
    client = _client(service)

    resp = client.get("/api/v0/persona")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["user_declared"]) == 1
    assert body["user_declared"][0]["text"] == "A"
    assert len(body["agent_inferred"]) == 1


@pytest.mark.unit
def test_post_persona_item_creates() -> None:
    service = MagicMock()
    new_item = _fake_item(text="新条")
    service.add_item.return_value = new_item
    client = _client(service)

    resp = client.post(
        "/api/v0/persona/items",
        json={"text": "新条", "target_section": "user"},
    )

    assert resp.status_code == 201
    assert resp.json()["text"] == "新条"


@pytest.mark.unit
def test_post_persona_rejects_invalid_payload() -> None:
    client = _client(MagicMock())
    resp = client.post(
        "/api/v0/persona/items",
        json={"text": "", "target_section": "user"},
    )
    assert resp.status_code == 422


@pytest.mark.unit
def test_patch_persona_item_returns_updated() -> None:
    service = MagicMock()
    upgraded = _fake_item(source="user", text="改后", position=3)
    service.update_item.return_value = upgraded
    client = _client(service)

    resp = client.patch(
        f"/api/v0/persona/items/{uuid4()}",
        json={"text": "改后"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "user"
    assert body["text"] == "改后"


@pytest.mark.unit
def test_patch_persona_item_not_found() -> None:
    service = MagicMock()
    service.update_item.side_effect = LookupError("not found")
    client = _client(service)
    resp = client.patch(
        f"/api/v0/persona/items/{uuid4()}",
        json={"text": "x"},
    )
    assert resp.status_code == 404


@pytest.mark.unit
def test_delete_persona_item_204() -> None:
    service = MagicMock()
    client = _client(service)
    resp = client.delete(f"/api/v0/persona/items/{uuid4()}")
    assert resp.status_code == 204


@pytest.mark.unit
def test_delete_persona_item_not_found() -> None:
    service = MagicMock()
    service.delete_item.side_effect = LookupError("not found")
    client = _client(service)
    resp = client.delete(f"/api/v0/persona/items/{uuid4()}")
    assert resp.status_code == 404

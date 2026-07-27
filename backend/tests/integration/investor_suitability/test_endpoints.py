from __future__ import annotations

import uuid
from collections.abc import Generator
from datetime import date
from typing import cast

import pytest
from app.core.database import get_db
from app.models.investor_suitability import MarketAccessRule
from app.models.user import User
from app.router.auth_router import get_current_user_required
from app.services.investor_suitability.rules import rulebook
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


@pytest.fixture
def permission_client(db_session: Session) -> Generator[tuple[TestClient, User], None, None]:
    from app.app_main import app

    for rule in rulebook().rules:
        db_session.add(MarketAccessRule(
            market=rule.market, effective_from=date(2026, 7, 27),
            minimum_average_assets_20d=rule.minimum_average_assets_20d,
            minimum_experience_months=rule.minimum_experience_months,
            required_disclosure_version=rule.required_disclosure_version,
            rule_version=rule.rule_version,
        ))
    suffix = uuid.uuid4().hex[:12]
    user = User(username=f"permission-{suffix}", email=f"permission-{suffix}@test.local", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user_required] = lambda: user
    try:
        yield TestClient(app), user
    finally:
        app.dependency_overrides.clear()


def _start(
    client: TestClient, key: str = "start-star", market: str = "star"
) -> dict[str, object]:
    response = client.post(
        f"/api/v0/market-permissions/{market}/applications", json={"idempotency_key": key}
    )
    assert response.status_code == 200, response.text
    return cast(dict[str, object], response.json())


def _qualify(client: TestClient, application_id: str) -> None:
    response = client.put(f"/api/v0/market-permissions/applications/{application_id}/profile", json={
        "declared_average_assets_20d": "600000.00", "securities_experience_months": 36, "risk_level": "C4",
    })
    assert response.status_code == 200, response.text
    assert response.json()["decision"] == "passed"


def test_user_can_start_submit_confirm_and_list_permissions(permission_client: tuple[TestClient, User]) -> None:
    client, _ = permission_client
    application = _start(client)
    _qualify(client, str(application["application_id"]))
    confirmed = client.post(f"/api/v0/market-permissions/applications/{application['application_id']}/confirm", json={
        "disclosure_version": "star-risk-disclosure-2026-07", "idempotency_key": "confirm-star",
    })
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "enabled"
    listed = client.get("/api/v0/market-permissions")
    assert listed.status_code == 200
    assert listed.json()[0]["market"] == "star"


def test_cross_user_application_is_not_found(permission_client: tuple[TestClient, User], db_session: Session) -> None:
    client, _ = permission_client
    application = _start(client)
    other = User(username=f"other-{uuid.uuid4().hex[:8]}", email=f"other-{uuid.uuid4().hex[:8]}@test.local", hashed_password="x")
    db_session.add(other)
    db_session.flush()
    from app.app_main import app
    app.dependency_overrides[get_current_user_required] = lambda: other
    response = client.put(f"/api/v0/market-permissions/applications/{application['application_id']}/profile", json={
        "declared_average_assets_20d": "600000.00", "securities_experience_months": 36, "risk_level": "C4",
    })
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "application_not_found"


def test_stale_disclosure_is_conflict_and_incomplete_profile_is_invalid(permission_client: tuple[TestClient, User]) -> None:
    client, _ = permission_client
    application = _start(client)
    incomplete = client.put(f"/api/v0/market-permissions/applications/{application['application_id']}/profile", json={"risk_level": "C4"})
    assert incomplete.status_code == 422
    _qualify(client, str(application["application_id"]))
    stale = client.post(f"/api/v0/market-permissions/applications/{application['application_id']}/confirm", json={
        "disclosure_version": "old", "idempotency_key": "confirm-star",
    })
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "stale_disclosure_version"


def test_confirmation_is_idempotent_and_cancel_never_enables(permission_client: tuple[TestClient, User]) -> None:
    client, _ = permission_client
    application = _start(client)
    _qualify(client, str(application["application_id"]))
    body = {"disclosure_version": "star-risk-disclosure-2026-07", "idempotency_key": "confirm-star"}
    first = client.post(f"/api/v0/market-permissions/applications/{application['application_id']}/confirm", json=body)
    replay = client.post(f"/api/v0/market-permissions/applications/{application['application_id']}/confirm", json=body)
    assert first.status_code == replay.status_code == 200
    assert first.json()["entitlement_id"] == replay.json()["entitlement_id"]
    cancelled = _start(client, "start-chinext", market="chinext")
    cancelled_response = client.post(f"/api/v0/market-permissions/applications/{cancelled['application_id']}/cancel")
    assert cancelled_response.status_code == 200
    assert cancelled_response.json()["status"] == "cancelled_by_user"
    assert {item["market"] for item in client.get("/api/v0/market-permissions").json()} == {"star"}

"""HTTP contract tests for the minimal tenant-management API."""

from __future__ import annotations

import uuid
from collections.abc import Callable

import pytest
from app.core.database import get_db
from app.models.tenant import Tenant, TenantAuditLog, TenantMembership
from app.models.user import User
from app.router.auth_router import get_current_user_required
from app.router.tenants import router
from app.services.tenant_service import TenantService
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def _user(label: str) -> User:
    return User(
        username=label,
        email=f"{label}@example.com",
        hashed_password="not-used",
        is_active=True,
    )


@pytest.fixture
def users(db_session: Session) -> dict[str, User]:
    rows = {
        role: _user(f"tenant-{role}-{uuid.uuid4().hex[:8]}")
        for role in ("owner", "admin", "member", "outsider", "target")
    }
    db_session.add_all(rows.values())
    db_session.flush()
    return rows


@pytest.fixture
def tenant(db_session: Session, users: dict[str, User]) -> Tenant:
    tenant = TenantService(db_session).create_with_owner(name="API tenant", owner=users["owner"])
    db_session.add_all(
        [
            TenantMembership(tenant_id=tenant.id, user_id=users["admin"].id, role="admin"),
            TenantMembership(tenant_id=tenant.id, user_id=users["member"].id, role="member"),
        ]
    )
    db_session.commit()
    return tenant


@pytest.fixture
def client_for(db_session: Session) -> Callable[[User | None], TestClient]:
    def build(user: User | None) -> TestClient:
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: db_session
        if user is not None:
            app.dependency_overrides[get_current_user_required] = lambda: user
        return TestClient(app)

    return build


def test_unauthenticated_request_is_rejected(
    client_for: Callable[[User | None], TestClient],
) -> None:
    response = client_for(None).get("/api/v1/tenants")

    assert response.status_code == 401


def test_list_returns_only_actor_tenants_with_limits_and_role(
    db_session: Session,
    users: dict[str, User],
    tenant: Tenant,
    client_for: Callable[[User | None], TestClient],
) -> None:
    TenantService(db_session).create_with_owner(name="Other tenant", owner=users["outsider"])
    db_session.commit()

    response = client_for(users["member"]).get("/api/v1/tenants")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": str(tenant.id),
            "name": "API tenant",
            "slug": tenant.slug,
            "is_personal": False,
            "max_running_runs": 2,
            "max_queued_runs": 100,
            "role": "member",
        }
    ]


def test_create_tenant_makes_actor_owner_and_writes_audit(
    db_session: Session,
    users: dict[str, User],
    client_for: Callable[[User | None], TestClient],
) -> None:
    response = client_for(users["member"]).post("/api/v1/tenants", json={"name": "New workspace"})

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "New workspace"
    assert body["role"] == "owner"
    assert body["max_running_runs"] == 2
    assert body["max_queued_runs"] == 100
    tenant_id = uuid.UUID(body["id"])
    assert (
        db_session.query(TenantMembership)
        .filter_by(tenant_id=tenant_id, user_id=users["member"].id, role="owner")
        .one()
    )
    assert (
        db_session.query(TenantAuditLog)
        .filter_by(tenant_id=tenant_id, action="tenant.created")
        .one()
    )


@pytest.mark.parametrize("name", ["", "x" * 121])
def test_create_rejects_invalid_name(
    name: str,
    users: dict[str, User],
    client_for: Callable[[User | None], TestClient],
) -> None:
    response = client_for(users["owner"]).post("/api/v1/tenants", json={"name": name})

    assert response.status_code == 422


def test_member_list_includes_user_identity_and_role(
    users: dict[str, User],
    tenant: Tenant,
    client_for: Callable[[User | None], TestClient],
) -> None:
    response = client_for(users["member"]).get(f"/api/v1/tenants/{tenant.id}/members")

    assert response.status_code == 200
    members = {item["email"]: item for item in response.json()}
    assert members[users["owner"].email] == {
        "id": str(users["owner"].id),
        "username": users["owner"].username,
        "email": users["owner"].email,
        "role": "owner",
    }
    assert members[users["admin"].email]["role"] == "admin"
    assert members[users["member"].email]["role"] == "member"


def test_outsider_cannot_list_members(
    users: dict[str, User],
    tenant: Tenant,
    client_for: Callable[[User | None], TestClient],
) -> None:
    response = client_for(users["outsider"]).get(f"/api/v1/tenants/{tenant.id}/members")

    assert response.status_code == 404


def test_member_cannot_add_existing_user(
    users: dict[str, User],
    tenant: Tenant,
    client_for: Callable[[User | None], TestClient],
) -> None:
    response = client_for(users["member"]).post(
        f"/api/v1/tenants/{tenant.id}/members",
        json={"email": users["target"].email, "role": "member"},
    )

    assert response.status_code == 403


def test_owner_can_add_existing_user_and_mutation_writes_audit(
    db_session: Session,
    users: dict[str, User],
    tenant: Tenant,
    client_for: Callable[[User | None], TestClient],
) -> None:
    response = client_for(users["owner"]).post(
        f"/api/v1/tenants/{tenant.id}/members",
        json={"email": users["target"].email, "role": "member"},
    )

    assert response.status_code == 201
    assert response.json() == {
        "id": str(users["target"].id),
        "username": users["target"].username,
        "email": users["target"].email,
        "role": "member",
    }
    assert (
        db_session.query(TenantAuditLog)
        .filter_by(
            tenant_id=tenant.id,
            action="tenant.member_added",
            target_user_id=users["target"].id,
        )
        .one()
    )


def test_admin_can_add_member(
    db_session: Session,
    users: dict[str, User],
    tenant: Tenant,
    client_for: Callable[[User | None], TestClient],
) -> None:
    response = client_for(users["admin"]).post(
        f"/api/v1/tenants/{tenant.id}/members",
        json={"email": users["target"].email, "role": "member"},
    )

    assert response.status_code == 201
    assert response.json()["role"] == "member"
    assert (
        db_session.query(TenantMembership)
        .filter_by(tenant_id=tenant.id, user_id=users["target"].id, role="member")
        .one()
    )


def test_owner_can_grant_admin_role(
    db_session: Session,
    users: dict[str, User],
    tenant: Tenant,
    client_for: Callable[[User | None], TestClient],
) -> None:
    response = client_for(users["owner"]).post(
        f"/api/v1/tenants/{tenant.id}/members",
        json={"email": users["target"].email, "role": "admin"},
    )

    assert response.status_code == 201
    assert response.json()["role"] == "admin"
    assert (
        db_session.query(TenantMembership)
        .filter_by(tenant_id=tenant.id, user_id=users["target"].id, role="admin")
        .one()
    )


def test_admin_cannot_grant_admin_role(
    users: dict[str, User],
    tenant: Tenant,
    client_for: Callable[[User | None], TestClient],
) -> None:
    response = client_for(users["admin"]).post(
        f"/api/v1/tenants/{tenant.id}/members",
        json={"email": users["target"].email, "role": "admin"},
    )

    assert response.status_code == 403


def test_admin_cannot_grant_owner_role(
    users: dict[str, User],
    tenant: Tenant,
    client_for: Callable[[User | None], TestClient],
) -> None:
    response = client_for(users["admin"]).post(
        f"/api/v1/tenants/{tenant.id}/members",
        json={"email": users["target"].email, "role": "owner"},
    )

    assert response.status_code == 422


def test_outsider_gets_404_when_adding_member(
    users: dict[str, User],
    tenant: Tenant,
    client_for: Callable[[User | None], TestClient],
) -> None:
    response = client_for(users["outsider"]).post(
        f"/api/v1/tenants/{tenant.id}/members",
        json={"email": users["target"].email, "role": "member"},
    )

    assert response.status_code == 404


def test_missing_target_user_is_404(
    users: dict[str, User],
    tenant: Tenant,
    client_for: Callable[[User | None], TestClient],
) -> None:
    response = client_for(users["owner"]).post(
        f"/api/v1/tenants/{tenant.id}/members",
        json={"email": "missing@example.com", "role": "member"},
    )

    assert response.status_code == 404


def test_duplicate_membership_is_409(
    users: dict[str, User],
    tenant: Tenant,
    client_for: Callable[[User | None], TestClient],
) -> None:
    response = client_for(users["owner"]).post(
        f"/api/v1/tenants/{tenant.id}/members",
        json={"email": users["member"].email, "role": "member"},
    )

    assert response.status_code == 409


def test_unrelated_integrity_error_is_not_reported_as_duplicate_membership(
    db_session: Session,
    users: dict[str, User],
    tenant: Tenant,
    client_for: Callable[[User | None], TestClient],
) -> None:
    db_session.execute(
        text(
            "ALTER TABLE tenant_audit_logs "
            "ADD CONSTRAINT ck_test_reject_member_added "
            "CHECK (action <> 'tenant.member_added')"
        )
    )
    db_session.commit()

    with pytest.raises(IntegrityError):
        client_for(users["owner"]).post(
            f"/api/v1/tenants/{tenant.id}/members",
            json={"email": users["target"].email, "role": "member"},
        )


def test_final_owner_cannot_be_removed(
    users: dict[str, User],
    tenant: Tenant,
    client_for: Callable[[User | None], TestClient],
) -> None:
    response = client_for(users["owner"]).delete(
        f"/api/v1/tenants/{tenant.id}/members/{users['owner'].id}"
    )

    assert response.status_code == 409


def test_owner_can_remove_member_and_mutation_writes_audit(
    db_session: Session,
    users: dict[str, User],
    tenant: Tenant,
    client_for: Callable[[User | None], TestClient],
) -> None:
    response = client_for(users["owner"]).delete(
        f"/api/v1/tenants/{tenant.id}/members/{users['member'].id}"
    )

    assert response.status_code == 204
    assert (
        db_session.query(TenantMembership)
        .filter_by(tenant_id=tenant.id, user_id=users["member"].id)
        .one_or_none()
        is None
    )
    assert (
        db_session.query(TenantAuditLog)
        .filter_by(
            tenant_id=tenant.id,
            action="tenant.member_removed",
            target_user_id=users["member"].id,
        )
        .one()
    )


def test_admin_can_remove_member(
    db_session: Session,
    users: dict[str, User],
    tenant: Tenant,
    client_for: Callable[[User | None], TestClient],
) -> None:
    response = client_for(users["admin"]).delete(
        f"/api/v1/tenants/{tenant.id}/members/{users['member'].id}"
    )

    assert response.status_code == 204
    assert (
        db_session.query(TenantMembership)
        .filter_by(tenant_id=tenant.id, user_id=users["member"].id)
        .one_or_none()
        is None
    )


def test_admin_cannot_remove_admin(
    db_session: Session,
    users: dict[str, User],
    tenant: Tenant,
    client_for: Callable[[User | None], TestClient],
) -> None:
    db_session.add(TenantMembership(tenant_id=tenant.id, user_id=users["target"].id, role="admin"))
    db_session.commit()

    response = client_for(users["admin"]).delete(
        f"/api/v1/tenants/{tenant.id}/members/{users['target'].id}"
    )

    assert response.status_code == 403


def test_outsider_gets_404_when_removing_member(
    users: dict[str, User],
    tenant: Tenant,
    client_for: Callable[[User | None], TestClient],
) -> None:
    response = client_for(users["outsider"]).delete(
        f"/api/v1/tenants/{tenant.id}/members/{users['member'].id}"
    )

    assert response.status_code == 404


def test_owner_can_remove_non_final_owner(
    db_session: Session,
    users: dict[str, User],
    tenant: Tenant,
    client_for: Callable[[User | None], TestClient],
) -> None:
    db_session.add(TenantMembership(tenant_id=tenant.id, user_id=users["target"].id, role="owner"))
    db_session.commit()

    response = client_for(users["owner"]).delete(
        f"/api/v1/tenants/{tenant.id}/members/{users['target'].id}"
    )

    assert response.status_code == 204
    assert (
        db_session.query(TenantMembership)
        .filter_by(tenant_id=tenant.id, user_id=users["owner"].id, role="owner")
        .one()
    )
    assert (
        db_session.query(TenantMembership)
        .filter_by(tenant_id=tenant.id, user_id=users["target"].id)
        .one_or_none()
        is None
    )


def test_missing_membership_target_is_404(
    users: dict[str, User],
    tenant: Tenant,
    client_for: Callable[[User | None], TestClient],
) -> None:
    response = client_for(users["owner"]).delete(
        f"/api/v1/tenants/{tenant.id}/members/{users['target'].id}"
    )

    assert response.status_code == 404

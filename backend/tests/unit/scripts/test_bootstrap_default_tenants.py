"""Tests for idempotent personal tenant bootstrap."""

from __future__ import annotations

from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.services.tenant_service import TenantService
from sqlalchemy.orm import Session


def _user(username: str) -> User:
    return User(
        username=username,
        email=f"{username}@example.com",
        hashed_password="not-used",
    )


def test_bootstrap_creates_only_missing_personal_tenants_and_is_idempotent(
    db_session: Session,
) -> None:
    from app.scripts.bootstrap_default_tenants import bootstrap_default_tenants

    missing = _user("missing_personal")
    company_member = _user("company_member")
    already_personal = _user("already_personal")
    db_session.add_all([missing, company_member, already_personal])
    db_session.flush()

    service = TenantService(db_session)
    service.create_with_owner(
        name="Company workspace",
        owner=company_member,
        is_personal=False,
    )
    service.create_with_owner(
        name="Existing personal workspace",
        owner=already_personal,
        is_personal=True,
    )
    db_session.commit()

    assert bootstrap_default_tenants(db_session) == 2

    for user in (missing, company_member, already_personal):
        personal_memberships = (
            db_session.query(TenantMembership)
            .join(Tenant, Tenant.id == TenantMembership.tenant_id)
            .filter(
                TenantMembership.user_id == user.id,
                Tenant.is_personal.is_(True),
            )
            .all()
        )
        assert len(personal_memberships) == 1

    assert bootstrap_default_tenants(db_session) == 0

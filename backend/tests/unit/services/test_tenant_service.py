from __future__ import annotations

from uuid import UUID

import pytest
from app.models.tenant import TenantAuditLog, TenantMembership
from app.models.user import User
from app.run_control.types import TenantRole
from app.services.tenant_service import TenantService
from sqlalchemy.orm import Session

from tests.unit._helpers import make_user


@pytest.fixture
def owner(db_session: Session) -> User:
    return make_user(db_session)


@pytest.fixture
def tenant_users(db_session: Session, owner: User):
    service = TenantService(db_session)
    tenant = service.create_with_owner(name="Acme", owner=owner, is_personal=False)
    member = make_user(db_session)
    target = make_user(db_session)
    db_session.add(TenantMembership(tenant_id=tenant.id, user_id=member.id, role=TenantRole.MEMBER))
    db_session.flush()
    return service, tenant, member, target


def test_create_with_owner_sets_defaults_and_creates_audit(
    db_session: Session, owner: User
) -> None:
    tenant = TenantService(db_session).create_with_owner(
        name="Personal", owner=owner, is_personal=True
    )

    membership = db_session.get(TenantMembership, (tenant.id, owner.id))
    audit = db_session.query(TenantAuditLog).one()
    assert tenant.max_running_runs == 2
    assert tenant.max_queued_runs == 100
    assert membership is not None
    assert membership.role == TenantRole.OWNER
    assert audit.action == "tenant.created"
    assert str(audit.actor_user_id) == str(owner.id)
    assert str(audit.target_user_id) == str(owner.id)


def test_list_for_user_and_list_members(db_session: Session, tenant_users) -> None:
    service, tenant, member, _target = tenant_users

    assert service.list_for_user(member.id) == [tenant]
    assert {row.user_id for row in service.list_members(tenant.id, member.id)} == {
        row.user_id for row in db_session.query(TenantMembership).filter_by(tenant_id=tenant.id)
    }


def test_member_cannot_add_member(tenant_users) -> None:
    service, tenant, member, target = tenant_users

    with pytest.raises(PermissionError):
        service.add_member(tenant.id, member.id, target.email, TenantRole.MEMBER)


def test_admin_can_add_member_and_mutation_is_audited(db_session: Session, tenant_users) -> None:
    service, tenant, _member, target = tenant_users
    admin = make_user(db_session)
    db_session.add(TenantMembership(tenant_id=tenant.id, user_id=admin.id, role=TenantRole.ADMIN))
    db_session.flush()

    membership = service.add_member(tenant.id, admin.id, target.email, TenantRole.MEMBER)

    audit = (
        db_session.query(TenantAuditLog)
        .filter_by(action="tenant.member_added", target_user_id=target.id)
        .one()
    )
    assert membership.role == TenantRole.MEMBER
    assert str(audit.actor_user_id) == str(admin.id)
    assert audit.payload == {"role": "member"}


def test_only_owner_can_grant_admin(db_session: Session, tenant_users) -> None:
    service, tenant, _member, target = tenant_users
    admin = make_user(db_session)
    db_session.add(TenantMembership(tenant_id=tenant.id, user_id=admin.id, role=TenantRole.ADMIN))
    db_session.flush()

    with pytest.raises(PermissionError):
        service.add_member(tenant.id, admin.id, target.email, TenantRole.ADMIN)


def test_outsider_membership_lookup_raises(db_session: Session, tenant_users) -> None:
    service, tenant, _member, _target = tenant_users
    outsider = make_user(db_session)

    with pytest.raises(LookupError):
        service.require_role(tenant.id, outsider.id, TenantRole.MEMBER)


def test_owner_can_remove_member_and_mutation_is_audited(
    db_session: Session, tenant_users, owner: User
) -> None:
    service, tenant, member, _target = tenant_users

    service.remove_member(tenant.id, owner.id, member.id)

    assert db_session.get(TenantMembership, (tenant.id, member.id)) is None
    audit = (
        db_session.query(TenantAuditLog)
        .filter_by(action="tenant.member_removed", target_user_id=member.id)
        .one()
    )
    assert audit.payload == {"role": "member"}


def test_admin_cannot_remove_admin(db_session: Session, tenant_users) -> None:
    service, tenant, _member, _target = tenant_users
    actor = make_user(db_session)
    target_admin = make_user(db_session)
    db_session.add_all(
        [
            TenantMembership(tenant_id=tenant.id, user_id=actor.id, role=TenantRole.ADMIN),
            TenantMembership(tenant_id=tenant.id, user_id=target_admin.id, role=TenantRole.ADMIN),
        ]
    )
    db_session.flush()

    with pytest.raises(PermissionError):
        service.remove_member(tenant.id, actor.id, target_admin.id)


def test_final_owner_cannot_be_removed(tenant_users, owner: User) -> None:
    service, tenant, _member, _target = tenant_users

    with pytest.raises(PermissionError, match="final owner"):
        service.remove_member(tenant.id, owner.id, owner.id)


def test_missing_target_user_raises_lookup_error(tenant_users, owner: User) -> None:
    service, tenant, _member, _target = tenant_users

    with pytest.raises(LookupError):
        service.add_member(
            tenant.id,
            owner.id,
            "missing@example.com",
            TenantRole.MEMBER,
        )


def test_ids_are_postgresql_uuids(db_session: Session, owner: User) -> None:
    tenant = TenantService(db_session).create_with_owner(
        name="UUID Tenant", owner=owner, is_personal=False
    )
    audit = db_session.query(TenantAuditLog).one()

    assert isinstance(tenant.id, UUID)
    assert isinstance(audit.id, UUID)

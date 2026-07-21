from __future__ import annotations

import pytest
from app.models.tenant import Tenant, TenantAuditLog, TenantMembership
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tests.unit._helpers import make_user


@pytest.fixture
def owner(db_session: Session):
    return make_user(db_session)


@pytest.fixture
def tenant(db_session: Session, owner) -> Tenant:
    row = Tenant(name="Acme", slug="acme", is_personal=False)
    db_session.add(row)
    db_session.flush()
    db_session.add(TenantMembership(tenant_id=row.id, user_id=owner.id, role="owner"))
    db_session.commit()
    return row


def test_tenant_defaults_have_positive_quotas(db_session: Session) -> None:
    tenant = Tenant(name="Personal", slug="personal", is_personal=True)
    db_session.add(tenant)
    db_session.flush()

    assert tenant.max_running_runs == 2
    assert tenant.max_queued_runs == 100


@pytest.mark.parametrize(
    ("field", "value"),
    [("max_running_runs", 0), ("max_running_runs", -1), ("max_queued_runs", 0)],
)
def test_tenant_quotas_must_be_positive(db_session: Session, field: str, value: int) -> None:
    values = {field: value}
    db_session.add(Tenant(name=f"Invalid {field}", slug=f"invalid-{field}-{value}", **values))

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_membership_is_unique(db_session: Session, tenant: Tenant, owner) -> None:
    db_session.add(TenantMembership(tenant_id=tenant.id, user_id=owner.id, role="member"))

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_membership_role_is_fixed(db_session: Session, tenant: Tenant) -> None:
    user = make_user(db_session)
    db_session.add(TenantMembership(tenant_id=tenant.id, user_id=user.id, role="custom-role"))

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_all_foreign_keys_declare_ondelete() -> None:
    for table in (TenantMembership.__table__, TenantAuditLog.__table__):
        assert table.foreign_keys
        assert all(foreign_key.ondelete is not None for foreign_key in table.foreign_keys)

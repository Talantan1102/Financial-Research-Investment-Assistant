"""Create a personal tenant for every user who does not have one."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.services.tenant_service import TenantService


def bootstrap_default_tenants(db: Session) -> int:
    personal_membership_exists = (
        select(TenantMembership.user_id)
        .join(Tenant, Tenant.id == TenantMembership.tenant_id)
        .where(
            TenantMembership.user_id == User.id,
            Tenant.is_personal.is_(True),
        )
        .exists()
    )
    users = db.query(User).filter(~personal_membership_exists).order_by(User.id).all()

    service = TenantService(db)
    for user in users:
        service.create_with_owner(
            name=f"{user.username} 的工作区",
            owner=user,
            is_personal=True,
        )
    db.commit()
    return len(users)


def main() -> None:
    db = SessionLocal()
    try:
        created = bootstrap_default_tenants(db)
    finally:
        db.close()
    print(f"Created {created} personal tenant(s).")


if __name__ == "__main__":
    main()

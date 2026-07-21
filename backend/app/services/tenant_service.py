"""Caller-transaction-owned tenant membership and RBAC operations."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.models.tenant import Tenant, TenantAuditLog, TenantMembership
from app.models.user import User
from app.run_control.types import TenantRole


class TenantService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_with_owner(self, *, name: str, owner: User, is_personal: bool = False) -> Tenant:
        tenant = Tenant(name=name, slug=uuid.uuid4().hex, is_personal=is_personal)
        self._session.add(tenant)
        self._session.flush()
        self._session.add_all(
            [
                TenantMembership(
                    tenant_id=tenant.id,
                    user_id=owner.id,
                    role=TenantRole.OWNER.value,
                ),
                TenantAuditLog(
                    tenant_id=tenant.id,
                    actor_user_id=owner.id,
                    action="tenant.created",
                    target_user_id=owner.id,
                    payload={"is_personal": is_personal},
                ),
            ]
        )
        self._session.flush()
        return tenant

    def list_for_user(self, user_id: uuid.UUID) -> list[Tenant]:
        return (
            self._session.query(Tenant)
            .join(TenantMembership, TenantMembership.tenant_id == Tenant.id)
            .filter(TenantMembership.user_id == user_id)
            .order_by(Tenant.created_at.asc(), Tenant.id.asc())
            .all()
        )

    def list_members(
        self, tenant_id: uuid.UUID, actor_user_id: uuid.UUID
    ) -> list[TenantMembership]:
        self.require_role(tenant_id, actor_user_id, *TenantRole)
        return (
            self._session.query(TenantMembership)
            .filter_by(tenant_id=tenant_id)
            .order_by(TenantMembership.joined_at.asc(), TenantMembership.user_id.asc())
            .all()
        )

    def add_member(
        self,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        target_email: str,
        role: TenantRole,
    ) -> TenantMembership:
        actor = self.require_role(tenant_id, actor_user_id, TenantRole.OWNER, TenantRole.ADMIN)
        if role is TenantRole.OWNER:
            raise PermissionError("owner role cannot be granted through membership management")
        if role is TenantRole.ADMIN and actor.role != TenantRole.OWNER:
            raise PermissionError("only an owner can grant the admin role")

        target = self._session.query(User).filter_by(email=target_email).one_or_none()
        if target is None:
            raise LookupError(f"no user with email={target_email}")

        membership = TenantMembership(
            tenant_id=tenant_id,
            user_id=target.id,
            role=role.value,
        )
        self._session.add_all(
            [
                membership,
                TenantAuditLog(
                    tenant_id=tenant_id,
                    actor_user_id=actor_user_id,
                    action="tenant.member_added",
                    target_user_id=target.id,
                    payload={"role": role.value},
                ),
            ]
        )
        self._session.flush()
        return membership

    def remove_member(
        self,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        target_user_id: uuid.UUID,
    ) -> None:
        actor = self.require_role(tenant_id, actor_user_id, TenantRole.OWNER, TenantRole.ADMIN)
        target = (
            self._session.query(TenantMembership)
            .filter_by(tenant_id=tenant_id, user_id=target_user_id)
            .one_or_none()
        )
        if target is None:
            raise LookupError(f"no membership for tenant_id={tenant_id} user_id={target_user_id}")

        if target.role == TenantRole.ADMIN and actor.role != TenantRole.OWNER:
            raise PermissionError("only an owner can remove an admin")
        if target.role == TenantRole.OWNER:
            if actor.role != TenantRole.OWNER:
                raise PermissionError("only an owner can remove an owner")
            (self._session.query(Tenant.id).filter(Tenant.id == tenant_id).with_for_update().one())
            owner_count = (
                self._session.query(TenantMembership)
                .filter_by(tenant_id=tenant_id, role=TenantRole.OWNER.value)
                .count()
            )
            if owner_count == 1:
                raise PermissionError("cannot remove the final owner")

        removed_role = str(target.role)
        self._session.delete(target)
        self._session.add(
            TenantAuditLog(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                action="tenant.member_removed",
                target_user_id=target_user_id,
                payload={"role": removed_role},
            )
        )
        self._session.flush()

    def require_role(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        *allowed_roles: TenantRole,
    ) -> TenantMembership:
        membership = (
            self._session.query(TenantMembership)
            .filter_by(tenant_id=tenant_id, user_id=user_id)
            .one_or_none()
        )
        if membership is None:
            raise LookupError(f"no membership for tenant_id={tenant_id} user_id={user_id}")
        allowed_values: Sequence[str] = tuple(role.value for role in allowed_roles)
        if allowed_values and membership.role not in allowed_values:
            raise PermissionError(
                f"role {membership.role!r} is not allowed; expected one of {allowed_values!r}"
            )
        return membership

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest
from app.models.tenant import Tenant, TenantAuditLog, TenantMembership
from app.models.user import User
from app.run_control.types import TenantRole
from app.services.tenant_service import TenantService
from sqlalchemy import text
from sqlalchemy.engine import Engine
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


def test_concurrent_cross_removals_cannot_delete_all_owners(
    pg_test_engine: Engine,
) -> None:
    with Session(pg_test_engine) as setup_session:
        owner_a = make_user(setup_session)
        owner_b = make_user(setup_session)
        tenant = TenantService(setup_session).create_with_owner(
            name="Concurrent owners", owner=owner_a
        )
        setup_session.add(
            TenantMembership(
                tenant_id=tenant.id,
                user_id=owner_b.id,
                role=TenantRole.OWNER,
            )
        )
        setup_session.commit()
        tenant_id = UUID(str(tenant.id))
        owner_a_id = UUID(str(owner_a.id))
        owner_b_id = UUID(str(owner_b.id))

    first_removed = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()
    second_finished = threading.Event()
    second_pid: list[int] = []

    def remove_b_then_wait() -> BaseException | None:
        with Session(pg_test_engine) as session:
            try:
                TenantService(session).remove_member(tenant_id, owner_a_id, owner_b_id)
                first_removed.set()
                if not release_first.wait(timeout=10):
                    raise TimeoutError("first removal was not released")
                session.commit()
            except BaseException as exc:
                session.rollback()
                return exc
        return None

    def remove_a_concurrently() -> BaseException | None:
        if not first_removed.wait(timeout=10):
            return TimeoutError("first removal did not reach its commit boundary")
        with Session(pg_test_engine) as session:
            second_pid.append(int(session.scalar(text("SELECT pg_backend_pid()"))))
            second_started.set()
            try:
                TenantService(session).remove_member(tenant_id, owner_b_id, owner_a_id)
                session.commit()
            except BaseException as exc:
                session.rollback()
                return exc
            finally:
                second_finished.set()
        return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(remove_b_then_wait)
        second_future = pool.submit(remove_a_concurrently)
        assert second_started.wait(timeout=10)

        deadline = time.monotonic() + 10
        while not second_finished.is_set() and time.monotonic() < deadline:
            with pg_test_engine.connect() as observer:
                wait_type = observer.scalar(
                    text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"),
                    {"pid": second_pid[0]},
                )
            if wait_type == "Lock":
                break
            time.sleep(0.01)
        release_first.set()

        first_error = first_future.result(timeout=10)
        second_error = second_future.result(timeout=10)

    with Session(pg_test_engine) as check_session:
        remaining_owners = (
            check_session.query(TenantMembership)
            .filter_by(tenant_id=tenant_id, role=TenantRole.OWNER)
            .count()
        )
        assert remaining_owners == 1
        assert check_session.get(Tenant, tenant_id) is not None
    assert first_error is None
    assert isinstance(second_error, (LookupError, PermissionError))


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

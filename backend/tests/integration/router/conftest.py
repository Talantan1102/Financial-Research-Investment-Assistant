"""Local fixtures for integration router tests.

Provides:
  - session: an in-memory sqlite session with the User + monitoring tables created
  - fake_auth: a real User row + dependency_overrides for get_current_user_required
  - client: TestClient wired with get_db override + dependency_overrides reset on teardown

`fake_auth` returns ``{"user_id": <id>, "headers": {"Authorization": "Bearer fake"}}``
so test calls can hit the endpoints without a real JWT round-trip.
"""

from __future__ import annotations

from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.models.monitoring import (
    MonitoringAlert,
    MonitoringRun,
    MonitoringSignal,
    Notification,
)
from app.models.user import User
from app.router.auth_router import get_current_user_required


@pytest.fixture
def session() -> Generator[Session, None, None]:
    """Fresh in-memory sqlite per test with the User + monitoring tables.

    Cannot use ``Base.metadata.create_all`` because other models pull in
    PG-only column types (e.g. JSONB) that sqlite can't compile.  Per-table
    create gives us only what these tests need.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    User.__table__.create(engine)
    MonitoringRun.__table__.create(engine)
    MonitoringSignal.__table__.create(engine)
    MonitoringAlert.__table__.create(engine)
    Notification.__table__.create(engine)

    Session_ = sessionmaker(bind=engine, expire_on_commit=False)
    sess = Session_()
    try:
        yield sess
    finally:
        sess.close()


@pytest.fixture
def fake_auth(session: Session) -> dict[str, object]:
    """Insert a real User row + override get_current_user_required to return it.

    The dependency override is registered on the global FastAPI app.  Tests must
    use the ``client`` fixture (which clears overrides on teardown).
    """
    from app.app_main import app

    uid = uuid4().hex[:8]
    user = User(
        id=str(uuid4()),
        username=f"u-{uid}",
        email=f"u-{uid}@test",
        hashed_password="x",
        is_active=True,
    )
    session.add(user)
    session.commit()

    app.dependency_overrides[get_current_user_required] = lambda: user
    return {
        "user_id": str(user.id),
        "headers": {"Authorization": "Bearer fake"},
    }


@pytest.fixture
def client(session: Session) -> Generator[TestClient, None, None]:
    """TestClient wired with get_db override.  Clears dependency_overrides on exit."""
    from app.app_main import app

    def _override_get_db() -> Generator[Session, None, None]:
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()

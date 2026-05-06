"""POST /auth/register endpoint — bcrypt 哈希 + 唯一约束 + EmailStr 校验.

Frontend (Task 5 frontend/src/api/auth.ts) is the ground truth:
- Path: POST /auth/register (no /api prefix in API call; vite proxies via VITE_API_BASE)
- Response shape: {access_token: str, token_type: str, user: UserInfo}

Test strategy: mount auth_router on a minimal FastAPI app + override get_db
with a tmp-path SQLite session. SQLAlchemy emulates postgresql.UUID on SQLite
since UUID inherits from generic sqltypes.Uuid (verified at session start).
"""

from __future__ import annotations

from collections.abc import Generator, Iterator
from pathlib import Path

import pytest
from app.core.database import Base, get_db
from app.models.user import User  # noqa: F401  — register table on Base.metadata
from app.router.auth_router import router as auth_router
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def db_engine(tmp_path: Path) -> Generator[Engine, None, None]:
    """Per-test SQLite file. Each test gets isolated state."""
    db_path = tmp_path / "test_auth.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine, tables=[User.__table__])
    yield engine
    engine.dispose()


@pytest.fixture
def client(db_engine: Engine) -> TestClient:
    """Minimal FastAPI app with only auth_router + get_db override → SQLite."""
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)

    def _override_get_db() -> Iterator[Session]:
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    test_app = FastAPI()
    test_app.include_router(auth_router)
    test_app.dependency_overrides[get_db] = _override_get_db
    return TestClient(test_app)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_register_creates_user_and_returns_token(client: TestClient) -> None:
    res = client.post(
        "/auth/register",
        json={"username": "alice_t7", "password": "secret123", "email": "alice_t7@b.com"},
    )
    assert res.status_code in (200, 201), res.text
    data = res.json()
    # Frontend ground truth: data.access_token (see frontend/src/api/auth.ts AuthResponse)
    assert "access_token" in data
    assert isinstance(data["access_token"], str) and data["access_token"]
    assert data["user"]["username"] == "alice_t7"
    assert data["user"]["email"] == "alice_t7@b.com"
    # Password fields must NOT leak in response
    assert "password" not in data["user"]
    assert "hashed_password" not in data["user"]


def test_register_password_is_bcrypt_hashed_not_plaintext(
    client: TestClient, db_engine: Engine
) -> None:
    """Verify password is stored as bcrypt hash, never plaintext."""
    res = client.post(
        "/auth/register",
        json={"username": "hashcheck_t7", "password": "secret123", "email": "h@b.com"},
    )
    assert res.status_code in (200, 201), res.text

    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    with TestingSession() as session:
        user = session.query(User).filter(User.username == "hashcheck_t7").first()
        assert user is not None
        # bcrypt hashes start with $2b$ / $2a$ and are ~60 chars; never plaintext
        assert user.hashed_password != "secret123"
        assert user.hashed_password.startswith("$2")
        assert len(user.hashed_password) >= 50


# ---------------------------------------------------------------------------
# Uniqueness
# ---------------------------------------------------------------------------


def test_register_rejects_duplicate_username(client: TestClient) -> None:
    res1 = client.post(
        "/auth/register",
        json={"username": "bob_t7", "password": "secret123", "email": "bob1@b.com"},
    )
    assert res1.status_code in (200, 201)
    res2 = client.post(
        "/auth/register",
        json={"username": "bob_t7", "password": "secret456", "email": "bob2@b.com"},
    )
    assert res2.status_code == 400


def test_register_rejects_duplicate_email(client: TestClient) -> None:
    res1 = client.post(
        "/auth/register",
        json={"username": "carol1_t7", "password": "secret123", "email": "carol@b.com"},
    )
    assert res1.status_code in (200, 201)
    res2 = client.post(
        "/auth/register",
        json={"username": "carol2_t7", "password": "secret456", "email": "carol@b.com"},
    )
    assert res2.status_code == 400


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_register_rejects_invalid_email(client: TestClient) -> None:
    res = client.post(
        "/auth/register",
        json={"username": "dave_t7", "password": "secret123", "email": "not-email"},
    )
    # Pydantic EmailStr → 422 Unprocessable Entity
    assert res.status_code == 422


def test_register_rejects_short_password(client: TestClient) -> None:
    res = client.post(
        "/auth/register",
        json={"username": "eve_t7", "password": "12", "email": "eve@b.com"},
    )
    # Schema enforces min_length=6 → 422
    assert res.status_code in (400, 422)

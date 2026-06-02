"""L0 — unit tests: pure functions / Pydantic / no LLM calls."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture(autouse=True)
def _force_llm_mode_none(monkeypatch):
    """Force LLM_MODE=none for every test in the unit layer."""
    monkeypatch.setenv("LLM_MODE", "none")
    yield


@pytest.fixture(autouse=True)
def _unset_proxy_env(monkeypatch):
    """Unit tests must not route through the dev-shell SOCKS proxy.

    Many local dev shells set all_proxy=socks5://... for web traffic. httpx
    picks up these env vars and tries to create a SOCKS transport (requires
    the socksio extra). Strip them so unit tests that construct httpx / OpenAI
    clients don't fail even when socksio isn't installed.
    """
    for var in (
        "all_proxy",
        "ALL_PROXY",
        "https_proxy",
        "HTTPS_PROXY",
        "http_proxy",
        "HTTP_PROXY",
    ):
        monkeypatch.delenv(var, raising=False)
    yield


@pytest_asyncio.fixture
async def async_session_factory(
    pg_test_container: dict[str, object],
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Function-scoped async session factory backed by the real PG test DB.

    pg_test_engine (session-scoped) already ran DROP SCHEMA CASCADE + create_all,
    so tables exist.  Each test gets a fresh async engine (connection pool) so
    the async chat repos — which call ``async with session_factory() as sess``
    internally — work without savepoint gymnastics.

    Isolation: repos use unique UUIDs per test; no cross-test row collisions.
    Engine is disposed on test teardown so connections are returned to PG.
    """
    from tests.pg_test_defaults import PG_PASSWORD_DEFAULT  # C37: SSOT

    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", PG_PASSWORD_DEFAULT)
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "industry_assistant_test")
    url = f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db}"

    engine = create_async_engine(url, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()

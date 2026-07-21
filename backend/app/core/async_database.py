"""Shared async SQLAlchemy construction for application services."""

import os

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def _sqlalchemy_async_pg_url() -> str:
    """Return the configured PostgreSQL URL for SQLAlchemy's psycopg3 driver."""
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.environ["POSTGRES_PASSWORD"]
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    database = os.getenv("POSTGRES_DB", "industry_assistant")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{database}"


def build_async_database() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Build the shared async engine and session factory for the web process."""
    engine = create_async_engine(_sqlalchemy_async_pg_url(), future=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False)

"""Crash-visible disposable PostgreSQL runtime for business conversation evals."""

from __future__ import annotations

import asyncio
import re
from enum import StrEnum
from hashlib import sha256
from typing import Any

import psycopg
from psycopg import sql
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker


class RuntimeState(StrEnum):
    NEW = "new"
    PROVISIONING = "provisioning"
    READY = "ready"
    CLOSING = "closing"
    CLOSED = "closed"
    BROKEN = "broken"
    LEAKED = "leaked"


class RuntimeCleanupError(RuntimeError):
    """The disposable database could not be proven absent after cleanup."""


class DisposableEvalRuntime:
    """Own one run-scoped database and expose only factories bound to it.

    PostgreSQL is physically isolated. AGE data is therefore removed with the
    database. Milvus and the durable API/worker process are not yet namespaced;
    callers must request those capabilities and fail closed before seeding.
    """

    def __init__(self, *, admin_dsn: str, run_id: str, database_name: str) -> None:
        self.admin_dsn = admin_dsn
        self.run_id = run_id
        self.database_name = database_name
        self.state = RuntimeState.NEW
        self._sync_engine: Any | None = None
        self._async_engine: Any | None = None
        self._sync_session_factory: sessionmaker[Session] | None = None
        self._async_session_factory: async_sessionmaker[AsyncSession] | None = None

    @classmethod
    def provision(cls, *, admin_dsn: str, run_id: str) -> DisposableEvalRuntime:
        if not run_id.strip():
            raise ValueError("run_id must be non-empty")
        admin_url = make_url(admin_dsn)
        if not admin_url.database:
            raise ValueError("admin_dsn must name an administrative database")
        database_name = _database_name(run_id)
        runtime = cls(admin_dsn=admin_dsn, run_id=run_id, database_name=database_name)
        runtime.state = RuntimeState.PROVISIONING
        try:
            runtime._create_database()
            runtime._initialize_schema(admin_url)
        except Exception:
            runtime.state = RuntimeState.BROKEN
            try:
                runtime._drop_database()
            except Exception as cleanup_error:
                runtime.state = RuntimeState.LEAKED
                raise RuntimeCleanupError(
                    f"provisioning failed and database leaked: {database_name}"
                ) from cleanup_error
            raise
        runtime.state = RuntimeState.READY
        return runtime

    @property
    def sync_session_factory(self) -> sessionmaker[Session]:
        self._require_ready()
        assert self._sync_session_factory is not None
        return self._sync_session_factory

    @property
    def async_session_factory(self) -> async_sessionmaker[AsyncSession]:
        self._require_ready()
        assert self._async_session_factory is not None
        return self._async_session_factory

    @property
    def subprocess_env(self) -> dict[str, str]:
        """Database overrides for evaluator-owned child processes such as MCP."""
        self._require_ready()
        url = make_url(self.admin_dsn).set(database=self.database_name)
        return {
            "POSTGRES_HOST": str(url.host or ""),
            "POSTGRES_PORT": str(url.port or 5432),
            "POSTGRES_USER": str(url.username or ""),
            "POSTGRES_PASSWORD": str(url.password or ""),
            "POSTGRES_DB": self.database_name,
        }

    def require_capabilities(
        self,
        *,
        memory: bool = False,
        durable: bool = False,
    ) -> None:
        self._require_ready()
        if memory:
            raise RuntimeError(
                "memory isolation is unavailable: a run-scoped Milvus collection is required"
            )
        if durable:
            raise RuntimeError(
                "durable stack isolation is unavailable: API and worker runtime binding is required"
            )

    async def aclose(self) -> None:
        if self.state is RuntimeState.CLOSED:
            return
        if self.state is RuntimeState.CLOSING:
            raise RuntimeError("runtime cleanup is already in progress")
        self.state = RuntimeState.CLOSING
        try:
            if self._async_engine is not None:
                await self._async_engine.dispose()
            if self._sync_engine is not None:
                self._sync_engine.dispose()
            self._drop_database()
        except Exception as exc:
            self.state = RuntimeState.LEAKED
            raise RuntimeCleanupError(
                f"could not prove disposable database was removed: {self.database_name}"
            ) from exc
        self.state = RuntimeState.CLOSED

    def close(self) -> None:
        if self.state is RuntimeState.CLOSED:
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.aclose())
            return
        raise RuntimeError("close() cannot run inside an event loop; await aclose()")

    def _require_ready(self) -> None:
        if self.state is not RuntimeState.READY:
            raise RuntimeError(f"eval runtime is not ready: {self.state.value}")

    def _create_database(self) -> None:
        with (
            psycopg.connect(self.admin_dsn, autocommit=True) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(
                    sql.Identifier(self.database_name)
                )
            )

    def _initialize_schema(self, admin_url: URL) -> None:
        # Import model barrels before create_all so the shared Base is complete.
        import app.models  # noqa: F401
        import app.services.trace_models  # noqa: F401
        from app.core.database import Base

        import eval.chatloop.recorder  # noqa: F401

        database_url = admin_url.set(database=self.database_name)
        sync_dsn = database_url.render_as_string(hide_password=False)
        async_dsn = database_url.set(drivername="postgresql+psycopg").render_as_string(
            hide_password=False
        )
        self._sync_engine = create_engine(sync_dsn, future=True, pool_pre_ping=True)
        with self._sync_engine.begin() as connection:
            connection.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
        Base.metadata.create_all(bind=self._sync_engine)
        with self._sync_engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE eval_runtime_meta ("
                    "singleton smallint PRIMARY KEY CHECK (singleton = 1), "
                    "run_id text NOT NULL, database_name text NOT NULL)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO eval_runtime_meta(singleton, run_id, database_name) "
                    "VALUES (1, :run_id, :database_name)"
                ),
                {"run_id": self.run_id, "database_name": self.database_name},
            )
        self._sync_session_factory = sessionmaker(
            bind=self._sync_engine,
            expire_on_commit=False,
        )
        self._async_engine = create_async_engine(async_dsn, future=True, pool_pre_ping=True)
        self._async_session_factory = async_sessionmaker(
            self._async_engine,
            expire_on_commit=False,
        )

    def _drop_database(self) -> None:
        with (
            psycopg.connect(self.admin_dsn, autocommit=True) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (self.database_name,),
            )
            cursor.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(self.database_name))
            )
            cursor.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (self.database_name,),
            )
            if cursor.fetchone() is not None:
                raise RuntimeError(f"database still exists: {self.database_name}")


def _database_name(run_id: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", run_id.lower()).strip("_")[:24] or "run"
    digest = sha256(run_id.encode()).hexdigest()[:12]
    return f"fria_eval_{slug}_{digest}"


__all__ = [
    "DisposableEvalRuntime",
    "RuntimeCleanupError",
    "RuntimeState",
]

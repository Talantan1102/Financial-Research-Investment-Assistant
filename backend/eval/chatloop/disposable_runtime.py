"""Crash-visible disposable PostgreSQL runtime for business conversation evals."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
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


@dataclass(frozen=True)
class RuntimeCleanupFailure:
    """One failed cleanup stage retained for audit and diagnosis."""

    stage: str
    error: BaseException


class RuntimeCleanupError(RuntimeError):
    """One or more cleanup stages failed, with explicit database leak status."""

    def __init__(
        self,
        *,
        database_name: str,
        database_leaked: bool,
        failures: tuple[tuple[str, BaseException], ...],
    ) -> None:
        if not failures:
            raise ValueError("runtime cleanup error requires at least one failure")
        self.database_name = database_name
        self.database_leaked = database_leaked
        self.failures = tuple(RuntimeCleanupFailure(stage, error) for stage, error in failures)
        state = "database leak not excluded" if database_leaked else "database removed"
        details = "; ".join(
            f"{failure.stage}: {type(failure.error).__name__}: {failure.error}"
            for failure in self.failures
        )
        super().__init__(f"runtime cleanup incomplete ({state}): {details}")


class DisposableEvalRuntime:
    """Own one run-scoped database and expose only factories bound to it.

    PostgreSQL is physically isolated. AGE data is therefore removed with the
    database. Milvus is not yet namespaced. Durable cases are admitted only
    while an evaluator-owned in-process driver is bound to this exact async
    session factory; otherwise capability preflight fails before seeding.
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
        self._durable_driver: Any | None = None

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
                    database_name=database_name,
                    database_leaked=True,
                    failures=(("drop_database", cleanup_error),),
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
            driver = self._durable_driver
            if (
                driver is None
                or not driver.is_open
                or driver.session_factory is not self.async_session_factory
            ):
                raise RuntimeError(
                    "durable stack isolation is unavailable: "
                    "API and worker runtime binding is required"
                )

    def bind_durable_driver(self, driver: Any) -> None:
        """Bind only the evaluator-owned driver using this runtime's factory."""
        from eval.chatloop.durable_runtime import InProcessDurableDriver

        self._require_ready()
        if not isinstance(driver, InProcessDurableDriver):
            raise TypeError("durable binding requires an InProcessDurableDriver")
        if driver.session_factory is not self.async_session_factory:
            raise ValueError("durable driver is not bound to this disposable runtime")
        if not driver.is_open:
            raise ValueError("durable driver is already closed")
        self._durable_driver = driver

    async def aclose(self) -> None:
        if self.state is RuntimeState.CLOSED:
            return
        if self.state is RuntimeState.CLOSING:
            raise RuntimeError("runtime cleanup is already in progress")
        self.state = RuntimeState.CLOSING
        failures: list[tuple[str, BaseException]] = []
        if self._durable_driver is not None:
            try:
                await self._durable_driver.aclose()
            except BaseException as exc:
                failures.append(("durable_driver", exc))
        if self._async_engine is not None:
            try:
                await self._async_engine.dispose()
            except BaseException as exc:
                failures.append(("async_engine", exc))
        if self._sync_engine is not None:
            try:
                self._sync_engine.dispose()
            except BaseException as exc:
                failures.append(("sync_engine", exc))
        database_removed = False
        try:
            self._drop_database()
            database_removed = True
        except BaseException as exc:
            failures.append(("drop_database", exc))
        self.state = RuntimeState.CLOSED if database_removed else RuntimeState.LEAKED
        cancellation = next(
            (error for _stage, error in failures if isinstance(error, asyncio.CancelledError)),
            None,
        )
        if database_removed and cancellation is not None:
            for stage, failure in failures:
                if failure is cancellation:
                    continue
                cancellation.add_note(
                    f"additional cleanup failure at {stage}: {type(failure).__name__}: {failure}"
                )
            raise cancellation
        if failures:
            error = RuntimeCleanupError(
                database_name=self.database_name,
                database_leaked=not database_removed,
                failures=tuple(failures),
            )
            raise error from failures[-1][1]

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
    "RuntimeCleanupFailure",
    "RuntimeState",
]

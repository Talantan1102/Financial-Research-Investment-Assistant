from __future__ import annotations

from uuid import uuid4

import psycopg
import pytest
from eval.chatloop.disposable_runtime import DisposableEvalRuntime, RuntimeState
from sqlalchemy import text


def _admin_dsn(pg_test_container: dict[str, object]) -> str:
    return (
        f"postgresql://{pg_test_container['user']}:{pg_test_container['password']}"
        f"@{pg_test_container['host']}:{pg_test_container['port']}/postgres"
    )


def _database_exists(admin_dsn: str, name: str) -> bool:
    with (
        psycopg.connect(admin_dsn, autocommit=True) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
        return cursor.fetchone() is not None


@pytest.mark.asyncio
async def test_runtime_creates_marked_database_and_drops_it(
    pg_test_container: dict[str, object],
) -> None:
    admin_dsn = _admin_dsn(pg_test_container)
    runtime = DisposableEvalRuntime.provision(
        admin_dsn=admin_dsn,
        run_id=f"runtime-{uuid4().hex}",
    )
    database_name = runtime.database_name

    try:
        assert runtime.state is RuntimeState.READY
        assert database_name.startswith("fria_eval_")
        assert _database_exists(admin_dsn, database_name)
        async with runtime.async_session_factory() as session:
            assert await session.scalar(text("SELECT current_database()")) == database_name
            marker = (
                await session.execute(
                    text("SELECT run_id, database_name FROM eval_runtime_meta WHERE singleton = 1")
                )
            ).one()
        assert marker.run_id == runtime.run_id
        assert marker.database_name == database_name
    finally:
        await runtime.aclose()

    assert runtime.state is RuntimeState.CLOSED
    assert not _database_exists(admin_dsn, database_name)


def test_runtime_close_is_idempotent(pg_test_container: dict[str, object]) -> None:
    runtime = DisposableEvalRuntime.provision(
        admin_dsn=_admin_dsn(pg_test_container),
        run_id=f"idempotent-{uuid4().hex}",
    )

    runtime.close()
    runtime.close()

    assert runtime.state is RuntimeState.CLOSED


def test_unsupported_external_isolation_fails_closed_before_use(
    pg_test_container: dict[str, object],
) -> None:
    runtime = DisposableEvalRuntime.provision(
        admin_dsn=_admin_dsn(pg_test_container),
        run_id=f"capabilities-{uuid4().hex}",
    )
    try:
        with pytest.raises(RuntimeError, match="memory isolation"):
            runtime.require_capabilities(memory=True)
        with pytest.raises(RuntimeError, match="durable stack isolation"):
            runtime.require_capabilities(durable=True)
    finally:
        runtime.close()

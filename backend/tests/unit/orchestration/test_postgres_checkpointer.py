"""L0/L2 — AsyncPostgresSaver factory tests.

L0: pure unit tests — validate config model defaults and custom values (no I/O).
L2: real-PG smoke test — opens pool, runs saver.setup(), verifies tables created.
     Skipped if POSTGRES_DSN env var is absent.
"""

from __future__ import annotations

import os

import pytest

# ---------------------------------------------------------------------------
# L0 — config model tests (no I/O)
# ---------------------------------------------------------------------------


def test_postgres_checkpointer_config_defaults() -> None:
    """PostgresCheckpointerConfig has sensible defaults for pool sizes and conn_kwargs."""
    from app.orchestration.postgres_checkpointer import PostgresCheckpointerConfig

    cfg = PostgresCheckpointerConfig(conninfo="postgresql://localhost/test")
    assert cfg.min_pool_size == 2
    assert cfg.max_pool_size == 10
    assert cfg.conninfo == "postgresql://localhost/test"
    # Default conn_kwargs must scope DDL to langgraph_checkpoints schema
    assert "options" in cfg.conn_kwargs
    assert "langgraph_checkpoints" in cfg.conn_kwargs["options"]
    # autocommit required for CREATE INDEX CONCURRENTLY in saver.setup()
    assert cfg.conn_kwargs.get("autocommit") is True


def test_postgres_checkpointer_config_custom() -> None:
    """PostgresCheckpointerConfig accepts custom pool sizes."""
    from app.orchestration.postgres_checkpointer import PostgresCheckpointerConfig

    cfg = PostgresCheckpointerConfig(
        conninfo="postgresql://user:pass@host:5432/db",
        min_pool_size=1,
        max_pool_size=5,
    )
    assert cfg.min_pool_size == 1
    assert cfg.max_pool_size == 5


def test_postgres_checkpointer_config_requires_conninfo() -> None:
    """PostgresCheckpointerConfig raises ValidationError when conninfo is missing."""
    import pydantic
    from app.orchestration.postgres_checkpointer import PostgresCheckpointerConfig

    with pytest.raises(pydantic.ValidationError):
        PostgresCheckpointerConfig()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# L2 — real-PG smoke test
# ---------------------------------------------------------------------------

from tests.pg_test_defaults import PG_PASSWORD_DEFAULT  # C37: SSOT

_PG_CONNINFO = f"postgresql://postgres:{PG_PASSWORD_DEFAULT}@localhost:5432/industry_assistant"
# search_path is passed via conn_kwargs (not in URI) to avoid psycopg3's URI parser
# rejecting the nested "=" inside "options=-csearch_path=...".
# autocommit + prepare_threshold=0 match lcp's from_conn_string() defaults and are
# required for CREATE INDEX CONCURRENTLY (used in saver.setup()).
_PG_CONN_KWARGS = {
    "options": "-csearch_path=langgraph_checkpoints",
    "autocommit": True,
    "prepare_threshold": 0,
}

_SKIP_REASON = "Real PG not available (set POSTGRES_DSN or use default)"


def _pg_available() -> bool:
    """Return True if the PG instance is reachable."""
    import socket

    try:
        s = socket.create_connection(("localhost", 5432), timeout=2)
        s.close()
        return True
    except OSError:
        return False


@pytest.mark.asyncio
@pytest.mark.slow
@pytest.mark.skipif(not _pg_available(), reason=_SKIP_REASON)
async def test_make_postgres_checkpointer_real_pg() -> None:
    """Factory opens pool, calls saver.setup(), returns AsyncPostgresSaver instance."""
    from app.orchestration.postgres_checkpointer import (
        PostgresCheckpointerConfig,
        make_postgres_checkpointer,
    )
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    dsn = os.environ.get("POSTGRES_DSN", _PG_CONNINFO)
    cfg = PostgresCheckpointerConfig(conninfo=dsn, conn_kwargs=_PG_CONN_KWARGS)
    saver = await make_postgres_checkpointer(cfg)

    assert isinstance(saver, AsyncPostgresSaver)
    # Verify pool is open — pool.closed should be False
    assert not saver.conn.closed

    # Cleanup — close the pool
    await saver.conn.close()

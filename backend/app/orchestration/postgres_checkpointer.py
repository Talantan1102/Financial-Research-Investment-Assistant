"""AsyncPostgresSaver factory — replaces legacy SqliteSaver for chat + research graphs.

LangGraph 1.x checkpointer using PG (psycopg3 backend in langgraph-checkpoint-postgres
3.x), persisting graph state to schema ``langgraph_checkpoints``.

The factory follows an explicit pool-open lifecycle:
  - ``AsyncConnectionPool`` is constructed with ``open=False``
  - ``await pool.open()`` is called before handing it to AsyncPostgresSaver
  - ``await saver.setup()`` runs DDL migrations inside the configured schema

Design note on search_path:
  psycopg3's URI parser rejects ``?options=-csearch_path=...`` (the ``=`` inside
  the value breaks the key=value URI grammar).  Instead we pass connection-time
  keyword args via the pool's ``kwargs`` parameter, which is forwarded to every
  new connection as keyword arguments to ``psycopg.AsyncConnection.connect()``.
  The caller should set ``conn_kwargs={"options": "-csearch_path=langgraph_checkpoints"}``
  rather than encoding options in the conninfo URI.
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, Field


class PostgresCheckpointerConfig(BaseModel):
    """Connection and pool configuration for the Postgres-backed checkpointer.

    Attributes:
        conninfo: A psycopg3-compatible connection info string (URI or keyword=value form).
            Do NOT embed ``options=-csearch_path=...`` in the URI — use ``conn_kwargs``
            instead to avoid URI encoding issues with nested ``=`` characters.
        conn_kwargs: Extra keyword arguments forwarded to every new pool connection
            (e.g. ``{"options": "-csearch_path=langgraph_checkpoints"}``).
        min_pool_size: Minimum number of connections kept alive in the pool.
        max_pool_size: Maximum number of connections the pool may open.
    """

    conninfo: str = Field(..., description="psycopg3 conninfo string for the PG database")
    conn_kwargs: dict[str, Any] = Field(
        default_factory=lambda: {
            "options": "-csearch_path=langgraph_checkpoints",
            # autocommit=True is required by AsyncPostgresSaver.setup() because
            # it issues CREATE INDEX CONCURRENTLY, which cannot run inside a
            # transaction block.  prepare_threshold=0 disables server-side
            # prepared statements (matches lcp's from_conn_string() defaults).
            "autocommit": True,
            "prepare_threshold": 0,
        },
        description="Extra kwargs forwarded to each new pool connection",
    )
    min_pool_size: int = Field(default=2, ge=1, description="Minimum pool connections")
    max_pool_size: int = Field(default=10, ge=1, description="Maximum pool connections")


async def make_postgres_checkpointer(
    cfg: PostgresCheckpointerConfig,
) -> AsyncPostgresSaver:
    """Build and ``setup()`` an AsyncPostgresSaver from config.

    Opens an ``AsyncConnectionPool`` using psycopg3 (the driver used by
    langgraph-checkpoint-postgres 3.x), then calls ``saver.setup()`` to
    apply DDL migrations (creates ``checkpoints``, ``checkpoint_blobs``,
    ``checkpoint_writes``, and ``checkpoint_migrations`` tables inside the
    schema specified by ``conn_kwargs["options"]``).

    Args:
        cfg: Pool and connection configuration.

    Returns:
        A fully initialised :class:`~langgraph.checkpoint.postgres.aio.AsyncPostgresSaver`
        whose underlying pool is open.  The caller owns the pool lifecycle —
        call ``await saver.conn.close()`` on shutdown.
    """
    pool: AsyncConnectionPool = AsyncConnectionPool(
        conninfo=cfg.conninfo,
        kwargs=cfg.conn_kwargs,
        min_size=cfg.min_pool_size,
        max_size=cfg.max_pool_size,
        open=False,  # explicit open() gives us lifecycle control
    )
    await pool.open()
    saver = AsyncPostgresSaver(pool)
    await saver.setup()
    return saver

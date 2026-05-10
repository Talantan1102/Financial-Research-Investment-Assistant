"""Integration test fixtures for backend/app/memory/.

Shape 跟 v1.0 monitoring / v0.9.x pg_test_container 一致(契约 § 6).

Per shared contract § 17 A1, Plan 1A creates this conftest with the initial
fixtures (pg_memory_fixture / pg_memory_session); milvus_memory_fixture is
added in Task 7. Plan 1B will Edit to add additional fixtures.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# ---------------------------------------------------------------------------
# pg_memory_fixture — 真 PG + create_all + 跑 SQL migration
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def pg_memory_fixture(pg_test_container: dict[str, object]) -> Iterator[dict[str, Any]]:
    """real PG + chat_memory_* 4 表 + SQL migration 已 apply.

    依赖 backend/tests/conftest.py 的 pg_test_container(已 ship v0.9.x).
    """
    url = str(pg_test_container["url"])
    engine = create_engine(url, future=True)

    # 1. create_all 4 表(走 SQLAlchemy)
    # 显式 import barrel + memory models 让 metadata 注册
    import app.models  # noqa: F401  barrel registers chat_memory_* + FK targets
    from app.core.database import Base

    # Pre-flight cleanup: drop existing chat_memory_* tables in case test db
    # has stale schema from prior plan iterations / failed runs. Order matters
    # (edges → nodes/episodes due to FK).
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS chat_memory_edges CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS chat_memory_nodes CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS chat_memory_episodes CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS chat_memory_working_blocks CASCADE"))

    # Selective create: only the 4 chat_memory_* tables (FK target tables —
    # users / chat_sessions — already exist in test db with legacy schema).
    from app.memory.models import (
        ChatMemoryEdge,
        ChatMemoryEpisode,
        ChatMemoryNode,
        ChatMemoryWorkingBlock,
    )

    target_tables = [
        ChatMemoryEpisode.__table__,
        ChatMemoryNode.__table__,
        ChatMemoryEdge.__table__,
        ChatMemoryWorkingBlock.__table__,
    ]
    Base.metadata.create_all(bind=engine, tables=target_tables)

    # 2. apply SQL migration(partial index / GIN / AGE / GENERATED tsvector)
    # backend_dir = backend/tests/integration/memory/conftest.py → parents[3] = backend/
    backend_dir = Path(__file__).resolve().parents[3]
    migration_path = backend_dir / "scripts" / "migrations" / "2026-05-11-c5-memory-schema.sql"
    if migration_path.exists():
        sql = migration_path.read_text(encoding="utf-8")
        with engine.begin() as conn:
            conn.execute(text(sql))

    yield {"url": url, "engine": engine, **pg_test_container}

    engine.dispose()


@pytest.fixture
def pg_memory_session(pg_memory_fixture: dict[str, Any]) -> Iterator[Any]:
    """function-scoped Session, 每 test 自己 rollback."""
    engine = pg_memory_fixture["engine"]
    Session = sessionmaker(bind=engine, future=True)
    session = Session()
    yield session
    session.rollback()
    session.close()


# ---------------------------------------------------------------------------
# milvus_memory_fixture — 真 Milvus + chat_memory_edge_embeddings_v1 + alias
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def milvus_memory_fixture(
    milvus_test_container: dict[str, object],
) -> Iterator[dict[str, Any]]:
    """Real Milvus + chat_memory_edge_embeddings_v1 collection + alias 已建.

    依赖 backend/tests/conftest.py 的 milvus_test_container(已 ship v0.7).
    """
    from app.memory.milvus_setup import (
        ALIAS_NAME,
        COLLECTION_V1_NAME,
        ensure_chat_memory_edge_collection,
    )

    host = str(milvus_test_container["host"])
    port = int(str(milvus_test_container["port"]))

    # 幂等创建
    ensure_chat_memory_edge_collection(host=host, port=port)

    yield {
        "host": host,
        "port": port,
        "collection_name": COLLECTION_V1_NAME,
        "alias_name": ALIAS_NAME,
    }

    # session 末不清理(跟 milvus_test_container 同 fail-safe)

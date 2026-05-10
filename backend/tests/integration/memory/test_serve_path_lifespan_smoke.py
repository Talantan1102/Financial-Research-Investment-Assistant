"""L1 verify app_main.lifespan 起来能 apply C.5 migration + ensure Milvus collection.

依赖 pg_test_container + milvus_test_container 都 up.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_PG_TESTS") == "1" or os.environ.get("SKIP_MILVUS_TESTS") == "1",
    reason="PG + Milvus required",
)


def test_app_main_imports_without_error() -> None:
    """import smoke — 不能因 c5 migration apply 把 lifespan 撞挂."""
    from app.app_main import app  # noqa: F401


def test_lifespan_applies_c5_migration(
    pg_test_container: dict[str, object],
    milvus_test_container: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fastapi lifespan startup → c5 schema 已 apply, c5 collection 已建."""
    monkeypatch.setenv("POSTGRES_HOST", str(pg_test_container["host"]))
    monkeypatch.setenv("POSTGRES_PORT", str(pg_test_container["port"]))
    monkeypatch.setenv("POSTGRES_DB", str(pg_test_container["db"]))
    monkeypatch.setenv("MILVUS_HOST", str(milvus_test_container["host"]))
    monkeypatch.setenv("MILVUS_PORT", str(milvus_test_container["port"]))
    monkeypatch.setenv("LLM_MODE", "mock")

    from app.app_main import app
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, text

    with TestClient(app):
        # lifespan startup 已跑
        engine = create_engine(str(pg_test_container["url"]))
        with engine.begin() as conn:
            # partial index 应当存在
            rows = conn.execute(
                text("SELECT 1 FROM pg_indexes WHERE indexname = 'idx_edges_current_snapshot'")
            ).fetchall()
            assert len(rows) == 1

        from pymilvus import MilvusClient

        m = MilvusClient(
            uri=f"http://{milvus_test_container['host']}:{milvus_test_container['port']}"
        )
        assert m.has_collection("chat_memory_edge_embeddings_v1")

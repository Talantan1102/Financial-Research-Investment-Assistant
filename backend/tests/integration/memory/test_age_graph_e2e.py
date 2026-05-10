"""L1 verify AGE 'chat_memory' graph + 7 vlabel + 11 elabel.

AGE 不可用时 skip(macOS dev / postgres:15 镜像无 AGE 扩展).
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_PG_TESTS") == "1",
    reason="PG container required",
)


def _age_available(engine: Any) -> bool:
    """Probe AGE 扩展是否真的加载."""
    try:
        with engine.begin() as conn:
            conn.execute(text("LOAD 'age'"))
            rows = conn.execute(
                text("SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'chat_memory'")
            ).fetchall()
            return len(rows) == 1
    except Exception:
        return False


def test_age_chat_memory_graph_exists(pg_memory_fixture: dict[str, Any]) -> None:
    engine = pg_memory_fixture["engine"]
    if not _age_available(engine):
        pytest.skip("AGE extension not available in this PG instance")

    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT name FROM ag_catalog.ag_graph WHERE name = 'chat_memory'")
        ).fetchall()
    assert len(rows) == 1


@pytest.mark.parametrize(
    "vlabel",
    [
        "User",
        "Stock",
        "Industry",
        "Sector",
        "Metric",
        "Strategy",
        "Concept",
    ],
)
def test_all_7_vlabels_created(pg_memory_fixture: dict[str, Any], vlabel: str) -> None:
    engine = pg_memory_fixture["engine"]
    if not _age_available(engine):
        pytest.skip("AGE extension not available")
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT name FROM ag_catalog.ag_label WHERE name = :n AND kind = 'v'"),
            {"n": vlabel},
        ).fetchall()
    assert len(rows) == 1, f"vlabel {vlabel} not created"


@pytest.mark.parametrize(
    "elabel",
    [
        "HOLDS",
        "WATCHES",
        "PREFERS",
        "AVOIDS",
        "EXPRESSED_VIEW",
        "SOLD",
        "STUDIED",
        "COMPARED",
        "BELONGS_TO",
        "HAS_CONCEPT",
        "CORRELATED_WITH",
    ],
)
def test_all_11_elabels_created(pg_memory_fixture: dict[str, Any], elabel: str) -> None:
    engine = pg_memory_fixture["engine"]
    if not _age_available(engine):
        pytest.skip("AGE extension not available")
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT name FROM ag_catalog.ag_label WHERE name = :n AND kind = 'e'"),
            {"n": elabel},
        ).fetchall()
    assert len(rows) == 1, f"elabel {elabel} not created"


def test_basic_cypher_create_match(pg_memory_fixture: dict[str, Any]) -> None:
    """smoke: Cypher CREATE + MATCH 通."""
    engine = pg_memory_fixture["engine"]
    if not _age_available(engine):
        pytest.skip("AGE extension not available")

    with engine.begin() as conn:
        conn.execute(text("LOAD 'age'"))
        conn.execute(text("SET search_path = ag_catalog, public"))
        # CREATE Stock node
        conn.execute(
            text(
                """
                SELECT * FROM cypher('chat_memory', $$
                    CREATE (s:Stock {ts_code: '600519.SH'})
                    RETURN s
                $$) AS (s ag_catalog.agtype)
                """
            )
        )
        # MATCH 回来
        rows = conn.execute(
            text(
                """
                SELECT * FROM cypher('chat_memory', $$
                    MATCH (s:Stock {ts_code: '600519.SH'})
                    RETURN s
                $$) AS (s ag_catalog.agtype)
                """
            )
        ).fetchall()
        assert len(rows) >= 1
        # 清理避免污染
        conn.execute(
            text(
                """
                SELECT * FROM cypher('chat_memory', $$
                    MATCH (s:Stock {ts_code: '600519.SH'})
                    DELETE s
                $$) AS (deleted ag_catalog.agtype)
                """
            )
        )

"""Plan 2 Task 6 — Milvus 真路径相关推荐 integration test.

需启动真 Milvus + qwen embedding API key,否则全部 skip。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from starlette.testclient import TestClient

milvus_skip = pytest.mark.skipif(
    os.getenv("MILVUS_HOST") is None, reason="needs real Milvus + embedding key"
)


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    from dashboard import server

    db = tmp_path / "board.db"
    monkeypatch.setattr(server, "DB_PATH", db)
    if os.getenv("MILVUS_HOST"):
        monkeypatch.setattr(server, "MILVUS_HOST", os.environ["MILVUS_HOST"])
    return TestClient(server.app)


@milvus_skip
def test_milvus_recommend_returns_real_hits(client: TestClient, tmp_path: Path) -> None:
    """Seed 3 DeepCard,Milvus upsert,再 query。"""
    from dashboard.derive.deep_card_types import DeepCard
    from dashboard.state.db import open_db
    from dashboard.state.repositories import DeepCardRepo

    db = tmp_path / "board.db"
    conn = open_db(db)
    repo = DeepCardRepo(conn)
    repo.upsert(
        DeepCard(
            cap_id="x.a",
            what="LangGraph supervisor + planner",
            why="multi-agent 编排",
        )
    )
    repo.upsert(DeepCard(cap_id="x.b", what="LangGraph Send API subgraph"))
    repo.upsert(DeepCard(cap_id="x.c", what="完全无关内容"))

    # 手动触发 upsert 到 Milvus
    resp = client.post("/admin/milvus/reindex")
    assert resp.status_code == 200

    resp = client.get("/cap/x.a/related?k=2")
    assert resp.headers.get("X-Milvus-Status") == "ok"
    body = resp.json()
    ids = [r["cap_id"] for r in body]
    assert "x.b" in ids
    assert "x.c" not in ids  # 应该在低位 / 不返回


def test_milvus_reindex_disabled_returns_503(client: TestClient) -> None:
    """无 MILVUS_HOST 时 reindex 503 — 无需真 Milvus,可常跑。"""
    from dashboard import server

    if server.MILVUS_HOST is not None:
        pytest.skip("Milvus enabled; skip the disabled-path test")
    resp = client.post("/admin/milvus/reindex")
    assert resp.status_code == 503

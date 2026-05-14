"""L2 e2e — refresh pipeline 跑完后,鸟瞰 graph.json 反映新 seed 数据。

spec § 8 验收标准 1:渲染 ≥ 35 节点 + ≥ 10 edges。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("dashboard.server.DB_PATH", tmp_path / "board.db")
    monkeypatch.delenv("HARNESS_BOARD_MILVUS_HOST", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)


def test_overview_graph_after_refresh_has_filled_nodes() -> None:
    """rough path:启动(lifespan ingest)→ GET /api/overview/graph.json,
    至少 35 + edges ≥ 10。"""
    from dashboard.server import app

    with TestClient(app) as client:
        # lifespan 在 with 进入时已跑 seed ingest
        r = client.get("/api/overview/graph.json")
        assert r.status_code == 200
        payload = r.json()

    nodes = payload.get("nodes") or payload.get("elements", {}).get("nodes") or []
    edges = payload.get("edges") or payload.get("elements", {}).get("edges") or []
    # graph_builder 当前 schema:见 dashboard/derive/graph_builder.py。
    # 若 schema 不同,在写测试时根据真实返回结构调整 key 抓取(此 fallback 已覆盖两种风格)。
    assert len(nodes) >= 35, f"expect ≥35 nodes after seed, got {len(nodes)}"
    assert len(edges) >= 10, f"expect ≥10 edges after seed, got {len(edges)}"


def test_overview_graph_after_explicit_refresh_has_filled_nodes() -> None:
    """同上,但显式触发 POST /refresh(verify SSE 完成后 graph 拉到新数据)。"""
    from dashboard.server import app

    with TestClient(app) as client:
        # 跑 SSE refresh(消耗完流)
        with client.stream("POST", "/refresh") as r:
            for _ in r.iter_bytes():
                pass
            assert r.status_code == 200
        r2 = client.get("/api/overview/graph.json")
        assert r2.status_code == 200
        payload = r2.json()
    nodes = payload.get("nodes") or payload.get("elements", {}).get("nodes") or []
    assert len(nodes) >= 35


def test_graph_edges_carry_weight_field() -> None:
    """Plan 3 Task 8 — 每个 edge 有 weight 字段(0.6 或 1.2)。"""
    from dashboard.server import app

    with TestClient(app) as client:
        r = client.get("/api/overview/graph.json")
        assert r.status_code == 200
        payload = r.json()
    edges = payload.get("edges") or payload.get("elements", {}).get("edges") or []
    assert len(edges) >= 10, f"expect ≥10 edges, got {len(edges)}"
    for e in edges:
        assert "weight" in e["data"], f"edge missing weight: {e}"
        assert e["data"]["weight"] in (0.6, 1.2), f"unexpected weight: {e['data']['weight']}"

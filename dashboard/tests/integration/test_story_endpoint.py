"""Plan 2 Task 8 — V4 /story endpoint integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    from dashboard import server

    monkeypatch.setattr(server, "DB_PATH", tmp_path / "board.db")
    # 测试中关掉 commit_time 抽取(性能 + 隔离)
    monkeypatch.setattr(server, "_extract_commit_times_for_caps", lambda _caps: {})
    return TestClient(server.app)


def test_story_empty_renders_placeholder(client: TestClient) -> None:
    resp = client.get("/story")
    assert resp.status_code == 200
    # 无 DeepCard 时显示引导文案
    body = resp.text
    assert "暂无" in body or "未填" in body or "no story" in body.lower()


def test_story_renders_3_section_card(client: TestClient, tmp_path: Path) -> None:
    from dashboard.derive.deep_card_types import DeepCard
    from dashboard.state.db import open_db
    from dashboard.state.repositories import DeepCardRepo

    db = tmp_path / "board.db"
    conn = open_db(db)
    DeepCardRepo(conn).upsert(
        DeepCard(
            cap_id="prompt_context.constrained_schema",
            why="避免 LLM 自由生成导致下游解析失败",
            tradeoff="选 constrained JSON schema 因为 OpenAI 协议支持",
            lessons_learned="撞过 ruff 行宽对齐撞了 3 次",
        )
    )
    resp = client.get("/story")
    assert resp.status_code == 200
    assert "避免 LLM 自由生成" in resp.text
    assert "constrained JSON schema" in resp.text
    assert "ruff 行宽" in resp.text


def test_story_filter_dim_via_query(client: TestClient) -> None:
    resp = client.get("/story?dim=memory")
    assert resp.status_code == 200

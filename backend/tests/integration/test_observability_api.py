"""只读可观测性 API —— 返回聚合 JSON,且不泄漏 span 原文。"""

from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.router.observability_router import router
from app.services.trace_models import TraceSpanRow


def _seed(db_session) -> None:
    end = datetime.now(UTC) - timedelta(seconds=5)
    db_session.add(
        TraceSpanRow(
            span_id="s1",
            request_id="r1",
            parent_id=None,
            name="tool:get_quote",
            inputs={"secret_arg": "茅台"},
            outputs={"price": 1688},
            attrs_json={"kind": "tool", "latency_ms": 500, "cached": False, "success": True},
            started_at=end - timedelta(milliseconds=500),
            ended_at=end,
            error=None,
        )
    )
    db_session.flush()


def _client(db_session) -> TestClient:
    import app.router.observability_router as mod

    mod._SESSION_FACTORY = lambda: nullcontext(db_session)  # 测试缝
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_aggregates_endpoint_returns_json(db_session) -> None:
    _seed(db_session)
    resp = _client(db_session).get("/api/v0/observability/chatloop/aggregates?window=7d")
    assert resp.status_code == 200
    body = resp.json()
    assert body["window"] == "7d"
    assert any(t["tool_name"] == "get_quote" for t in body["tool_latency"])


def test_response_leaks_no_span_content(db_session) -> None:
    _seed(db_session)
    resp = _client(db_session).get("/api/v0/observability/chatloop/aggregates?window=7d")
    raw = resp.text
    assert "secret_arg" not in raw
    assert "茅台" not in raw
    assert "1688" not in raw


def test_invalid_window_400(db_session) -> None:
    resp = _client(db_session).get("/api/v0/observability/chatloop/aggregates?window=99y")
    assert resp.status_code == 400

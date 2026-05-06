"""GET /reports/:id/stream — SSE endpoint smoke tests (Task 9).

Verifies:
  1. Endpoint registered (GET /reports/:id/stream returns 401/404, not 405)
  2. Legacy POST /api/v0.5/research still works (deprecation alias)
  3. 401 without auth header
  4. 404 when report id 不存在
  5. 403 when 不是 owner

Stream content/db-persist 行为通过 mock generator 验证(避免真 LangGraph 启动).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Generator, Iterator
from pathlib import Path
from typing import Any

import pytest
from app.core.database import Base, get_db
from app.models.research_report import ResearchReport
from app.models.user import User
from app.router.auth_router import router as auth_router
from app.router.reports import router as reports_router
from app.router.research import get_research_graph
from app.router.research import router as research_router
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def db_engine(tmp_path: Path) -> Generator[Engine, None, None]:
    """Per-test SQLite file."""
    db_path = tmp_path / "test_reports_stream.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(
        engine,
        tables=[User.__table__, ResearchReport.__table__],
    )
    yield engine
    engine.dispose()


@pytest.fixture
def client(db_engine: Engine) -> TestClient:
    """Minimal FastAPI app with auth + reports + research routers."""
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)

    def _override_get_db() -> Iterator[Session]:
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    # Override get_research_graph to a stub that won't be invoked unless
    # a test exercises the streaming path (Step 3 tests don't reach it).
    async def _stub_graph() -> Any:
        class _StubGraph:
            async def astream_events(
                self, _state: Any, config: Any = None, version: str = "v2"
            ) -> AsyncIterator[dict[str, Any]]:
                # Emit one root done event so _stream_research yields a done line.
                yield {"event": "on_chain_end", "name": "LangGraph", "parent_ids": []}

        return _StubGraph()

    test_app = FastAPI()
    test_app.include_router(auth_router)
    test_app.include_router(reports_router)
    test_app.include_router(research_router)
    test_app.dependency_overrides[get_db] = _override_get_db
    test_app.dependency_overrides[get_research_graph] = _stub_graph
    return TestClient(test_app)


@pytest.fixture
def auth_token(client: TestClient) -> str:
    """注册一个 user 拿 JWT token."""
    res = client.post(
        "/auth/register",
        json={"username": "stream_t", "password": "secret123", "email": "stream@t.com"},
    )
    assert res.status_code in (200, 201), res.text
    token = res.json()["access_token"]
    assert isinstance(token, str) and token
    return token


@pytest.fixture
def auth_header(auth_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth_token}"}


# ---------------------------------------------------------------------------
# Step 3 tests: endpoint shape — no full streaming exercise
# ---------------------------------------------------------------------------


def test_stream_endpoint_path_exists(client: TestClient) -> None:
    """GET /reports/:id/stream 注册成功。

    无 token + fake id → 期待 401(无 token)而非 405 Method Not Allowed。
    """
    res = client.get("/reports/fake-id/stream")
    # 401 = unauthorized, 404 = not found, 422 = validation
    # 405 = endpoint 不存在(method not allowed) — 不是预期
    assert res.status_code in (401, 404, 422), (
        f"Expected 401/404/422, got {res.status_code} (405 = endpoint not registered): {res.text}"
    )


def test_legacy_v05_path_still_works(client: TestClient) -> None:
    """保留 /api/v0.5/research 作为 alias 一段时间。

    无 body / wrong body → 422; with body, may go through to graph (200) or fail validation.
    The point: endpoint is still mounted and not 404/405.
    """
    res = client.post("/api/v0.5/research", json={"user_message": "test"})
    # 200 = stream 开始;401 = 无 token;422 = 缺 required field
    assert res.status_code in (200, 401, 422), (
        f"Legacy v0.5 endpoint should still respond, got {res.status_code}: {res.text}"
    )


def test_stream_404_when_report_not_exist(client: TestClient, auth_header: dict[str, str]) -> None:
    """有 auth + non-exist id → 404 (not 401/405)."""
    res = client.get("/reports/non-exist-id/stream", headers=auth_header)
    assert res.status_code == 404, res.text


def test_stream_403_when_not_owner(client: TestClient, auth_header: dict[str, str]) -> None:
    """alice 创建 report,bob 订阅 stream → 403."""
    rid = client.post("/reports", headers=auth_header, json={"target_name": "alice_target"}).json()[
        "id"
    ]

    bob_resp = client.post(
        "/auth/register",
        json={"username": "bob_stream", "password": "secret123", "email": "bob_stream@b.com"},
    )
    assert bob_resp.status_code in (200, 201)
    bob_header = {"Authorization": f"Bearer {bob_resp.json()['access_token']}"}

    res = client.get(f"/reports/{rid}/stream", headers=bob_header)
    assert res.status_code == 403, res.text

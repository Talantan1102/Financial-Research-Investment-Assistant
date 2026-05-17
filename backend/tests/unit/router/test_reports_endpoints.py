"""POST/GET/DELETE /reports — CRUD endpoints (Task 8).

Test strategy: mount auth_router + reports_router on a minimal FastAPI app +
override get_db with the shared db_session fixture (PG transaction rollback
isolation). 不用 `from app.app_main import app` 因为 app_main 有重 lifespan
(MonitoringService / research graph 构建)+ PG 硬依赖, 单元测试不需要这些副作用.

Real JWT auth 通过 Bearer token Authorization header 走 OAuth2PasswordBearer.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from app.core.database import get_db
from app.models.research_report import ResearchReport  # noqa: F401
from app.models.user import User  # noqa: F401
from app.router.auth_router import router as auth_router
from app.router.reports import router as reports_router
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


@pytest.fixture
def client(db_session: Session) -> TestClient:
    """Minimal FastAPI app with auth_router + reports_router + get_db → db_session."""

    def _override_get_db() -> Iterator[Session]:
        yield db_session

    test_app = FastAPI()
    test_app.include_router(auth_router)
    test_app.include_router(reports_router)
    test_app.dependency_overrides[get_db] = _override_get_db
    return TestClient(test_app)


@pytest.fixture
def auth_token(client: TestClient) -> str:
    """注册一个 user 拿 JWT token."""
    res = client.post(
        "/auth/register",
        json={"username": "rpt_test", "password": "secret123", "email": "rpt@test.com"},
    )
    assert res.status_code in (200, 201), res.text
    token = res.json()["access_token"]
    assert isinstance(token, str) and token
    return token


@pytest.fixture
def auth_header(auth_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth_token}"}


# ---------------------------------------------------------------------------
# GET /reports — list
# ---------------------------------------------------------------------------


def test_list_reports_empty(client: TestClient, auth_header: dict[str, str]) -> None:
    res = client.get("/reports", headers=auth_header)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["items"] == []
    assert body["total"] == 0
    assert body["page"] == 1
    assert body["page_size"] == 20


def test_list_reports_after_post(client: TestClient, auth_header: dict[str, str]) -> None:
    """POST 后 list 能看到该条目."""
    res_post = client.post(
        "/reports",
        headers=auth_header,
        json={"target_name": "测试标的"},
    )
    assert res_post.status_code in (200, 201), res_post.text

    res = client.get("/reports", headers=auth_header)
    assert res.status_code == 200
    items = res.json()["items"]
    assert any(r["target_name"] == "测试标的" for r in items)


# ---------------------------------------------------------------------------
# GET /reports/{id} — detail
# ---------------------------------------------------------------------------


def test_get_report_404_when_not_exist(client: TestClient, auth_header: dict[str, str]) -> None:
    res = client.get("/reports/non-exist-id", headers=auth_header)
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# POST /reports — create placeholder
# ---------------------------------------------------------------------------


def test_post_report_creates_streaming_placeholder(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    """POST /reports 创建 placeholder (status=streaming), 返回 id; 后续 GET detail 可读到."""
    res = client.post(
        "/reports",
        headers=auth_header,
        json={"target_name": "贵州茅台", "target_ts_code": "600519.SH"},
    )
    assert res.status_code in (200, 201), res.text
    body = res.json()
    assert "id" in body and isinstance(body["id"], str) and body["id"]

    rid = body["id"]
    res2 = client.get(f"/reports/{rid}", headers=auth_header)
    assert res2.status_code == 200, res2.text
    detail = res2.json()
    assert detail["target_name"] == "贵州茅台"
    assert detail["target_ts_code"] == "600519.SH"
    assert detail["status"] == "streaming"
    assert detail["report_json"] == {}


# ---------------------------------------------------------------------------
# DELETE /reports/{id}
# ---------------------------------------------------------------------------


def test_delete_report(client: TestClient, auth_header: dict[str, str]) -> None:
    """先 create, 再 delete (204), 再 get → 404."""
    rid = client.post("/reports", headers=auth_header, json={"target_name": "to_delete"}).json()[
        "id"
    ]
    res = client.delete(f"/reports/{rid}", headers=auth_header)
    assert res.status_code == 204, res.text
    res2 = client.get(f"/reports/{rid}", headers=auth_header)
    assert res2.status_code == 404


# ---------------------------------------------------------------------------
# Isolation: 403 when 不属于当前 user
# ---------------------------------------------------------------------------


def test_isolation_403_when_not_owner(client: TestClient, auth_header: dict[str, str]) -> None:
    """alice (auth_header fixture user) 创建 report, bob 拿另一个 token 看 → 403; delete 也 → 403."""
    rid = client.post("/reports", headers=auth_header, json={"target_name": "alice_target"}).json()[
        "id"
    ]

    # 注册 bob (与 fixture user 'rpt_test' 不同用户)
    bob_resp = client.post(
        "/auth/register",
        json={"username": "bob_iso8", "password": "secret123", "email": "bob_iso8@b.com"},
    )
    assert bob_resp.status_code in (200, 201), bob_resp.text
    bob_token = bob_resp.json()["access_token"]
    bob_header = {"Authorization": f"Bearer {bob_token}"}

    res = client.get(f"/reports/{rid}", headers=bob_header)
    assert res.status_code == 403, res.text

    res2 = client.delete(f"/reports/{rid}", headers=bob_header)
    assert res2.status_code == 403, res2.text

    # 验证 bob 的 list 看不到 alice 的 report
    bob_list = client.get("/reports", headers=bob_header)
    assert bob_list.status_code == 200
    assert bob_list.json()["items"] == []

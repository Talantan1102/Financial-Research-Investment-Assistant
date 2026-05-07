"""Roadmap #2.5 护栏 — 唯一加载完整 app.app_main + 真 PG 的 e2e test.

覆盖 serve path:
1. app_main lifespan 真启动(包括 Base.metadata.create_all 在 test db 建表)
2. /auth/register 真插 users 表
3. POST /reports 真插 research_reports 表(placeholder, status=streaming)
4. SSE drain 收到 done,写回 report_json + status=completed
5. GET /reports 用户隔离(alice 看到自己的;bob 看不到 alice 的)

本测试 **不复用** L0/L1 的 sqlite-override 模式 — 那些已覆盖路由逻辑;
本测试唯一目的是验证 lifespan + 真 PG 真行为 + 多用户隔离。

LLM_MODE=mock(不录 cassette,不消耗真 LLM):本测试不验证研报内容,
只验证 SSE 流能跑完到 `event: done`(或在合理超时内拿到非空事件流)。

POSTGRES_DB 已被 `tests/conftest.py` `pytest_configure` 强制为
`industry_assistant_test`,本测试只需让 fixture 起 PG container、再 import
app_main 即可(import 时机敏感:必须在 fixture yield 之后)。

设计 ref: `docs/superpowers/specs/2026-05-07-v0.9.x-pg-and-ci-setup.md` § Task 3
"""

from __future__ import annotations

import uuid as _uuid
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    pass


@pytest.mark.usefixtures("pg_test_container")
def test_register_post_sse_get_with_real_pg(
    pg_test_container: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Roadmap #2.5 acceptance — register → POST → SSE → GET + 双用户隔离."""
    # 1. 覆盖 e2e conftest 的 LLM_MODE=cassette(本测试用 mock,不读 cassette)
    monkeypatch.setenv("LLM_MODE", "mock")

    # 2. import app_main(serve path 真覆盖) — fixture 已确保 PG up + test db exists
    #    NOTE: app.core.database.engine 在 import 时读 POSTGRES_*。
    #    pytest_configure 已在 session 起始把 POSTGRES_DB 强制为 test db,
    #    因此 import 链上任何模块若已经 import 了 database,engine 也是连 test db。
    from app.app_main import app

    client = TestClient(app)

    # 3. 用 uuid 后缀做用户名,使重复 run 不冲突(避免 409 duplicate username)
    suffix = _uuid.uuid4().hex[:8]
    alice_username = f"alice_e2e_{suffix}"
    alice_email = f"alice_e2e_{suffix}@example.com"
    bob_username = f"bob_e2e_{suffix}"
    bob_email = f"bob_e2e_{suffix}@example.com"

    # 4. User A 注册
    r = client.post(
        "/auth/register",
        json={"username": alice_username, "password": "alice_password_123", "email": alice_email},
    )
    assert r.status_code in (200, 201), f"register alice failed: {r.status_code} {r.text}"
    body = r.json()
    assert "access_token" in body, f"missing access_token: {body}"
    token_a = body["access_token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # 5. User A 发起报告(POST /reports — body shape: target_name, target_ts_code, research_style)
    r = client.post(
        "/reports",
        json={
            "target_name": "贵州茅台",
            "target_ts_code": "600519.SH",
            "research_style": "comprehensive",
        },
        headers=headers_a,
    )
    assert r.status_code in (200, 201), f"POST /reports failed: {r.status_code} {r.text}"
    report_id = r.json()["id"]
    assert isinstance(report_id, str) and report_id

    # 6. User A 订阅 SSE,drain 完到 event: done
    #    用 read=120s 因为 mock LLM 全链路要跑 5 agents
    saw_done = False
    with client.stream(
        "GET",
        f"/reports/{report_id}/stream",
        headers=headers_a,
        timeout=120.0,
    ) as resp:
        assert resp.status_code == 200, f"SSE not 200: {resp.status_code}"
        for raw in resp.iter_lines():
            line = raw if isinstance(raw, str) else raw.decode("utf-8", errors="replace")
            if line.startswith("event: done"):
                saw_done = True
                break
    assert saw_done, "SSE did not reach 'event: done' before stream closed"

    # 7. User A 看到自己的列表(列表 wrap 在 {items, total, page, page_size})
    r = client.get("/reports", headers=headers_a)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert any(item["id"] == report_id for item in items), (
        f"alice should see her own report {report_id} in list: {items}"
    )

    # 8. User B 注册
    r = client.post(
        "/auth/register",
        json={"username": bob_username, "password": "bob_password_456", "email": bob_email},
    )
    assert r.status_code in (200, 201), f"register bob failed: {r.status_code} {r.text}"
    token_b = r.json()["access_token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # 9. User B 列表里看不到 alice 的 report(数据隔离 — list)
    r = client.get("/reports", headers=headers_b)
    assert r.status_code == 200
    items = r.json()["items"]
    assert all(item["id"] != report_id for item in items), (
        f"bob should NOT see alice's report {report_id} in his list: {items}"
    )

    # 10. User B 看不到 alice 的报告详情(数据隔离 — detail,403/404 都 ok)
    r = client.get(f"/reports/{report_id}", headers=headers_b)
    assert r.status_code in (403, 404), (
        f"bob should be 403/404 on alice's report; got {r.status_code} {r.text}"
    )

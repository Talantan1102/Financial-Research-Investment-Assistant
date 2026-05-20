"""Legacy CRUD 数据隔离 verify — alice / bob 互看不见 (Task 10).

覆盖 active routers 的 isolation 守护:
  - /reports          → 已 in test_reports_endpoints.test_isolation_403_when_not_owner (Task 8); 不重复
  - /attachments      → 本文件 (Task 10 fix: get_current_user_required + user_id filter)
  - /knowledge (base) → 本文件 (legacy 已 ok, regression 守护)
  - /api/monitoring   → schema 无 user_id, B-3 by design 全局/admin; 不写 isolation 测试
  - /auth             → 仅 auth flow, 不 expose user data; 不写 isolation 测试

测试架构 (PR-A T15: 迁到全局 db_session PG fixture):
  - mount auth_router + 目标 router on minimal FastAPI app
  - override get_db with db_session (real PG, transaction-rollback isolation)
  - PG 原生支持 UUID,不再需要 SQLite UUID column patching
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from app.core.database import get_db
from app.models.chat import ChatAttachment, ChatSession
from app.router.attachment_router import router as attachment_router
from app.router.auth_router import router as auth_router
from app.router.knowledge_router import router as knowledge_router
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


@pytest.fixture
def client(db_session: Session) -> TestClient:
    """Minimal FastAPI app with auth + knowledge + attachment routers.

    PR-A T15: 改用全局 db_session(真 PG + transaction rollback),
    _override_get_db 直接 yield db_session,所有 INSERT/SELECT 共享同一
    connection,跨 test 不可见。
    """

    def _override_get_db() -> Iterator[Session]:
        yield db_session

    test_app = FastAPI()
    test_app.include_router(auth_router)
    test_app.include_router(knowledge_router)
    test_app.include_router(attachment_router)
    test_app.dependency_overrides[get_db] = _override_get_db
    return TestClient(test_app)


def _register(client: TestClient, username: str) -> str:
    """Register a user and return their JWT access token."""
    res = client.post(
        "/auth/register",
        json={
            "username": username,
            "password": "secret123",
            "email": f"{username}@test.com",
        },
    )
    assert res.status_code in (200, 201), res.text
    return str(res.json()["access_token"])


# ---------------------------------------------------------------------------
# Knowledge — alice 创建 KB, bob 看不见 + 不能 GET / DELETE
# ---------------------------------------------------------------------------


_KB_PREFIX = "/knowledge-bases"  # 与 knowledge_router.py APIRouter(prefix=...) 同步


def test_knowledge_isolation_alice_bob(client: TestClient) -> None:
    """alice 创建 KB → bob list 看不见 → bob GET → 404 → bob DELETE → 404."""
    alice_token = _register(client, "alice_kb")
    bob_token = _register(client, "bob_kb")
    alice_h = {"Authorization": f"Bearer {alice_token}"}
    bob_h = {"Authorization": f"Bearer {bob_token}"}

    # alice 创建 KB
    res = client.post(_KB_PREFIX, headers=alice_h, json={"name": "alice_kb1", "description": "x"})
    assert res.status_code in (200, 201), res.text
    kb_id = res.json()["id"]

    # bob list — 看不到 alice 的 KB
    res_list = client.get(_KB_PREFIX, headers=bob_h)
    assert res_list.status_code == 200
    bob_kbs = res_list.json()
    assert all(kb.get("id") != kb_id for kb in bob_kbs), f"bob 看到了 alice 的 KB: {bob_kbs}"

    # bob GET by id — 应 404 (legacy router 用 404 not 403, 即不暴露存在性)
    res_get = client.get(f"{_KB_PREFIX}/{kb_id}", headers=bob_h)
    assert res_get.status_code == 404, res_get.text

    # bob DELETE — 也 404
    res_del = client.delete(f"{_KB_PREFIX}/{kb_id}", headers=bob_h)
    assert res_del.status_code == 404, res_del.text


# ---------------------------------------------------------------------------
# Attachment — alice 上传 attachment → bob GET 列表 / 单个 / DELETE 都看不见
# ---------------------------------------------------------------------------
# attachment_router 依赖 ChatSession (chat router 已 v0.9.x 删除, 但 attachment_router
# 还 mount 着). 直接拿 sqlalchemy session 创 ChatSession + ChatAttachment row,
# 不走 chat 上传流程 (那个 endpoint 已删).


def test_attachment_isolation_alice_bob(client: TestClient, db_session: Session) -> None:
    """alice 创 attachment row → bob GET 单个 → 404 → bob list session 附件 → 404."""
    alice_token = _register(client, "alice_att")
    bob_token = _register(client, "bob_att")
    alice_h = {"Authorization": f"Bearer {alice_token}"}
    bob_h = {"Authorization": f"Bearer {bob_token}"}

    # 拿 alice / bob user.id from token
    alice_me = client.get("/auth/me", headers=alice_h).json()
    bob_me = client.get("/auth/me", headers=bob_h).json()
    alice_id = alice_me["id"]
    bob_id = bob_me["id"]

    # 直接从 db 创 ChatSession + ChatAttachment for alice (chat router 已删, 走 db)
    alice_session = ChatSession(user_id=alice_id, title="alice_session")
    db_session.add(alice_session)
    db_session.flush()

    att = ChatAttachment(
        session_id=alice_session.id,
        user_id=alice_id,
        filename="alice_file.txt",
        file_type="txt",
        file_size=10,
        file_path="/tmp/x",
        status="completed",
    )
    db_session.add(att)
    db_session.flush()
    att_id = str(att.id)
    alice_session_id = str(alice_session.id)

    # 也给 bob 创一个空 session (用于对照)
    bob_session = ChatSession(user_id=bob_id, title="bob_session")
    db_session.add(bob_session)
    db_session.flush()

    # bob 拿单个 attachment by id → 404 (隔离)
    res_get = client.get(f"/attachments/{att_id}", headers=bob_h)
    assert res_get.status_code == 404, res_get.text

    # alice 自己拿 → 200
    res_alice_get = client.get(f"/attachments/{att_id}", headers=alice_h)
    assert res_alice_get.status_code == 200, res_alice_get.text
    assert res_alice_get.json()["filename"] == "alice_file.txt"

    # bob 拿 alice 的 session 附件列表 → 404 (session 不属于 bob)
    res_list = client.get(f"/attachments/session/{alice_session_id}", headers=bob_h)
    assert res_list.status_code == 404, res_list.text

    # bob delete alice 的 attachment → 404
    res_del = client.delete(f"/attachments/{att_id}", headers=bob_h)
    assert res_del.status_code == 404, res_del.text

    # alice 自己 list 自己 session → 200, 看到 1 条
    res_alice_list = client.get(f"/attachments/session/{alice_session_id}", headers=alice_h)
    assert res_alice_list.status_code == 200
    assert res_alice_list.json()["total"] == 1


# ---------------------------------------------------------------------------
# Attachment — 未认证 (无 token) 不能访问 (Task 10 fix: get_current_user_required)
# ---------------------------------------------------------------------------


def test_attachment_requires_auth(client: TestClient) -> None:
    """没 token → 401 (不再是 200/None user)."""
    res = client.get("/attachments/some-id")
    assert res.status_code == 401, res.text

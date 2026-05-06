"""Legacy CRUD 数据隔离 verify — alice / bob 互看不见 (Task 10).

覆盖 active routers 的 isolation 守护:
  - /reports          → 已 in test_reports_endpoints.test_isolation_403_when_not_owner (Task 8); 不重复
  - /attachments      → 本文件 (Task 10 fix: get_current_user_required + user_id filter)
  - /knowledge (base) → 本文件 (legacy 已 ok, regression 守护)
  - /api/monitoring   → schema 无 user_id, B-3 by design 全局/admin; 不写 isolation 测试
  - /auth             → 仅 auth flow, 不 expose user data; 不写 isolation 测试

测试架构 (Task 8 同 pattern, 复用 schema-rewrite trick 让 PG-only 模型 work on SQLite):
  - mount auth_router + 目标 router on minimal FastAPI app
  - override get_db with tmp-path SQLite session
  - 把 PG `UUID(as_uuid=True)` columns 改成 `String(36)` + `ColumnDefault(str(uuid4()))`
    (legacy 模型未用 with_variant — User/ResearchReport 已经是; legacy KB/Chat 没改)
"""

from __future__ import annotations

import uuid as _uuid
from collections.abc import Generator, Iterator
from pathlib import Path

import pytest
from app.core.database import Base, get_db
from app.models.chat import ChatAttachment, ChatSession
from app.models.knowledge import Document, KnowledgeBase
from app.models.user import User
from app.router.attachment_router import router as attachment_router
from app.router.auth_router import router as auth_router
from app.router.knowledge_router import router as knowledge_router
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import ColumnDefault, Engine, String, TypeDecorator, create_engine
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Session, sessionmaker


def _str_uuid() -> str:
    return str(_uuid.uuid4())


class _UUIDOrStr(TypeDecorator):  # type: ignore[type-arg]
    """SQLite 测试用 UUID column type:bind 时把 UUID/str 都转 str.

    问题:legacy 模型的 PG `UUID(as_uuid=True)` 列在 SQLite 下被 patch 成
    `String(36)`,但 router 代码 `UUID(attachment_id)` 拿到 UUID 对象后
    `Column == UUID(...)` 在 SQLite 下不 auto-cast,filter 永远 False.
    本 type 让 String column 也能匹配 UUID 对象 (绑定时 str 化).
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value: object, dialect: object) -> str | None:
        if value is None:
            return None
        return str(value)


def _patch_uuid_columns_to_string() -> None:
    """让 PG-only UUID 列在 SQLite test 下 work — 把 column.type 改 _UUIDOrStr (length 36),
    primary key default 改成返回 str 的 callable (PG_UUID column 的默认 lambda
    返回 UUID 对象, SQLAlchemy 在 String 列上调 .hex 会炸).
    """
    tables_to_patch = [
        KnowledgeBase.__table__,
        Document.__table__,
        ChatSession.__table__,
        ChatAttachment.__table__,
    ]
    for tbl in tables_to_patch:
        for col in tbl.columns:
            if isinstance(col.type, PG_UUID):
                col.type = _UUIDOrStr(36)
                if col.primary_key and col.default is not None:
                    col.default = ColumnDefault(_str_uuid)


# Module-level: 一次 patch, 所有测试共享 (column 改 type 是 idempotent).
_patch_uuid_columns_to_string()


@pytest.fixture
def db_engine(tmp_path: Path) -> Generator[Engine, None, None]:
    """Per-test SQLite file. 每个 test 拿独立 state."""
    db_path = tmp_path / "test_isolation.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            KnowledgeBase.__table__,
            Document.__table__,
            ChatSession.__table__,
            ChatAttachment.__table__,
        ],
    )
    yield engine
    engine.dispose()


@pytest.fixture
def client(db_engine: Engine) -> TestClient:
    """Minimal FastAPI app with auth + knowledge + attachment routers."""
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)

    def _override_get_db() -> Iterator[Session]:
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

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


def test_attachment_isolation_alice_bob(client: TestClient, db_engine: Engine) -> None:
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
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    db = SessionLocal()
    try:
        alice_session = ChatSession(user_id=alice_id, title="alice_session")
        db.add(alice_session)
        db.commit()
        db.refresh(alice_session)
        alice_session_id = str(alice_session.id)

        att = ChatAttachment(
            session_id=alice_session.id,
            user_id=alice_id,
            filename="alice_file.txt",
            file_type="txt",
            file_size=10,
            file_path="/tmp/x",
            status="completed",
        )
        db.add(att)
        db.commit()
        db.refresh(att)
        att_id = str(att.id)

        # 也给 bob 创一个空 session (用于对照)
        bob_session = ChatSession(user_id=bob_id, title="bob_session")
        db.add(bob_session)
        db.commit()
    finally:
        db.close()

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

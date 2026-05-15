"""Plan 1 集成测试 — POST /api/v0/chat 落 user + finally 落 assistant + mark task。

L1 集成测试: in-memory sqlite + dependency_overrides 模拟 PG path。
LLM 走 MockLLMClient(test_chat_router_sse.py 同款), 不依赖 Celery / Redis(Plan 1 范围)。

覆盖:
- POST /chat 入口 INSERT 1 行 user message + create chat_task(running)
- 主流跑完 finally 落 1 行 assistant message + mark task done
- 老的 SSE event framing 不被破坏(re-uses test_chat_router_sse fixtures pattern)
"""

from __future__ import annotations

import importlib
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from app.agents.chat_planner import ChatPlanner
from app.agents.in_session_memory import InSessionMemory
from app.agents.responder import Responder
from app.core.database import Base
from app.models.chat import ChatSession
from app.models.user import User  # noqa: F401 — registers users table
from app.orchestration.chat_graph import build_chat_graph
from app.services.chat_session_repo import ChatSessionRepo
from app.services.chat_task_repo import ChatTaskRepo
from app.services.llm_mock_client import MockLLMClient
from app.services.llm_service import LLMService
from app.services.tool_result_cache import ToolResultCache
from app.tools.base import Tool
from app.tools.registry import ToolRegistry
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

# Import the chat router module so we can monkey-patch its session-factory getter
_chat_mod = importlib.import_module("app.router.chat")
get_chat_graph = _chat_mod.get_chat_graph
get_current_user = _chat_mod.get_current_user
get_escalation_extractor = _chat_mod.get_escalation_extractor
get_escalation_record_repo = _chat_mod.get_escalation_record_repo
get_async_session_factory = _chat_mod.get_async_session_factory

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "llm_mocks"

# 4 张表: Repo 真实使用 + sqlite 编译可过
_REQUIRED_TABLE_NAMES = ("users", "chat_sessions", "chat_tasks", "chat_messages")


def _selective_create_all(sync_conn: object) -> None:
    tables = [Base.metadata.tables[name] for name in _REQUIRED_TABLE_NAMES]
    Base.metadata.create_all(sync_conn, tables=tables)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Stub tools (mirror test_chat_router_sse.py)
# ---------------------------------------------------------------------------


class _StubQuoteArgs(BaseModel):
    ts_code: str


class _StubQuoteTool(Tool):
    name = "get_stock_quote"
    description = "Return the latest daily price for a given A-share."
    args_schema = _StubQuoteArgs

    async def run(self, args: BaseModel) -> dict[str, Any]:
        validated = _StubQuoteArgs.model_validate(args.model_dump())
        return {"ts_code": validated.ts_code, "price": 1820.5, "change_pct": 0.5}


class _StubFinancialsArgs(BaseModel):
    ts_code: str
    period: str = "latest"


class _StubFinancialsTool(Tool):
    name = "get_financials"
    description = "Return revenue and net profit for a given A-share."
    args_schema = _StubFinancialsArgs

    async def run(self, args: BaseModel) -> dict[str, Any]:
        validated = _StubFinancialsArgs.model_validate(args.model_dump())
        return {"ts_code": validated.ts_code, "revenue": 1e10, "net_profit": 2e9}


class _StubNewsArgs(BaseModel):
    ts_code: str | None = None
    n: int = 5
    days_back: int = 7


class _StubNewsTool(Tool):
    name = "get_news"
    description = "Return recent news for a given A-share."
    args_schema = _StubNewsArgs

    async def run(self, args: BaseModel) -> dict[str, Any]:
        return {"items": [{"title": "stub news", "url": "https://example.com"}]}


class _StubUser:
    def __init__(self) -> None:
        self.id = "test-user"


def _build_test_graph() -> Any:
    mock_client = MockLLMClient.from_fixture_dir(FIXTURES_DIR)
    svc = LLMService(client=mock_client)
    registry = ToolRegistry()
    registry.register(_StubQuoteTool())
    registry.register(_StubFinancialsTool())
    registry.register(_StubNewsTool())
    planner = ChatPlanner(llm=svc, registry=registry)
    responder = Responder(llm=svc)
    memory = InSessionMemory()
    cache = ToolResultCache(session_factory=MagicMock())
    return build_chat_graph(
        planner=planner, responder=responder, registry=registry, memory=memory, cache=cache
    )


# ---------------------------------------------------------------------------
# Fixtures: in-memory async sqlite + seeded ChatSession
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[object]]:
    engine: AsyncEngine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(_selective_create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def seeded_session_id(
    session_factory: async_sessionmaker[object],
) -> uuid.UUID:
    sid = uuid.uuid4()
    async with session_factory() as sess:
        sess.add(ChatSession(id=sid, user_id=None, title="t"))
        await sess.commit()
    return sid


@pytest.fixture
def test_client_with_pg(
    session_factory: async_sessionmaker[object],
):
    """FastAPI TestClient with chat router + PG session factory wired via DI override."""
    from app.router.chat import router as chat_router

    minimal_app = FastAPI()
    minimal_app.include_router(chat_router)

    test_graph = _build_test_graph()
    minimal_app.dependency_overrides[get_chat_graph] = lambda: test_graph
    minimal_app.dependency_overrides[get_current_user] = lambda: _StubUser()
    minimal_app.dependency_overrides[get_escalation_extractor] = lambda: None
    minimal_app.dependency_overrides[get_escalation_record_repo] = lambda: None
    # Plan 1 Task 5: inject the async session factory so chat handler persists
    minimal_app.dependency_overrides[get_async_session_factory] = lambda: session_factory

    client = TestClient(minimal_app, raise_server_exceptions=True)
    yield client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_chat_persists_user_and_assistant_messages(
    test_client_with_pg: TestClient,
    session_factory: async_sessionmaker[object],
    seeded_session_id: uuid.UUID,
) -> None:
    """POST /chat → 1 chat_task(done) + 2 chat_messages(user + assistant)."""
    resp = test_client_with_pg.post(
        "/api/v0/chat",
        json={
            "session_id": str(seeded_session_id),
            "message": "查一下 600519.SH 的股价",
        },
    )
    assert resp.status_code == 200, f"expected 200 got {resp.status_code}: {resp.text}"
    # Consume the full SSE stream so finally runs in handler
    _ = resp.content

    # === Assert chat_messages: 1 user + 1 assistant ===
    repo = ChatSessionRepo(session_factory)
    msgs = await repo.list_messages(str(seeded_session_id))
    assert len(msgs) == 2, (
        f"expected 2 chat_messages, got {len(msgs)}: {[(m.role, m.content[:30]) for m in msgs]}"
    )

    user_msg = msgs[0]
    assert user_msg.role == "user"
    assert user_msg.content == "查一下 600519.SH 的股价"
    assert user_msg.task_id is None, "user message should not be linked to task_id (entry-only)"
    assert user_msg.status == "done"

    asst_msg = msgs[1]
    assert asst_msg.role == "assistant"
    assert asst_msg.status == "done"
    assert asst_msg.task_id is not None, "assistant message must reference its task_id"

    # === Assert chat_task: status=done, finished_at set ===
    task_repo = ChatTaskRepo(session_factory)
    task = await task_repo.get_by_id(asst_msg.task_id)
    assert task is not None, "chat_task row must exist"
    assert task.status == "done", f"expected status=done, got {task.status}"
    assert task.finished_at is not None
    assert task.started_at is not None  # mark_running called on entry
    assert task.session_id == seeded_session_id
    assert task.initial_prompt_message_id == user_msg.id


@pytest.mark.asyncio
async def test_post_chat_creates_task_with_running_status_at_entry(
    test_client_with_pg: TestClient,
    session_factory: async_sessionmaker[object],
    seeded_session_id: uuid.UUID,
) -> None:
    """Sanity: task is created with status=running (not stuck at queued) after handler entry."""
    resp = test_client_with_pg.post(
        "/api/v0/chat",
        json={
            "session_id": str(seeded_session_id),
            "message": "查一下 600519.SH 的股价",
        },
    )
    assert resp.status_code == 200
    _ = resp.content

    # After full stream, task should be done (which transitively confirms running was set).
    # Use find_active_for_session — after done, no active task remains.
    task_repo = ChatTaskRepo(session_factory)
    active = await task_repo.find_active_for_session(seeded_session_id)
    assert active is None, "no active task should remain after stream finishes"

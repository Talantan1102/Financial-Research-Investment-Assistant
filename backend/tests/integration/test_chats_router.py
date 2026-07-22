import uuid
from datetime import datetime
from types import SimpleNamespace

from app.router.auth_router import get_current_user_required
from app.router.chats import get_repo, router
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_history_returns_paper_approval_payload() -> None:
    uid = uuid.uuid4()
    sid = uuid.uuid4()
    approval = {"approval_id": "a1", "approval_type": "paper_order", "resource_id": "o1"}
    msg = SimpleNamespace(
        id=uuid.uuid4(),
        role="assistant",
        content="请确认",
        message_type="paper_approval",
        tool_call_data=approval,
        task_id=None,
        status="done",
        created_at=datetime.now(),
    )
    session = SimpleNamespace(id=sid, user_id=uid, title="x", updated_at=datetime.now())

    class Repo:
        async def get_session(self, _sid):
            return session

        async def list_messages(self, _sid):
            return [msg]

        async def find_active_task_for_session(self, _sid):
            return None

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_repo] = lambda: Repo()
    app.dependency_overrides[get_current_user_required] = lambda: SimpleNamespace(id=uid)
    body = TestClient(app).get(f"/api/v0/chats/{sid}").json()
    assert body["messages"][0]["tool_call_data"] == approval

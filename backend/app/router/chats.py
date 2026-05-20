"""HTTP endpoints for chat session management (Q6 multi-chat list)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.services.chat_session_repo import ChatSessionRepo

router = APIRouter(prefix="/api/v0/chats", tags=["chats-v0.9"])


class ChatSessionView(BaseModel):
    id: str
    title: str
    updated_at: str
    message_count: int
    last_msg_preview: str


class CreateChatRequest(BaseModel):
    title: str = "新对话"


class RenameChatRequest(BaseModel):
    title: str


def get_repo() -> ChatSessionRepo:
    """Replaced via Depends override in tests; defaults wired in app_main lifespan (Task 20)."""
    raise RuntimeError("ChatSessionRepo dependency not configured")


def _to_view(s: Any, message_count: int = 0, preview: str = "") -> ChatSessionView:
    """Build view from a ChatSession ORM row, handling UUID id + updated_at."""
    return ChatSessionView(
        id=str(s.id),
        title=s.title,
        updated_at=s.updated_at.isoformat() if getattr(s, "updated_at", None) else "",
        message_count=getattr(s, "message_count", None) or message_count,
        last_msg_preview=getattr(s, "last_msg_preview", None) or preview,
    )


@router.get("/")
async def list_chats(repo: ChatSessionRepo = Depends(get_repo)) -> list[ChatSessionView]:
    sessions = await repo.list_for_user("anonymous")  # C.6 will switch to JWT user
    return [_to_view(s) for s in sessions]


@router.post("/")
async def create_chat(
    req: CreateChatRequest,
    repo: ChatSessionRepo = Depends(get_repo),
) -> ChatSessionView:
    s = await repo.create_session(user_id="anonymous", title=req.title)
    return _to_view(s)


@router.get("/{session_id}")
async def get_chat(session_id: str, repo: ChatSessionRepo = Depends(get_repo)) -> dict[str, Any]:
    """Get one session with messages + active_task_id (if a chat_task is in_flight).

    Plan 1 Task 7: 新增 active_task_id 字段(null 或 chat_task.id str)。每条 message
    携带 task_id + status,方便前端展示 task-level 状态(Plan 2 会扩展 stream URL)。
    """
    s = await repo.get_session(session_id)
    if not s:
        raise HTTPException(404, "session not found")
    msgs = await repo.list_messages(session_id)
    active_task = await repo.find_active_task_for_session(uuid.UUID(session_id))
    last_preview = msgs[-1].content[:100] if msgs else ""
    return {
        "session": _to_view(s, message_count=len(msgs), preview=last_preview).model_dump(),
        "messages": [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "message_type": m.message_type,
                "task_id": str(m.task_id) if m.task_id else None,
                "status": m.status,
                "created_at": m.created_at.isoformat() if m.created_at else "",
            }
            for m in msgs
        ],
        "active_task_id": str(active_task.id) if active_task else None,
    }


@router.put("/{session_id}")
async def rename_chat(
    session_id: str,
    req: RenameChatRequest,
    repo: ChatSessionRepo = Depends(get_repo),
) -> ChatSessionView:
    """User-driven rename. Sets title_source='user_renamed' (terminal) via repo."""
    s = await repo.get_session(session_id)
    if not s:
        raise HTTPException(404, "session not found")
    await repo.rename_session(session_id, req.title)
    updated = await repo.get_session(session_id)
    assert updated is not None
    return _to_view(updated)


@router.delete("/{session_id}")
async def delete_chat(session_id: str, repo: ChatSessionRepo = Depends(get_repo)) -> dict[str, str]:
    await repo.delete_session(session_id)
    return {"status": "deleted"}

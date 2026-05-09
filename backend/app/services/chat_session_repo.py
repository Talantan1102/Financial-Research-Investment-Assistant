"""ChatSessionRepo — multi-chat list CRUD with PG SQLAlchemy.

Wraps ChatSession + ChatMessage ORM models with an async session factory
(async_sessionmaker or compatible context-manager factory).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage, ChatSession


class ChatSessionRepo:
    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self._sf = session_factory

    async def create_session(self, user_id: str, title: str = "新对话") -> ChatSession:
        async with self._sf() as sess:
            row = ChatSession(
                id=uuid.uuid4(),
                user_id=uuid.UUID(user_id) if isinstance(user_id, str) else user_id,
                title=title,
            )
            sess.add(row)
            await sess.commit()
            await sess.refresh(row)
            return row

    async def list_for_user(self, user_id: str, limit: int = 50) -> list[ChatSession]:
        uid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
        async with self._sf() as sess:
            stmt = (
                select(ChatSession)
                .where(ChatSession.user_id == uid)
                .order_by(desc(ChatSession.updated_at))
                .limit(limit)
            )
            return list((await sess.execute(stmt)).scalars().all())

    async def get_session(self, session_id: str) -> ChatSession | None:
        sid = uuid.UUID(session_id) if isinstance(session_id, str) else session_id
        async with self._sf() as sess:
            return await sess.get(ChatSession, sid)

    async def append_message(
        self,
        session_id: str,
        role: Literal["user", "assistant", "tool"],
        content: str,
        message_type: str = "text",
        tool_call_data: dict[str, Any] | None = None,
        research_report_id: str | None = None,
        research_report_summary: str | None = None,
    ) -> ChatMessage:
        sid = uuid.UUID(session_id) if isinstance(session_id, str) else session_id
        async with self._sf() as sess:
            row = ChatMessage(
                id=uuid.uuid4(),
                session_id=sid,
                role=role,
                content=content,
                message_type=message_type,
                tool_call_data=tool_call_data,
                research_report_id=research_report_id,
                research_report_summary=research_report_summary,
            )
            sess.add(row)
            # bump session updated_at so list_for_user ordering is MRU
            await sess.execute(
                update(ChatSession)
                .where(ChatSession.id == sid)
                .values(updated_at=datetime.utcnow())
            )
            await sess.commit()
            await sess.refresh(row)
            return row

    async def list_messages(self, session_id: str, limit: int = 200) -> list[ChatMessage]:
        sid = uuid.UUID(session_id) if isinstance(session_id, str) else session_id
        async with self._sf() as sess:
            stmt = (
                select(ChatMessage)
                .where(ChatMessage.session_id == sid)
                .order_by(ChatMessage.created_at.asc())
                .limit(limit)
            )
            return list((await sess.execute(stmt)).scalars().all())

    async def rename_session(self, session_id: str, new_title: str) -> None:
        sid = uuid.UUID(session_id) if isinstance(session_id, str) else session_id
        async with self._sf() as sess:
            await sess.execute(
                update(ChatSession).where(ChatSession.id == sid).values(title=new_title)
            )
            await sess.commit()

    async def delete_session(self, session_id: str) -> None:
        sid = uuid.UUID(session_id) if isinstance(session_id, str) else session_id
        async with self._sf() as sess:
            row = await sess.get(ChatSession, sid)
            if row:
                await sess.delete(row)  # CASCADE clears ChatMessage rows
                await sess.commit()

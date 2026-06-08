"""ChatSessionRepo — multi-chat list CRUD with PG SQLAlchemy.

Wraps ChatSession + ChatMessage ORM models with an async session factory
(async_sessionmaker or compatible context-manager factory).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal

# Placeholder UUID for the pre-auth "anonymous" user (C.6 will use JWT sub).
_ANONYMOUS_UUID = uuid.UUID("00000000-0000-0000-0000-000000000000")

from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage, ChatSession, ChatTask
from app.services.chat_task_repo import ChatTaskRepo


class ChatSessionRepo:
    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _resolve_user_uuid(user_id: str | uuid.UUID) -> uuid.UUID | None:
        """Resolve user_id string to UUID.

        'anonymous' maps to None (NULL in DB) since pre-auth sessions have no
        real user row. C.6 will pass a real JWT sub UUID here instead.
        """
        if isinstance(user_id, uuid.UUID):
            return user_id
        if user_id == "anonymous":
            return None  # FK is nullable — NULL avoids FK violation pre-auth
        return uuid.UUID(user_id)

    async def create_session(self, user_id: str, title: str = "新对话") -> ChatSession:
        async with self._sf() as sess:
            row = ChatSession(
                id=uuid.uuid4(),
                user_id=self._resolve_user_uuid(user_id),
                title=title,
            )
            sess.add(row)
            await sess.commit()
            await sess.refresh(row)
            return row

    async def list_for_user(self, user_id: str, limit: int = 50) -> list[ChatSession]:
        uid = self._resolve_user_uuid(user_id)
        async with self._sf() as sess:
            # NULL user_id (anonymous) requires IS NULL, not == NULL
            user_filter = (
                ChatSession.user_id.is_(None) if uid is None else ChatSession.user_id == uid
            )
            stmt = (
                select(ChatSession)
                .where(user_filter)
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
        *,
        task_id: uuid.UUID | None = None,
        status: Literal["done", "partial", "cancelled", "error"] = "done",
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
                task_id=task_id,
                status=status,
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

    async def delete_message(self, message_id: str | uuid.UUID) -> None:
        """删除一条 message(steer 竞态兜底:已终态 task 的插话刚落库即撤销)。

        spec § 4.3 ③:merged=False 时把先行落库的插话行删掉,前端转普通新 turn
        自己重新落库,避免双行。
        """
        mid = uuid.UUID(message_id) if isinstance(message_id, str) else message_id
        async with self._sf() as sess:
            row = await sess.get(ChatMessage, mid)
            if row is not None:
                await sess.delete(row)
                await sess.commit()

    async def rebuild_turn_user_message(
        self,
        *,
        initial_prompt_message_id: uuid.UUID | None,
        task_id: uuid.UUID,
    ) -> str:
        """重建一个 turn 的 user 输入(retry 用,spec § 4.3)。

        = 原始 user 消息 + 该 turn 全部插话(steering),拼成单 user_message。

        关联现状(读 POST /chat 与 POST /chat/steer 的落库形状):
        - 原始 user 消息:POST /chat 落 user 行时 task 尚未创建,故 ChatMessage.task_id
          为空;它经 ``ChatTask.initial_prompt_message_id`` 关联。本方法用传入的
          ``initial_prompt_message_id`` 主键直取。
        - 插话:POST /chat/steer 落库时带 ``task_id``,故经 ``ChatMessage.task_id ==
          原 tid 且 role=user`` 查,按 created_at 升序。

        拼接策略:主消息 + "\\n\\n(补充指令: <插话1>)" 逐条追加。无原始消息(早期失败
        前甚至 user 行都没落)时,退化为只用插话;两者皆空返回空串(worker 仍会跑,
        多半直答兜底)。
        """
        parts: list[str] = []

        if initial_prompt_message_id is not None:
            async with self._sf() as sess:
                orig = await sess.get(ChatMessage, initial_prompt_message_id)
                if orig is not None and orig.content:
                    parts.append(str(orig.content))

        async with self._sf() as sess:
            stmt = (
                select(ChatMessage)
                .where(ChatMessage.task_id == task_id)
                .where(ChatMessage.role == "user")
                .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
            )
            steer_rows = list((await sess.execute(stmt)).scalars().all())

        main = parts[0] if parts else ""
        steer_texts = [str(r.content) for r in steer_rows if r.content]
        if not main and steer_texts:
            # 无原始消息 → 第一条插话当主消息,其余作补充
            main = steer_texts[0]
            steer_texts = steer_texts[1:]

        out = main
        for s in steer_texts:
            out = f"{out}\n\n(补充指令: {s})" if out else f"(补充指令: {s})"
        return out

    async def rename_session(self, session_id: str, new_title: str) -> None:
        sid = uuid.UUID(session_id) if isinstance(session_id, str) else session_id
        async with self._sf() as sess:
            await sess.execute(
                update(ChatSession)
                .where(ChatSession.id == sid)
                .values(
                    title=new_title, title_source="user_renamed"
                )  # 2026-05-17: user rename is terminal
            )
            await sess.commit()

    async def delete_session(self, session_id: str) -> None:
        sid = uuid.UUID(session_id) if isinstance(session_id, str) else session_id
        async with self._sf() as sess:
            row = await sess.get(ChatSession, sid)
            if row:
                await sess.delete(row)  # CASCADE clears ChatMessage rows
                await sess.commit()

    async def find_active_task_for_session(self, session_id: uuid.UUID | str) -> ChatTask | None:
        """委托 ChatTaskRepo;放在 ChatSessionRepo 作为前端 single endpoint
        (/chats/{sid}) 的便利方法。
        """
        sid = uuid.UUID(session_id) if isinstance(session_id, str) else session_id
        task_repo = ChatTaskRepo(self._sf)
        return await task_repo.find_active_for_session(sid)

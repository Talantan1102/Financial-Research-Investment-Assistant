"""ChatTaskRepo — chat_tasks 表 CRUD + 6 状态机迁移。

设计目标:
- 状态机方法集(mark_running / mark_done / mark_partial / mark_cancelled /
  mark_error)幂等且只前进
- bump_seq 用于 Plan 2 的事件序号 + stale 探测
- find_active_for_session 用于 GET /chats/{sid} 返回 active_task_id

异常处理:不在 repo 层抛业务异常,只在 SQLAlchemy 层报错;调用方决定如何处理。
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import and_, desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatTask

_ACTIVE_STATUSES = ("queued", "running")


class ChatTaskRepo:
    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self._sf = session_factory

    async def create_queued(
        self,
        *,
        session_id: str | uuid.UUID,
        user_id: str | uuid.UUID | None,
        langgraph_thread_id: str,
        initial_prompt_message_id: uuid.UUID | None,
        parent_task_id: uuid.UUID | None = None,
    ) -> ChatTask:
        sid = uuid.UUID(session_id) if isinstance(session_id, str) else session_id
        uid: uuid.UUID | None
        if user_id is None:
            uid = None  # anonymous pre-auth(对齐 ChatSession.user_id 模式)
        else:
            uid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
        async with self._sf() as sess:
            row = ChatTask(
                id=uuid.uuid4(),
                session_id=sid,
                user_id=uid,
                status="queued",
                langgraph_thread_id=langgraph_thread_id,
                initial_prompt_message_id=initial_prompt_message_id,
                parent_task_id=parent_task_id,
            )
            sess.add(row)
            await sess.commit()
            await sess.refresh(row)
            return row

    async def mark_running(self, task_id: uuid.UUID) -> None:
        async with self._sf() as sess:
            await sess.execute(
                update(ChatTask)
                .where(ChatTask.id == task_id)
                .values(status="running", started_at=datetime.utcnow())
            )
            await sess.commit()

    async def mark_done(self, task_id: uuid.UUID, *, langgraph_checkpoint_id: str | None) -> None:
        async with self._sf() as sess:
            await sess.execute(
                update(ChatTask)
                .where(ChatTask.id == task_id)
                .values(
                    status="done",
                    finished_at=datetime.utcnow(),
                    langgraph_checkpoint_id=langgraph_checkpoint_id,
                )
            )
            await sess.commit()

    async def mark_partial(
        self, task_id: uuid.UUID, *, langgraph_checkpoint_id: str | None
    ) -> None:
        async with self._sf() as sess:
            await sess.execute(
                update(ChatTask)
                .where(ChatTask.id == task_id)
                .values(
                    status="partial",
                    finished_at=datetime.utcnow(),
                    langgraph_checkpoint_id=langgraph_checkpoint_id,
                )
            )
            await sess.commit()

    async def mark_cancelled(
        self, task_id: uuid.UUID, *, langgraph_checkpoint_id: str | None
    ) -> None:
        async with self._sf() as sess:
            await sess.execute(
                update(ChatTask)
                .where(ChatTask.id == task_id)
                .values(
                    status="cancelled",
                    finished_at=datetime.utcnow(),
                    langgraph_checkpoint_id=langgraph_checkpoint_id,
                )
            )
            await sess.commit()

    async def mark_error(self, task_id: uuid.UUID, *, error_message: str) -> None:
        async with self._sf() as sess:
            await sess.execute(
                update(ChatTask)
                .where(ChatTask.id == task_id)
                .values(
                    status="error",
                    finished_at=datetime.utcnow(),
                    error_message=error_message,
                )
            )
            await sess.commit()

    async def get_by_id(self, task_id: uuid.UUID) -> ChatTask | None:
        async with self._sf() as sess:
            return await sess.get(ChatTask, task_id)

    async def find_active_for_session(self, session_id: uuid.UUID) -> ChatTask | None:
        """返回 session 内最新的 queued/running 任务。最多一个(单 user 单 session 串行)。"""
        async with self._sf() as sess:
            stmt = (
                select(ChatTask)
                .where(
                    and_(
                        ChatTask.session_id == session_id,
                        ChatTask.status.in_(_ACTIVE_STATUSES),
                    )
                )
                .order_by(desc(ChatTask.created_at))
                .limit(1)
            )
            return (await sess.execute(stmt)).scalar_one_or_none()

    async def bump_seq(self, task_id: uuid.UUID, *, delta: int = 1) -> None:
        """递增 last_event_seq。Plan 2 用,Plan 1 先实现 + 测。"""
        async with self._sf() as sess:
            await sess.execute(
                update(ChatTask)
                .where(ChatTask.id == task_id)
                .values(last_event_seq=ChatTask.last_event_seq + delta)
            )
            await sess.commit()

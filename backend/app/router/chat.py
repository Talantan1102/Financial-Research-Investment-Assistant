"""HTTP /api/v0/chat — chat enqueue + SSE replay endpoints.

老 supervisor 图退役(Phase 7,spec § 5.4):chat 路径完全跑在 chatloop ToolLoop
引擎上,由 Celery worker(app.tasks.chat_runner)异步驱动。本 router 不再 inline
跑 LangGraph(astream_events / _stream_chat / _adapt_event 全删),只负责:

- POST /api/v0/chat        : 落 user message + create chat_task + enqueue Celery
                             run_chat,返回 ``{task_id, session_id, stream_url}``;
                             首轮触发 session-start persona populate + title 任务。
- GET  /api/v0/chat/stream/{task_id} : 从 Redis Streams XREAD chunk-level event 转 SSE。
- POST /api/v0/chat/cancel|steer|retry/{task_id} : 取消 / 插话 / 整 turn 重跑。
- GET  /api/v0/tools       : MCP chat-profile 工具清单(slash 菜单)。

升级事件(escalate_request / escalate_packet_draft)由 Celery worker 在 turn 后
chunk-level forward(见 app.tasks.chat_runner._emit_escalation),不再 inline。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.agents.escalation_extractor import EscalationExtractor
from app.services.chat_session_repo import ChatSessionRepo
from app.services.chat_task_repo import ChatTaskRepo
from app.services.escalation_record_repo import EscalationRecordRepo

if TYPE_CHECKING:
    from redis.asyncio import Redis as AsyncRedis

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat-v0"])

# ---------------------------------------------------------------------------
# Escalation dependency stubs (Plan 3 E2 — wired by app_main lifespan in T11)
# ---------------------------------------------------------------------------


def get_escalation_extractor() -> EscalationExtractor:
    """Return an EscalationExtractor instance.

    Replaced via ``dependency_overrides`` in tests and by app_main lifespan in
    Task 11 (which wires the real LLMService).  Raising here acts as a safe
    sentinel: any request that reaches escalation without a proper override will
    fail loudly rather than silently skip extraction.
    """
    raise RuntimeError("EscalationExtractor dependency not configured")


def get_escalation_record_repo() -> EscalationRecordRepo:
    """Return an EscalationRecordRepo instance.

    Replaced via ``dependency_overrides`` in tests and by app_main lifespan in
    Task 11 (which wires the real async DB session factory).
    """
    raise RuntimeError("EscalationRecordRepo dependency not configured")


def get_async_session_factory(request: Request) -> Any | None:
    """Return the async PG session factory wired by app_main lifespan, or None.

    Plan 1 Task 5: POST /api/v0/chat reads this dependency to decide whether to
    persist chat messages + task rows. If the factory is None (test path / dev
    without PG), the handler degrades gracefully to legacy streaming-only
    behavior so existing SSE tests keep passing.

    Sourced from ``app.state.async_session_factory`` (set in app_main.lifespan).
    Overridden in tests via ``dependency_overrides[get_async_session_factory]``
    to inject an in-memory sqlite ``async_sessionmaker``.
    """
    return getattr(request.app.state, "async_session_factory", None)


def get_redis_async(request: Request) -> AsyncRedis | None:
    """Plan 2: Redis async client wired by app_main lifespan to app.state.redis_async.

    Returns None if Redis is not configured — endpoints that need it 503 gracefully.
    Overridden in tests via ``dependency_overrides[get_redis_async]`` to inject
    a fakeredis instance.
    """
    return getattr(request.app.state, "redis_async", None)


# ---------------------------------------------------------------------------
# Request / Response schemas (spec § 5)
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    session_id: str  # client-generated UUID; cross-turn session identifier
    message: str
    enable_web_search: bool = False  # v0 placeholder
    enable_kb_search: bool = False  # v0 placeholder
    forced_tool_name: str | None = None  # slash command: force this MCP tool
    forced_tool_args: dict[str, Any] | None = None  # args for the forced tool


# ---------------------------------------------------------------------------
# Stub User — v0 anonymous auth. C44: single source in auth_helpers (chat.py
# previously kept a byte-for-byte duplicate); re-export so the Depends usages
# below resolve to the shared definitions and future auth changes propagate.
# ---------------------------------------------------------------------------
from app.router.auth_helpers import _AnonUser, get_current_user  # noqa: E402

# ---------------------------------------------------------------------------
# PG session factory helper(供 session-start persona populate 用)
# ---------------------------------------------------------------------------


def _build_async_pg_session_factory_or_none() -> Any | None:
    """Build sync session factory from env DATABASE_URL.

    无 PG / 测试环境返回 None(persona populate hook 会 no-op skip)。
    """
    import os

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return None
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session, sessionmaker

        engine = create_engine(db_url, pool_pre_ping=True)
        Factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)

        def _factory() -> Session:
            return Factory()

        return _factory
    except Exception as e:
        logger.warning("PG session factory build failed (persona populate will skip): %s", e)
        return None


# ---------------------------------------------------------------------------
# Session-start persona populate(老 inline path 搬来,enqueue 路径首轮触发)
# ---------------------------------------------------------------------------

_persona_populated_sessions: set[str] = set()
"""C.5 Plan 3 session-start dedupe — best-effort per-process cache.

避免每 turn 重跑 4 次 PG query. 生产可换成 PG 标记 / Redis ttl, 当前 portfolio
范围只防 in-process 重跑就够用.
"""


async def _maybe_populate_persona_on_session_start(user: _AnonUser, session_id: str) -> None:
    """首轮 session 把 portfolio 蒸馏进 working_blocks(persona)。

    老 inline SSE path(_stream_chat)在 turn 开头跑这个 hook;chatloop 换引擎后
    POST /chat 只 enqueue 不 inline,故把 hook 搬到 enqueue 路径(首轮触发一次)。
    worker 端 _render_persona 只渲染既有 persona,不负责 populate,故此 hook 必须
    在 router 这一层保留(spec § 5.4 退役清单"保留 persona populate")。

    best-effort / fail-safe:失败仅 log,不阻塞 enqueue。
    """
    session_key = f"{user.id}:{session_id}"
    if session_key in _persona_populated_sessions:
        return
    _persona_populated_sessions.add(session_key)
    try:
        from app.memory.persona_populator import populate_persona_on_session_start

        persona_pg_factory = _build_async_pg_session_factory_or_none()
        if persona_pg_factory is not None:
            user_uuid = user.id if isinstance(user.id, UUID) else UUID(str(user.id))
            # populate_persona_on_session_start 跑 ~6 个 blocking PG query + commit;
            # offload 出事件循环,别 stall 并发请求。
            await asyncio.to_thread(
                populate_persona_on_session_start, persona_pg_factory, user_id=user_uuid
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("populate_persona_on_session_start failed: %s", exc)


def _coerce_user_uuid(user_id: Any) -> UUID | None:
    """Resolve a possibly-anonymous user_id into a real UUID or None.

    Production users have UUID; the v0 stub uses ``"anonymous"`` and test code
    uses ``"test-user"``. Non-UUID strings (anonymous / test stub) → None so
    that ChatTask.user_id stays NULL pre-auth — matches ChatSession.user_id's
    nullable behavior. Production PG FK (``users.id``) would otherwise reject
    a synthetic uuid5 that has no matching row in ``users``.

    C.6 接 JWT 后,user.id 永远是真 UUID,本函数走直通分支。
    """
    if isinstance(user_id, UUID):
        return user_id
    s = str(user_id)
    try:
        return UUID(s)
    except (ValueError, AttributeError):
        return None  # anonymous / test stub → NULL in DB


# ---------------------------------------------------------------------------
# Route handler
# ---------------------------------------------------------------------------


@router.post("/api/v0/chat", response_model=None)
async def chat(
    req: ChatRequest,
    user: _AnonUser = Depends(get_current_user),
    pg_factory: Any | None = Depends(get_async_session_factory),
    redis: AsyncRedis | None = Depends(get_redis_async),
) -> dict[str, str]:
    """POST /api/v0/chat — chat entry endpoint(enqueue-only,老图退役后单 path)。

    落 user message + create chat_task + enqueue Celery ``run_chat``(chatloop
    ToolLoop 引擎,见 app.tasks.chat_runner),返回 JSON
    ``{task_id, session_id, stream_url}``。前端用 GET /chat/stream/{tid} 订阅
    Redis Streams replay。

    首轮 session 触发 session-start persona populate(working_blocks 蒸馏)+
    session title 异步生成。升级事件由 Celery worker turn 后 chunk-level forward
    (不再 inline)。

    Status:
        - 200: ``{task_id, session_id, stream_url}``(enqueued)
        - 503: PG / Redis 未 wire(chat 不可用 —— 老 inline SSE fallback 已随
          supervisor 图退役删除,spec § 5.4)。
    """
    if pg_factory is None or redis is None:
        raise HTTPException(
            status_code=503,
            detail="chat not available — PG or Redis unavailable",
        )

    from app.tasks.chat_runner import enqueue_run_chat

    # 首轮 session 把 portfolio 蒸馏进 working_blocks(persona)。best-effort。
    await _maybe_populate_persona_on_session_start(user, req.session_id)

    session_repo = ChatSessionRepo(pg_factory)
    task_repo = ChatTaskRepo(pg_factory)

    user_msg = await session_repo.append_message(
        session_id=req.session_id,
        role="user",
        content=req.message,
    )
    task = await task_repo.create_queued(
        session_id=req.session_id,
        user_id=_coerce_user_uuid(user.id),
        langgraph_thread_id=f"{user.id}:{req.session_id}",
        initial_prompt_message_id=user_msg.id,
    )

    enqueue_run_chat(
        task_id=str(task.id),
        session_id=req.session_id,
        user_id=str(user.id),
        user_message=req.message,
    )

    # === Async session title (2026-05-17): user msg 入库即触发, 跟 worker 并行跑;
    # LLM 只读 user_msg, 不必等 assistant 完成 → "新对话" 中间态尽量短。
    # task 内部检查 title_source != "pending" 幂等 skip, 重复触发安全。
    try:
        session = await session_repo.get_session(str(req.session_id))
        if session and session.title_source == "pending":
            from app.tasks.title_generation import generate_session_title

            generate_session_title.apply_async(args=[str(req.session_id)])
            logger.info("enqueued generate_session_title for session %s", req.session_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("title enqueue skipped: %s", exc)

    return {
        "task_id": str(task.id),
        "session_id": req.session_id,
        "stream_url": f"/api/v0/chat/stream/{task.id}",
    }


# ---------------------------------------------------------------------------
# Plan 2 Task 4: GET /api/v0/chat/stream/{task_id} — SSE replay endpoint
# ---------------------------------------------------------------------------


@router.get("/api/v0/chat/stream/{task_id}")
async def chat_stream(
    task_id: str,
    request: Request,
    last_event_id: str = "0",
    pg_factory: Any | None = Depends(get_async_session_factory),
    redis: AsyncRedis | None = Depends(get_redis_async),
) -> StreamingResponse:
    """SSE replay endpoint — XREAD from Redis Streams + forward as SSE frames.

    Plan 2 Task 4:前端打开 SSE 后,我们从 Redis Stream 拉 chunk-level event 转发。
    Spec § 6.2:entry id 直接透传作为 SSE ``id:`` field → 前端断流时回传
    ``last_event_id`` 续读;§ 5.5:客户端断开 → 停转发(不杀 Celery task)。

    Args:
        task_id: ChatTask UUID
        last_event_id: Redis Stream entry id ("0" = from start; ``<ms>-<seq>``
            from a previous reconnect)

    Returns:
        text/event-stream with frames ``event: <type>\\nid: <entry_id>\\ndata: <json>\\n\\n``.

    Status codes:
        - 200: streaming OK
        - 404: invalid uuid OR task not found
        - 503: PG / Redis not wired
    """
    try:
        task_uuid = uuid.UUID(task_id)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(status_code=404, detail=f"invalid task_id: {task_id}") from exc

    if pg_factory is None or redis is None:
        raise HTTPException(
            status_code=503,
            detail="chat streaming not configured (PG or Redis unavailable)",
        )

    task_repo = ChatTaskRepo(pg_factory)
    task = await task_repo.get_by_id(task_uuid)
    if task is None:
        raise HTTPException(status_code=404, detail=f"task {task_id} not found")

    session_id_uuid = task.session_id  # ChatTask.session_id is UUID

    async def _forward_sse() -> AsyncIterator[str]:
        # Inline import: ChatEventBus → redis.asyncio import; defer to runtime so
        # the chat router stays importable in dev environments without redis.
        from app.services.chat_event_bus import ChatEventBus

        bus = ChatEventBus(redis=redis)  # type: ignore[arg-type]
        cur_id = last_event_id
        while True:
            # Spec § 5.5: client disconnect → stop forwarding, do NOT kill Celery task.
            if await request.is_disconnected():
                logger.debug(
                    "client disconnected from /chat/stream/%s; stopping forward",
                    task_id,
                )
                return
            entries = await bus.xread_blocking(
                session_id_uuid,
                task_uuid,
                last_id=cur_id,
                count=20,
                block_ms=10_000,  # 10s block then re-check disconnect
            )
            if not entries:
                continue
            for entry_id, payload in entries:
                cur_id = entry_id
                ev_type = payload.get("type", "unknown")
                data_str = json.dumps(payload, ensure_ascii=False)
                yield f"event: {ev_type}\nid: {entry_id}\ndata: {data_str}\n\n"
                # Terminal events: stop the forward loop.
                if ev_type in ("done", "error_done"):
                    return

    return StreamingResponse(
        _forward_sse(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Plan 3 Task 4: POST /api/v0/chat/cancel/{task_id} — publish cancel signal
# ---------------------------------------------------------------------------


@router.post("/api/v0/chat/cancel/{task_id}", status_code=202)
async def chat_cancel(
    task_id: str,
    pg_factory: Any | None = Depends(get_async_session_factory),
    redis: AsyncRedis | None = Depends(get_redis_async),
) -> dict[str, str]:
    """Publish cancel signal to ``chat:cancel:{tid}`` channel.

    Spec § 5.3 Scenario C:用户点停止 → 立即 return 202(异步生效);worker 内
    listener 收到 signal → raise GraphInterrupt → finalize 走 partial commit
    (Plan 3 Task 3 已实施)。

    Status codes:
        - 202: cancel signal published (worker reacts async)
        - 404: invalid task_id (not UUID) OR task not found in PG
        - 503: PG / Redis 未 wire
    """
    try:
        task_uuid = uuid.UUID(task_id)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(status_code=404, detail=f"invalid task_id: {task_id}") from exc

    if pg_factory is None or redis is None:
        raise HTTPException(
            status_code=503,
            detail="chat cancel not available — PG or Redis unavailable",
        )

    task_repo = ChatTaskRepo(pg_factory)
    task = await task_repo.get_by_id(task_uuid)
    if task is None:
        raise HTTPException(status_code=404, detail=f"task {task_id} not found")

    # Inline import: ChatCancelBus → redis.asyncio import; defer to runtime to
    # keep chat router importable in dev environments without redis configured.
    from app.services.chat_cancel_bus import ChatCancelBus

    cancel_bus = ChatCancelBus(redis=redis)  # type: ignore[arg-type]
    receivers = await cancel_bus.publish_cancel(task_uuid)
    return {
        "task_id": task_id,
        "receivers": str(receivers),
        "status": "cancel_published",
    }


# ---------------------------------------------------------------------------
# Phase 4 Task 4.3: POST /api/v0/chat/steer/{task_id} — 插话(steering)并入当前 turn
# ---------------------------------------------------------------------------


class SteerRequest(BaseModel):
    message: str


@router.post("/api/v0/chat/steer/{task_id}")
async def chat_steer(
    task_id: str,
    body: SteerRequest,
    pg_factory: Any | None = Depends(get_async_session_factory),
    redis: AsyncRedis | None = Depends(get_redis_async),
) -> dict[str, Any]:
    """插话:streaming 中把新指令并入当前 turn(spec § 4.3 三步)。

    ① 先落库 chat_messages(role=user, task_id=本 tid):崩溃/重跑不蒸发,且 retry
       能查到该 turn 的全部插话(ChatMessage.task_id == 原 tid)合成 user_message;
    ② task 处于 queued/running → LPUSH steer List(ChatSteerBus),worker 圈边界
       RPOP 并入 messages 尾部 → SSE steer_merged。返回 ``{merged: True}``;
    ③ 竞态兜底:task 已终态 → 不入队,把 ① 刚落的 user 行删除(同事务语义),
       返回 ``{merged: False}``。前端(Phase 5)拿到 false 后走普通 sendMessage
       (POST /chat 自己落库),避免双行(否则新 turn 入口会再落一次)。

    Status codes:
        - 200: ``{merged: bool, message_id?: str}``
        - 404: invalid task_id (not UUID) OR task not found
        - 503: PG / Redis unavailable
    """
    try:
        task_uuid = uuid.UUID(task_id)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(status_code=404, detail=f"invalid task_id: {task_id}") from exc

    if pg_factory is None or redis is None:
        raise HTTPException(
            status_code=503,
            detail="chat steer not available — PG or Redis unavailable",
        )

    task_repo = ChatTaskRepo(pg_factory)
    task = await task_repo.get_by_id(task_uuid)
    if task is None:
        raise HTTPException(status_code=404, detail=f"task {task_id} not found")

    session_repo = ChatSessionRepo(pg_factory)

    # ① 先落库(role=user,关联本 task,status 默认 done) — 崩溃/重跑不蒸发。
    steer_msg = await session_repo.append_message(
        session_id=str(task.session_id),
        role="user",
        content=body.message,
        task_id=task_uuid,
    )

    if task.status in ("queued", "running"):
        # ② LPUSH steer List(读端 RedisSteerSource 圈边界 RPOP 并入)
        from app.services.chat_steer_bus import ChatSteerBus

        steer_bus = ChatSteerBus(redis=redis)
        await steer_bus.push(task_uuid, body.message)
        return {"merged": True, "message_id": str(steer_msg.id)}

    # ③ 竞态兜底:已终态 → 删掉刚落的行,前端转普通新 turn(自己落库,避免双行)。
    await session_repo.delete_message(str(steer_msg.id))
    return {"merged": False}


# ---------------------------------------------------------------------------
# Phase 4 Task 4.3: POST /api/v0/chat/retry/{task_id} — 整 turn 重跑(checkpoint 退役)
# ---------------------------------------------------------------------------


@router.post("/api/v0/chat/retry/{task_id}")
async def chat_retry(
    task_id: str,
    pg_factory: Any | None = Depends(get_async_session_factory),
    redis: AsyncRedis | None = Depends(get_redis_async),
) -> dict[str, str]:
    """重试 failed/cancelled/partial task —— 整 turn 从头重跑(spec § 4.3)。

    checkpoint 退役后(turn 原子语义):不再"恢复到第几圈",而是整 turn 重跑。
    - task.status 必须 ∈ {error, partial, cancelled}(done / running / queued 拒);
    - **不再有 "checkpoint 非空" 守卫**(worker 路径上 checkpoint 本就是坏的,
      spec § 0.2);
    - user_message = 原 turn 的 user 消息 + 该 turn 全部插话(行为不漂移,
      spec § 4.3)。原 user 消息经 ``ChatTask.initial_prompt_message_id`` 关联
      (POST /chat 落 user 行时 task 尚不存在,故走 task 的 initial_prompt 字段,
      不是 ChatMessage.task_id);插话经 ``ChatMessage.task_id == 原 tid`` 关联
      (POST /chat/steer 落库时带 task_id)。多条拼接:主消息 +
      "\\n\\n(补充指令: ...)";
    - 创建新 chat_tasks row,parent_task_id=旧 tid,initial_prompt_message_id 沿用;
    - enqueue Celery 整 turn 重跑(resume_checkpoint_id=None;历史靠 rebuild_context
      取到上一 turn 为止,partial/error 行不进窗口)。

    Status codes:
        - 200: new task enqueued; body = {task_id, parent_task_id, stream_url}
        - 404: invalid task_id (not UUID) OR task not found
        - 409: task status ∉ retryable set
        - 503: PG / Redis unavailable
    """
    try:
        task_uuid = uuid.UUID(task_id)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(status_code=404, detail=f"invalid task_id: {task_id}") from exc

    if pg_factory is None or redis is None:
        raise HTTPException(
            status_code=503,
            detail="chat retry not available — PG or Redis unavailable",
        )

    task_repo = ChatTaskRepo(pg_factory)
    old_task = await task_repo.get_by_id(task_uuid)
    if old_task is None:
        raise HTTPException(status_code=404, detail=f"task {task_id} not found")

    if old_task.status not in ("error", "partial", "cancelled"):
        raise HTTPException(
            status_code=409,
            detail=(
                f"cannot retry task in status={old_task.status}; "
                "only error/partial/cancelled retryable"
            ),
        )

    # 重建原 turn 的 user_message:原始 user 消息 + 该 turn 全部插话(时间序)。
    session_repo = ChatSessionRepo(pg_factory)
    user_message = await session_repo.rebuild_turn_user_message(
        initial_prompt_message_id=old_task.initial_prompt_message_id,
        task_id=old_task.id,
    )

    # Create new task linked to old (parent_task_id chain; initial prompt msg sticky)
    new_task = await task_repo.create_queued(
        session_id=old_task.session_id,
        user_id=old_task.user_id,
        langgraph_thread_id=old_task.langgraph_thread_id,
        initial_prompt_message_id=old_task.initial_prompt_message_id,
        parent_task_id=old_task.id,
    )

    # Inline import: chat_runner pulls Celery + redis; defer to runtime so the
    # chat router stays importable in dev environments without Celery configured.
    from app.tasks.chat_runner import enqueue_run_chat

    enqueue_run_chat(
        task_id=str(new_task.id),
        session_id=str(old_task.session_id),
        user_id=str(old_task.user_id) if old_task.user_id else "anonymous",
        # 整 turn 重跑:user_message = 原消息 + 该 turn 插话;checkpoint 退役 → None。
        user_message=user_message,
        resume_checkpoint_id=None,
        parent_task_id=str(old_task.id),
    )

    return {
        "task_id": str(new_task.id),
        "parent_task_id": str(old_task.id),
        "stream_url": f"/api/v0/chat/stream/{new_task.id}",
    }


@router.get("/api/v0/tools")
async def list_chat_tools(request: Request) -> dict[str, Any]:
    """List MCP chat-profile tools (name/description/inputSchema) for the slash menu.

    Source of truth = the live MCP client's list_tools() — the 8 chat tools wired
    to the chat agent. Returns 503 if the MCP subprocess isn't up.
    """
    mcp_client = getattr(request.app.state, "mcp_client", None)
    if mcp_client is None:
        raise HTTPException(
            status_code=503, detail="tools unavailable — mcp_client not initialized"
        )
    tools = await mcp_client.list_tools()
    return {
        "tools": [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "inputSchema": t.get("inputSchema", {}),
            }
            for t in tools
        ]
    }

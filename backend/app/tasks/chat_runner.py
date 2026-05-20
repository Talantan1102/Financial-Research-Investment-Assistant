"""Celery task: run_chat — 异步跑 LangGraph + XADD events to Redis Streams。

入口语义:
- Celery worker 收到 task_id → mark_running → 跑 graph
- 每个 LangGraph chunk-level event → XADD to chat:events:{sid}:{tid}
- 完成 / 异常 → XADD 终止事件 + finalize_task_persistence(commit assistant +
  mark task)

Plan 2 Task 3 scope:
- run_chat_async(internal async,test 直接 await 它)
- run_chat(Celery sync wrapper,thin shim;real worker 走 .delay() → 这里)
- enqueue_run_chat(production 入口,POST /chat 改造在 Task 5)

Plan 2 Task 8 scope:
- run_chat wrapper production wiring(替换 NotImplementedError stub)
- worker-side build helpers(_build_chat_graph_for_worker /
  _build_session_factory_for_worker / _build_redis_for_worker), module-level
  lazy singletons — worker init once + reuse across tasks
- 1 个 L2 sanity test(test_chat_inflight_l2.py)守护 wrapper wire 通

Test 策略(test_chat_runner.py):directly await run_chat_async,inject
fakeredis + fake graph + sqlite session_factory。
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from app.router.chat_finalize import finalize_task_persistence
from app.services.chat_event_bus import ChatEventBus
from app.services.chat_task_repo import ChatTaskRepo
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Worker-side singleton caches — initialized lazily on first task invocation.
# Worker subprocess does NOT have access to FastAPI app.state, so we re-build
# graph / session_factory / redis using env vars (same primitives lifespan uses).
# ---------------------------------------------------------------------------
_GRAPH_SINGLETON: Any | None = None
_SESSION_FACTORY_SINGLETON: Any | None = None
_REDIS_SINGLETON: Any | None = None
_MCP_CLIENT_SINGLETON: Any | None = None
_MCP_CTX_SINGLETON: Any | None = None  # keep ctx ref alive — GC would tear down subprocess


async def _build_chat_graph_for_worker() -> Any:
    """Build (or reuse cached) chat graph for Celery worker context (async).

    Worker has no lifespan — we lazy-launch the MCP subprocess on first task
    in this worker process, cache the client + ctx at module level, then build
    the graph via `app.router.chat._build_graph_singleton`.

    Subprocess lifetime: __aenter__'d but never __aexit__'d here; Celery
    worker shutdown SIGKILLs the subprocess as part of process exit. This
    matches app_main.py's web lifespan handling (it also keeps the ctx ref
    on app.state to prevent GC tear-down).

    checkpointer=None on worker side — web side threads PG checkpointer in
    via DI; worker tasks use LangGraph thread_id for state lookup, no
    shared in-memory checkpoint required.
    """
    global _GRAPH_SINGLETON, _MCP_CLIENT_SINGLETON, _MCP_CTX_SINGLETON
    if _GRAPH_SINGLETON is None:
        from app.router.chat import _build_graph_singleton
        from app.services.mcp_client import MCPClient

        if _MCP_CLIENT_SINGLETON is None:
            _MCP_CTX_SINGLETON = MCPClient.from_subprocess()
            _MCP_CLIENT_SINGLETON = await _MCP_CTX_SINGLETON.__aenter__()

        _GRAPH_SINGLETON = await _build_graph_singleton(
            mcp_client=_MCP_CLIENT_SINGLETON,
            checkpointer=None,
        )
    return _GRAPH_SINGLETON


def _build_session_factory_for_worker() -> Any:
    """Build async_sessionmaker for Celery worker context.

    Worker has no lifespan; can't use app.state.async_session_factory.
    Builds the same SQLAlchemy async engine that web lifespan does, using
    `_sqlalchemy_async_pg_url` from app_main (single source of URL truth).
    """
    global _SESSION_FACTORY_SINGLETON
    if _SESSION_FACTORY_SINGLETON is None:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.app_main import _sqlalchemy_async_pg_url

        engine = create_async_engine(_sqlalchemy_async_pg_url(), future=True)
        _SESSION_FACTORY_SINGLETON = async_sessionmaker(engine, expire_on_commit=False)
    return _SESSION_FACTORY_SINGLETON


def _build_redis_for_worker() -> Any:
    """Build redis.asyncio client for Celery worker context.

    Same conn pool reuse pattern as factory — Redis client is cached and reused
    across tasks within the same worker process.
    """
    global _REDIS_SINGLETON
    if _REDIS_SINGLETON is None:
        import redis.asyncio as redis_async

        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        _REDIS_SINGLETON = redis_async.Redis.from_url(redis_url, decode_responses=False)
    return _REDIS_SINGLETON


def _adapt_event_for_stream(ev: dict[str, Any]) -> dict[str, Any] | None:
    """Map LangGraph astream_events dict → Plan 2 chunk-level event dict (or None).

    Plan 2 输出的事件类型(spec § 6.5):
    - token : {type, text}  (chunk-level model output)
    - tool_start: {type, node}
    - tool_end  : {type, node, output}
    - plan      : {type, output}

    LangGraph 自然结束(on_chain_end + name=LangGraph)由调用方在 finally
    内 XADD `{type: done}`,因此本函数对它返 None。
    """
    ev_type = ev.get("event", "")
    ev_name = ev.get("name", "")
    ev_data = ev.get("data", {})

    if ev_type == "on_chat_model_stream":
        chunk = ev_data.get("chunk", {}) if isinstance(ev_data, dict) else {}
        text = ""
        if hasattr(chunk, "content"):
            text = str(chunk.content)
        elif isinstance(chunk, dict):
            text = str(chunk.get("content", ""))
        # Dual field: `text` for backend tests (chat_runner / event_bus L0 测试),
        # `content` for frontend TokenEvent.content(frontend/src/types/chat.ts).
        # 两端历史约定不一致,Plan 2 dogfood 暴露;双字段发避免破 unit test 同时让前端能消费。
        return {"type": "token", "text": text, "content": text}

    if ev_type == "on_chain_start" and ev_name == "tool_node":
        return {"type": "tool_start", "node": ev_name}

    if ev_type == "on_chain_end" and ev_name == "tool_node":
        output = ev_data.get("output", {}) if isinstance(ev_data, dict) else {}
        return {"type": "tool_end", "node": ev_name, "output": _to_jsonable(output)}

    if ev_type == "on_chain_end" and ev_name == "planner_node":
        output = ev_data.get("output", {}) if isinstance(ev_data, dict) else {}
        return {"type": "plan", "output": _to_jsonable(output)}

    return None  # all others skip (LangGraph done emitted by finally)


def _extract_response_text(raw: str) -> str:
    """LLM 输出可能是 JSON-encoded `{"text"/"answer"/"response"/"content": "..."}`。
    试解析拿 string-valued 字段(优先 text > answer > response > content > 任意 string),
    失败 fallback 用 raw 字符串。
    """
    import json as _json

    try:
        parsed = _json.loads(raw)
    except Exception:
        return raw
    if not isinstance(parsed, dict):
        return raw
    for key in ("text", "answer", "response", "content"):
        v = parsed.get(key)
        if isinstance(v, str) and v:
            return v
    # Fallback: 第一个 string-valued 字段
    for v in parsed.values():
        if isinstance(v, str) and v:
            return v
    return raw


def _to_jsonable(obj: Any) -> Any:
    """LangGraph node output 可能含 Pydantic BaseModel(如 planner 的 Plan,tool 结果等)。
    json.dumps 不接 Pydantic 对象,需要 model_dump 转 dict。递归处理 dict / list / Pydantic。

    Plan 2 dogfood 暴露的 bug:plan event xadd_event 报 "Object of type Plan is not
    JSON serializable" → plan event 没推到 Redis Stream → 前端拿不到 plan / partial state。
    """
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_jsonable(v) for v in obj]
    return obj


class _CancelledByUser(Exception):  # noqa: N818
    """Internal signal: cancel_event 被 listener 设置后,graph stream loop raise 它,
    finally 块走 partial commit 路径(非 finalize_task_persistence)。

    Spec § 6.1: LangGraph 1.x 不支持外部 kill 信号 → wrapper 在每个 graph event
    之间检查 cancel_event,触发即 raise → finalize 走 partial commit。

    Naming intentionally not "Error" suffix — 这是 control-flow signal 不是错误。
    """


async def run_chat_async(
    *,
    task_id: uuid.UUID,
    graph_factory: Callable[[], Awaitable[Any]],
    session_factory: Callable[[], Any],
    redis: Any,
    user_message: str,
    session_id: str,
    user_id: uuid.UUID | str | None,
    resume_checkpoint_id: str | None = None,
) -> None:
    """Main worker async entry — DI 友好,test 可直接 await。

    Contract:
    - task_id: chat_tasks row id;调用前 router 已 create_queued
    - graph_factory: returns a CompiledStateGraph (or fake stub in tests)
    - session_factory: async_sessionmaker / 同 ChatTaskRepo / ChatSessionRepo 约定
    - redis: redis.asyncio.Redis(production)或 fakeredis.aioredis.FakeRedis(test)
    - user_message / session_id: 注入 LangGraph 的 initial state
    - user_id: 真 UUID(post-auth)/ 字符串如 "anonymous"(pre-auth)/ None;
      仅用于 LangGraph thread_id 拼接,不写 PG(chat_tasks.user_id 由 router 写入)
    - resume_checkpoint_id: Plan 3 retry 用,若传则注入 LangGraph config 让其
      从该 checkpoint state 续跑(本 Task 3 仅加签名 + config 接通,真行为留 Task 5
      golden case 测)

    Plan 3 加:
    - ChatCancelBus listener task — Redis pub/sub subscribe task channel,
      收到 cancel 信号即 set asyncio.Event flag
    - graph stream loop 每 event 之间 check cancel_event → raise _CancelledByUser
    - finally 块:cancel 走 mark_partial + append_message(status="partial");
      success 走 finalize_task_persistence(原 Plan 2 路径);error 同 Plan 2
    """
    import asyncio
    from contextlib import suppress

    from app.services.chat_cancel_bus import ChatCancelBus

    task_repo = ChatTaskRepo(session_factory)
    bus = ChatEventBus(redis=redis)
    cancel_bus = ChatCancelBus(redis=redis)
    cancel_event = asyncio.Event()

    async def _cancel_listener() -> None:
        try:
            async for _ in cancel_bus.subscribe_cancel(task_id):
                cancel_event.set()
                return
        except Exception as exc:  # noqa: BLE001
            logger.debug("cancel listener exit for task %s: %s", task_id, exc)

    listener_task = asyncio.create_task(_cancel_listener())

    sid_uuid: uuid.UUID = uuid.UUID(session_id) if isinstance(session_id, str) else session_id

    # mark_running idempotent (Plan 1 router 已 mark,这里 race-safe 再 mark)
    try:
        await task_repo.mark_running(task_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("mark_running on worker entry skipped: %s", exc)

    try:
        await bus.set_ttl(sid_uuid, task_id, seconds=ChatEventBus.DEFAULT_TTL_SECONDS)
    except Exception as exc:  # noqa: BLE001
        logger.debug("set_ttl on worker entry skipped: %s", exc)

    acc_assistant: list[str] = []
    graph_error: Exception | None = None
    cancelled_by_user = False
    final_state: dict[str, Any] | None = None

    graph = await graph_factory()

    initial = {
        "user_id": str(user_id),
        "session_id": session_id,
        "user_message": user_message,
        "request_id": f"req-{uuid.uuid4().hex[:12]}",
        "trace_request_id": f"req-{uuid.uuid4().hex[:12]}",
    }
    # Plan 3 retry:传 checkpoint_id 让 LangGraph 从 checkpoint state 续跑。
    # Task 3 仅加签名 + config 接通;真 resume 行为 Task 5 + golden 测。
    configurable: dict[str, Any] = {"thread_id": f"{user_id}:{session_id}"}
    if resume_checkpoint_id is not None:
        configurable["checkpoint_id"] = resume_checkpoint_id
    config: dict[str, Any] = {"configurable": configurable}

    try:
        async for ev in graph.astream_events(initial, config=config, version="v2"):
            # Plan 3:每 event 之间检查 cancel flag(spec § 6.1 wrapper 模式)
            if cancel_event.is_set():
                raise _CancelledByUser()

            # capture final_state from LangGraph done event
            if ev.get("event") == "on_chain_end" and ev.get("name") == "LangGraph":
                output = (ev.get("data") or {}).get("output") or {}
                if isinstance(output, dict):
                    final_state = output

            adapted = _adapt_event_for_stream(ev)
            if adapted is None:
                continue
            try:
                await bus.xadd_event(sid_uuid, task_id, adapted)
            except Exception as exc:  # noqa: BLE001
                logger.warning("xadd_event failed for task %s: %s", task_id, exc)
            if adapted.get("type") == "token":
                acc_assistant.append(adapted.get("text", ""))
            try:
                await task_repo.bump_seq(task_id, delta=1)
            except Exception as exc:  # noqa: BLE001
                logger.debug("bump_seq skipped for task %s: %s", task_id, exc)
    except _CancelledByUser:
        cancelled_by_user = True
        try:
            await bus.xadd_event(sid_uuid, task_id, {"type": "cancelled", "reason": "user_cancel"})
        except Exception as exc:  # noqa: BLE001
            logger.warning("xadd cancelled event failed for task %s: %s", task_id, exc)
    except Exception as exc:  # noqa: BLE001
        graph_error = exc
        try:
            await bus.xadd_event(sid_uuid, task_id, {"type": "error", "message": str(exc)[:500]})
        except Exception as inner:  # noqa: BLE001
            logger.warning("xadd error event failed for task %s: %s", task_id, inner)
    finally:
        # Stop cancel listener — 不论如何退,listener 都要 clean up。
        listener_task.cancel()
        with suppress(asyncio.CancelledError):
            await listener_task

        # Plan 2 dogfood bug fix: 如果 graph 走 direct_response 路径(planner 决定不调
        # tool,responder 一次性 invoke),没 on_chat_model_stream 事件 → acc_assistant
        # 空 → 前端 typewriter 没字符可吐 → assistant message 不显示。
        # Fallback: 拿 final_state.final_response 一次性 emit 为 token event,
        # 让前端 typewriter 接到 content 后逐字符吐(视觉等同 streaming)。
        # Cancel 路径跳过(用户主动停,不补内容)。
        if graph_error is None and not cancelled_by_user and not acc_assistant:
            fallback_text = ""
            if isinstance(final_state, dict):
                fr = final_state.get("final_response")
                if isinstance(fr, str) and fr:
                    # responder 设计是自由文本,但 LLM(qwen / dashscope)
                    # 实际常返 JSON 格式 `{"text": ...}` / `{"answer": ...}` /
                    # `{"response": ...}`。兼容尝试解第一个 string-valued 字段,
                    # 失败 fallback 用 raw string。
                    fallback_text = _extract_response_text(fr)
            if fallback_text:
                try:
                    await bus.xadd_event(
                        sid_uuid,
                        task_id,
                        # Dual field — 同 _adapt_event_for_stream 的 token event
                        {"type": "token", "text": fallback_text, "content": fallback_text},
                    )
                    acc_assistant.append(fallback_text)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("fallback token xadd failed for task %s: %s", task_id, exc)

        # 终止事件:cancel → cancelled;成功 → done;失败 → error_done
        try:
            if cancelled_by_user:
                terminal_event: dict[str, Any] = {"type": "cancelled"}
            elif graph_error is None:
                terminal_event = {"type": "done"}
            else:
                terminal_event = {"type": "error_done"}
            await bus.xadd_event(sid_uuid, task_id, terminal_event)
        except Exception as exc:  # noqa: BLE001
            logger.warning("terminal xadd failed for task %s: %s", task_id, exc)

        # Finalize commit
        accumulated = "".join(acc_assistant)
        try:
            if cancelled_by_user:
                # Custom partial commit path — 不走 finalize_task_persistence
                # (那条路径会按 graph_error 是否空判 done/error,partial 不在其语义内)。
                from app.services.chat_session_repo import ChatSessionRepo

                session_repo = ChatSessionRepo(session_factory)
                checkpoint_id: str | None = None
                try:
                    state = await graph.aget_state(config)
                    cp = (state.config.get("configurable", {}) or {}).get("checkpoint_id")
                    if isinstance(cp, str):
                        checkpoint_id = cp
                except Exception:  # noqa: BLE001
                    # aget_state 可能失败(stub graph / 真 graph 未起 checkpointer),
                    # 那就 checkpoint_id=None,后续 retry 走从头重跑(spec § 6.1 兜底)。
                    pass
                await session_repo.append_message(
                    session_id=session_id,
                    role="assistant",
                    content=accumulated,
                    task_id=task_id,
                    status="partial",
                )
                await task_repo.mark_partial(task_id, langgraph_checkpoint_id=checkpoint_id)
            else:
                await finalize_task_persistence(
                    pg_factory=session_factory,
                    task_id=task_id,
                    session_id=session_id,
                    graph=graph,
                    config=config,  # type: ignore[arg-type]
                    final_state=final_state,
                    accumulated_token_text=accumulated,
                    graph_error=graph_error,
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception("finalize failed for task %s: %s", task_id, exc)

        # Refresh TTL — task 结束后再续 24h
        try:
            await bus.set_ttl(sid_uuid, task_id, seconds=ChatEventBus.DEFAULT_TTL_SECONDS)
        except Exception as exc:  # noqa: BLE001
            logger.debug("TTL refresh skipped for task %s: %s", task_id, exc)


# ---------------------------------------------------------------------------
# Celery wrapper — thin sync→async bridge
# ---------------------------------------------------------------------------


@celery_app.task(name="app.tasks.chat_runner.run_chat", bind=True)
def run_chat(
    self: Any,
    task_id: str,
    session_id: str,
    user_id: str,
    user_message: str,
    resume_checkpoint_id: str | None = None,
) -> None:
    """Celery sync entry. Bridges to async via asyncio.run() + builds worker-side deps.

    Production-ready wiring(Plan 2 Task 8):
    - graph_factory: _build_chat_graph_for_worker — reuses _build_graph_singleton
      from app.router.chat(env-driven, no app.state needed)
    - session_factory: _build_session_factory_for_worker — async_sessionmaker
      tied to PG via _sqlalchemy_async_pg_url
    - redis: _build_redis_for_worker — redis.asyncio.Redis from REDIS_URL

    Plan 3 Task 5:resume_checkpoint_id 直接透传给 run_chat_async,worker
    LangGraph 从该 checkpoint state 续跑(spec § 5.4 Scenario D / § 6.4)。

    L0 / L1 path 直接 await run_chat_async(test_chat_runner.py);
    L2 path 走真 worker subprocess(test_chat_inflight_l2.py)。
    """
    import asyncio

    # user_id 可能是真 UUID(post-auth)/ "anonymous" / 任何非 UUID 字符串。
    # 不强制 cast UUID — run_chat_async user_id 只用于 thread_id 拼接,接受 str/UUID/None。
    asyncio.run(
        run_chat_async(
            task_id=uuid.UUID(task_id),
            graph_factory=_build_chat_graph_for_worker,
            session_factory=_build_session_factory_for_worker(),
            redis=_build_redis_for_worker(),
            user_message=user_message,
            session_id=session_id,
            user_id=user_id,
            resume_checkpoint_id=resume_checkpoint_id,
        )
    )


def enqueue_run_chat(
    *,
    task_id: str,
    session_id: str,
    user_id: str,
    user_message: str,
    resume_checkpoint_id: str | None = None,
    parent_task_id: str | None = None,  # noqa: ARG001 — audit-only; worker doesn't consume
) -> Any:
    """Production enqueue — POST /chat 改造(Plan 2 Task 5)+ POST /chat/retry
    (Plan 3 Task 5)都调本函数。

    Plan 3 retry 加 resume_checkpoint_id 参数;worker async entry 用它构造
    RunnableConfig {configurable: {thread_id, checkpoint_id}} 让 LangGraph
    从 checkpoint state 续跑。

    parent_task_id 是 audit-only(retry 链已经在 chat_tasks.parent_task_id
    列里持久化了);此参数让 endpoint 显式表达"这是 retry enqueue"以便
    后续监控 hook 接入,但 worker 路径不需要消费它。

    Tests monkey-patch this function to bypass real Celery .delay()。
    """
    return run_chat.delay(
        task_id=task_id,
        session_id=session_id,
        user_id=user_id,
        user_message=user_message,
        resume_checkpoint_id=resume_checkpoint_id,
    )

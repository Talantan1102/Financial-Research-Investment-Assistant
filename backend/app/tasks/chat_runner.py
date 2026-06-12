"""Celery task: run_chat — 异步跑 ToolLoop + XADD events to Redis Streams。

Phase 4 Task 4.2(换引擎):chat worker 从 LangGraph 图切到裸 while ToolLoop。
LangGraph 完全退出 chat 路径(spec § 0.2);checkpoint 退役(turn 原子语义下中间圈
状态无消费者,spec § 4.1)。事件不再经 astream_events 节点名适配,而是 ToolLoop
主动发射 LoopEvent → 本模块 XADD。

保留的外壳(本任务不改语义):
- Celery task 包装(run_chat / enqueue_run_chat);
- worker 单例区(MCP subprocess + HeavySingletons,进程级懒构造一次);
- cancel listener(ChatCancelBus 订阅 → cancel_event,圈边界 + 流式 delta 间检查);
- Redis Streams TTL 管理(进出各刷一次 24h);
- 终止事件(loop 已 emit done;runner 只补 cancelled / error_done,避免双 done)。

换掉的核心:
- run_chat_async 主体:astream_events 循环 → loop.run(state);
- 事件发射:_adapt_event_for_stream → LoopEvent → bus.xadd_event(直发);
- 持久化:finalize_task_persistence(依赖 graph.aget_state)→ 直接 append + mark_done
  (checkpoint_id 退役,统一传 None);
- 升级后处理:从 chat.py 搬来(turn 后看 state.escalate_offered)。

Test 策略(test_chat_runner_loop.py):directly await run_chat_async,注入
ScriptedStepClient(覆盖 llm)+ fakeredis + 真 PG async_session_factory。
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from contextlib import suppress
from typing import Any

from app.chatloop.context import ContextDeps
from app.chatloop.events import LoopEvent, SeqCounter
from app.chatloop.loop import CancelledByUser, ToolLoop
from app.chatloop.rebuild import rebuild_context
from app.chatloop.state import ChatLoopState, turn_summary
from app.services.chat_event_bus import ChatEventBus
from app.services.chat_session_repo import ChatSessionRepo
from app.services.chat_task_repo import ChatTaskRepo
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Worker-side singleton caches — initialized lazily on first task invocation.
# Worker subprocess has no FastAPI app.state; rebuild deps from env (same
# primitives lifespan uses).
# ---------------------------------------------------------------------------
_SINGLETONS_CACHE: Any | None = None  # HeavySingletons(llm/registry/memory/...)
_SESSION_FACTORY_SINGLETON: Any | None = None
_REDIS_SINGLETON: Any | None = None
_MCP_CLIENT_SINGLETON: Any | None = None
_MCP_CTX_SINGLETON: Any | None = None  # keep ctx ref alive — GC would tear down subprocess

# 进程级常驻事件循环(E2E 实测修复,根因见 run_chat docstring)。
# prefork 每子进程一个 loop,使 MCP stdio / redis.asyncio / httpx 等 loop-bound 单例
# 跨 task 存活;之前每个 task 用 asyncio.run() 新建并关闭一个 loop,第二个 task 的
# 新循环里复用第一个循环上构造的对象 → MCP stdio asyncgen 关闭崩坏 + redis 跨循环。
_WORKER_LOOP: asyncio.AbstractEventLoop | None = None


def _get_worker_loop() -> asyncio.AbstractEventLoop:
    """惰性构造本 worker 子进程的常驻事件循环(进程级单例)。

    不调 ``asyncio.set_event_loop`` —— 所有协程统一经 ``run_until_complete`` 驱动,
    不依赖隐式 current-loop 解析。Celery prefork 单子进程内 task 串行执行,无并发
    ``run_until_complete``,故复用同一 loop 安全;loop-bound 单例(MCP stdio 流 /
    redis.asyncio 客户端 / LLMService 持的 AsyncOpenAI httpx)因此跨 task 存活,
    不再每 task 新建循环导致跨循环使用崩坏。
    """
    global _WORKER_LOOP
    if _WORKER_LOOP is None or _WORKER_LOOP.is_closed():
        _WORKER_LOOP = asyncio.new_event_loop()
    return _WORKER_LOOP


async def _build_singletons_for_worker(session_factory: Any) -> Any:
    """Build (or reuse) the chatloop HeavySingletons for this worker process.

    Lazy-launches the MCP `chat_tools` subprocess on first task, caches the
    client + ctx at module level (never __aexit__'d here — Celery worker shutdown
    SIGKILLs the subprocess; matches app_main web lifespan ctx-ref handling).
    """
    global _SINGLETONS_CACHE, _MCP_CLIENT_SINGLETON, _MCP_CTX_SINGLETON
    if _SINGLETONS_CACHE is None:
        from app.chatloop.worker_wiring import build_heavy_singletons
        from app.services.mcp_client import MCPClient

        if _MCP_CLIENT_SINGLETON is None:
            _MCP_CTX_SINGLETON = MCPClient.from_subprocess(profile="chat_tools")
            _MCP_CLIENT_SINGLETON = await _MCP_CTX_SINGLETON.__aenter__()

        _SINGLETONS_CACHE = await build_heavy_singletons(
            session_factory=session_factory,
            mcp_client=_MCP_CLIENT_SINGLETON,
        )
    return _SINGLETONS_CACHE


def _build_session_factory_for_worker() -> Any:
    """Build async_sessionmaker for Celery worker context (cached)."""
    global _SESSION_FACTORY_SINGLETON
    if _SESSION_FACTORY_SINGLETON is None:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.app_main import _sqlalchemy_async_pg_url

        engine = create_async_engine(_sqlalchemy_async_pg_url(), future=True)
        _SESSION_FACTORY_SINGLETON = async_sessionmaker(engine, expire_on_commit=False)
    return _SESSION_FACTORY_SINGLETON


def _build_redis_for_worker() -> Any:
    """Build redis.asyncio client for Celery worker context (cached)."""
    global _REDIS_SINGLETON
    if _REDIS_SINGLETON is None:
        import os

        import redis.asyncio as redis_async

        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        _REDIS_SINGLETON = redis_async.Redis.from_url(redis_url, decode_responses=False)
    return _REDIS_SINGLETON


# ---------------------------------------------------------------------------
# 事件信封:LoopEvent → Redis Stream payload(spec § 5.1)
# ---------------------------------------------------------------------------


def _event_payload(event: LoopEvent) -> dict[str, Any]:
    """LoopEvent → XADD payload。

    形状:{**event.data, "type", "seq", "step"}。token 事件保持双字段:
    data 里 text 与 content 同值(前端历史约定 TokenEvent.content,后端测试读 text)。
    """
    payload: dict[str, Any] = {
        **event.data,
        "type": event.type,
        "seq": event.seq,
        "step": event.step,
    }
    if event.type == "token" and "text" in payload:
        payload.setdefault("content", payload["text"])
    return payload


async def run_chat_async(
    *,
    task_id: uuid.UUID,
    singletons: Any,
    session_factory: Any,
    redis: Any,
    user_message: str,
    session_id: str,
    user_id: uuid.UUID | str | None,
    resume_checkpoint_id: str | None = None,  # noqa: ARG001 — checkpoint 退役;签名留作 retry 兼容
) -> None:
    """Main worker async entry — DI 友好,test 可直接 await。

    Contract:
    - task_id: chat_tasks row id;调用前 router 已 create_queued;
    - singletons: HeavySingletons(worker 单例;test 用 build_heavy_singletons 注入 Fake llm/memory);
    - session_factory: async_sessionmaker(ChatTaskRepo / ChatSessionRepo / rebuild / cache 共用);
    - redis: redis.asyncio.Redis(prod)或 fakeredis.aioredis.FakeRedis(test);
    - user_message / session_id: 初始 ChatLoopState;
    - user_id: 真 UUID(post-auth)/ "anonymous"(pre-auth)/ None;
    - resume_checkpoint_id: checkpoint 退役后无意义;签名保留(retry 整 turn 重跑,
      历史从 rebuild_context 取,不靠 checkpoint —— spec § 4.3)。

    turn 流程(spec § 4.4):mark_running → rebuild_context → ContextDeps →
    ChatLoopState → build_turn_components(per-turn hub)→ ToolLoop.run →
    finalize(append assistant + mark_done/partial/error)→ 升级后处理。
    """
    from app.chatloop.worker_wiring import RedisSteerSource, build_turn_components
    from app.services.chat_cancel_bus import ChatCancelBus

    task_repo = ChatTaskRepo(session_factory)
    session_repo = ChatSessionRepo(session_factory)
    bus = ChatEventBus(redis=redis)
    cancel_bus = ChatCancelBus(redis=redis)
    cancel_event = asyncio.Event()

    sid_uuid: uuid.UUID = uuid.UUID(session_id) if isinstance(session_id, str) else session_id

    async def _cancel_listener() -> None:
        try:
            async for _ in cancel_bus.subscribe_cancel(task_id):
                cancel_event.set()
                return
        except asyncio.CancelledError:
            # 正常关闭路径:turn 收尾 listener_task.cancel();不是异常,不报。
            raise
        except Exception as exc:  # noqa: BLE001 — fail loud 进日志(曾吞 redis pubsub 跨循环错)
            logger.warning("cancel listener error for task %s: %s", task_id, exc)

    listener_task = asyncio.create_task(_cancel_listener())

    # mark_running idempotent(router 已 mark,这里 race-safe 再 mark)
    try:
        await task_repo.mark_running(task_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("mark_running on worker entry skipped: %s", exc)

    try:
        await bus.set_ttl(sid_uuid, task_id, seconds=ChatEventBus.DEFAULT_TTL_SECONDS)
    except Exception as exc:  # noqa: BLE001
        logger.debug("set_ttl on worker entry skipped: %s", exc)

    # per-turn 事件信封:LoopEvent → XADD + bump_seq(进度计数)
    seq_counter = SeqCounter()

    # 已流出 token 累积器(spec § 4.3):取消若在 apply_step 前抛(state.messages
    # 尚无最后 assistant content),partial 落库须靠这里累积的流出文本,否则恒空串。
    emitted_tokens: list[str] = []

    async def _emit(event: LoopEvent) -> None:
        if event.type == "token":
            text = event.data.get("text")
            if isinstance(text, str):
                emitted_tokens.append(text)
        try:
            await bus.xadd_event(sid_uuid, task_id, _event_payload(event))
        except Exception as exc:  # noqa: BLE001
            logger.warning("xadd_event failed for task %s: %s", task_id, exc)
        try:
            await task_repo.bump_seq(task_id, delta=1)
        except Exception as exc:  # noqa: BLE001
            logger.debug("bump_seq skipped for task %s: %s", task_id, exc)

    cancelled_by_user = False
    loop_error: Exception | None = None
    final_state: ChatLoopState | None = None

    # 1. 跨 turn 历史重建(压缩在此触发,水位防重复)。失败降级空历史。
    try:
        history_block = await _rebuild_history(session_factory, session_id, singletons.llm)
    except Exception as exc:  # noqa: BLE001
        logger.warning("rebuild_context failed for task %s, 降级空历史: %s", task_id, exc)
        history_block = ()

    # 2. persona 注入稳定前缀(失败降级空串,不阻塞 turn)
    persona_block = ""
    if user_id is not None:
        try:
            persona_block = await _render_persona(singletons.memory, user_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("persona render failed for task %s, 降级空: %s", task_id, exc)

    # per-turn 组装(轻 hub 持 turn 级 emit/seq;system_prompt/skill_listing 在此收口)
    components = build_turn_components(singletons, emit=_emit, seq_counter=seq_counter)

    deps = ContextDeps(
        system_prompt=components.system_prompt,
        persona_block=persona_block,
        skill_listing=components.skill_listing,
        history_block=history_block,
        max_steps=components.gate_cfg.max_steps,
        max_cny=components.gate_cfg.max_cny,
        max_context_tokens=int(os.getenv("CHATLOOP_MAX_CONTEXT_TOKENS", "100000")),
    )

    state = ChatLoopState(
        user_id=str(user_id),
        session_id=session_id,
        request_id=str(task_id),
        messages=[{"role": "user", "content": user_message}],
    )

    loop = ToolLoop(
        llm=components.llm,
        tool_hub=components.tool_hub,
        context_deps=deps,
        gate_cfg=components.gate_cfg,
        emit=_emit,
        steer_source=RedisSteerSource(redis, task_id),
        cancel_event=cancel_event,
        seq_counter=seq_counter,
    )

    try:
        final_state = await loop.run(state)
    except CancelledByUser:
        cancelled_by_user = True
        try:
            await bus.xadd_event(sid_uuid, task_id, {"type": "cancelled", "reason": "user_cancel"})
        except Exception as exc:  # noqa: BLE001
            logger.warning("xadd cancelled event failed for task %s: %s", task_id, exc)
    except Exception as exc:  # noqa: BLE001
        loop_error = exc
        try:
            await bus.xadd_event(sid_uuid, task_id, {"type": "error", "message": str(exc)[:500]})
        except Exception as inner:  # noqa: BLE001
            logger.warning("xadd error event failed for task %s: %s", task_id, inner)
    finally:
        # cancel listener clean up
        listener_task.cancel()
        with suppress(asyncio.CancelledError):
            await listener_task

        # 唯一终止 done 的归属:escalate_offered 时 loop 跳过 done(loop.py 修法 A),
        # 由下面的 _emit_escalation 在升级事件尾部补发唯一终止 done。故凡是会走
        # _emit_escalation 的 turn,runner 的 finally 不能再发 error_done,否则双终止。
        will_escalate = (
            not cancelled_by_user and final_state is not None and bool(final_state.escalate_offered)
        )

        # 终止事件:loop 已 emit done(成功且非升级路径),runner 不重复发 done。
        # cancelled / error_done 由 runner 发(loop 抛异常 / cancel 未走到 emit done)。
        # will_escalate 路径的唯一终止 done 改由 _emit_escalation 补发,这里不发
        # error_done(即便 loop_error 也提议了升级 —— extractor 失败有 try/finally done 兜)。
        try:
            if cancelled_by_user:
                await bus.xadd_event(sid_uuid, task_id, {"type": "cancelled"})
            elif loop_error is not None and not will_escalate:
                await bus.xadd_event(sid_uuid, task_id, {"type": "error_done"})
        except Exception as exc:  # noqa: BLE001
            logger.warning("terminal xadd failed for task %s: %s", task_id, exc)

        # 持久化(checkpoint 退役 → 不写 langgraph_checkpoint_id)
        try:
            await _finalize(
                session_repo=session_repo,
                task_repo=task_repo,
                session_id=session_id,
                task_id=task_id,
                final_state=final_state,
                cancelled=cancelled_by_user,
                loop_error=loop_error,
                emitted_text="".join(emitted_tokens),
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("finalize failed for task %s: %s", task_id, exc)

        # Refresh TTL
        try:
            await bus.set_ttl(sid_uuid, task_id, seconds=ChatEventBus.DEFAULT_TTL_SECONDS)
        except Exception as exc:  # noqa: BLE001
            logger.debug("TTL refresh skipped for task %s: %s", task_id, exc)

        # Path A 写 episode + 触发 Path B 抽取(干净成功轮;纯副作用,fail-soft 双保险)。
        # 回复与持久化已在前完成,本块失败绝不影响 turn。钩子内部已守卫 + fail-soft。
        try:
            from app.tasks.chat_memory_hook import persist_episode_and_trigger

            await persist_episode_and_trigger(
                singletons.memory,
                session_id=session_id,
                user_id=user_id,
                user_message=user_message,
                agent_response="".join(emitted_tokens),
                cancelled=cancelled_by_user,
                loop_error=loop_error,
                final_state=final_state,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("chat memory hook failed task=%s: %s", task_id, exc)

    # 升级后处理(offered 即走,不再要求 loop_error is None):escalate_request +
    # EscalationExtractor + draft + 唯一终止 done。条件与上面的 will_escalate 一致 ——
    # _emit_escalation 内部仅在 final_state.escalate_offered 时真跑(否则早 return),
    # 故非升级 turn 进来也无副作用;loop_error 也走是为了补发那条唯一终止 done
    # (loop 在 escalate 时跳过 done,error_done 又被 will_escalate 挡掉)。
    if not cancelled_by_user and final_state is not None:
        try:
            await _emit_escalation(
                bus=bus,
                sid_uuid=sid_uuid,
                task_id=task_id,
                session_id=session_id,
                session_factory=session_factory,
                llm=singletons.llm,
                final_state=final_state,
                history_block=history_block,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("escalation post-processing failed for task %s: %s", task_id, exc)


# ---------------------------------------------------------------------------
# turn 内部 helpers
# ---------------------------------------------------------------------------


async def _rebuild_history(session_factory: Any, session_id: str, llm: Any) -> tuple[Any, ...]:
    """rebuild_context 需要一个 AsyncSession;从 session_factory 开一个。"""
    async with session_factory() as db:
        return await rebuild_context(session_id, db=db, llm=llm)


async def _render_persona(memory: Any, user_id: uuid.UUID | str) -> str:
    """persona 稳定前缀注入(spec § 3.3 复用 render_persona_markdown)。"""
    from app.memory.render import render_persona_markdown

    uid = uuid.UUID(str(user_id))
    return await render_persona_markdown(memory, uid)


async def _finalize(
    *,
    session_repo: ChatSessionRepo,
    task_repo: ChatTaskRepo,
    session_id: str,
    task_id: uuid.UUID,
    final_state: ChatLoopState | None,
    cancelled: bool,
    loop_error: Exception | None,
    emitted_text: str = "",
) -> None:
    """append assistant + mark task 状态(checkpoint 退役,统一 None)。

    - cancelled:已流出文本落库标 partial(仅展示,不是恢复点 — spec § 4.3);
      mark_partial(checkpoint=None)。取消可能在 apply_step 之前抛(state.messages
      尚无最后 assistant content),此时 final_state 的兜底链为空 → 用 emitted_text
      (_emit 闭包累积的流出 token);两者取更长者,兼顾流出半截 vs 已折叠的整圈。
    - error:assistant content = 已流出文本(同上兜底),status=error;mark_error。
    - success:final_response 兜底链 → status=done;mark_done(checkpoint=None)。
    """
    body = _final_text(final_state)

    if cancelled:
        partial_body = body if len(body) >= len(emitted_text) else emitted_text
        await session_repo.append_message(
            session_id=session_id,
            role="assistant",
            content=partial_body,
            task_id=task_id,
            status="partial",
        )
        await task_repo.mark_partial(task_id, langgraph_checkpoint_id=None)
        return

    if loop_error is not None:
        error_body = body if len(body) >= len(emitted_text) else emitted_text
        await session_repo.append_message(
            session_id=session_id,
            role="assistant",
            content=error_body,
            task_id=task_id,
            status="error",
        )
        await task_repo.mark_error(task_id, error_message=str(loop_error)[:500])
        return

    await session_repo.append_message(
        session_id=session_id,
        role="assistant",
        content=body,
        task_id=task_id,
        status="done",
    )
    await task_repo.mark_done(task_id, langgraph_checkpoint_id=None)


def _final_text(final_state: ChatLoopState | None) -> str:
    """final_response 兜底链:final_response or 最后一条 assistant content or ""。"""
    if final_state is None:
        return ""
    if isinstance(final_state.final_response, str) and final_state.final_response:
        return final_state.final_response
    for msg in reversed(final_state.messages):
        if msg.get("role") == "assistant":
            content = msg.get("content")
            if isinstance(content, str) and content:
                return content
    return ""


async def _emit_escalation(
    *,
    bus: ChatEventBus,
    sid_uuid: uuid.UUID,
    task_id: uuid.UUID,
    session_id: str,
    session_factory: Any,
    llm: Any,
    final_state: ChatLoopState,
    history_block: tuple[Any, ...],
) -> None:
    """turn 后升级链路(从 chat.py 搬来,事件 payload 形状保持一致)。

    触发:final_state.escalate_offered。
    1. escalate_request{session_id, reason};
    2. EscalationExtractor.run(history=对话文本, cached_tool_results=ledger 视图)→ packet;
    3. create_draft → escalate_packet_draft{draft_record_id, packet};
    4. **修法 A(spec § 4.3 升级事件次序):补发唯一终止 done**。escalate 时 loop 不发
       done(loop.py 圈一/force_conclude 跳过),由本函数在 escalate_packet_draft 之后
       发,保证升级 turn 的事件序 = ... escalate_request → escalate_packet_draft → done。
       即便 extractor/draft 抛异常,done 也在 finally 兜底补发(否则前端永远等不到终止)。
    """
    if not final_state.escalate_offered:
        return

    done_stop_reason = final_state.halt_reason or "natural"

    from app.agents.escalation_extractor import EscalationExtractor
    from app.services.escalation_record_repo import EscalationRecordRepo

    reason = final_state.escalate_reason or ""

    # 1. escalate_request(payload 形状与老 chat.py 一致)
    await bus.xadd_event(
        sid_uuid,
        task_id,
        {"type": "escalate_request", "session_id": session_id, "reason": reason},
    )

    # 2. history_dicts:rebuild 历史 + 本 turn 的 user/assistant 文本对话
    history_dicts: list[dict[str, Any]] = []
    for h in history_block:
        if isinstance(h, dict):
            history_dicts.append({"role": h.get("role", ""), "content": h.get("content", "")})
    for m in final_state.messages:
        role = m.get("role")
        if role in ("user", "assistant"):
            content = m.get("content")
            if isinstance(content, str) and content:
                history_dicts.append({"role": role, "content": content})

    # 3. cached_tool_results:台账视图(spec § 3.5 唯一改动 —— Extractor 物料来源换台账)
    extractor_view = final_state.ledger.to_extractor_view()
    cached_tool_results: list[dict[str, Any]] = [
        {
            "tool_name": e.get("tool_name", ""),
            "tool_args": {},
            "result_summary": e.get("summary", ""),
            "cache_id": e.get("cache_id"),
        }
        for e in extractor_view
    ]

    extractor = EscalationExtractor(llm=llm)
    record_repo = EscalationRecordRepo(session_factory)

    try:
        packet = await extractor.run(
            chat_session_id=session_id,
            chat_turn_count=len(history_dicts),
            chat_history_summary=None,
            history=history_dicts,
            cached_tool_results=cached_tool_results,
            request_id=str(task_id),
        )
        rec = await record_repo.create_draft(
            session_id=session_id,
            packet_draft=packet.model_dump(mode="json"),
        )
        await bus.xadd_event(
            sid_uuid,
            task_id,
            {
                "type": "escalate_packet_draft",
                "draft_record_id": str(rec.id),
                "packet": packet.model_dump(mode="json"),
            },
        )
    finally:
        # 修法 A:唯一终止 done 一定在升级链路尾部补发(即便 extractor/draft 抛,
        # done 仍发,前端才能收尾;loop 在 escalate 时已跳过 done,故此处不会双发)。
        await bus.xadd_event(
            sid_uuid,
            task_id,
            {"type": "done", "stop_reason": done_stop_reason, **turn_summary(final_state)},
        )


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
    """Celery sync entry. Bridges to async via 进程级常驻 loop + builds worker-side deps.

    Production wiring:
    - singletons: _build_singletons_for_worker — MCP chat_tools subprocess +
      HeavySingletons(llm/registry/memory/loader/executor/cache), built once/process;
    - session_factory: _build_session_factory_for_worker;
    - redis: _build_redis_for_worker。

    事件循环(E2E 实测修复):用 ``_get_worker_loop().run_until_complete(...)`` 而非
    ``asyncio.run(...)``。后者每个 task 新建并关闭一个事件循环,但模块级单例
    (MCP stdio 流 / redis.asyncio 客户端 / LLMService 持的 AsyncOpenAI httpx)在
    第一个 task 的循环上构造;第二个 task 的新循环里复用这些 loop-bound 对象 →
    MCP stdio asyncgen 关闭报错(an error occurred during closing of asynchronous
    generator <stdio_client>)、redis RPOP/RPUSH 跨循环行为异常(steer 不生效)。
    prefork 每子进程一个常驻 loop,使这些单例跨 task 存活;子进程内 task 串行,
    无并发 run_until_complete。

    resume_checkpoint_id 透传(checkpoint 退役 → run_chat_async 忽略;retry 整 turn 重跑)。
    """

    async def _run() -> None:
        session_factory = _build_session_factory_for_worker()
        singletons = await _build_singletons_for_worker(session_factory)
        await run_chat_async(
            task_id=uuid.UUID(task_id),
            singletons=singletons,
            session_factory=session_factory,
            redis=_build_redis_for_worker(),
            user_message=user_message,
            session_id=session_id,
            user_id=user_id,
            resume_checkpoint_id=resume_checkpoint_id,
        )

    _get_worker_loop().run_until_complete(_run())


def enqueue_run_chat(
    *,
    task_id: str,
    session_id: str,
    user_id: str,
    user_message: str,
    resume_checkpoint_id: str | None = None,
    parent_task_id: str | None = None,  # noqa: ARG001 — audit-only; worker doesn't consume
) -> Any:
    """Production enqueue — POST /chat + POST /chat/retry 都调本函数。

    Tests monkey-patch this function to bypass real Celery .delay()。
    """
    return run_chat.delay(
        task_id=task_id,
        session_id=session_id,
        user_id=user_id,
        user_message=user_message,
        resume_checkpoint_id=resume_checkpoint_id,
    )

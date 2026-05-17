"""chat_finalize — task persistence 三件事(append assistant / mark task / log error)。

Plan 1 在 chat.py 内 inline;Plan 2 抽出供 Celery worker (chat_runner.py) 也调用。
本 module 不引入新逻辑 — 只是把 Plan 1 helper 升级为 public + 可被 Celery worker import。

设计契约:
- 调用方负责传 pg_factory + task_id;helper 内部 build ChatSessionRepo / ChatTaskRepo
- final_state["final_response"] 优先;空时 fallback accumulated_token_text
- graph.aget_state checkpoint_id 是 best-effort,失败 → checkpoint=None (mark_done 仍写)
- graph_error 非 None 时走 error 路径:assistant.status=error + mark_error
- finally 自身失败 NOT 由本函数 catch — 调用方(_stream_chat / Celery task)的 finally 兜底
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph

from app.services.chat_session_repo import ChatSessionRepo
from app.services.chat_task_repo import ChatTaskRepo

logger = logging.getLogger(__name__)


async def finalize_task_persistence(
    *,
    pg_factory: Any,
    task_id: UUID,
    session_id: str,
    graph: CompiledStateGraph[Any, Any, Any, Any],
    config: RunnableConfig,
    final_state: dict[str, Any] | None,
    accumulated_token_text: str,
    graph_error: Exception | None,
) -> None:
    """Plan 1 Task 5: write the trailing assistant message + mark chat_task status.

    Called from ``_stream_chat`` finally block when persistence is wired
    (``pg_factory`` and ``task_id`` both non-None). Failures here are caught
    by the caller and logged — they MUST NOT propagate into the SSE stream.

    Behavior:
    - Success path: pick the assistant body in priority order
        1. ``final_state["final_response"]`` — set by the responder node
        2. accumulated ``on_chat_model_stream`` token text
        3. empty string (no responder ran — degraded transcript)
      then ``append_message(role='assistant', status='done')`` + ``mark_done``.
    - Error path: assistant body = accumulated text (may be empty), status=error;
      ``mark_error(error_message=<truncated str(exc)>)``.

    The LangGraph checkpoint id is best-effort: the API surface for it varies
    across LG versions, so failures to read it fall through to None.
    """
    session_repo = ChatSessionRepo(pg_factory)
    task_repo = ChatTaskRepo(pg_factory)

    if graph_error is None:
        assistant_content = ""
        if isinstance(final_state, dict):
            fr = final_state.get("final_response")
            if isinstance(fr, str) and fr:
                assistant_content = fr
        if not assistant_content:
            assistant_content = accumulated_token_text

        checkpoint_id: str | None = None
        try:
            state = await graph.aget_state(config)
            cfg = getattr(state, "config", None) or {}
            configurable = cfg.get("configurable", {}) if isinstance(cfg, dict) else {}
            cp = configurable.get("checkpoint_id") if isinstance(configurable, dict) else None
            if isinstance(cp, str):
                checkpoint_id = cp
        except Exception as exc:  # noqa: BLE001
            logger.debug("aget_state checkpoint_id unavailable (%s); leaving NULL", exc)

        await session_repo.append_message(
            session_id=session_id,
            role="assistant",
            content=assistant_content,
            task_id=task_id,
            status="done",
        )
        await task_repo.mark_done(task_id, langgraph_checkpoint_id=checkpoint_id)
    else:
        await session_repo.append_message(
            session_id=session_id,
            role="assistant",
            content=accumulated_token_text,
            task_id=task_id,
            status="error",
        )
        await task_repo.mark_error(task_id, error_message=str(graph_error)[:500])

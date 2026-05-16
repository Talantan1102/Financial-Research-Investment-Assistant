"""chat_finalize helper L0 unit。

Plan 1 把 finalize 逻辑放在 chat.py 内部;Plan 2 抽出共享 module 供
Celery worker (chat_runner.py) 也调用。本 test 守护抽出后行为不变 —
给定 (final_state, accumulated_token_text, graph_error) 应该产生
正确的 ChatMessage append + ChatTask mark 调用 / 状态。

isolation:用 monkeypatch.setattr 替换 chat_finalize 模块里的
ChatSessionRepo / ChatTaskRepo 构造器,test 结束 monkeypatch 自动恢复,
不污染下游 integration test 的模块状态。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.router import chat_finalize as cf
from app.router.chat_finalize import finalize_task_persistence


@pytest.mark.asyncio
async def test_finalize_success_appends_done_assistant_and_marks_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """成功路径:final_response 优先;mark_done 带 checkpoint_id。"""
    # Build stubs that mimic ChatSessionRepo / ChatTaskRepo / Graph
    session_repo_mock = AsyncMock()  # captures append_message call
    task_repo_mock = AsyncMock()  # captures mark_done call

    pg_factory_mock = MagicMock()

    # monkeypatch isolation: the helper does `ChatSessionRepo(pg_factory)` internally;
    # patch the names imported into chat_finalize so the helper builds our mocks.
    monkeypatch.setattr(cf, "ChatSessionRepo", MagicMock(return_value=session_repo_mock))
    monkeypatch.setattr(cf, "ChatTaskRepo", MagicMock(return_value=task_repo_mock))

    graph_mock = AsyncMock()
    state_mock = MagicMock()
    state_mock.config = {"configurable": {"checkpoint_id": "ckpt-abc"}}
    graph_mock.aget_state = AsyncMock(return_value=state_mock)

    task_id = uuid.uuid4()

    await finalize_task_persistence(
        pg_factory=pg_factory_mock,
        task_id=task_id,
        session_id="sid-1",
        graph=graph_mock,
        config={"configurable": {"thread_id": "u:s"}},
        final_state={"final_response": "canonical answer"},
        accumulated_token_text="streamed tokens fallback",
        graph_error=None,
    )

    session_repo_mock.append_message.assert_awaited_once()
    kwargs = session_repo_mock.append_message.await_args.kwargs
    assert kwargs["session_id"] == "sid-1"
    assert kwargs["role"] == "assistant"
    assert kwargs["content"] == "canonical answer"  # final_response wins
    assert kwargs["task_id"] == task_id
    assert kwargs["status"] == "done"

    task_repo_mock.mark_done.assert_awaited_once_with(task_id, langgraph_checkpoint_id="ckpt-abc")


@pytest.mark.asyncio
async def test_finalize_falls_back_to_accumulated_when_no_final_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """final_state 没 final_response → 用 accumulated_token_text。"""
    session_repo_mock = AsyncMock()
    task_repo_mock = AsyncMock()

    monkeypatch.setattr(cf, "ChatSessionRepo", MagicMock(return_value=session_repo_mock))
    monkeypatch.setattr(cf, "ChatTaskRepo", MagicMock(return_value=task_repo_mock))

    graph_mock = AsyncMock()
    graph_mock.aget_state = AsyncMock(side_effect=Exception("LG version skew"))  # best-effort

    await finalize_task_persistence(
        pg_factory=MagicMock(),
        task_id=uuid.uuid4(),
        session_id="sid",
        graph=graph_mock,
        config={"configurable": {}},
        final_state={"final_response": ""},  # empty
        accumulated_token_text="partial tokens",
        graph_error=None,
    )

    kwargs = session_repo_mock.append_message.await_args.kwargs
    assert kwargs["content"] == "partial tokens"
    # mark_done with None checkpoint (best-effort failed)
    task_repo_mock.mark_done.assert_awaited_once()
    mark_kwargs = task_repo_mock.mark_done.await_args.kwargs
    assert mark_kwargs["langgraph_checkpoint_id"] is None


@pytest.mark.asyncio
async def test_finalize_error_appends_error_assistant_and_marks_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """graph_error 路径:assistant.status=error,task.mark_error,内容 = accumulated。"""
    session_repo_mock = AsyncMock()
    task_repo_mock = AsyncMock()

    monkeypatch.setattr(cf, "ChatSessionRepo", MagicMock(return_value=session_repo_mock))
    monkeypatch.setattr(cf, "ChatTaskRepo", MagicMock(return_value=task_repo_mock))

    err = RuntimeError("LLM 429 rate limited")
    task_id = uuid.uuid4()

    await finalize_task_persistence(
        pg_factory=MagicMock(),
        task_id=task_id,
        session_id="sid",
        graph=AsyncMock(),
        config={"configurable": {}},
        final_state=None,
        accumulated_token_text="some partial output",
        graph_error=err,
    )

    kwargs = session_repo_mock.append_message.await_args.kwargs
    assert kwargs["content"] == "some partial output"
    assert kwargs["status"] == "error"

    task_repo_mock.mark_error.assert_awaited_once()
    mark_kwargs = task_repo_mock.mark_error.await_args.kwargs
    assert "LLM 429" in mark_kwargs["error_message"]

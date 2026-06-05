# mypy: disable-error-code="arg-type"
# SQLAlchemy classical Column[UUID] mypy 推断不准 — 测试代码 silence。
"""Phase 4 Task 4.3 集成测试 — steer 端点 + retry turn 原子化 + 升级事件次序。

覆盖(spec § 4.3 + § 5.2 差分):
- steer running 态:落库 + LPUSH steer List + merged True;
- steer worker 端到端:ScriptedStepClient 两圈剧本,圈间 LPUSH → 最终 state.messages 含插话;
- steer 终态竞态:done 后 push → merged False + 落库行已删(差分 golden 之一);
- steer 404;
- retry partial(含插话)→ 新 task user_message = 原消息 + 插话(查 enqueue mock,差分之一);
- retry 无 checkpoint 不再 422;
- 升级事件次序:escalate turn → 唯一 done 且在 escalate_packet_draft 之后;
  非 escalate turn 无双 done(回归加强)。

router 测试走 FastAPI TestClient + dependency_overrides;worker 端到端走直调
run_chat_async + ScriptedStepClient(借 test_chat_runner_loop 的基建形状)。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from app.chatloop.worker_wiring import build_heavy_singletons
from app.models.chat import ChatSession
from app.models.user import User  # noqa: F401 — 注册 users 表
from app.router.chat import (
    get_async_session_factory,
    get_current_user,
    get_redis_async,
)
from app.router.chat import router as chat_router
from app.services.chat_event_bus import ChatEventBus
from app.services.chat_session_repo import ChatSessionRepo
from app.services.chat_steer_bus import steer_key
from app.services.chat_task_repo import ChatTaskRepo
from app.services.llm_step import StepDelta, StepResult, StepToolCall
from app.tasks.chat_runner import run_chat_async
from fakeredis.aioredis import FakeRedis
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# ---------------------------------------------------------------------------
# Scripted LLM(stream_step 协议)+ Fake memory(借 test_chat_runner_loop 形状)
# ---------------------------------------------------------------------------


def _call(name: str, args: dict[str, Any], *, id_: str | None = None) -> StepToolCall:
    return StepToolCall(
        id=id_ or f"{name}-call",
        name=name,
        arguments=json.dumps(args, ensure_ascii=False),
    )


def _step(
    content: str = "",
    tool_calls: list[StepToolCall] | None = None,
    finish_reason: str | None = None,
) -> StepResult:
    tcs = tool_calls or []
    return StepResult(
        content=content,
        tool_calls=tcs,
        finish_reason=finish_reason or ("tool_calls" if tcs else "stop"),
        prompt_tokens=10,
        completion_tokens=5,
        cached_tokens=0,
        cost_cny=0.001,
    )


class ScriptedStepClient:
    """脚本化多圈 stream_step。

    push_between_rounds: {round_idx: (redis, task_id, message)} — 在该圈(0-based)
    stream_step 内、返回 step 之前 LPUSH 一条插话进 steer List,模拟"worker 流式输出
    的几秒里用户插话";下一圈圈边界 RedisSteerSource.pop_all 应取到并并入。
    """

    SUMMARY_TEXT = "## 用户意图\n关注茅台"

    def __init__(
        self,
        steps: list[StepResult],
        *,
        push_between_rounds: dict[int, tuple[Any, uuid.UUID, str]] | None = None,
    ) -> None:
        self._steps = list(steps)
        self.received_messages: list[list[dict[str, Any]]] = []
        self._push = push_between_rounds or {}
        self._round = 0

    async def stream_step(
        self,
        *,
        messages: Any,
        tools: Any = None,
        tool_choice: str = "auto",
        tier: str = "balanced",
        request_id: Any = None,
        on_delta: Any = None,
    ) -> StepResult:
        cur = self._round
        self._round += 1
        self.received_messages.append([dict(m) for m in messages])
        if not self._steps:
            raise AssertionError("ScriptedStepClient 剧本耗尽")
        step = self._steps.pop(0)
        if on_delta is not None:
            for tc in step.tool_calls:
                await on_delta(StepDelta(kind="tool_call", text="", tool_name=tc.name))
            if step.content:
                await on_delta(StepDelta(kind="content", text=step.content))
        # 圈内插话:返回 step 前 LPUSH(下一圈圈边界 pop_all 并入)
        if cur in self._push:
            redis, tid, msg = self._push[cur]
            from app.services.chat_steer_bus import ChatSteerBus

            await ChatSteerBus(redis=redis).push(tid, msg)
        return step

    def chat(self, prompt: str = "", tier: str = "fast", schema: Any = None, **_: Any) -> Any:
        class _R:
            content = ScriptedStepClient.SUMMARY_TEXT

        return _R()


class _FakeMemory:
    async def get_working_blocks(self, _user_id: Any) -> dict[str, Any]:
        return {}

    async def archival_memory_search(self, *_a: Any, **_k: Any) -> list[Any]:
        return []


async def _singletons(
    pg_async_session_factory: Any,
    llm: ScriptedStepClient,
    *,
    tmp_path: Path | None = None,
) -> Any:
    return await build_heavy_singletons(
        session_factory=pg_async_session_factory,
        mcp_client=None,
        llm=llm,
        memory=_FakeMemory(),
        skills_root=tmp_path,
        workdir_root=tmp_path,
    )


async def _read_events(
    redis: FakeRedis, sid: uuid.UUID, tid: uuid.UUID
) -> list[dict[str, Any]]:
    bus = ChatEventBus(redis)
    entries = await bus.xread_blocking(sid, tid, last_id="0", count=200, block_ms=10)
    return [payload for _id, payload in entries]


# ---------------------------------------------------------------------------
# Router test scaffolding(TestClient + overrides)
# ---------------------------------------------------------------------------


class _StubUser:
    def __init__(self) -> None:
        self.id = "test-user"


@pytest_asyncio.fixture
async def fake_redis() -> AsyncIterator[FakeRedis]:
    r = FakeRedis(decode_responses=False)
    yield r
    await r.aclose()


def _client(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis_obj: FakeRedis,
) -> TestClient:
    app = FastAPI()
    app.include_router(chat_router)
    app.dependency_overrides[get_current_user] = lambda: _StubUser()
    app.dependency_overrides[get_async_session_factory] = lambda: session_factory
    app.dependency_overrides[get_redis_async] = lambda: fake_redis_obj
    return TestClient(app, raise_server_exceptions=True)


async def _seed_session_and_task(
    factory: async_sessionmaker[AsyncSession],
    *,
    status: str = "running",
    with_user_msg: str | None = None,
) -> dict[str, Any]:
    """建 session + (可选)原始 user 消息 + task(initial_prompt 关联),mark 到目标态。"""
    sid = uuid.uuid4()
    async with factory() as sess:
        sess.add(ChatSession(id=sid, user_id=None, title="t"))
        await sess.commit()

    repo = ChatSessionRepo(factory)
    user_msg_id: uuid.UUID | None = None
    if with_user_msg is not None:
        # POST /chat 形状:task 尚不存在,user 行不带 task_id;经 initial_prompt 关联。
        m = await repo.append_message(session_id=str(sid), role="user", content=with_user_msg)
        user_msg_id = m.id

    task_repo = ChatTaskRepo(factory)
    task = await task_repo.create_queued(
        session_id=sid,
        user_id=None,
        langgraph_thread_id=f"u:{sid}",
        initial_prompt_message_id=user_msg_id,
    )
    if status == "running":
        await task_repo.mark_running(task.id)
    elif status == "done":
        await task_repo.mark_running(task.id)
        await task_repo.mark_done(task.id, langgraph_checkpoint_id=None)
    elif status == "partial":
        await task_repo.mark_running(task.id)
        await task_repo.mark_partial(task.id, langgraph_checkpoint_id=None)
    elif status == "error":
        await task_repo.mark_error(task.id, error_message="boom")
    return {"session_id": sid, "task_id": task.id, "user_msg_id": user_msg_id}


# ---------------------------------------------------------------------------
# 1. steer running 态:落库 + LPUSH + merged True
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_steer_running_persists_and_enqueues(
    pg_async_session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
) -> None:
    seeded = await _seed_session_and_task(pg_async_session_factory, status="running")
    client = _client(pg_async_session_factory, fake_redis)

    resp = client.post(
        f"/api/v0/chat/steer/{seeded['task_id']}",
        json={"message": "先看负债率"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["merged"] is True
    assert "message_id" in body

    # 落库:role=user, task_id=本 tid, content
    msgs = await ChatSessionRepo(pg_async_session_factory).list_messages(
        str(seeded["session_id"])
    )
    steer_rows = [m for m in msgs if m.role == "user" and m.content == "先看负债率"]
    assert len(steer_rows) == 1
    assert steer_rows[0].task_id == seeded["task_id"]

    # LPUSH:steer List 含一条
    key = steer_key(seeded["task_id"])
    assert await fake_redis.llen(key) == 1
    raw = await fake_redis.rpop(key)
    assert (raw.decode() if isinstance(raw, bytes) else raw) == "先看负债率"


# ---------------------------------------------------------------------------
# 2. steer worker 端到端:圈间 push → 最终 state.messages 含插话
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_steer_merged_into_running_turn_end_to_end(
    pg_async_session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
    tmp_path: Path,
) -> None:
    seeded = await _seed_session_and_task(pg_async_session_factory, status="running")
    tid = seeded["task_id"]

    # 圈0:发一个 tool_call(loop 继续)+ 圈内 LPUSH 插话;
    # 圈1:圈边界 pop_all 取到插话并入 messages 尾部 → 直答收尾。
    args = {"query": "茅台"}
    llm = ScriptedStepClient(
        [
            _step(tool_calls=[_call("memory_search", args)]),
            _step(content="结合负债率,茅台财务稳健。", finish_reason="stop"),
        ],
        push_between_rounds={0: (fake_redis, tid, "再看负债率")},
    )
    singletons = await _singletons(pg_async_session_factory, llm, tmp_path=tmp_path)

    await run_chat_async(
        task_id=tid,
        singletons=singletons,
        session_factory=pg_async_session_factory,
        redis=fake_redis,
        user_message="我持有茅台吗",
        session_id=str(seeded["session_id"]),
        user_id=None,
    )

    # 第 2 圈(index 1)收到的 messages 应含插话(并入到尾部动态区/轨迹区)
    second_round = llm.received_messages[1]
    flat = " ".join(str(m.get("content", "")) for m in second_round)
    assert "再看负债率" in flat

    # steer_merged 事件发了
    events = await _read_events(fake_redis, seeded["session_id"], tid)
    types = [e.get("type") for e in events]
    assert "steer_merged" in types
    merged = next(e for e in events if e.get("type") == "steer_merged")
    assert merged.get("preview") == "再看负债率"


# ---------------------------------------------------------------------------
# 3. steer 终态竞态:done 后 push → merged False + 落库行已删(差分 golden)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_steer_terminal_race_returns_false_and_deletes_row(
    pg_async_session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
) -> None:
    seeded = await _seed_session_and_task(pg_async_session_factory, status="done")
    client = _client(pg_async_session_factory, fake_redis)

    resp = client.post(
        f"/api/v0/chat/steer/{seeded['task_id']}",
        json={"message": "太晚了的插话"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["merged"] is False

    # 落库行已删(避免与前端转新 turn 落库双行)
    msgs = await ChatSessionRepo(pg_async_session_factory).list_messages(
        str(seeded["session_id"])
    )
    assert all(m.content != "太晚了的插话" for m in msgs)

    # steer List 未入队
    assert await fake_redis.llen(steer_key(seeded["task_id"])) == 0


# ---------------------------------------------------------------------------
# 4. steer 404
# ---------------------------------------------------------------------------


def test_steer_404_for_unknown_task(
    pg_async_session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
) -> None:
    client = _client(pg_async_session_factory, fake_redis)
    resp = client.post(
        f"/api/v0/chat/steer/{uuid.uuid4()}", json={"message": "x"}
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 5. retry partial(含插话)→ 新 task user_message = 原消息 + 插话(差分 golden)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_partial_includes_original_and_steer(
    pg_async_session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enqueued: list[dict[str, Any]] = []
    from app.tasks import chat_runner

    def fake_enqueue(**kwargs: Any) -> Any:
        enqueued.append(kwargs)

        class _R:
            def __init__(self, tid: str) -> None:
                self.id = tid

        return _R(kwargs["task_id"])

    monkeypatch.setattr(chat_runner, "enqueue_run_chat", fake_enqueue)

    # partial task,带原始 user 消息(initial_prompt 关联)
    seeded = await _seed_session_and_task(
        pg_async_session_factory, status="partial", with_user_msg="分析茅台"
    )
    # 该 turn 的一条插话(task_id 关联,模拟 POST /chat/steer 落库)
    repo = ChatSessionRepo(pg_async_session_factory)
    await repo.append_message(
        session_id=str(seeded["session_id"]),
        role="user",
        content="重点看负债率",
        task_id=seeded["task_id"],
    )

    client = _client(pg_async_session_factory, fake_redis)
    resp = client.post(f"/api/v0/chat/retry/{seeded['task_id']}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["parent_task_id"] == str(seeded["task_id"])
    assert "resumed_from_checkpoint" not in body  # checkpoint 退役

    assert len(enqueued) == 1
    user_message = enqueued[0]["user_message"]
    assert "分析茅台" in user_message
    assert "重点看负债率" in user_message
    assert enqueued[0]["resume_checkpoint_id"] is None


# ---------------------------------------------------------------------------
# 6. retry 无 checkpoint 不再 422(整 turn 重跑)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_without_checkpoint_no_longer_422(
    pg_async_session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enqueued: list[dict[str, Any]] = []
    from app.tasks import chat_runner

    def fake_enqueue(**kwargs: Any) -> Any:
        enqueued.append(kwargs)

        class _R:
            id = kwargs["task_id"]

        return _R()

    monkeypatch.setattr(chat_runner, "enqueue_run_chat", fake_enqueue)

    # error task 无 checkpoint(早期失败),且无原始 user 消息
    seeded = await _seed_session_and_task(pg_async_session_factory, status="error")
    client = _client(pg_async_session_factory, fake_redis)
    resp = client.post(f"/api/v0/chat/retry/{seeded['task_id']}")
    # 旧契约 422,新契约 200(整 turn 重跑,无需 checkpoint)
    assert resp.status_code == 200, resp.text
    assert len(enqueued) == 1
    assert enqueued[0]["resume_checkpoint_id"] is None


# ---------------------------------------------------------------------------
# 7. 升级事件次序:唯一 done 在 escalate_packet_draft 之后
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_escalation_unique_done_after_packet_draft(
    pg_async_session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
    tmp_path: Path,
) -> None:
    """修法 A:escalate turn → done 恰一次,且在 escalate_packet_draft 之后。"""
    seeded = await _seed_session_and_task(pg_async_session_factory, status="running")
    tid = seeded["task_id"]

    # offer_deep_research 是 InProcessTool(mutate-state 控制工具);修复后完全绕过
    # ToolResultCache,同参重复调用也真执行,无需 uuid 唯一化。
    reason = "需要深度尽调"
    llm = ScriptedStepClient(
        [
            _step(tool_calls=[_call("offer_deep_research", {"reason": reason})]),
            _step(content="已为你准备深度研究入口。", finish_reason="stop"),
        ]
    )
    singletons = await _singletons(pg_async_session_factory, llm, tmp_path=tmp_path)

    await run_chat_async(
        task_id=tid,
        singletons=singletons,
        session_factory=pg_async_session_factory,
        redis=fake_redis,
        user_message="帮我深度研究茅台",
        session_id=str(seeded["session_id"]),
        user_id=None,
    )

    events = await _read_events(fake_redis, seeded["session_id"], tid)
    types = [e.get("type") for e in events]

    # done 恰一次(loop 不发 + runner 唯一补发)
    assert types.count("done") == 1
    # 次序:escalate_request → escalate_packet_draft → done
    assert "escalate_request" in types
    assert "escalate_packet_draft" in types
    i_req = types.index("escalate_request")
    i_draft = types.index("escalate_packet_draft")
    i_done = types.index("done")
    assert i_req < i_draft < i_done


# ---------------------------------------------------------------------------
# 8. 非 escalate turn 无双 done(回归加强)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_escalate_turn_single_done(
    pg_async_session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
    tmp_path: Path,
) -> None:
    seeded = await _seed_session_and_task(pg_async_session_factory, status="running")
    tid = seeded["task_id"]

    llm = ScriptedStepClient([_step(content="一次性回答。", finish_reason="stop")])
    singletons = await _singletons(pg_async_session_factory, llm, tmp_path=tmp_path)

    await run_chat_async(
        task_id=tid,
        singletons=singletons,
        session_factory=pg_async_session_factory,
        redis=fake_redis,
        user_message="你好",
        session_id=str(seeded["session_id"]),
        user_id=None,
    )

    events = await _read_events(fake_redis, seeded["session_id"], tid)
    types = [e.get("type") for e in events]
    assert types.count("done") == 1
    # 非 escalate 路径不发升级事件
    assert "escalate_request" not in types

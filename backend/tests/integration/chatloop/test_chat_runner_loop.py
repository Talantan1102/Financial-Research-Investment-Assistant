# mypy: disable-error-code="arg-type"
# SQLAlchemy classical Column[UUID] mypy 推断不准 — 测试代码 silence
# (对齐 test_chat_runner.py / Plan 1 Task 6)。
"""chat_runner 换 ToolLoop 引擎后的集成测试(Phase 4 Task 4.2)。

测试策略(eager / 直调 run_chat_async):
- 注入 ScriptedStepClient(覆盖 singletons.llm)—— 脚本化多圈 StepResult;
- 真 PG pg_async_session_factory(commit cycle)+ fakeredis Redis;
- build_heavy_singletons(llm=Scripted, memory=Fake, skills_root=tmp)绕开真依赖;
- 不起 Celery / MCP subprocess(mcp_client=None → registry 空表,纯 in-process 工具)。

覆盖:
1. 单工具 turn 端到端:1 call + 收尾 → assistant 落库 / task done / 事件序列 / seq 递增;
2. 直答 turn:一圈 → final_response 落库;
3. 取消:cancel_event 预置 → partial 落库(无 checkpoint)+ cancelled 终止事件;
4. 升级:offer_deep_research → escalate_request + escalate_packet_draft + draft 落库;
5. rebuild 注入:预置 6 轮历史 → ScriptedStepClient 收到的 messages 含历史区;
6. persona 失败降级:render 抛 → turn 照常;
7. 无双 done:事件流里 done 恰一次。
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest_asyncio
from app.chatloop.worker_wiring import build_heavy_singletons
from app.models.chat import ChatMessage, ChatSession
from app.models.user import User  # noqa: F401 — 注册 users 表
from app.services.chat_cancel_bus import ChatCancelBus
from app.services.chat_event_bus import ChatEventBus
from app.services.chat_session_repo import ChatSessionRepo
from app.services.chat_task_repo import ChatTaskRepo
from app.services.llm_step import StepDelta, StepResult, StepToolCall
from app.tasks.chat_runner import run_chat_async
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# ---------------------------------------------------------------------------
# Scripted LLM(stream_step 协议)+ Fake memory
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
    """持脚本 list[StepResult]，stream_step 逐圈弹出并触发 on_delta(content/tool_call)。

    .chat 兜底(rebuild 压缩/escalation extractor 可能调到)：返回固定文本。
    记录每圈收到的 messages 供历史注入断言。

    取消注入(I-1 partial 文本测试):
    - 注入 cancel_bus + task_id,在受控时点 publish cancel 并 sleep 等 listener 投递,
      使 run_chat_async 内部 cancel_event 在确定的节拍被 set(pub/sub 在 fakeredis
      内进程内投递,数次 sleep(0) 即可见到)。
    - content_chunks_for_round[r]: 第 r 圈(0-based)的 content 按片流式发,可在指定片后
      触发取消(模拟流中取消,partial 只含半截已流出文本)。
    - cancel_after_round=N: 第 N 圈完整跑完(token 全流出 + apply_step)后触发取消,
      下一圈圈边界抛 CancelledByUser(partial 含第 N 圈完整文本)。
    """

    SUMMARY_TEXT = "## 用户意图\n关注茅台"

    def __init__(
        self,
        steps: list[StepResult],
        *,
        cancel_bus: ChatCancelBus | None = None,
        task_id: uuid.UUID | None = None,
        cancel_after_round: int | None = None,
        content_chunks_per_round: dict[int, list[str]] | None = None,
        cancel_mid_chunk: tuple[int, int] | None = None,
        raise_on_round: tuple[int, BaseException] | None = None,
    ) -> None:
        self._steps = list(steps)
        self.received_messages: list[list[dict[str, Any]]] = []
        self._cancel_bus = cancel_bus
        self._task_id = task_id
        self._cancel_after_round = cancel_after_round
        self._content_chunks = content_chunks_per_round or {}
        # (round, chunk_index): 该圈发完第 chunk_index 片 content 后触发取消
        self._cancel_mid_chunk = cancel_mid_chunk
        # (round, exc): 第 round 圈(0-based)stream_step 直接抛 exc(loop_error 路径)
        self._raise_on_round = raise_on_round
        self._round = 0

    async def _trigger_cancel(self) -> None:
        """publish cancel 并 sleep 让 listener 投递到 run_chat_async 的 cancel_event。"""
        if self._cancel_bus is None or self._task_id is None:
            return
        import asyncio

        for _ in range(40):
            await self._cancel_bus.publish_cancel(self._task_id)
            await asyncio.sleep(0.005)

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
        cur_round = self._round
        # loop_error 路径:本圈直接抛(在 pop 剧本前,不消耗 step)
        if self._raise_on_round is not None and self._raise_on_round[0] == cur_round:
            self._round += 1
            self.received_messages.append([dict(m) for m in messages])
            raise self._raise_on_round[1]
        if not self._steps:
            raise AssertionError("ScriptedStepClient 剧本耗尽 — 剧本步数与循环圈数不符")
        self._round += 1
        self.received_messages.append([dict(m) for m in messages])
        step = self._steps.pop(0)
        if on_delta is not None:
            for tc in step.tool_calls:
                await on_delta(StepDelta(kind="tool_call", text="", tool_name=tc.name))
            chunks = self._content_chunks.get(cur_round)
            if chunks is not None:
                # 分片流式发 content(模拟流中取消)
                for idx, piece in enumerate(chunks):
                    await on_delta(StepDelta(kind="content", text=piece))
                    if (
                        self._cancel_mid_chunk is not None
                        and self._cancel_mid_chunk == (cur_round, idx)
                    ):
                        # 已流出本片 → 触发取消;下一片的 on_delta 圈首检查抛 CancelledByUser
                        await self._trigger_cancel()
            elif step.content:
                await on_delta(StepDelta(kind="content", text=step.content))
        # 本圈完整跑完后触发取消(下一圈圈边界抛)
        if self._cancel_after_round is not None and cur_round == self._cancel_after_round:
            await self._trigger_cancel()
        return step

    def chat(self, prompt: str = "", tier: str = "fast", schema: Any = None, **_: Any) -> Any:
        class _R:
            content = ScriptedStepClient.SUMMARY_TEXT

        return _R()


class _FakeMemory:
    """最小 Memory：search 返回空，render persona 走 get_working_blocks。"""

    def __init__(self, *, persona_raises: bool = False) -> None:
        self._persona_raises = persona_raises

    async def get_working_blocks(self, _user_id: Any) -> dict[str, Any]:
        if self._persona_raises:
            raise RuntimeError("simulated persona DB error")
        return {}

    async def archival_memory_search(self, *_a: Any, **_k: Any) -> list[Any]:
        return []


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded_task(
    pg_async_session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, Any]:
    sid = uuid.uuid4()
    async with pg_async_session_factory() as sess:
        sess.add(ChatSession(id=sid, user_id=None, title="t"))
        await sess.commit()
    task_repo = ChatTaskRepo(pg_async_session_factory)
    task = await task_repo.create_queued(
        session_id=sid,
        user_id=None,
        langgraph_thread_id=f"test:{sid}",
        initial_prompt_message_id=None,
    )
    await task_repo.mark_running(task.id)
    return {"session_id": sid, "user_id": None, "task_id": task.id}


async def _singletons(
    pg_async_session_factory: Any,
    llm: ScriptedStepClient,
    *,
    persona_raises: bool = False,
    tmp_path: Path | None = None,
) -> Any:
    return await build_heavy_singletons(
        session_factory=pg_async_session_factory,
        mcp_client=None,  # registry 空表，纯 in-process 工具
        llm=llm,
        memory=_FakeMemory(persona_raises=persona_raises),
        skills_root=tmp_path,  # None → 真 backend/app/skills；tmp → 空清单
        workdir_root=tmp_path,
    )


async def _read_events(
    redis: FakeRedis, sid: uuid.UUID, tid: uuid.UUID
) -> list[dict[str, Any]]:
    bus = ChatEventBus(redis)
    entries = await bus.xread_blocking(sid, tid, last_id="0", count=200, block_ms=10)
    return [payload for _id, payload in entries]


# ---------------------------------------------------------------------------
# 1. 单工具 turn 端到端
# ---------------------------------------------------------------------------


async def test_single_tool_turn_end_to_end(
    pg_async_session_factory: async_sessionmaker[AsyncSession],
    seeded_task: dict[str, Any],
    tmp_path: Path,
) -> None:
    args = {"query": "茅台持仓"}
    llm = ScriptedStepClient(
        [
            _step(tool_calls=[_call("memory_search", args)]),
            _step(content="你持有茅台，估值偏高。", finish_reason="stop"),
        ]
    )
    singletons = await _singletons(pg_async_session_factory, llm, tmp_path=tmp_path)
    redis = FakeRedis(decode_responses=False)

    await run_chat_async(
        task_id=seeded_task["task_id"],
        singletons=singletons,
        session_factory=pg_async_session_factory,
        redis=redis,
        user_message="我持有什么",
        session_id=str(seeded_task["session_id"]),
        user_id=seeded_task["user_id"],
    )

    events = await _read_events(redis, seeded_task["session_id"], seeded_task["task_id"])
    types = [e.get("type") for e in events]
    assert "step_start" in types
    assert "token" in types
    assert "tool_call" in types or "tool_start" in types
    assert "cost_update" in types
    assert "done" in types
    # token 事件双字段
    tok = next(e for e in events if e.get("type") == "token")
    assert tok.get("text") == tok.get("content")
    # seq 全局递增（去掉无 seq 的 runner 终止补发，loop 发的都带 seq）
    seqs = [e["seq"] for e in events if "seq" in e]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)

    # PG：assistant done
    msgs = await ChatSessionRepo(pg_async_session_factory).list_messages(
        str(seeded_task["session_id"])
    )
    assistant = [m for m in msgs if m.role == "assistant"]
    assert len(assistant) == 1
    assert assistant[0].status == "done"
    assert assistant[0].content == "你持有茅台，估值偏高。"

    task = await ChatTaskRepo(pg_async_session_factory).get_by_id(seeded_task["task_id"])
    assert task is not None
    assert task.status == "done"
    assert task.langgraph_checkpoint_id is None  # checkpoint 退役


# ---------------------------------------------------------------------------
# 2. 直答 turn
# ---------------------------------------------------------------------------


async def test_direct_answer_turn(
    pg_async_session_factory: async_sessionmaker[AsyncSession],
    seeded_task: dict[str, Any],
    tmp_path: Path,
) -> None:
    llm = ScriptedStepClient([_step(content="你好，我能帮你分析股票。", finish_reason="stop")])
    singletons = await _singletons(pg_async_session_factory, llm, tmp_path=tmp_path)
    redis = FakeRedis(decode_responses=False)

    await run_chat_async(
        task_id=seeded_task["task_id"],
        singletons=singletons,
        session_factory=pg_async_session_factory,
        redis=redis,
        user_message="你好",
        session_id=str(seeded_task["session_id"]),
        user_id=seeded_task["user_id"],
    )

    msgs = await ChatSessionRepo(pg_async_session_factory).list_messages(
        str(seeded_task["session_id"])
    )
    assistant = [m for m in msgs if m.role == "assistant"]
    assert len(assistant) == 1
    assert assistant[0].content == "你好，我能帮你分析股票。"
    task = await ChatTaskRepo(pg_async_session_factory).get_by_id(seeded_task["task_id"])
    assert task is not None and task.status == "done"


# ---------------------------------------------------------------------------
# 3. 取消
# ---------------------------------------------------------------------------


async def test_cancel_marks_partial_no_checkpoint(
    pg_async_session_factory: async_sessionmaker[AsyncSession],
    seeded_task: dict[str, Any],
    tmp_path: Path,
) -> None:
    """边界取消:第 1 圈完整跑完(token 全流出)→ 第 2 圈圈边界抛 CancelledByUser。

    I-1 回归:partial 行 content 必须含第 1 圈已流出的 token 文本(非空),
    而非恒空串(取消在 apply_step 前抛时靠 _emit 累积器兜底)。
    """
    redis = FakeRedis(decode_responses=False)
    cancel_bus = ChatCancelBus(redis)
    # 圈1:content(token 流出)+ tool_call(loop 继续);跑完后触发取消 → 圈2 边界抛。
    args = {"query": "茅台持仓"}
    first_round_text = "正在为你查询茅台持仓"
    llm = ScriptedStepClient(
        [
            _step(content=first_round_text, tool_calls=[_call("memory_search", args)]),
            _step(content="第二圈不应被采用", finish_reason="stop"),
        ],
        cancel_bus=cancel_bus,
        task_id=seeded_task["task_id"],
        cancel_after_round=0,
    )
    singletons = await _singletons(pg_async_session_factory, llm, tmp_path=tmp_path)

    await run_chat_async(
        task_id=seeded_task["task_id"],
        singletons=singletons,
        session_factory=pg_async_session_factory,
        redis=redis,
        user_message="取消我",
        session_id=str(seeded_task["session_id"]),
        user_id=seeded_task["user_id"],
    )

    task = await ChatTaskRepo(pg_async_session_factory).get_by_id(seeded_task["task_id"])
    assert task is not None
    assert task.status == "partial"
    assert task.langgraph_checkpoint_id is None

    msgs = await ChatSessionRepo(pg_async_session_factory).list_messages(
        str(seeded_task["session_id"])
    )
    assistant = [m for m in msgs if m.role == "assistant"]
    assert len(assistant) == 1
    assert assistant[0].status == "partial"
    # I-1 核心断言:partial 含第 1 圈已流出文本(非空串)
    assert assistant[0].content
    assert first_round_text in assistant[0].content

    events = await _read_events(redis, seeded_task["session_id"], seeded_task["task_id"])
    types = [e.get("type") for e in events]
    assert "cancelled" in types
    assert "done" not in types  # 取消路径不发 done


async def test_cancel_mid_stream_keeps_partial_tokens(
    pg_async_session_factory: async_sessionmaker[AsyncSession],
    seeded_task: dict[str, Any],
    tmp_path: Path,
) -> None:
    """流中取消:第 1 圈 content 分片流式发,发完首片即取消 → on_delta 圈首抛。

    此时 apply_step 尚未跑(state.messages 无 assistant content),partial 文本
    只能靠 _emit 累积器:断言 partial 含已流出的首片半截文本,且不含未流出的后续片。
    """
    redis = FakeRedis(decode_responses=False)
    cancel_bus = ChatCancelBus(redis)
    head = "茅台当前估值"
    tail = "偏高，建议观望。"
    # 单圈直答,content 分两片;发完第 0 片后触发取消 → 第 1 片的 on_delta 圈首抛。
    llm = ScriptedStepClient(
        [_step(content=head + tail, finish_reason="stop")],
        cancel_bus=cancel_bus,
        task_id=seeded_task["task_id"],
        content_chunks_per_round={0: [head, tail]},
        cancel_mid_chunk=(0, 0),
    )
    singletons = await _singletons(pg_async_session_factory, llm, tmp_path=tmp_path)

    await run_chat_async(
        task_id=seeded_task["task_id"],
        singletons=singletons,
        session_factory=pg_async_session_factory,
        redis=redis,
        user_message="流中取消",
        session_id=str(seeded_task["session_id"]),
        user_id=seeded_task["user_id"],
    )

    task = await ChatTaskRepo(pg_async_session_factory).get_by_id(seeded_task["task_id"])
    assert task is not None and task.status == "partial"

    msgs = await ChatSessionRepo(pg_async_session_factory).list_messages(
        str(seeded_task["session_id"])
    )
    assistant = [m for m in msgs if m.role == "assistant"]
    assert len(assistant) == 1
    assert assistant[0].status == "partial"
    # 已流出首片落库(累积器兜底,apply_step 未跑)
    assert head in assistant[0].content
    # 未流出的后续片不应落库
    assert tail not in assistant[0].content

    events = await _read_events(redis, seeded_task["session_id"], seeded_task["task_id"])
    types = [e.get("type") for e in events]
    assert "cancelled" in types
    assert "done" not in types


# ---------------------------------------------------------------------------
# 4. 升级
# ---------------------------------------------------------------------------


async def test_escalation_emits_request_and_draft(
    pg_async_session_factory: async_sessionmaker[AsyncSession],
    seeded_task: dict[str, Any],
    tmp_path: Path,
) -> None:
    # offer_deep_research → state.escalate_offered=True + tool_choice=none 熔断；
    # 收尾圈直答。turn 后 runner 跑 EscalationExtractor + create_draft。
    llm = ScriptedStepClient(
        [
            _step(tool_calls=[_call("offer_deep_research", {"reason": "需要深度尽调"})]),
            _step(content="已为你准备深度研究入口。", finish_reason="stop"),
        ]
    )
    singletons = await _singletons(pg_async_session_factory, llm, tmp_path=tmp_path)
    redis = FakeRedis(decode_responses=False)

    await run_chat_async(
        task_id=seeded_task["task_id"],
        singletons=singletons,
        session_factory=pg_async_session_factory,
        redis=redis,
        user_message="帮我深度研究茅台",
        session_id=str(seeded_task["session_id"]),
        user_id=seeded_task["user_id"],
    )

    events = await _read_events(redis, seeded_task["session_id"], seeded_task["task_id"])
    types = [e.get("type") for e in events]
    assert "escalate_request" in types
    assert "escalate_packet_draft" in types
    req = next(e for e in events if e.get("type") == "escalate_request")
    assert req.get("reason") == "需要深度尽调"
    draft = next(e for e in events if e.get("type") == "escalate_packet_draft")
    assert "draft_record_id" in draft
    assert "packet" in draft

    # task 仍 done（升级是 turn 后处理，不改终态）
    task = await ChatTaskRepo(pg_async_session_factory).get_by_id(seeded_task["task_id"])
    assert task is not None and task.status == "done"


# ---------------------------------------------------------------------------
# 5. rebuild 注入：预置历史 → ScriptedStepClient messages 含历史区
# ---------------------------------------------------------------------------


async def test_rebuild_history_injected_into_messages(
    pg_async_session_factory: async_sessionmaker[AsyncSession],
    seeded_task: dict[str, Any],
    tmp_path: Path,
) -> None:
    # 预置 3 轮历史（user/assistant 对）。不超压缩阈值 → 全量轮原文进历史区。
    sid = seeded_task["session_id"]
    async with pg_async_session_factory() as sess:
        for i in range(3):
            sess.add(ChatMessage(id=uuid.uuid4(), session_id=sid, role="user", content=f"历史问题{i}"))
            sess.add(
                ChatMessage(id=uuid.uuid4(), session_id=sid, role="assistant", content=f"历史回答{i}")
            )
        await sess.commit()

    llm = ScriptedStepClient([_step(content="结合历史，茅台仍稳健。", finish_reason="stop")])
    singletons = await _singletons(pg_async_session_factory, llm, tmp_path=tmp_path)
    redis = FakeRedis(decode_responses=False)

    await run_chat_async(
        task_id=seeded_task["task_id"],
        singletons=singletons,
        session_factory=pg_async_session_factory,
        redis=redis,
        user_message="现在呢",
        session_id=str(sid),
        user_id=seeded_task["user_id"],
    )

    # 第一圈收到的 messages 应含历史问题/回答（历史区透传）
    first_round = llm.received_messages[0]
    flat = " ".join(str(m.get("content", "")) for m in first_round)
    assert "历史问题0" in flat
    assert "历史回答2" in flat


# ---------------------------------------------------------------------------
# 6. persona 失败降级
# ---------------------------------------------------------------------------


async def test_persona_render_failure_degrades_gracefully(
    pg_async_session_factory: async_sessionmaker[AsyncSession],
    pg_test_engine: Any,
    tmp_path: Path,
) -> None:
    # 需要真 user（persona render 用 user_id）。建一个 user + session + task。
    from sqlalchemy import text as _text

    uid = uuid.uuid4()
    sid = uuid.uuid4()
    async with pg_async_session_factory() as sess:
        await sess.execute(
            _text(
                "INSERT INTO users (id, username, email, hashed_password, is_active) "
                "VALUES (:i, :u, :e, :p, true)"
            ),
            {"i": str(uid), "u": f"loop-{uid.hex[:8]}", "e": f"loop-{uid.hex[:8]}@t.local", "p": "x"},
        )
        sess.add(ChatSession(id=sid, user_id=uid, title="t"))
        await sess.commit()
    task_repo = ChatTaskRepo(pg_async_session_factory)
    task = await task_repo.create_queued(
        session_id=sid, user_id=uid, langgraph_thread_id=f"t:{sid}", initial_prompt_message_id=None
    )

    llm = ScriptedStepClient([_step(content="即便画像渲染失败也照常回答。", finish_reason="stop")])
    singletons = await _singletons(
        pg_async_session_factory, llm, persona_raises=True, tmp_path=tmp_path
    )
    redis = FakeRedis(decode_responses=False)

    await run_chat_async(
        task_id=task.id,
        singletons=singletons,
        session_factory=pg_async_session_factory,
        redis=redis,
        user_message="你好",
        session_id=str(sid),
        user_id=str(uid),
    )

    refreshed = await task_repo.get_by_id(task.id)
    assert refreshed is not None and refreshed.status == "done"
    msgs = await ChatSessionRepo(pg_async_session_factory).list_messages(str(sid))
    assistant = [m for m in msgs if m.role == "assistant"]
    assert len(assistant) == 1
    assert assistant[0].content == "即便画像渲染失败也照常回答。"


# ---------------------------------------------------------------------------
# 7. 无双 done
# ---------------------------------------------------------------------------


async def test_no_double_done(
    pg_async_session_factory: async_sessionmaker[AsyncSession],
    seeded_task: dict[str, Any],
    tmp_path: Path,
) -> None:
    llm = ScriptedStepClient([_step(content="一次性回答。", finish_reason="stop")])
    singletons = await _singletons(pg_async_session_factory, llm, tmp_path=tmp_path)
    redis = FakeRedis(decode_responses=False)

    await run_chat_async(
        task_id=seeded_task["task_id"],
        singletons=singletons,
        session_factory=pg_async_session_factory,
        redis=redis,
        user_message="一句话",
        session_id=str(seeded_task["session_id"]),
        user_id=seeded_task["user_id"],
    )

    events = await _read_events(redis, seeded_task["session_id"], seeded_task["task_id"])
    done_count = sum(1 for e in events if e.get("type") == "done")
    assert done_count == 1


# ---------------------------------------------------------------------------
# 8. loop_error 路径（I-2）：stream_step 抛 → mark_error + error_done 事件
# ---------------------------------------------------------------------------


async def test_loop_error_marks_error_and_emits_error_done(
    pg_async_session_factory: async_sessionmaker[AsyncSession],
    seeded_task: dict[str, Any],
    tmp_path: Path,
) -> None:
    """I-2 回归:ToolLoop.stream_step 抛 RuntimeError → loop_error 路径。

    断言:task status=error / assistant 行 status=error / error_message 截断到 ≤500 /
    事件流含 error 与 error_done(终止事件不双发 done)。
    """
    # 长 error message(>500)验证截断;开头保留 "boom" 供内容断言。
    long_msg = "boom" + "x" * 600
    llm = ScriptedStepClient(
        [],  # 不需要剧本步,第 0 圈直接抛
        raise_on_round=(0, RuntimeError(long_msg)),
    )
    singletons = await _singletons(pg_async_session_factory, llm, tmp_path=tmp_path)
    redis = FakeRedis(decode_responses=False)

    await run_chat_async(
        task_id=seeded_task["task_id"],
        singletons=singletons,
        session_factory=pg_async_session_factory,
        redis=redis,
        user_message="触发错误",
        session_id=str(seeded_task["session_id"]),
        user_id=seeded_task["user_id"],
    )

    task = await ChatTaskRepo(pg_async_session_factory).get_by_id(seeded_task["task_id"])
    assert task is not None
    assert task.status == "error"
    assert task.error_message is not None
    assert task.error_message.startswith("boom")
    assert len(task.error_message) <= 500  # 截断

    msgs = await ChatSessionRepo(pg_async_session_factory).list_messages(
        str(seeded_task["session_id"])
    )
    assistant = [m for m in msgs if m.role == "assistant"]
    assert len(assistant) == 1
    assert assistant[0].status == "error"

    events = await _read_events(redis, seeded_task["session_id"], seeded_task["task_id"])
    types = [e.get("type") for e in events]
    assert "error" in types
    assert "error_done" in types
    assert "done" not in types  # error 路径不发成功 done
    # error 事件携带截断后的 message
    err = next(e for e in events if e.get("type") == "error")
    assert str(err.get("message", "")).startswith("boom")
    assert len(str(err.get("message", ""))) <= 500

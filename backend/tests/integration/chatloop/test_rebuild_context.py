"""rebuild_context 集成测试(真 PG,spec § 4.1 / § 4.2 / § 2.3 跨 turn 级)。

覆盖:
- 空 session → 空 tuple;
- 短历史(不超阈值)→ 无摘要,全量轮原文,表无行写入;
- 长历史(超阈值)→ 摘要行写入 / 水位 = 被总结最后一条 id / 产出 = [摘要] + 最近 4 轮;
- 幂等:再次 rebuild(无新消息)→ Fake llm 不再被调 / 产出一致;
- 水位后新增 2 轮再 rebuild(仍超阈值)→ 只有水位后老轮参与新总结 / prior_summary 进 prompt;
- llm=None 超阈值 → 不压缩不炸,全量轮产出;
- LLM 抛异常 → 降级不炸;
- assistant 缺失的孤儿 user 轮容错。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from app.chatloop.rebuild import RECENT_TURNS, rebuild_context
from app.models.chat import ChatMessage, ChatSession, ChatSessionContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# 长内容:超阈值需要 0.70 * 24000 = 16800 token。CJK 约 1.65 字符/token。
# 每条 ~2880 汉字 ≈ 1745 token,6 轮 12 条 ≈ 20940 token,稳超阈值。
_LONG_CONTENT = "贵州茅台毛利率九成营收增长稳健现金流充沛护城河深厚" * 120  # ~2880 字


# ---------------------------------------------------------------------------
# Fake LLM — 轻量,带 chat(prompt, tier, schema) 签名,记录调用与收到的 prompt
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeLLM:
    """返回固定摘要文本;记录调用次数与每次 prompt(断言水位/prior_summary 用)。"""

    SUMMARY_TEXT = "## 用户意图\n关注贵州茅台估值\n## 已确认的关键事实\n毛利率 91.2%(2025 年报)"

    def __init__(self, content: str | None = None, *, raises: bool = False) -> None:
        self._content = content if content is not None else self.SUMMARY_TEXT
        self._raises = raises
        self.calls: list[dict[str, Any]] = []

    def chat(
        self,
        prompt: str,
        tier: str = "fast",
        schema: Any = None,
    ) -> _FakeResponse:
        self.calls.append({"prompt": prompt, "tier": tier})
        if self._raises:
            raise RuntimeError("simulated LLM failure during summarize")
        return _FakeResponse(self._content)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def async_factory(
    pg_async_session_factory: async_sessionmaker[AsyncSession],
) -> async_sessionmaker[AsyncSession]:
    return pg_async_session_factory


@pytest_asyncio.fixture
async def seeded_session_id(
    async_factory: async_sessionmaker[AsyncSession],
) -> uuid.UUID:
    sid = uuid.uuid4()
    async with async_factory() as sess:
        sess.add(ChatSession(id=sid, user_id=None, title="rebuild-test"))
        await sess.commit()
    return sid


async def _seed_turns(
    factory: async_sessionmaker[AsyncSession],
    session_id: uuid.UUID,
    turns: list[tuple[str, str]],
    *,
    content_user: str = "user 问题",
    content_assistant: str = "assistant 终答",
    start: datetime | None = None,
) -> list[uuid.UUID]:
    """插入 N 轮 (user, assistant) 消息,显式递增 created_at 保证确定序。

    turns 是 (user_content, assistant_content) 列表;返回插入消息的 id 顺序。
    """
    base = start or datetime(2026, 6, 5, 12, 0, 0)
    ids: list[uuid.UUID] = []
    async with factory() as sess:
        offset = 0
        for u_content, a_content in turns:
            u_id = uuid.uuid4()
            sess.add(
                ChatMessage(
                    id=u_id,
                    session_id=session_id,
                    role="user",
                    content=u_content,
                    created_at=base + timedelta(seconds=offset),
                )
            )
            ids.append(u_id)
            offset += 1
            if a_content is not None:
                a_id = uuid.uuid4()
                sess.add(
                    ChatMessage(
                        id=a_id,
                        session_id=session_id,
                        role="assistant",
                        content=a_content,
                        created_at=base + timedelta(seconds=offset),
                    )
                )
                ids.append(a_id)
                offset += 1
        await sess.commit()
    return ids


async def _cleanup(factory: async_sessionmaker[AsyncSession], session_id: uuid.UUID) -> None:
    """pg_async_session_factory 无 rollback isolation,test 末显式清。"""
    async with factory() as sess:
        ctx = await sess.get(ChatSessionContext, session_id)
        if ctx is not None:
            await sess.delete(ctx)
        for m in (
            (await sess.execute(select(ChatMessage).where(ChatMessage.session_id == session_id)))
            .scalars()
            .all()
        ):
            await sess.delete(m)
        sess_row = await sess.get(ChatSession, session_id)
        if sess_row is not None:
            await sess.delete(sess_row)
        await sess.commit()


async def _read_ctx(
    factory: async_sessionmaker[AsyncSession], session_id: uuid.UUID
) -> ChatSessionContext | None:
    async with factory() as sess:
        return await sess.get(ChatSessionContext, session_id)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_session_returns_empty_tuple(
    async_factory: async_sessionmaker[AsyncSession],
    seeded_session_id: uuid.UUID,
) -> None:
    """空 session(无消息、无摘要)→ 空 tuple。"""
    try:
        async with async_factory() as db:
            result = await rebuild_context(str(seeded_session_id), db=db, llm=_FakeLLM())
        assert result == ()
    finally:
        await _cleanup(async_factory, seeded_session_id)


@pytest.mark.asyncio
async def test_short_history_no_summary_full_turns(
    async_factory: async_sessionmaker[AsyncSession],
    seeded_session_id: uuid.UUID,
) -> None:
    """3 轮短历史(不超阈值)→ 无摘要,3 轮原文,表无行写入。"""
    fake = _FakeLLM()
    try:
        await _seed_turns(
            async_factory,
            seeded_session_id,
            [(f"问题{i}", f"回答{i}") for i in range(3)],
        )
        async with async_factory() as db:
            result = await rebuild_context(str(seeded_session_id), db=db, llm=fake)

        # 无 system 摘要消息
        assert all(m["role"] != "system" for m in result)
        # 3 轮 = 6 条 (user + assistant)
        assert len(result) == 6
        assert [m["role"] for m in result] == [
            "user",
            "assistant",
            "user",
            "assistant",
            "user",
            "assistant",
        ]
        assert result[0]["content"] == "问题0"
        # 未触发压缩 → Fake 不被调,表无行
        assert fake.calls == []
        assert await _read_ctx(async_factory, seeded_session_id) is None
    finally:
        await _cleanup(async_factory, seeded_session_id)


@pytest.mark.asyncio
async def test_long_history_triggers_summary_and_watermark(
    async_factory: async_sessionmaker[AsyncSession],
    seeded_session_id: uuid.UUID,
) -> None:
    """6 轮长历史(超阈值)→ 摘要行写入 / 水位 = 被总结最后一条 id / 产出 = [摘要] + 最近 4 轮。"""
    fake = _FakeLLM()
    try:
        ids = await _seed_turns(
            async_factory,
            seeded_session_id,
            [(_LONG_CONTENT + f" 轮{i} user", _LONG_CONTENT + f" 轮{i} ast") for i in range(6)],
        )
        # 6 轮 → 老轮 = 前 2 轮(turns[:-4]);被总结最后一条 = 第 2 轮 assistant。
        # ids 顺序:turn0(u,a), turn1(u,a), ... → 第 2 轮(index 1)的 assistant = ids[3]
        expected_watermark = ids[3]

        async with async_factory() as db:
            result = await rebuild_context(str(seeded_session_id), db=db, llm=fake)

        # Fake 被调 1 次
        assert len(fake.calls) == 1
        # 产出:[摘要 system] + 最近 4 轮(8 条)
        assert result[0]["role"] == "system"
        assert "[对话摘要]" in result[0]["content"]
        assert _FakeLLM.SUMMARY_TEXT in result[0]["content"]
        body = result[1:]
        assert len(body) == RECENT_TURNS * 2  # 4 轮 × 2
        # 最近 4 轮 = 轮 2..5,第一条 body 是 轮2 的 user
        assert "轮2 user" in body[0]["content"]
        assert "轮5 ast" in body[-1]["content"]

        # 表写入 + 水位
        ctx = await _read_ctx(async_factory, seeded_session_id)
        assert ctx is not None
        assert ctx.history_summary == _FakeLLM.SUMMARY_TEXT
        assert ctx.summarized_upto == expected_watermark
    finally:
        await _cleanup(async_factory, seeded_session_id)


@pytest.mark.asyncio
async def test_idempotent_second_rebuild_no_llm_call(
    async_factory: async_sessionmaker[AsyncSession],
    seeded_session_id: uuid.UUID,
) -> None:
    """幂等:压缩后再次 rebuild(无新消息)→ Fake 不再被调 / 产出一致。"""
    try:
        await _seed_turns(
            async_factory,
            seeded_session_id,
            [(_LONG_CONTENT + f" 轮{i} user", _LONG_CONTENT + f" 轮{i} ast") for i in range(6)],
        )
        fake1 = _FakeLLM()
        async with async_factory() as db:
            first = await rebuild_context(str(seeded_session_id), db=db, llm=fake1)
        assert len(fake1.calls) == 1

        fake2 = _FakeLLM()
        async with async_factory() as db:
            second = await rebuild_context(str(seeded_session_id), db=db, llm=fake2)

        # 水位之后只剩最近 4 轮(< RECENT_TURNS+1)→ 不再压缩,Fake2 零调用
        assert fake2.calls == []
        # 产出一致(都是 [摘要] + 最近 4 轮)
        assert [m["role"] for m in first] == [m["role"] for m in second]
        assert [m["content"] for m in first] == [m["content"] for m in second]
    finally:
        await _cleanup(async_factory, seeded_session_id)


@pytest.mark.asyncio
async def test_new_turns_after_watermark_only_resummarize_new(
    async_factory: async_sessionmaker[AsyncSession],
    seeded_session_id: uuid.UUID,
) -> None:
    """水位后新增轮再 rebuild(仍超阈值)→ 只有水位后老轮参与新总结 / prior_summary 进 prompt。"""
    try:
        # 第一批 6 轮 → 压缩,水位落在第 2 轮 assistant
        await _seed_turns(
            async_factory,
            seeded_session_id,
            [
                (_LONG_CONTENT + f" FIRST{i} user", _LONG_CONTENT + f" FIRST{i} ast")
                for i in range(6)
            ],
            start=datetime(2026, 6, 5, 12, 0, 0),
        )
        fake1 = _FakeLLM()
        async with async_factory() as db:
            await rebuild_context(str(seeded_session_id), db=db, llm=fake1)

        # 新增 4 轮(水位之后总轮数 = 4(原最近) + 4(新) = 8,仍超阈值)
        await _seed_turns(
            async_factory,
            seeded_session_id,
            [
                (_LONG_CONTENT + f" SECOND{i} user", _LONG_CONTENT + f" SECOND{i} ast")
                for i in range(4)
            ],
            start=datetime(2026, 6, 5, 13, 0, 0),
        )
        fake2 = _FakeLLM(content="第二次摘要")
        async with async_factory() as db:
            await rebuild_context(str(seeded_session_id), db=db, llm=fake2)

        assert len(fake2.calls) == 1
        prompt2 = fake2.calls[0]["prompt"]
        # 已总结轮(FIRST0 / FIRST1)不应再进新 prompt(水位过滤)
        assert "FIRST0" not in prompt2
        assert "FIRST1" not in prompt2
        # prior_summary(第一次的摘要)进了第二次 prompt
        assert _FakeLLM.SUMMARY_TEXT in prompt2
    finally:
        await _cleanup(async_factory, seeded_session_id)


@pytest.mark.asyncio
async def test_llm_none_over_threshold_no_compress_full_turns(
    async_factory: async_sessionmaker[AsyncSession],
    seeded_session_id: uuid.UUID,
) -> None:
    """llm=None 超阈值 → 不压缩不炸,全量轮产出,无表写入。"""
    try:
        await _seed_turns(
            async_factory,
            seeded_session_id,
            [(_LONG_CONTENT + f" 轮{i} user", _LONG_CONTENT + f" 轮{i} ast") for i in range(6)],
        )
        async with async_factory() as db:
            result = await rebuild_context(str(seeded_session_id), db=db, llm=None)

        # 无摘要;全量 6 轮 = 12 条
        assert all(m["role"] != "system" for m in result)
        assert len(result) == 12
        assert await _read_ctx(async_factory, seeded_session_id) is None
    finally:
        await _cleanup(async_factory, seeded_session_id)


@pytest.mark.asyncio
async def test_llm_raises_degrades_gracefully(
    async_factory: async_sessionmaker[AsyncSession],
    seeded_session_id: uuid.UUID,
) -> None:
    """LLM 抛异常 → 降级不炸,全量轮产出,无表写入。"""
    fake = _FakeLLM(raises=True)
    try:
        await _seed_turns(
            async_factory,
            seeded_session_id,
            [(_LONG_CONTENT + f" 轮{i} user", _LONG_CONTENT + f" 轮{i} ast") for i in range(6)],
        )
        async with async_factory() as db:
            result = await rebuild_context(str(seeded_session_id), db=db, llm=fake)

        # 尝试过压缩(被调)但抛错 → 降级不压缩
        assert len(fake.calls) == 1
        assert all(m["role"] != "system" for m in result)
        assert len(result) == 12
        # 压缩失败 → 不写表
        assert await _read_ctx(async_factory, seeded_session_id) is None
    finally:
        await _cleanup(async_factory, seeded_session_id)


@pytest.mark.asyncio
async def test_partial_and_error_assistant_rows_excluded(
    async_factory: async_sessionmaker[AsyncSession],
    seeded_session_id: uuid.UUID,
) -> None:
    """spec § 4.3:partial / error 的 assistant 行不进历史窗口(只展示,非结晶终答)。

    构造一个完整 turn(user + done assistant)+ 一个失败 turn(user + partial assistant)
    + 一个 error turn(user + error assistant)。rebuild 应只带 done assistant,
    partial / error 的 assistant content 不应出现在产出里(但其 user 仍保留)。
    """
    base = datetime(2026, 6, 5, 12, 0, 0)
    try:
        async with async_factory() as sess:
            # 完整 turn(done)
            sess.add(
                ChatMessage(
                    id=uuid.uuid4(),
                    session_id=seeded_session_id,
                    role="user",
                    content="完整提问",
                    created_at=base,
                )
            )
            sess.add(
                ChatMessage(
                    id=uuid.uuid4(),
                    session_id=seeded_session_id,
                    role="assistant",
                    content="完整结晶终答",
                    status="done",
                    created_at=base + timedelta(seconds=1),
                )
            )
            # 失败 turn(partial assistant)
            sess.add(
                ChatMessage(
                    id=uuid.uuid4(),
                    session_id=seeded_session_id,
                    role="user",
                    content="被取消的提问",
                    created_at=base + timedelta(seconds=2),
                )
            )
            sess.add(
                ChatMessage(
                    id=uuid.uuid4(),
                    session_id=seeded_session_id,
                    role="assistant",
                    content="半截被取消的输出",
                    status="partial",
                    created_at=base + timedelta(seconds=3),
                )
            )
            # error turn(error assistant)
            sess.add(
                ChatMessage(
                    id=uuid.uuid4(),
                    session_id=seeded_session_id,
                    role="user",
                    content="出错的提问",
                    created_at=base + timedelta(seconds=4),
                )
            )
            sess.add(
                ChatMessage(
                    id=uuid.uuid4(),
                    session_id=seeded_session_id,
                    role="assistant",
                    content="出错的残答",
                    status="error",
                    created_at=base + timedelta(seconds=5),
                )
            )
            await sess.commit()

        async with async_factory() as db:
            result = await rebuild_context(str(seeded_session_id), db=db, llm=_FakeLLM())

        contents = [m["content"] for m in result]
        # done assistant 保留
        assert "完整结晶终答" in contents
        # partial / error assistant content 被排除
        assert "半截被取消的输出" not in contents
        assert "出错的残答" not in contents
        # 三个 user 提问仍保留(user 行不受 status 过滤)
        assert "完整提问" in contents
        assert "被取消的提问" in contents
        assert "出错的提问" in contents
    finally:
        await _cleanup(async_factory, seeded_session_id)


@pytest.mark.asyncio
async def test_orphan_user_turn_tolerated(
    async_factory: async_sessionmaker[AsyncSession],
    seeded_session_id: uuid.UUID,
) -> None:
    """assistant 缺失的孤儿 user 轮容错 — 不炸,产出含该 user。"""
    base = datetime(2026, 6, 5, 12, 0, 0)
    try:
        async with async_factory() as sess:
            # 轮0: user + assistant;轮1: 只有 user(孤儿,assistant 缺失)
            sess.add(
                ChatMessage(
                    id=uuid.uuid4(),
                    session_id=seeded_session_id,
                    role="user",
                    content="第一轮提问",
                    created_at=base,
                )
            )
            sess.add(
                ChatMessage(
                    id=uuid.uuid4(),
                    session_id=seeded_session_id,
                    role="assistant",
                    content="第一轮回答",
                    created_at=base + timedelta(seconds=1),
                )
            )
            sess.add(
                ChatMessage(
                    id=uuid.uuid4(),
                    session_id=seeded_session_id,
                    role="user",
                    content="第二轮提问没人答",
                    created_at=base + timedelta(seconds=2),
                )
            )
            await sess.commit()

        async with async_factory() as db:
            result = await rebuild_context(str(seeded_session_id), db=db, llm=_FakeLLM())

        contents = [m["content"] for m in result]
        assert "第一轮提问" in contents
        assert "第一轮回答" in contents
        assert "第二轮提问没人答" in contents
        # 孤儿 user 后无 assistant — 角色序列以 user 收尾
        assert result[-1]["role"] == "user"
    finally:
        await _cleanup(async_factory, seeded_session_id)

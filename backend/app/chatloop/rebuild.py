"""跨 turn 历史重建 — DB-as-truth(spec § 4.2)。

老 turn 的多圈工具轨迹不重建:assistant 终答已是结晶;模型要旧数字
重调工具(缓存命中)或 read_cached_result。压缩(70% 软阈值)发生在
rebuild 时,水位 summarized_upto 防重复总结。

产物形状对齐 ContextDeps.history_block(tuple[dict[str, Any], ...]):
    ([{"role":"system","content":"[对话摘要]\n..."}](若有摘要)
     + 最近 RECENT_TURNS 轮的 [{"role":"user",...},{"role":"assistant",...}]).

async/sync:ChatSessionRepo / chat_runner 均为 async(AsyncSession),本模块
对齐选择 async。LLMService.chat 是 sync,压缩时用 asyncio.to_thread 包。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Final, Protocol, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chatloop.context import estimate_tokens
from app.models.chat import ChatMessage, ChatSessionContext

logger = logging.getLogger(__name__)


class _SummaryResponse(Protocol):
    content: str


class SummarizerLLM(Protocol):
    """rebuild 压缩只需 chat(prompt, tier, schema) → 带 .content 的响应。

    结构化协议,LLMService(.chat 返回 LLMResponse)天然满足;测试可注入轻量
    Fake。避免 rebuild 直接依赖 LLMService 具体类。
    """

    def chat(
        self, prompt: str, tier: str = ..., schema: Any = ...
    ) -> _SummaryResponse: ...

RECENT_TURNS: Final[int] = 4  # 最近 K 轮原文保留
SUMMARIZE_THRESHOLD: Final[float] = 0.70  # 估算 token 超此比例触发压缩
CONTEXT_TOKEN_BUDGET: Final[int] = 24_000

_SUMMARIZE_TEMPLATE: Final[str] = """请把下面的对话历史浓缩成结构化摘要(400 字内):
## 用户意图
## 已确认的关键事实(每个定量数字必须带口径与来源,原样保留,如"贵州茅台毛利率 91.2%(2025 年报)")
## 出过的错误与解法
## 未决问题
## 下一步方向

[既有摘要]
{prior_summary}

[对话历史]
{history_text}"""


class _Turn:
    """一轮对话:一条 user + (可选)一条 assistant 终答。

    每轮记录其涉及的全部 message id,以便压缩后把水位推到被总结的最后一条。
    存纯 str/UUID(从 ORM 行在 _split_turns 边界提取),避免 ORM Column 类型外泄。
    """

    __slots__ = ("user_content", "assistant_content", "message_ids")

    def __init__(self) -> None:
        self.user_content: str | None = None
        self.assistant_content: str | None = None
        self.message_ids: list[uuid.UUID] = []

    def to_messages(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if self.user_content is not None:
            out.append({"role": "user", "content": self.user_content})
        if self.assistant_content is not None:
            out.append({"role": "assistant", "content": self.assistant_content})
        return out

    def to_text(self) -> str:
        parts: list[str] = []
        if self.user_content is not None:
            parts.append(f"user: {self.user_content}")
        if self.assistant_content is not None:
            parts.append(f"assistant: {self.assistant_content}")
        return "\n".join(parts)


def _split_turns(messages: list[ChatMessage]) -> list[_Turn]:
    """切轮:user→assistant 配对为一轮。

    容错(现实数据宽松处理):
    - 连续 user(缺 assistant):上一个开放轮在遇到新 user 时封轮,新建一轮;
    - 孤儿 assistant(开头就是 assistant,无前置 user):自成一轮(只有 assistant)。
    """
    turns: list[_Turn] = []
    cur: _Turn | None = None

    for msg in messages:
        # ORM 行属性 mypy 视作 Column[T];运行时是真实标量,边界处 cast 一次。
        role = cast(str, msg.role)
        content = cast(str, msg.content)
        msg_id = cast(uuid.UUID, msg.id)
        if role == "user":
            # 新 user 开启新一轮;若上一轮已开(还没等到 assistant)先封存
            cur = _Turn()
            cur.user_content = content
            cur.message_ids.append(msg_id)
            turns.append(cur)
        elif role == "assistant":
            if cur is not None and cur.assistant_content is None:
                cur.assistant_content = content
                cur.message_ids.append(msg_id)
                # 一轮已配满,关闭当前轮(下一条 assistant 不再并入)
                cur = None
            else:
                # 孤儿 assistant(无前置开放 user)→ 自成一轮
                orphan = _Turn()
                orphan.assistant_content = content
                orphan.message_ids.append(msg_id)
                turns.append(orphan)
                cur = None
    return turns


async def _load_context_row(
    db: AsyncSession, session_uuid: uuid.UUID
) -> ChatSessionContext | None:
    return await db.get(ChatSessionContext, session_uuid)


async def _load_messages_after(
    db: AsyncSession, session_uuid: uuid.UUID, summarized_upto: uuid.UUID | None
) -> list[ChatMessage]:
    """读该 session 的 user/assistant 消息,按 created_at 升序,水位之后,content 非空。

    水位过滤:summarized_upto 之前(含)的消息已被总结,排除——这是幂等的来源。
    用 created_at 做边界(取水位行的 created_at,只留严格更晚的),id 自身不可比序。

    status 过滤(spec § 4.3 / § 4.2):排除 status ∈ (partial, error) 的行。partial
    是取消时仅供展示的半截输出,error 是失败 turn 的残答——都不是结晶的历史终答,
    重跑/续问时不该进上下文窗口(否则模型把半截当成上轮结论)。只留 done(默认)与
    cancelled(整轮取消但若有 done 文本仍可作历史,实际取消落 partial,这里宽松保留)。
    """
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_uuid)
        .where(ChatMessage.role.in_(("user", "assistant")))
        .where(ChatMessage.status.notin_(("partial", "error")))
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
    )
    rows = list((await db.execute(stmt)).scalars().all())

    rows = [r for r in rows if r.content and cast(str, r.content).strip()]

    if summarized_upto is None:
        return rows

    # 找到水位行,丢弃它及之前的所有行(按 created_at + id 复合序)
    cutoff_idx = -1
    for i, r in enumerate(rows):
        if cast(uuid.UUID, r.id) == summarized_upto:
            cutoff_idx = i
            break
    if cutoff_idx >= 0:
        return rows[cutoff_idx + 1 :]
    # 水位行已被删/不在范围 → 不丢弃(宽松降级,宁可多带不漏带未总结轮)
    return rows


def _estimate_turns_tokens(turns: list[_Turn], prior_summary: str | None) -> int:
    total = estimate_tokens(prior_summary) if prior_summary else 0
    for t in turns:
        total += estimate_tokens(t.to_text())
    return total


async def _summarize(
    llm: SummarizerLLM, old_turns: list[_Turn], prior_summary: str | None
) -> str:
    history_text = "\n\n".join(t.to_text() for t in old_turns)
    prompt = _SUMMARIZE_TEMPLATE.format(
        prior_summary=prior_summary or "(无)",
        history_text=history_text,
    )
    # LLMService.chat 是 sync — 在 async 函数里 offload 到线程,别阻塞 event loop
    resp = await asyncio.to_thread(llm.chat, prompt=prompt, tier="fast", schema=None)
    return resp.content.strip()


async def _persist_summary(
    db: AsyncSession,
    session_uuid: uuid.UUID,
    row: ChatSessionContext | None,
    new_summary: str,
    new_watermark: uuid.UUID,
) -> None:
    if row is None:
        row = ChatSessionContext(
            session_id=session_uuid,
            history_summary=new_summary,
            summarized_upto=new_watermark,
        )
        db.add(row)
    else:
        # ORM 列赋值:mypy 视 row.* 为 Column[T],运行时是 instrumented attr。
        row.history_summary = new_summary  # type: ignore[assignment]
        row.summarized_upto = new_watermark  # type: ignore[assignment]
    await db.commit()


async def rebuild_context(
    session_id: str,
    *,
    db: AsyncSession,
    llm: SummarizerLLM | None,
    token_budget: int = CONTEXT_TOKEN_BUDGET,
) -> tuple[dict[str, Any], ...]:
    """跨 turn 历史重建 + 按需压缩(spec § 4.2)。

    步骤:
    1. 读 ChatSessionContext 行(无则视为空摘要、零水位);
    2. 读水位后的 user/assistant 消息(content 非空,按 created_at 升序);
    3. 切轮(user→assistant 配对,容错孤儿);
    4. 估算 token(摘要 + 全部未总结轮)超 0.70*budget 且 llm 非 None →
       把"除最近 RECENT_TURNS 轮外"的老轮 + prior_summary 喂模板 → llm.chat(fast) →
       新摘要写回表,水位推到被总结的最后一条 message id;
    5. 产出:[摘要 system 消息](若有)+ 最近 RECENT_TURNS 轮原文。

    幂等:水位之前的消息已在步骤 2 过滤,永不再次参与总结。
    压缩失败(LLM 异常)→ logger.warning + 不压缩降级(本次窗口大一点,不破功能)。
    """
    session_uuid = uuid.UUID(session_id) if isinstance(session_id, str) else session_id

    # 1. 读上下文行(摘要 + 水位)。ORM 行属性在边界 cast 成标量类型。
    ctx_row = await _load_context_row(db, session_uuid)
    prior_summary: str | None = (
        cast("str | None", ctx_row.history_summary) if ctx_row is not None else None
    )
    summarized_upto: uuid.UUID | None = (
        cast("uuid.UUID | None", ctx_row.summarized_upto) if ctx_row is not None else None
    )

    # 2. 读水位后的消息
    messages = await _load_messages_after(db, session_uuid, summarized_upto)

    # 空 session 且无既有摘要 → 空 tuple
    if not messages and not prior_summary:
        return ()

    # 3. 切轮
    turns = _split_turns(messages)

    # 4. 估算 + 按需压缩
    if (
        llm is not None
        and turns
        and len(turns) > RECENT_TURNS
        and _estimate_turns_tokens(turns, prior_summary)
        > SUMMARIZE_THRESHOLD * token_budget
    ):
        old_turns = turns[:-RECENT_TURNS]
        # 被总结的最后一条 message id = 老轮最后一条消息(水位)
        last_summarized_id: uuid.UUID | None = None
        for t in reversed(old_turns):
            if t.message_ids:
                last_summarized_id = t.message_ids[-1]
                break
        try:
            new_summary = await _summarize(llm, old_turns, prior_summary)
        except Exception as exc:  # noqa: BLE001 — 压缩失败降级,不破功能
            logger.warning(
                "rebuild_context: 跨 turn 压缩失败,降级为不压缩(全量轮): %s", exc
            )
        else:
            if last_summarized_id is not None:
                await _persist_summary(
                    db, session_uuid, ctx_row, new_summary, last_summarized_id
                )
            prior_summary = new_summary
            turns = turns[-RECENT_TURNS:]

    # 5. 产出:[摘要 system 消息](若有)+ 剩余轮原文。
    #    压缩发生时 turns 已截到最近 RECENT_TURNS 轮;不压缩(含 llm=None / 降级)
    #    则全量轮产出(不截断,窗口大一点不破功能)。
    result: list[dict[str, Any]] = []
    if prior_summary:
        result.append(
            {"role": "system", "content": f"[对话摘要]\n{prior_summary}"}
        )
    for t in turns:
        result.extend(t.to_messages())

    return tuple(result)

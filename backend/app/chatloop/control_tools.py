"""控制双工具 in-process —— offer_deep_research + read_cached_result(spec § 3.5 / § 2.4)。

两个"碰 harness 内部状态"的控制类工具(spec § 3.3 判据 → in-process):

**offer_deep_research**(reason):升级深度研究的**信号工具**(不直接产出答案)。
- 幂等:同 turn 第二次调用被拒(state.escalate_offered 已 True);
- 置 state.escalate_offered=True / escalate_reason=reason / **tool_choice="none"**
  (熔断,spec § 3.5;loop 下一圈自然带 tool_choice="none",代码强制非文案自律);
- 返回 escalation_proposed=true + note(本轮工具通道关闭,请基于已有信息简要作答)。
- escalate_request SSE 事件不在本任务发(InProcessTool 无 emit 通道):Phase 4
  chat_runner 看 state.escalate_offered 发专用事件;本任务沿用 hub 通用 tool_end。

**read_cached_result**(ref, offset=0, limit=2000):按缓存键取回降级/截断的完整原文。
- 跨用户防护(spec § 4):ref 必须以 f"{state.user_id}::" 开头(cache_key 命名空间),
  否则 [无权访问];校验先于 cache 读取(不泄露其它用户键的存在性);
- cache.get_raw(ref) 返回 None → [缓存不存在/已过期](指导模型重调原工具);
- 命中 → {ref, content(原文[offset:offset+limit]), total_len, offset}(分页)。

部署形态:in-process Tool(碰 state.escalate_offered / state.tool_choice /
state.user_id,spec § 3.3 判据)。Phase 4 worker 注入 ToolResultCache 实例
(协议 get_raw(cache_key) -> str | None)。
"""
from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel

from app.chatloop.inprocess import InProcessTool
from app.chatloop.state import ChatLoopState
from app.tools.base import ToolError

# read_cached_result 默认分页长度上限(与 context.py 降级阈值同量级)。
_DEFAULT_LIMIT = 2000


class _RawCacheProto(Protocol):
    """read_cached_result 只依赖 get_raw(cache_key) -> str | None。"""

    async def get_raw(self, cache_key: str) -> str | None: ...


# ---------------------------------------------------------------------------
# args schema
# ---------------------------------------------------------------------------


class OfferDeepResearchArgs(BaseModel):
    reason: str


class ReadCachedResultArgs(BaseModel):
    ref: str
    offset: int = 0
    limit: int = _DEFAULT_LIMIT


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _fail(error: str) -> ToolError:
    """指导性错误 —— 以 [标签] 开头,ToolHub._guidance_error 原样透出。"""
    return ToolError(error)


# ---------------------------------------------------------------------------
# offer_deep_research
# ---------------------------------------------------------------------------


class OfferDeepResearchTool(InProcessTool):
    """name="offer_deep_research" —— 升级信号工具 + 本轮熔断。"""

    name = "offer_deep_research"
    description = "提议把当前问题升级到深度研究子流程(信号工具,调用后本轮工具通道关闭)。"
    args_schema = OfferDeepResearchArgs

    async def run_with_state(
        self, args: BaseModel, state: ChatLoopState
    ) -> dict[str, Any]:
        args = OfferDeepResearchArgs.model_validate(args.model_dump())

        # 幂等:同 turn 第二次调用被拒(state 已被前一次置位)
        if state.escalate_offered:
            raise _fail(
                "[已提议过] 本轮已发出升级提议,等待用户确认,请直接收尾。"
            )

        # 置三个 state 字段:offered / reason / tool_choice 熔断(spec § 3.5)
        state.escalate_offered = True
        state.escalate_reason = args.reason
        state.tool_choice = "none"

        return {
            "escalation_proposed": True,
            "note": "升级提议已发出,本轮工具调用通道已关闭,请基于已有信息简要作答。",
        }


# ---------------------------------------------------------------------------
# read_cached_result
# ---------------------------------------------------------------------------


class ReadCachedResultTool(InProcessTool):
    """name="read_cached_result" —— 按缓存键取回降级/截断的完整原文(分页)。"""

    name = "read_cached_result"
    description = "按缓存键取回此前因降级/截断而压缩掉的完整工具结果(可逆,分页取回)。"
    args_schema = ReadCachedResultArgs

    def __init__(self, *, cache: Any) -> None:
        self._cache = cache

    async def run_with_state(
        self, args: BaseModel, state: ChatLoopState
    ) -> dict[str, Any]:
        args = ReadCachedResultArgs.model_validate(args.model_dump())

        # 跨用户防护:ref 必须以 user_id:: 命名空间开头(校验先于 cache 读取,
        # 不向越权请求泄露其它用户键的存在性)
        if not args.ref.startswith(f"{state.user_id}::"):
            raise _fail("[无权访问] ref 不属于当前用户。")

        raw = await self._cache.get_raw(args.ref)
        if raw is None:
            raise _fail(
                "[缓存不存在/已过期] 该 ref 无对应缓存,请直接重新调用原工具。"
            )

        offset = max(0, args.offset)
        # limit<=0 回退到默认值(_DEFAULT_LIMIT=2000);调用方无需特判,省略 limit 与传 0 等效。
        limit = args.limit if args.limit > 0 else _DEFAULT_LIMIT
        return {
            "ref": args.ref,
            "content": raw[offset : offset + limit],
            "total_len": len(raw),
            "offset": offset,
        }


__all__ = [
    "OfferDeepResearchArgs",
    "OfferDeepResearchTool",
    "ReadCachedResultArgs",
    "ReadCachedResultTool",
]

"""记忆双工具 in-process —— 六件套合并 + 注入分类器单入口收口(spec § 3.3)。

把 C.5 HierarchicalMemory 的六个方法合并成两个 in-process 工具:

    memory_search(query, scope: index|archival|recall|graph = archival, k=5)
        index    → memory_index_summary(MEMORY.md 等价 DB 投影,无正文)
        archival → archival_memory_search(语义检索)
        recall   → recall_memory_search(历史对话)
        graph    → archival_memory_traverse(实体关系遍历,query 当实体名)

    memory_write(action: core_append|core_replace|archival_insert, content,
                 block=None, old_content=None, evidence_quote=None)
        core_append   → core_memory_append(block 必填)
        core_replace  → core_memory_replace(block + old_content 必填)
        archival_insert → archival_memory_insert(evidence_quote 必填且逐字在本 turn user 消息中)

收口设计(spec § 3.3):
- 注入分类器只在 memory_write 一个入口(模型侧写流量收窄到一处);search 不过分类器;
- 条件必填 / evidence_quote 校验失败 → 返回 ToolResult-shape dict(success=False + 指导性
  错误),由 ToolHub 包成 tool 消息喂回,模型自纠重试(不抛异常)。

部署形态:in-process Tool(碰 harness 内部状态 —— memory 实例 / state.user_id /
state.messages,spec § 3.3 判据)。Phase 4 chat worker 构造时注入已持的
HierarchicalMemory 实例与 is_prompt_injection 分类器。

契约偏差(向 Phase 4 显式标注):
- HierarchicalMemory.archival_memory_insert 真实签名要 content: dict(rel_type/
  source_label/target_label/...)+ episode_id: UUID,而合并 schema 的 content 是自由
  文本、无 episode_id。本工具把自由文本 content 包成最小结构化 fact(User -[stated]->
  Note);episode_id 经构造注入的 episode_id_resolver(state) 取 —— Phase 4 worker 在
  首次 archival_insert 时惰性 write_episode 后,返回本 turn episode_id(ChatLoopState
  是冻结字段集,不便挂临时属性,故走 resolver 闭包而非 state 字段)。resolver 可异步；
  默认返回 None,此时 archival_insert 返回指导错误而非静默丢。
- user_id 在合并 schema 里不出现(对齐 MCP 三原语:应用该当背景喂的不进工具参数);
  从 state.user_id 取,run_with_state 时转 UUID。
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

from app.chatloop.inprocess import InProcessTool
from app.chatloop.state import ChatLoopState
from app.memory.injection_classifier import evidence_quote_in_episode
from app.tools.base import ToolError

# 分类器签名:text -> (is_injection, confidence, reason)。默认用规则层 is_prompt_injection。
InjectionClassifier = Callable[[str], tuple[bool, float, str]]
# episode_id 解析:Phase 4 worker 注入(write_episode 后绑定本 turn 的 episode_id)。
EpisodeIdResolver = Callable[[ChatLoopState], "UUID | None | Awaitable[UUID | None]"]

# archival_insert 自由文本 → 结构化 fact 的默认 importance(中档,contextual)。
_DEFAULT_IMPORTANCE = 0.5


# ---------------------------------------------------------------------------
# args schema
# ---------------------------------------------------------------------------


class MemorySearchArgs(BaseModel):
    query: str
    scope: Literal["index", "archival", "recall", "graph"] = "archival"
    k: int = 5


class MemoryWriteArgs(BaseModel):
    action: Literal["core_append", "core_replace", "archival_insert"]
    content: str
    block: Literal["persona", "scratchpad"] | None = None
    old_content: str | None = None
    evidence_quote: str | None = None


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _fail(error: str) -> ToolError:
    """构造指导性错误 —— raise 后 ToolHub 包成 ToolResult(success=False)喂回自纠。

    error 文案以 [标签] 开头(如 [参数缺失]/[已拦截]/[校验失败]),ToolHub._guidance_error
    对预格式化的 ToolError 原样透出(不再二次包 [执行失败]),保证文案逐字到模型。
    """
    return ToolError(error)


def _default_episode_resolver(state: ChatLoopState) -> UUID | None:
    """默认无 episode 绑定 —— Phase 4 worker 注入返回本 turn episode_id 的 resolver。"""
    return None


def _this_turn_user_text(state: ChatLoopState) -> str:
    """本 turn 全部 role==user 消息 content 拼接(含插话),供 evidence_quote 子串校验。

    注:ChatLoopState.messages 是本 turn 的窗口(turn 原子,不跨 turn),所以这里
    拼的就是"本 turn 的 user 消息";多条 user(原始问题 + 插话)按序用换行拼接。
    """
    parts: list[str] = []
    for m in state.messages:
        if m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, str):
                parts.append(c)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# memory_search
# ---------------------------------------------------------------------------


class MemorySearchTool(InProcessTool):
    """name="memory_search" —— scope 路由到 HierarchicalMemory 的三个检索方法。

    不过注入分类器(读流量,spec § 3.3 收口只在 write)。
    """

    name = "memory_search"
    description = (
        "检索用户个人记忆(scope: index 索引 / archival 语义 / recall 历史对话 / graph 实体关系)。"
    )
    args_schema = MemorySearchArgs

    def __init__(self, *, memory: Any) -> None:
        self._memory = memory

    async def run_with_state(self, args: BaseModel, state: ChatLoopState) -> dict[str, Any]:
        # 项目惯例(对齐 Tool.run):签名收 BaseModel,内部 narrow 回具体 args_schema。
        args = MemorySearchArgs.model_validate(args.model_dump())
        user_id = UUID(state.user_id)

        if args.scope == "index":
            hits = await self._memory.memory_index_summary(user_id=user_id)
        elif args.scope == "recall":
            hits = await self._memory.recall_memory_search(
                user_id=user_id, query=args.query, k=args.k
            )
        elif args.scope == "graph":
            # graph scope:query 当实体名(start_label),做关系遍历
            hits = await self._memory.archival_memory_traverse(
                user_id=user_id, start_label=args.query
            )
        else:  # archival(默认)
            hits = await self._memory.archival_memory_search(
                user_id=user_id, query=args.query, k=args.k
            )

        return {"scope": args.scope, "results": _to_serializable(hits)}


# ---------------------------------------------------------------------------
# memory_write
# ---------------------------------------------------------------------------


class MemoryWriteTool(InProcessTool):
    """name="memory_write" —— action 路由 + 条件必填 + evidence_quote 校验 + 分类器收口。

    模型侧写记忆的唯一入口;content 先过注入分类器(防护面从四个写入口收窄到一处)。
    """

    name = "memory_write"
    description = (
        "写入/更新用户记忆(action: core_append/core_replace/archival_insert,经注入分类器收口)。"
    )
    args_schema = MemoryWriteArgs

    def __init__(
        self,
        *,
        memory: Any,
        injection_classifier: InjectionClassifier,
        episode_id_resolver: EpisodeIdResolver = _default_episode_resolver,
    ) -> None:
        self._memory = memory
        self._classify = injection_classifier
        self._resolve_episode = episode_id_resolver

    async def run_with_state(self, args: BaseModel, state: ChatLoopState) -> dict[str, Any]:
        # 项目惯例(对齐 Tool.run):签名收 BaseModel,内部 narrow 回具体 args_schema。
        args = MemoryWriteArgs.model_validate(args.model_dump())
        # 0. 条件必填校验(fail loud 指导性错误,先于一切副作用)
        if err := self._check_required(args):
            raise _fail(err)

        # 1. 注入分类器单入口收口(只对 write 的 content,spec § 3.3)
        is_inj, conf, reason = self._classify(args.content)
        if is_inj:
            raise _fail(
                f"[已拦截] 写入内容疑似提示注入(命中 {reason},置信度 {conf:.2f}),已拒绝写入。"
            )

        user_id = UUID(state.user_id)

        # 2. action 路由
        if args.action == "core_append":
            block = await self._memory.core_memory_append(
                user_id=user_id, block_name=args.block, content=args.content
            )
            return {
                "action": "core_append",
                "block": args.block,
                "ok": True,
                "block_result": _to_serializable(block),
            }

        if args.action == "core_replace":
            block = await self._memory.core_memory_replace(
                user_id=user_id,
                block_name=args.block,
                old_content=args.old_content,
                new_content=args.content,
            )
            return {
                "action": "core_replace",
                "block": args.block,
                "ok": True,
                "block_result": _to_serializable(block),
            }

        # archival_insert
        return await self._do_archival_insert(args, state, user_id)

    # ------------------------------------------------------------------
    # 条件必填(指导性错误,自纠回路)
    # ------------------------------------------------------------------

    @staticmethod
    def _check_required(args: MemoryWriteArgs) -> str | None:
        """条件必填校验,返回指导性错误文案;通过返回 None。"""
        if args.action in ("core_append", "core_replace") and not args.block:
            return (
                f"[参数缺失] action={args.action} 必须提供 block(persona 或 scratchpad,"
                "指定写入哪个核心块)。"
            )
        if args.action == "core_replace" and not args.old_content:
            return (
                "[参数缺失] action=core_replace 必须提供 old_content(被替换的原文,逐字匹配)。"
                "提示:若想新增而非替换,改用 action=core_append。"
            )
        if args.action == "archival_insert" and not args.evidence_quote:
            return (
                "[参数缺失] action=archival_insert 必须提供 evidence_quote(写入依据的用户原话"
                "逐字片段,系统会逐字校验防编造)。"
            )
        return None

    # ------------------------------------------------------------------
    # archival_insert(evidence_quote 逐字校验 + 结构化 fact 包装)
    # ------------------------------------------------------------------

    async def _do_archival_insert(
        self, args: MemoryWriteArgs, state: ChatLoopState, user_id: UUID
    ) -> dict[str, Any]:
        # evidence_quote 逐字在本 turn user 消息(含插话)中 —— 复用 evidence_quote_in_episode
        # 的空白容忍子串校验(spec § 3.3,与 Plan 4 同一函数,口径一致)
        user_text = _this_turn_user_text(state)
        assert args.evidence_quote is not None  # _check_required 已保证
        if not evidence_quote_in_episode(args.evidence_quote, user_text):
            raise _fail(
                f"[校验失败] evidence_quote {args.evidence_quote!r} 未在本 turn 的用户原话中逐字"
                "找到(防编造)。请改用用户确实说过的原文片段,或先用 memory_search 确认。"
            )

        episode_id = self._resolve_episode(state)
        if inspect.isawaitable(episode_id):
            episode_id = await episode_id
        if episode_id is None:
            raise _fail(
                "[前置缺失] 当前 turn 尚未绑定 episode,archival_insert 暂不可用。"
                "提示:核心事实可改用 memory_write(action=core_append, block=...)。"
            )

        # 自由文本 → 最小结构化 fact(契约偏差见模块 docstring):User -[stated]-> Note
        content = {
            "rel_type": "stated",
            "source_entity_type": "User",
            "source_label": str(user_id),
            "target_entity_type": "Note",
            "target_label": args.content,
            "valid_from": datetime.now(UTC),
            "valid_to": None,
        }
        edge = await self._memory.archival_memory_insert(
            user_id=user_id,
            content=content,
            reasoning=f"agent memory_write: {args.content}",
            importance=_DEFAULT_IMPORTANCE,
            evidence_quote=args.evidence_quote,
            episode_id=episode_id,
        )
        return {"action": "archival_insert", "ok": True, "edge": _to_serializable(edge)}


# ---------------------------------------------------------------------------
# 序列化辅助 —— memory 方法返回 ORM 行/dict/None,统一压成可 JSON 序列化形态
# ---------------------------------------------------------------------------


def _to_serializable(obj: Any) -> Any:
    """把 memory 返回值压成 JSON-safe(进 tool 消息)。

    - None / 基本类型 / dict / list 原样(list/dict 递归);
    - ORM 行等带不可序列化属性的对象 → str(obj)(digest 已够 loop 用,细节不进窗口)。
    """
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _to_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_serializable(v) for v in obj]
    return str(obj)


__all__ = [
    "MemorySearchArgs",
    "MemorySearchTool",
    "MemoryWriteArgs",
    "MemoryWriteTool",
    "InjectionClassifier",
    "EpisodeIdResolver",
]

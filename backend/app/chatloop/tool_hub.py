"""ToolHub — 统一工具分发层(spec § 3.1)。

双后端:MCP 工具经既有 ToolRegistry;in-process 工具(记忆/技能/控制类,
Phase 3 后续任务注册)直接持 Tool 实例。对 loop 暴露统一的 dispatch:
gather 并行 + 缓存 + 指导性错误包装 + 台账记账 + tool_start/end 事件。

硬契约(loop 依赖):
- dispatch 绝不抛异常 —— 任何内部异常(含 BaseException 子类如 RuntimeError)
  都包成 ToolResult(success=False) 返回;loop._merge_results 依赖此契约;
- 返回的 results 与收到的 calls 严格等长且按序(loop._merge_results 用 iter 消费)。
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import ValidationError

from app.agents.schemas import ToolResult
from app.chatloop.events import EventType, LoopEvent, SeqCounter
from app.chatloop.inprocess import InProcessTool
from app.chatloop.state import ChatLoopState
from app.chatloop.tool_docs import (
    CORE_TOOLS,
    DEFERRED_TOOLS,
    TOOL_DOCS,
    search_docs,
    thin_schema,
)
from app.services.llm_step import StepToolCall
from app.services.tool_result_cache import CacheHit, ToolResultCache
from app.tools.base import Tool, ToolError

logger = logging.getLogger(__name__)

EmitFn = Callable[[LoopEvent], Awaitable[None]]

# digest / 错误文案截断长度(spec § 3.1)
_DIGEST_LEN = 120  # tool_end 事件里的 digest 长度
_LEDGER_DIGEST_LEN = 200  # 台账 digest 上限(LedgerEntry 自身也截 200,双保险)
_ERR_MSG_LEN = 200

# search_tools 内置工具名(殿后第 15 个,spec § 3.2)
SEARCH_TOOLS_NAME = "search_tools"
_SEARCH_TOOLS_K = 3  # search_docs top-k


class ToolHub:
    """统一工具分发层 —— 双后端(in-process Tool + MCP via ToolRegistry)。

    工具表 dict[str, Tool] 保持注册顺序(Python 3.7+ dict 有序);注册顺序
    即 schemas_for_llm 顺序(位置偏置:高频工具在前)。渐进披露三组在 Task 3.2
    叠加,本任务先全量全 schema。
    """

    def __init__(
        self,
        *,
        emit: EmitFn | None = None,
        cache: ToolResultCache | None = None,
        seq_counter: SeqCounter | None = None,
    ) -> None:
        self._tools: dict[str, Tool] = {}
        self._emit_fn = emit
        self._cache = cache
        self._seq_counter = seq_counter if seq_counter is not None else SeqCounter()

    # ------------------------------------------------------------------
    # 注册
    # ------------------------------------------------------------------

    def register_inprocess(self, tools: list[Tool]) -> None:
        """注册 in-process 工具实例(记忆/技能/控制类)。重名 fail loud。"""
        for tool in tools:
            if tool.name in self._tools:
                raise ValueError(f"duplicate tool name: {tool.name}")
            self._tools[tool.name] = tool

    def register_registry(self, registry: Any) -> None:
        """把 registry 当前的全部工具并入(MCP 工具路径)。

        registry 暴露 list_for_llm()(取 schema/顺序)与 get(name)(取 Tool 实例)。
        重名 fail loud,避免静默覆盖。
        """
        for schema in registry.list_for_llm():
            name = schema["function"]["name"]
            if name in self._tools:
                raise ValueError(f"duplicate tool name: {name}")
            self._tools[name] = registry.get(name)

    # ------------------------------------------------------------------
    # schema
    # ------------------------------------------------------------------

    def schemas_for_llm(self) -> list[dict[str, Any]]:
        """OpenAI function 格式,按渐进披露三组产出(spec § 3.2)。

        顺序(位置偏置):CORE_TOOLS 序在前(完整 schema)→ DEFERRED_TOOLS 序
        (瘦条目)→ 未在 TOOL_DOCS 的注册工具(完整 schema + warning,fail-safe)
        → search_tools 殿后第 15 个。

        仅产出"已注册"的工具:CORE/DEFERRED 列表里未注册的名字跳过(注册由
        Phase 3 后续任务分批接通,本任务允许部分注册)。
        """
        out: list[dict[str, Any]] = []
        emitted: set[str] = set()

        # 1. 核心组:已注册的按 CORE_TOOLS 序给完整 schema(description 换 brief)
        for name in CORE_TOOLS:
            tool = self._tools.get(name)
            if tool is None:
                continue
            out.append(self._core_schema(tool))
            emitted.add(name)

        # 2. 延迟组:已注册的按 DEFERRED_TOOLS 序给瘦条目
        for name in DEFERRED_TOOLS:
            if name not in self._tools:
                continue
            out.append(thin_schema(TOOL_DOCS[name]))
            emitted.add(name)

        # 3. fail-safe:注册了但不在 TOOL_DOCS / 不在两组里的工具 → 完整 schema + warning
        for name, tool in self._tools.items():
            if name in emitted or name == SEARCH_TOOLS_NAME:
                continue
            logger.warning(
                "ToolHub.schemas_for_llm: 工具 %r 未在 TOOL_DOCS 分组里,"
                "回退为完整 schema(请补 tool_docs 条目)",
                name,
            )
            out.append(tool.schema_for_llm())

        # 4. search_tools 殿后
        out.append(self._search_tools_schema())
        return out

    @staticmethod
    def _core_schema(tool: Tool) -> dict[str, Any]:
        """核心组完整 schema:保留工具自身的参数,description 换成 ToolDoc.brief。"""
        schema = tool.schema_for_llm()
        doc = TOOL_DOCS.get(tool.name)
        if doc is not None:
            schema["function"]["description"] = doc.brief
        return schema

    @staticmethod
    def _search_tools_schema() -> dict[str, Any]:
        """内置 search_tools 的 schema(query string required)。"""
        return {
            "type": "function",
            "function": {
                "name": SEARCH_TOOLS_NAME,
                "description": (
                    "检索某个工具的完整使用文档(参数 schema/硬约束/示例/何时用)。"
                    "裸调延迟工具参数报错时,先用本工具拿到目标工具的参数文档。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "工具名或自然语言描述(如 'compare_stocks' / '对比多只股票')",
                        }
                    },
                    "required": ["query"],
                },
            },
        }

    # ------------------------------------------------------------------
    # 事件
    # ------------------------------------------------------------------

    async def _emit(self, type_: EventType, step: int, /, **data: Any) -> None:
        """构造 LoopEvent(带自增 seq 与当前 step)并发射;emit 为 None 时静默。

        seq 由注入的 SeqCounter 产生;loop 与 hub 共享同一个实例时(Phase 4
        chat_runner 负责注入),全局事件序号严格单调递增,前端按 last_seq 排序。
        """
        seq = self._seq_counter.next()
        if self._emit_fn is None:
            return
        await self._emit_fn(LoopEvent(type=type_, seq=seq, step=step, data=data))

    # ------------------------------------------------------------------
    # dispatch
    # ------------------------------------------------------------------

    async def dispatch(
        self, calls: list[StepToolCall], state: ChatLoopState
    ) -> list[ToolResult]:
        """并行分发 calls,返回与之等长按序的 ToolResult 列表。

        每个 call 走 _dispatch_one(自身全包不抛);外层 gather 不需要
        return_exceptions=True,但仍断言等长(fail loud 守护契约)。
        """
        results: list[ToolResult] = list(
            await asyncio.gather(*(self._dispatch_one(call, state) for call in calls))
        )
        assert len(results) == len(calls), (
            f"ToolHub.dispatch: results({len(results)}) 与 calls({len(calls)}) 长度不匹配"
        )
        return results

    async def _dispatch_one(
        self, call: StepToolCall, state: ChatLoopState
    ) -> ToolResult:
        """单 call 协程 —— 全包不抛,任何路径都返回 ToolResult。

        外层 try 是双保险:理论上下面每条分支都自产 ToolResult,但若有未预料的
        异常(如 emit 回调自身抛),也兜成 success=False,绝不向 dispatch/loop 冒泡。
        """
        try:
            return await self._dispatch_one_inner(call, state)
        except BaseException as e:  # noqa: BLE001 — hub 不抛硬契约:双保险兜底
            # 尽力记账(用工具名),但记账失败也不能抛
            args = self._safe_parsed_args(call)
            error = f"[执行失败] {type(e).__name__}: {str(e)[:_ERR_MSG_LEN]}"
            self._safe_record(state, call.name, args, error, success=False, cache_key=None)
            return self._fail_result(call.name, args, error)

    async def _dispatch_one_inner(
        self, call: StepToolCall, state: ChatLoopState
    ) -> ToolResult:
        name = call.name

        # 1. parsed_args:坏 JSON → 指导性错误(工具名仍记账)
        try:
            args = call.parsed_args
        except ValueError:
            error = "[参数格式错误] arguments 不是合法 JSON。请检查后重试。"
            await self._emit_error(call.name, error, step=state.step)
            self._safe_record(state, name, {}, error, success=False, cache_key=None)
            return self._fail_result(name, {}, error)

        # 2a. search_tools 内置工具:不走 Tool 实例,直接检索文档
        if name == SEARCH_TOOLS_NAME:
            return await self._dispatch_search_tools(args, state)

        # 2. 工具不存在 → 指导性错误
        tool = self._tools.get(name)
        if tool is None:
            error = (
                f"[未知工具] {name} 不存在。可用工具见列表;"
                "若需参数细节可调 search_tools。"
            )
            await self._emit_error(name, error, step=state.step)
            self._safe_record(state, name, args, error, success=False, cache_key=None)
            return self._fail_result(name, args, error)

        # 3. ledger 去重:同 (tool, args) 本 turn 已成功过 → 不重跑。
        #    InProcessTool(记忆写入/控制/技能类)是状态变更工具,同参二次调用不代表
        #    "已有结果可复用"——memory_write 重复写入是业务意图,offer_deep_research
        #    重复触发需真执行以确保 escalate_offered 置位。台账去重短路仅对 registry
        #    后端的只读 MCP 数据工具生效;InProcessTool 的幂等由工具自身管理。
        is_inprocess = isinstance(tool, InProcessTool)
        if not is_inprocess:
            hit = state.ledger.find_success(tool_name=name, args=args)
            if hit is not None:
                output = {
                    "cached_digest": hit.digest,
                    "note": "本轮已查过,结果同前(完整内容见 ref)",
                    "ref": hit.cache_key,
                }
                await self._emit("tool_end", state.step, tool=name, digest=hit.digest, cached=True)
                # 去重命中也记一条台账(success,带原 cache_key),保持轨迹完整
                self._safe_record(
                    state, name, args, hit.digest, success=True, cache_key=hit.cache_key
                )
                return ToolResult(
                    tool_name=name,
                    args=args,
                    success=True,
                    output=output,
                    latency_ms=0,
                )

        # 4. tool_call(完整 args,spec § 5.1)+ tool_start
        await self._emit("tool_call", state.step, tool=name, args=args)
        await self._emit("tool_start", state.step, tool=name)

        # 5. 执行:
        #    - InProcessTool(记忆/技能/控制类)是状态变更或本地廉价操作,完全绕过
        #      cache——同参缓存命中会导致 run_with_state 被跳过:
        #        * offer_deep_research: escalate_offered 不置位 → 升级静默失败
        #        * memory_write: 写入静默丢失
        #        * load_skill: active_skill 不置位
        #      cache_key=None(无缓存键),直接 run_with_state。
        #    - MCP 只读数据工具(registry 后端)才吃 TTL 缓存(cache 注入则包一层
        #      get_or_compute),cache_key 按 (user_id, tool_name, args) 生成。
        started = time.perf_counter()
        cache_key: str | None = None

        async def _compute() -> dict[str, Any]:
            validated = tool.args_schema.model_validate(args)
            # InProcessTool(记忆/控制类,spec § 3.3)需要 turn 级 state(user_id /
            # messages / ledger);其余 Tool 走纯 run(args)。唯一一处 isinstance 分支。
            if isinstance(tool, InProcessTool):
                return await tool.run_with_state(validated, state)
            return await tool.run(validated)

        is_cache_hit = False
        try:
            if self._cache is not None and not is_inprocess:
                # 只读 MCP 数据工具走缓存
                cache_key = ToolResultCache.cache_key(state.user_id, name, args)
                output, cache_status = await self._cache.get_or_compute(
                    user_id=state.user_id,
                    tool_name=name,
                    args=args,
                    compute_fn=_compute,
                )
                is_cache_hit = cache_status == CacheHit.HIT
            else:
                # InProcessTool 或无 cache 注入:直接执行,cache_key 保持 None
                output = await _compute()
        except BaseException as e:  # noqa: BLE001 — hub 不抛:全包成指导性错误
            error = self._guidance_error(tool, e)
            error = self._maybe_append_search_hint(name, e, error)
            await self._emit_error(name, error, step=state.step)
            self._safe_record(
                state, name, args, error, success=False, cache_key=cache_key
            )
            return self._fail_result(name, args, error)

        latency_ms = int((time.perf_counter() - started) * 1000)
        digest = self._digest(output)

        # 6. tool_end
        await self._emit("tool_end", state.step, tool=name, digest=digest, cached=is_cache_hit)

        # 7. 记账(post-apply_step 契约:step=state.step)
        self._safe_record(
            state, name, args, digest, success=True, cache_key=cache_key
        )

        return ToolResult(
            tool_name=name,
            args=args,
            success=True,
            output=output,
            latency_ms=latency_ms,
            cached=is_cache_hit,
        )

    # ------------------------------------------------------------------
    # search_tools 内置工具(渐进披露,spec § 3.2)
    # ------------------------------------------------------------------

    async def _dispatch_search_tools(
        self, args: dict[str, Any], state: ChatLoopState
    ) -> ToolResult:
        """检索目标工具文档,top-k 拼成 {"docs": [{name, doc}...]} 返回。

        - query 缺失/非字符串 → 指导性错误(仍记账);
        - 命中工具名进 ledger.searched_docs(记账);
        - 同 turn 重复检索同一工具 → 文档文本前加 "(本 turn 已检索过)" 仍返回。
        本身不进 cache、不计预算、不做去重(检索是确定性纯函数,可重复调)。
        """
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            error = (
                "[参数校验失败] search_tools 需要 query(string)。"
                "请传工具名或自然语言描述。"
            )
            await self._emit_error(SEARCH_TOOLS_NAME, error, step=state.step)
            self._safe_record(
                state, SEARCH_TOOLS_NAME, args, error, success=False, cache_key=None
            )
            return self._fail_result(SEARCH_TOOLS_NAME, args, error)

        await self._emit("tool_call", state.step, tool=SEARCH_TOOLS_NAME, args=args)
        await self._emit("tool_start", state.step, tool=SEARCH_TOOLS_NAME)

        hits = search_docs(query, k=_SEARCH_TOOLS_K)
        docs: list[dict[str, str]] = []
        for d in hits:
            already = d.name in state.ledger.searched_docs
            text = d.doc
            if already:
                text = f"(本 turn 已检索过)\n{text}"
            docs.append({"name": d.name, "doc": text})
            state.ledger.searched_docs.add(d.name)

        output = {"docs": docs}
        digest = self._digest(output)
        await self._emit(
            "tool_end", state.step, tool=SEARCH_TOOLS_NAME, digest=digest, cached=False
        )
        self._safe_record(
            state, SEARCH_TOOLS_NAME, args, digest, success=True, cache_key=None
        )
        return ToolResult(
            tool_name=SEARCH_TOOLS_NAME,
            args=args,
            success=True,
            output=output,
            latency_ms=0,
        )

    @staticmethod
    def _maybe_append_search_hint(name: str, exc: BaseException, error: str) -> str:
        """裸调延迟工具参数错(ValidationError)→ 追加 search_tools 指引(spec § 3.2)。"""
        if (
            isinstance(exc, ValidationError)
            and name in TOOL_DOCS
            and TOOL_DOCS[name].group == "deferred"
        ):
            return f"{error}。可调 search_tools('{name}') 获取参数文档"
        return error

    # ------------------------------------------------------------------
    # 指导性错误文案(spec § 1.4 错误自纠)
    # ------------------------------------------------------------------

    @staticmethod
    def _guidance_error(tool: Tool, exc: BaseException) -> str:
        """把执行期异常映射成指导性错误文案。

        - 预格式化 ToolError(msg 以 "[" 开头,如 in-process 工具的 [参数缺失]/
          [已拦截])→ 原样透出(不二次包 [执行失败],保证指导文案逐字到模型);
          未以 '[' 开头的 ToolError 仍走 [执行失败] 包装(设计决定:强制指导性文案带标签前缀)。
        - ValidationError → "[参数校验失败] {简述}。参数要求:{字段名列表}"
        - Timeout → "[超时] 稍后重试或换数据源"
        - 其它 → "[执行失败] {type}: {msg 截 200}"
        """
        if isinstance(exc, ToolError):
            msg = str(exc)
            if msg.startswith("["):
                return msg[:_ERR_MSG_LEN]
        if isinstance(exc, ValidationError):
            fields = ", ".join(tool.args_schema.model_fields.keys())
            brief = str(exc).splitlines()[0][:_ERR_MSG_LEN]
            return f"[参数校验失败] {brief}。参数要求:{fields}"
        if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
            return "[超时] 稍后重试或换数据源"
        return f"[执行失败] {type(exc).__name__}: {str(exc)[:_ERR_MSG_LEN]}"

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    async def _emit_error(self, tool: str, error: str, *, step: int) -> None:
        """失败路径统一发 tool_error(带 error + 可选 hint)。"""
        await self._emit("tool_error", step, tool=tool, error=error, hint=error)

    @staticmethod
    def _digest(output: Any) -> str:
        """输出序列化前 120 字作为 digest。"""
        try:
            serialized = json.dumps(output, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            serialized = str(output)
        return serialized[:_DIGEST_LEN]

    @staticmethod
    def _safe_parsed_args(call: StepToolCall) -> dict[str, Any]:
        try:
            return call.parsed_args
        except ValueError:
            return {}

    @staticmethod
    def _safe_record(
        state: ChatLoopState,
        tool_name: str,
        args: dict[str, Any],
        digest: str,
        *,
        success: bool,
        cache_key: str | None,
    ) -> None:
        """记账 —— 失败也不抛(hub 不抛硬契约)。

        post-apply_step 契约:step=state.step(第 N 圈调用记 step=N,见 gates.py)。
        """
        # 记账失败不能破坏 dispatch 契约(hub 不抛)
        with contextlib.suppress(Exception):
            state.ledger.record(
                step=state.step,
                tool_name=tool_name,
                args=args,
                digest=digest[:_LEDGER_DIGEST_LEN],
                success=success,
                cache_key=cache_key,
            )

    @staticmethod
    def _fail_result(
        tool_name: str, args: dict[str, Any], error: str
    ) -> ToolResult:
        return ToolResult(
            tool_name=tool_name,
            args=args,
            success=False,
            output=None,
            error=error,
            latency_ms=0,
        )


__all__ = ["SEARCH_TOOLS_NAME", "EmitFn", "ToolHub"]

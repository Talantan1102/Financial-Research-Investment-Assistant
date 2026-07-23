"""ToolHub — 统一工具分发层(spec § 3.1)。

双后端:MCP 工具经既有 ToolRegistry;in-process 工具(记忆/技能/控制类,
Phase 3 后续任务注册)直接持 Tool 实例。对 loop 暴露统一的 dispatch:
gather 并行 + 缓存 + 指导性错误包装 + 台账记账 + tool_start/end 事件。

硬契约(loop 依赖):
- dispatch 对普通执行异常绝不抛 —— 都包成 ToolResult(success=False) 返回;
  asyncio.CancelledError 是请求控制流,必须原样传播给 loop/chat_runner;
- 返回的 results 与收到的 calls 严格等长且按序(loop._merge_results 用 iter 消费)。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from app.agents.schemas import ToolResult
from app.chatloop.events import EventType, LoopEvent, SeqCounter
from app.chatloop.state import ChatLoopState
from app.chatloop.tool_docs import (
    CORE_TOOLS,
    DEFERRED_TOOLS,
    TOOL_DOCS,
    search_docs,
    thin_schema,
)
from app.chatloop.tool_runtime_adapter import ChatloopToolAdapter
from app.chatloop.tool_runtime_policy import ToolRiskPolicy
from app.runtime.events import RuntimeEvent
from app.runtime.hooks import HookPipeline
from app.runtime.models import (
    CapabilityDefinition,
    CapabilityType,
    ErrorCategory,
    ExecutionContext,
    ExecutionStatus,
    RiskLevel,
    RuntimeErrorInfo,
    RuntimeResult,
)
from app.runtime.permissions import AuthorizationCallback, PermissionEngine
from app.runtime.registry import CapabilityRegistry
from app.runtime.safe_executor import SafeExecutor
from app.runtime.scheduler import TaskScheduler
from app.runtime.tasks import Task, TaskBuilder
from app.runtime.tool_runtime import ToolRuntime
from app.services.llm_step import StepToolCall
from app.services.tool_result_cache import ToolResultCache
from app.services.trace_models import Span
from app.tools.base import Tool, ToolError

logger = logging.getLogger(__name__)

EmitFn = Callable[[LoopEvent], Awaitable[None]]
VisibilityResolver = Callable[[ChatLoopState], frozenset[str]]

# digest / 错误文案截断长度(spec § 3.1)
_DIGEST_LEN = 120  # tool_end 事件里的 digest 长度
_LEDGER_DIGEST_LEN = 200  # 台账 digest 上限(LedgerEntry 自身也截 200,双保险)
_ERR_MSG_LEN = 200

# search_tools 内置工具名(殿后第 15 个,spec § 3.2)
SEARCH_TOOLS_NAME = "search_tools"
_SEARCH_TOOLS_K = 3  # search_docs top-k

# 所有工具统一执行超时;超时落进指导性错误的 [超时] 映射。
DEFAULT_TOOL_TIMEOUT_S = 30.0


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
        progressive: bool = True,
        tool_timeout_s: float = DEFAULT_TOOL_TIMEOUT_S,
        max_output_bytes: int = 1_048_576,
        hooks: HookPipeline | None = None,
        authorization_callback: AuthorizationCallback | None = None,
        visibility_resolver: VisibilityResolver | None = None,
        max_concurrency: int = 8,
        trace: Any = None,  # TraceService | None —— 写工具 span(可观测性);None 则不写
    ) -> None:
        self._tools: dict[str, Tool] = {}
        self._emit_fn = emit
        self._cache = cache
        self._seq_counter = seq_counter if seq_counter is not None else SeqCounter()
        self._progressive = progressive
        self._tool_timeout_s = tool_timeout_s
        self._max_output_bytes = max_output_bytes
        self._hooks = hooks or HookPipeline()
        self._risk_policy = ToolRiskPolicy(authorization_callback)
        self._visibility_resolver = visibility_resolver
        self._max_concurrency = max_concurrency
        self._trace = trace

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

    def register_subset(self, registry: Any, names: list[str]) -> None:
        """只注册 registry 中指定名字的工具(子循环只读子集用)。重名 fail loud。

        registry 须暴露 list_for_llm()(取可用名)与 get(name)(取 Tool 实例)。
        不在 registry 中的名字静默跳过(白名单与实际可用工具求交集)。
        """
        available = {s["function"]["name"] for s in registry.list_for_llm()}
        for name in names:
            if name not in available:
                continue
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
        # 子循环用 flat 模式:全部已注册工具出完整 schema,无渐进披露/无 search_tools。
        if not self._progressive:
            return [self._tools[name].schema_for_llm() for name in self._tools]
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

    async def dispatch(self, calls: list[StepToolCall], state: ChatLoopState) -> list[ToolResult]:
        """Build and schedule a request-local DAG, preserving provider call order."""
        if not calls:
            return []

        # A malformed provider call becomes one isolated scheduler task. Other
        # tasks still retain concurrency-group and dependency semantics.
        normalized_calls: list[StepToolCall] = []
        malformed_calls: dict[str, StepToolCall] = {}
        for call in calls:
            try:
                _ = call.parsed_args
                normalized_calls.append(call)
            except ValueError:
                malformed_calls[call.id] = call
                normalized_calls.append(StepToolCall(id=call.id, name=call.name, arguments="{}"))

        definitions = {
            name: self._risk_policy.definition_for(tool, timeout_s=self._tool_timeout_s)
            for name, tool in self._tools.items()
        }
        for call in calls:
            definitions.setdefault(
                call.name,
                CapabilityDefinition(
                    name=call.name,
                    type=CapabilityType.DATA_TOOL,
                    input_schema={"type": "object"},
                    output_schema={"type": "object"},
                    minimum_risk=RiskLevel.LOW,
                    read_only=True,
                    idempotent=True,
                    default_timeout_s=self._tool_timeout_s,
                    max_attempts=1,
                ),
            )
        definitions.setdefault(
            SEARCH_TOOLS_NAME,
            CapabilityDefinition(
                name=SEARCH_TOOLS_NAME,
                type=CapabilityType.DATA_TOOL,
                input_schema=self._search_tools_schema()["function"]["parameters"],
                output_schema={"type": "object"},
                minimum_risk=RiskLevel.LOW,
                read_only=True,
                idempotent=True,
                default_timeout_s=self._tool_timeout_s,
                max_attempts=1,
            ),
        )
        try:
            graph = TaskBuilder(definitions).build(normalized_calls)
        except ValueError as exc:
            return await self._graph_build_failures(calls, state, str(exc))

        legacy_results: dict[str, ToolResult] = {}

        async def execute(task: Task, inputs: dict[str, Any], attempt: int) -> RuntimeResult:
            del attempt
            call = malformed_calls.get(task.id) or StepToolCall(
                id=task.id, name=task.capability, arguments=json.dumps(inputs, ensure_ascii=False)
            )
            legacy = await self._dispatch_one(call, state, defer_failures=True)
            legacy_results[task.id] = legacy
            if legacy.success:
                return RuntimeResult(
                    status=ExecutionStatus.SUCCEEDED,
                    output=legacy.output,
                    latency_ms=legacy.latency_ms,
                    audit={"cached": legacy.cached},
                    effective_input=legacy.args,
                )
            category = self._legacy_error_category(legacy.error)
            return RuntimeResult(
                status=ExecutionStatus.FAILED,
                error=RuntimeErrorInfo(
                    code="legacy_tool_failed",
                    category=category,
                    message=legacy.error or "tool execution failed",
                    retryable=category in {ErrorCategory.TIMEOUT, ErrorCategory.TRANSIENT},
                ),
                latency_ms=legacy.latency_ms,
                effective_input=legacy.args,
            )

        async def emit_runtime(_event: RuntimeEvent) -> None:
            # ToolHub's existing tool_call/start/end/error events remain the
            # public stream vocabulary. Runtime task events are internal here.
            return None

        try:
            scheduled = await TaskScheduler(definitions, max_concurrency=self._max_concurrency).run(
                graph, execute, emit_runtime
            )
        except ValueError as exc:
            return await self._graph_build_failures(calls, state, str(exc))

        results: list[ToolResult] = []
        for task in graph.tasks:
            legacy = legacy_results.get(task.id)
            if legacy is not None:
                if not legacy.success:
                    await self._finalize_deferred_failure(
                        legacy,
                        state,
                        definitions[task.capability],
                        self._tools.get(task.capability),
                    )
                results.append(legacy)
                continue
            runtime_result = scheduled[task.id]
            error = self._scheduled_guidance_error(runtime_result)
            args = dict(runtime_result.effective_input or task.inputs)
            await self._emit_error(task.capability, error, step=state.step)
            self._safe_record(state, task.capability, args, error, success=False, cache_key=None)
            results.append(self._fail_result(task.capability, args, error))
        assert len(results) == len(calls), (
            f"ToolHub.dispatch: results({len(results)}) 与 calls({len(calls)}) 长度不匹配"
        )
        return results

    async def _finalize_deferred_failure(
        self,
        result: ToolResult,
        state: ChatLoopState,
        definition: CapabilityDefinition,
        tool: Tool | None,
    ) -> None:
        error = result.error or "[执行失败] 工具执行失败"
        permission_source = (result.tool_call_data or {}).get("permission_source")
        if tool is not None and self._risk_policy.should_emit_permission_required(
            tool, permission_source
        ):
            await self._emit(
                "permission_required",
                state.step,
                tool=result.tool_name,
                risk=definition.minimum_risk.value,
            )
        await self._emit_error(result.tool_name, error, step=state.step)
        self._safe_record(
            state,
            result.tool_name,
            result.args,
            error,
            success=False,
            cache_key=None,
        )
        self._write_tool_span(state, result, datetime.now(UTC))

    async def _graph_build_failures(
        self, calls: list[StepToolCall], state: ChatLoopState, detail: str
    ) -> list[ToolResult]:
        error = f"[任务依赖无效] {detail[:_ERR_MSG_LEN]}"
        results: list[ToolResult] = []
        for call in calls:
            args = self._safe_parsed_args(call)
            await self._emit_error(call.name, error, step=state.step)
            self._safe_record(state, call.name, args, error, success=False, cache_key=None)
            results.append(self._fail_result(call.name, args, error))
        return results

    @staticmethod
    def _legacy_error_category(error: str | None) -> ErrorCategory:
        if error is None:
            return ErrorCategory.EXECUTION_ERROR
        if error.startswith("[超时]"):
            return ErrorCategory.TIMEOUT
        if error.startswith(("[需要授权]", "[不可见工具]")):
            return ErrorCategory.PERMISSION_DENIED
        if error.startswith(("[参数", "[任务依赖")):
            return ErrorCategory.VALIDATION_ERROR
        if any(marker in error.lower() for marker in ("503", "429", "temporary", "transient")):
            return ErrorCategory.TRANSIENT
        return ErrorCategory.EXECUTION_ERROR

    @staticmethod
    def _scheduled_guidance_error(result: RuntimeResult) -> str:
        if result.error is None:
            return "[执行失败] 任务调度失败"
        if result.error.category is ErrorCategory.DEPENDENCY_FAILED:
            return f"[依赖失败] {result.error.message}"
        if result.error.category is ErrorCategory.CANCELLED:
            return "[已取消] 任务未执行"
        return f"[执行失败] {result.error.message[:_ERR_MSG_LEN]}"

    async def _dispatch_one(
        self,
        call: StepToolCall,
        state: ChatLoopState,
        *,
        defer_failures: bool = False,
    ) -> ToolResult:
        """单 call 协程 —— 普通异常全包,取消信号原样传播。

        外层 try 是双保险:理论上下面每条分支都自产 ToolResult,但若有未预料的
        异常(如 emit 回调自身抛),也兜成 success=False。CancelledError 除外。

        dispatch 后写一条工具 span(覆盖所有返回路径:坏 JSON / 未知工具 / 缓存命中 /
        成功 / 失败 / search_tools),span 写入非致命。
        """
        started_at = datetime.now(UTC)
        try:
            result = await self._dispatch_one_inner(call, state, defer_failures=defer_failures)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — hub 不抛硬契约:双保险兜底
            # 尽力记账(用工具名),但记账失败也不能抛
            args = self._safe_parsed_args(call)
            error = f"[执行失败] {type(e).__name__}: {str(e)[:_ERR_MSG_LEN]}"
            if not defer_failures:
                self._safe_record(state, call.name, args, error, success=False, cache_key=None)
            result = self._fail_result(call.name, args, error)
        if result.success or not defer_failures:
            self._write_tool_span(state, result, started_at)
        return result

    def _write_tool_span(
        self, state: ChatLoopState, result: ToolResult, started_at: datetime
    ) -> None:
        """每次工具调用写一条 span(同 request_id)。trace=None 不写;写失败非致命。

        隐私:inputs 只放参数 key 名、outputs 留空 —— 不落工具结果/参数值原文。
        """
        if self._trace is None:
            return
        try:
            span = Span(
                span_id=f"{state.request_id}-tool-{uuid4().hex[:8]}",
                request_id=state.request_id,
                parent_id=None,
                name=f"tool:{result.tool_name}",
                inputs={"arg_keys": sorted(result.args.keys())},
                outputs={},
                metadata={
                    "kind": "tool",
                    "tool_name": result.tool_name,
                    "latency_ms": int(result.latency_ms),
                    "cached": bool(result.cached),
                    "success": bool(result.success),
                    "step": state.step,
                },
                started_at=started_at,
                ended_at=datetime.now(UTC),
                error=None if result.success else result.error,
            )
            self._trace.write_span(span)
        except Exception:  # noqa: BLE001 — 观测写入非致命,绝不打断工具调用
            logger.warning("tool span write failed (non-fatal)", exc_info=True)

    async def _dispatch_one_inner(
        self,
        call: StepToolCall,
        state: ChatLoopState,
        *,
        defer_failures: bool,
    ) -> ToolResult:
        name = call.name

        # 1. parsed_args:坏 JSON → 指导性错误(工具名仍记账)
        try:
            args = call.parsed_args
        except ValueError:
            error = "[参数格式错误] arguments 不是合法 JSON。请检查后重试。"
            if not defer_failures:
                await self._emit_error(call.name, error, step=state.step)
                self._safe_record(state, name, {}, error, success=False, cache_key=None)
            return self._fail_result(name, {}, error)

        # 2a. search_tools 内置工具:不走 Tool 实例,直接检索文档
        if name == SEARCH_TOOLS_NAME:
            return await self._dispatch_search_tools(
                call.id, args, state, defer_failures=defer_failures
            )

        # 2. 工具不存在 → 指导性错误
        tool = self._tools.get(name)
        if tool is None:
            error = f"[未知工具] {name} 不存在。可用工具见列表;若需参数细节可调 search_tools。"
            if not defer_failures:
                await self._emit_error(name, error, step=state.step)
                self._safe_record(state, name, args, error, success=False, cache_key=None)
            return self._fail_result(name, args, error)

        # 3. InProcessTool 不参与 ledger/cache 去重。普通工具的 ledger 去重
        #    位于 runtime adapter 内部，确保 visibility/hooks/permission/input
        #    validation 每次都先执行，缓存命中绝不能成为安全链旁路。

        # 4. tool_call(完整 args,spec § 5.1)+ tool_start
        await self._emit("tool_call", state.step, tool=name, args=args)
        await self._emit("tool_start", state.step, tool=name)

        # 5. 执行:
        #    - InProcessTool(记忆/技能/控制类)是状态变更或本地操作,完全绕过
        #      cache——同参缓存命中会导致 run_with_state 被跳过:
        #        * offer_deep_research: escalate_offered 不置位 → 升级静默失败
        #        * memory_write: 写入静默丢失
        #        * load_skill: active_skill 不置位
        #      cache_key=None(无缓存键),run_with_state 仍受统一安全执行器约束。
        #    - MCP 只读数据工具(registry 后端)才吃 TTL 缓存(cache 注入则包一层
        #      get_or_compute),cache_key 按 (user_id, tool_name, args) 生成。
        adapter = ChatloopToolAdapter(tool=tool, state=state, cache=self._cache)
        definition = self._risk_policy.definition_for(tool, timeout_s=self._tool_timeout_s)
        registry = CapabilityRegistry()
        registry.register(definition, adapter)
        visible = self._visible_for(state)
        context = ExecutionContext(
            request_id=state.request_id,
            turn_id=state.session_id,
            task_id=call.id,
            user_id=state.user_id,
            visible_capabilities=visible,
            approved_input=state.approved_inputs.get(call.id),
        )
        runtime = ToolRuntime(
            registry,
            hooks=self._hooks,
            permissions=PermissionEngine(self._risk_policy.authorize),
            executor=SafeExecutor(max_output_bytes=self._max_output_bytes),
        )
        runtime_result = await runtime.execute(name, args, context)
        effective_args = adapter.last_input or args
        cache_key = adapter.cache_key
        if not runtime_result.success:
            error = self._runtime_guidance_error(tool, runtime_result)
            logger.info("tool dispatch failed: tool=%s error=%s", name, error[:120])
            permission_source = runtime_result.audit.get("permission_source")
            if not defer_failures and self._risk_policy.should_emit_permission_required(
                tool, permission_source
            ):
                await self._emit(
                    "permission_required",
                    state.step,
                    tool=name,
                    risk=definition.minimum_risk.value,
                )
            if not defer_failures:
                await self._emit_error(name, error, step=state.step)
                self._safe_record(
                    state,
                    name,
                    effective_args,
                    error,
                    success=False,
                    cache_key=cache_key,
                    tool_call_id=call.id,
                )
            return self._fail_result(name, effective_args, error).model_copy(
                update={"tool_call_data": dict(runtime_result.audit)}
            )

        output = runtime_result.output or {}
        is_cache_hit = bool(runtime_result.audit.get("cached", False))
        digest = self._digest(output)

        # 6. tool_end
        await self._emit("tool_end", state.step, tool=name, digest=digest, cached=is_cache_hit)

        # 7. 记账(post-apply_step 契约:step=state.step)
        self._safe_record(
            state,
            name,
            effective_args,
            digest,
            success=True,
            cache_key=cache_key,
            tool_call_id=call.id,
        )

        return ToolResult(
            tool_name=name,
            args=effective_args,
            success=True,
            output=output,
            latency_ms=runtime_result.latency_ms,
            cached=is_cache_hit,
        )

    # ------------------------------------------------------------------
    # search_tools 内置工具(渐进披露,spec § 3.2)
    # ------------------------------------------------------------------

    async def _dispatch_search_tools(
        self,
        tool_call_id: str,
        args: dict[str, Any],
        state: ChatLoopState,
        *,
        defer_failures: bool = False,
    ) -> ToolResult:
        """检索目标工具文档,top-k 拼成 {"docs": [{name, doc}...]} 返回。

        - query 缺失/非字符串 → 指导性错误(仍记账);
        - 命中工具名进 ledger.searched_docs(记账);
        - 同 turn 重复检索同一工具 → 文档文本前加 "(本 turn 已检索过)" 仍返回。
        本身不进 cache、不计预算、不做去重(检索是确定性纯函数,可重复调)。
        """
        visible = self._visible_for(state)
        if SEARCH_TOOLS_NAME not in visible:
            error = "[不可见工具] search_tools 不在本请求允许的工具集合中。"
            if not defer_failures:
                await self._emit_error(SEARCH_TOOLS_NAME, error, step=state.step)
                self._safe_record(
                    state,
                    SEARCH_TOOLS_NAME,
                    args,
                    error,
                    success=False,
                    cache_key=None,
                    tool_call_id=tool_call_id,
                )
            return self._fail_result(SEARCH_TOOLS_NAME, args, error)
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            error = "[参数校验失败] search_tools 需要 query(string)。请传工具名或自然语言描述。"
            if not defer_failures:
                await self._emit_error(SEARCH_TOOLS_NAME, error, step=state.step)
                self._safe_record(
                    state,
                    SEARCH_TOOLS_NAME,
                    args,
                    error,
                    success=False,
                    cache_key=None,
                    tool_call_id=tool_call_id,
                )
            return self._fail_result(SEARCH_TOOLS_NAME, args, error)

        await self._emit("tool_call", state.step, tool=SEARCH_TOOLS_NAME, args=args)
        await self._emit("tool_start", state.step, tool=SEARCH_TOOLS_NAME)

        hits = [doc for doc in search_docs(query, k=len(TOOL_DOCS)) if doc.name in visible][
            :_SEARCH_TOOLS_K
        ]
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
            state,
            SEARCH_TOOLS_NAME,
            args,
            digest,
            success=True,
            cache_key=None,
            tool_call_id=tool_call_id,
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
    def _runtime_guidance_error(tool: Tool, result: RuntimeResult) -> str:
        """Translate structured runtime failures into the loop's corrective prose."""
        error = result.error
        if error is None:
            return "[执行失败] 工具运行时返回了无错误信息的失败结果"
        message = error.message[:_ERR_MSG_LEN]
        if message.startswith("["):
            return message
        if error.code == "capability_not_visible":
            return f"[不可见工具] {tool.name} 不在本请求允许的工具集合中。"
        if error.category is ErrorCategory.PERMISSION_DENIED:
            return f"[需要授权] {tool.name} 未获得执行许可;本次已安全拒绝。"
        if error.category is ErrorCategory.VALIDATION_ERROR:
            fields = ", ".join(tool.args_schema.model_fields.keys())
            guidance = f"[参数校验失败] {message}。参数要求:{fields}"
            if tool.name in TOOL_DOCS and TOOL_DOCS[tool.name].group == "deferred":
                guidance += f"。可调 search_tools('{tool.name}') 获取参数文档"
            return guidance
        if error.category is ErrorCategory.TIMEOUT:
            return "[超时] 稍后重试或换数据源"
        if error.category is ErrorCategory.RESULT_INVALID:
            if error.code == "output_limit_exceeded":
                return f"[输出超限] {message}"
            return f"[结果无效] {message}"
        return f"[执行失败] {message}"

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
            # 逐字段错误(loc: msg),而非 str(exc) 的第一行 —— 第一行只有 "N validation
            # error(s) for X",字段名+原因全在第 2 行起。只给第一行模型不知错在哪 →
            # 同一错法无限 retry 撞 max_steps(实测 qwen3.7-max 把 data 当 JSON 字符串传,
            # 反馈却只说"1 validation error",自我修正不了)。逐错暴露后模型下一步即可纠。
            detail = "; ".join(
                f"{'.'.join(str(p) for p in e['loc']) or '?'}: {e['msg']}" for e in exc.errors()
            )[:_ERR_MSG_LEN]
            return f"[参数校验失败] {detail}。参数要求:{fields}"
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

    def _visible_for(self, state: ChatLoopState) -> frozenset[str]:
        registered = frozenset((*self._tools, SEARCH_TOOLS_NAME))
        if self._visibility_resolver is None:
            return registered
        return frozenset(self._visibility_resolver(state) & registered)

    @staticmethod
    def _safe_record(
        state: ChatLoopState,
        tool_name: str,
        args: dict[str, Any],
        digest: str,
        *,
        success: bool,
        cache_key: str | None,
        tool_call_id: str | None = None,
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
                tool_call_id=tool_call_id,
            )

    @staticmethod
    def _fail_result(tool_name: str, args: dict[str, Any], error: str) -> ToolResult:
        return ToolResult(
            tool_name=tool_name,
            args=args,
            success=False,
            output=None,
            error=error,
            latency_ms=0,
        )


__all__ = ["SEARCH_TOOLS_NAME", "EmitFn", "ToolHub"]

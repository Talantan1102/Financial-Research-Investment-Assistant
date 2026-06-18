"""ToolLoop — 裸 while 工具调用循环本体(spec § 1.2)。

唯一有副作用的编排者:LLM 调用、工具分发、事件发射、取消/插话检查。
判定逻辑全在纯函数模块(gates/context/state),本模块只编排。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from app.agents.schemas import ToolResult
from app.chatloop.context import ContextDeps, assemble_context
from app.chatloop.events import EventType, LoopEvent, SeqCounter
from app.chatloop.gates import (
    GateConfig,
    budget_margin_exhausted,
    check_gates,
    filter_burned,
    update_burned,
)
from app.chatloop.state import ChatLoopState, apply_results, apply_step, turn_summary
from app.services.llm_step import StepDelta, StepResult, StepToolCall

logger = logging.getLogger(__name__)

# 烧签名后被拒调用喂回模型的指导性错误文案(协议红线:rejected 也要有 tool 消息)。
# apply_results 对 success=False 的结果产出 "[ERROR] {error}",故此处不带 [ERROR] 前缀。
_BURNED_REJECT_ERROR = "该调用已连续失败 3 次被熔断,请换方法或基于已有信息作答"

# 分发前预算余量不足时,为本圈每个工具调用喂回的指导文案(不带 [ERROR],apply_results 会加)。
_BUDGET_SKIP_ERROR = "预算余量不足,本轮工具未执行;请基于已有信息作答,不要再调用工具"

# 分发前插话到达时,为被取消的本轮工具调用喂回的占位文案(不带 [ERROR],apply_results 会加)。
_STEER_INTERRUPT_ERROR = "用户插话,本轮工具未执行,请结合新指令重新决定"

# 撞闸原因 → 给模型看的人话短语(事件层 reason/stop_reason 仍用 raw 码做看板归因)。
_HALT_REASON_TEXT = {
    "max_steps": "已达步数上限",
    "budget": "已达预算上限",
    "spinning": "检测到原地重复调用",
    "repeated_failures": "检测到连续多次工具失败",
}


class CancelledByUser(Exception):  # noqa: N818 — 设计契约固定此名(对齐 asyncio.CancelledError 语义)
    """用户硬打断信号 — 由调用方(chat_runner)捕获走 partial commit。"""


class ToolHubProtocol(Protocol):
    async def dispatch(
        self, calls: list[StepToolCall], state: ChatLoopState
    ) -> list[ToolResult]: ...

    def schemas_for_llm(self) -> list[dict[str, Any]]: ...


class SteerSourceProtocol(Protocol):
    async def pop_all(self) -> list[str]:  # 圈边界取插话(FIFO),无则 []
        ...


EmitFn = Callable[[LoopEvent], Awaitable[None]]


class ToolLoop:
    """while 工具调用循环本体。

    run() 的精确节拍见 spec § 1.2;判定逻辑全部委派给 gates/context/state 纯函数,
    本类只负责编排副作用与事件发射。
    """

    def __init__(
        self,
        *,
        llm: Any,
        tool_hub: ToolHubProtocol,
        context_deps: ContextDeps,
        gate_cfg: GateConfig | None = None,
        emit: EmitFn | None = None,
        steer_source: SteerSourceProtocol | None = None,
        cancel_event: asyncio.Event | None = None,
        tier: str = "balanced",
        model: str | None = None,
        seq_counter: SeqCounter | None = None,
    ) -> None:
        self._llm = llm
        self._tool_hub = tool_hub
        self._deps = context_deps
        self._gate_cfg = gate_cfg or GateConfig()
        self._emit_fn = emit
        self._steer = steer_source
        self._cancel = cancel_event
        self._tier = tier
        self._model = model
        # 工具 schema 会话内恒定,turn 开始时取一次。
        self._schemas: list[dict[str, Any]] = tool_hub.schemas_for_llm()
        self._seq_counter = seq_counter if seq_counter is not None else SeqCounter()

    # ------------------------------------------------------------------
    # 事件 / 增量发射
    # ------------------------------------------------------------------

    async def _emit(self, type_: EventType, event_step: int, /, **data: Any) -> None:
        """构造 LoopEvent(带自增 seq 与当前 step)并发射;emit 为 None 时静默。

        event_step 为位置-only(/ 之后才是 data),故 data 里可携带同名 ``step`` 键
        (如 step_start{step,max_steps})而不与事件级 step 冲突。
        """
        seq = self._seq_counter.next()
        if self._emit_fn is None:
            return
        await self._emit_fn(LoopEvent(type=type_, seq=seq, step=event_step, data=data))

    def _make_on_delta(self, step: int) -> Callable[[StepDelta], Awaitable[None]]:
        """构造流式增量回调:content→token / reasoning→reasoning / tool_call→tool_call。

        回调内也检查 cancel_event(流中可断)。
        """

        async def _on_delta(delta: StepDelta) -> None:
            # 流式增量间也能被硬打断
            if self._cancel is not None and self._cancel.is_set():
                raise CancelledByUser("cancelled during stream")
            if delta.kind == "content":
                await self._emit("token", step, text=delta.text)
            elif delta.kind == "reasoning":
                await self._emit("reasoning", step, text=delta.text)
            elif delta.kind == "tool_call":
                # name 级:tool_call 事件(完整 args 版本在 dispatch 前由 hub 发)
                await self._emit("tool_call", step, tool_name=delta.tool_name)

        return _on_delta

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------

    async def run(self, state: ChatLoopState) -> ChatLoopState:
        max_steps = self._gate_cfg.max_steps
        while True:
            # 1. 取消检查(圈边界硬打断)
            if self._cancel is not None and self._cancel.is_set():
                raise CancelledByUser("cancelled at loop boundary")

            # 2. 闸二三 + 打转(纯谓词)— 圈首检查,口径与 gates 单测对齐:
            #    此时 state.step == 已完成圈数,前一圈的工具调用已由 dispatch 记入台账,
            #    spinning 才能比较"已完成的最近两圈"(详见 gates.py 记账契约注释)。
            #    spec § 1.2 伪码把闸画在 apply_step 之后是示意;spinning 的台账时序
            #    要求闸在"当前圈 dispatch 之后、下一圈 stream_step 之前"判定,故落在圈首。
            halt = check_gates(state, self._gate_cfg)
            if halt:
                await self._emit("loop_halt", state.step, reason=halt)
                return await self._force_conclude(state, halt)

            # 3. 插话并入(FIFO,圈边界)— 归到即将执行的 1-based 步号
            if self._steer is not None:
                for msg in await self._steer.pop_all():
                    state.messages.append({"role": "user", "content": msg})
                    await self._emit("steer_merged", state.step + 1, preview=msg[:80])

            # 4. step_start(事件 step 与 data.step 同为即将执行的 1-based 步号)
            await self._emit("step_start", state.step + 1, step=state.step + 1, max_steps=max_steps)

            # 5. 组窗口(纯函数)
            messages = assemble_context(state, self._deps)

            # 5.1 上下文压力安全阀触发 → 发事件(喂⑦看板,可观测/可归因)
            if state.context_pressure_passes > 0:
                await self._emit(
                    "context_pressure",
                    state.step + 1,
                    passes=state.context_pressure_passes,
                    floor_hit=state.context_pressure_floor_hit,
                )

            # 6. 单 LLM 流式调用
            step_result: StepResult = await self._llm.stream_step(
                messages=messages,
                tools=self._schemas,
                tool_choice=state.tool_choice,
                tier=self._tier,
                model=self._model,
                request_id=state.request_id,
                on_delta=self._make_on_delta(state.step + 1),
            )

            # 7. 折叠 LLM 输出(step += 1)
            state = apply_step(state, step_result)

            # 8. cost_update
            await self._emit(
                "cost_update",
                state.step,
                cny=state.budget_spent_cny,
                tokens=state.budget_spent_tokens,
                cached_tokens=step_result.cached_tokens,
                step_cost_cny=step_result.cost_cny,
                step_prompt_tokens=step_result.prompt_tokens,
                step_completion_tokens=step_result.completion_tokens,
            )

            # 9. 闸一:自然停
            if not step_result.tool_calls:
                state.halt_reason = state.halt_reason or "natural"
                # 修法 A(spec § 4.3 升级事件次序):escalate_offered 时 loop 不发 done,
                # 由 runner 在 escalate_request + escalate_packet_draft 之后补发唯一终止 done。
                # 非 escalate 时 loop 自己发 done(runner 不补,防双 done)。
                if not state.escalate_offered:
                    await self._emit(
                        "done",
                        state.step,
                        stop_reason=state.halt_reason,
                        **turn_summary(state),
                    )
                return state

            # 10. 熔断收尾圈竟然还出 tool_calls?协议异常,fail loud
            if state.tool_choice == "none":
                raise RuntimeError("tool_choice=none 下模型仍产出 tool_calls — 协议违例")

            # 11. 烧签名过滤(rejected 的签名列表此处不直接用 —
            #     _merge_results 以 allowed 的 id 集合判定每个 call 是否放行)
            allowed, _rejected = filter_burned(step_result.tool_calls, state)

            # 11.5 ④(b) 分发前预算预检:本圈 LLM 成本已入账,若余量不足则整轮跳过工具、
            #      直接收尾——避免单圈重型工具(+随后又一轮 LLM)把预算炸穿。
            #      给每个 tool_call 回预算指导占位,守住协议红线(每个 id 必有 tool 消息)。
            if budget_margin_exhausted(state, self._gate_cfg):
                await self._emit("loop_halt", state.step, reason="budget")
                skipped = [self._budget_skipped_result(c) for c in step_result.tool_calls]
                state = apply_results(state, skipped, step_result.tool_calls)
                return await self._force_conclude(state, "budget")

            # 11.6 ⑤ 分发前插话检查点:LLM 已决定本轮工具但尚未 dispatch 时,
            #      若此刻有插话到达 → 取消本轮工具批(占位守协议红线)、并入插话、
            #      回圈首让模型结合新指令重新决定。把改方向型插话的延迟从"整圈"
            #      缩到"当前 LLM 流"那段,并立省一整批可能已不需要的工具。
            #      圈首 pop_all 保留(管上一圈工具执行期间到达的插话),两点互补。
            if self._steer is not None:
                steers = await self._steer.pop_all()
                if steers:
                    interrupted = [
                        self._steer_interrupted_result(c) for c in step_result.tool_calls
                    ]
                    state = apply_results(state, interrupted, step_result.tool_calls)
                    for msg in steers:
                        state.messages.append({"role": "user", "content": msg})
                        await self._emit("steer_merged", state.step + 1, preview=msg[:80])
                    continue

            # 12. 工具分发(hub 负责 gather/缓存/记账/tool_start/tool_end)
            results = await self._tool_hub.dispatch(allowed, state)

            # 13. 按原顺序合并 allowed 的 results 与 rejected 的熔断错误,
            #     再折叠 tool 消息(协议红线:每个 tool_call_id 都要有 tool 消息)
            merged = self._merge_results(step_result.tool_calls, allowed, results)
            await self._extract_and_emit_charts(merged, state)
            state = apply_results(state, merged, step_result.tool_calls)

            # 14. 烧签名记账
            update_burned(state, self._gate_cfg)

            # 15. 回到圈首

    # ------------------------------------------------------------------
    # 图抽取:figures 发 chart 事件并剥离出 LLM 上下文(spec § 5)
    # ------------------------------------------------------------------

    async def _extract_and_emit_charts(
        self, results: list[ToolResult], state: ChatLoopState
    ) -> None:
        """把工具输出里的 figures 抽出发 chart 事件,并从 output 剥离(spec § 5)。

        figure JSON 可达数 KB,绝不进 LLM 上下文(窗口铁律)—— 图只走 chart 事件
        旁路渲染到前端;LLM 侧 output 的 figures 被替换为 charts_rendered 计数。
        chart_id 确定性:{request_id}-{step}-{结果序}-{图序}(无随机,可复现)。
        """
        for ridx, r in enumerate(results):
            if not (r.success and isinstance(r.output, dict)):
                continue
            figures = r.output.get("figures")
            if isinstance(figures, list) and figures:
                for fidx, fig in enumerate(figures):
                    chart_id = f"{state.request_id}-{state.step}-{ridx}-{fidx}"
                    await self._emit("chart", state.step, chart_id=chart_id, figure=fig)
                r.output.pop("figures", None)
                r.output["charts_rendered"] = len(figures)
            else:
                # 无图:把空 figures 键也清掉,保持 LLM 侧 output 干净
                r.output.pop("figures", None)
            # ② 超大结果截断(figures 已剥,量真正进窗口的体积)
            self._cap_oversized_output(r, state)

    def _cap_oversized_output(self, r: ToolResult, state: ChatLoopState) -> None:
        """超阈值且能取回(有 cache ref)的 dict 结果 → 换成 digest+ref;取不回的不截。

        安全不变量:绝不截断取不回的内容(无 cache ref 则保留全文 + log 警告)。
        in-process 工具 / load_skill cache_key 恒为 None → 自动豁免;无需识别工具类型。
        """
        if not isinstance(r.output, dict):
            return
        threshold = self._deps.oversize_result_char_threshold
        try:
            serialized = json.dumps(r.output, ensure_ascii=False)
        except (TypeError, ValueError):
            return
        if len(serialized) <= threshold:
            return
        entry = state.ledger.find_success(tool_name=r.tool_name, args=r.args)
        cache_key = entry.cache_key if entry is not None else None
        if cache_key is None:
            logger.warning(
                "oversize tool output without cache ref, kept intact: tool=%s chars=%d",
                r.tool_name,
                len(serialized),
            )
            return
        # ToolResult 是 frozen,但 output dict 可变 —— 原地 clear+update(同既有 figures 剥离手法)
        summary = r.output.get("summary")
        r.output.clear()
        capped: dict[str, Any] = {
            "note": (
                "结果过大已截断,完整数据已缓存(见 ref)。要对它做计算,"
                "用 run_python 传 data_refs={变量名: 上面的 ref} 把完整数据一次灌进沙箱算全量——"
                "别用 read_cached_result 分页翻取(大数据翻页会耗尽预算);只想看少量原文才用 read_cached_result。"
            ),
            "ref": cache_key,
            "original_chars": len(serialized),
        }
        if isinstance(summary, dict):
            capped["summary"] = summary  # 工具自带信息卡 → 存活,优于粗暴 digest
        else:
            capped["truncated_digest"] = serialized[:600]
        r.output.update(capped)

    # ------------------------------------------------------------------
    # 结果合并:allowed→真实 result,rejected→熔断错误,按原顺序对齐
    # ------------------------------------------------------------------

    def _merge_results(
        self,
        all_calls: list[StepToolCall],
        allowed: list[StepToolCall],
        results: list[ToolResult],
    ) -> list[ToolResult]:
        """按 all_calls 原顺序产出与之等长的 ToolResult 列表。

        - allowed 的 call 用 dispatch 回来的 results(按 allowed 顺序消费);
        - rejected(被 filter_burned 剔除)的 call 用熔断错误 ToolResult 占位,
          保证 apply_results 的长度断言与协议红线(每个 tool_call_id 都有 tool 消息)。
        """
        # allowed 的 id 集合 → 判定每个 call 是否被放行
        allowed_ids = {c.id for c in allowed}
        results_by_iter = iter(results)
        merged: list[ToolResult] = []
        for call in all_calls:
            if call.id in allowed_ids:
                merged.append(next(results_by_iter))
            else:
                merged.append(self._burned_result(call))
        return merged

    @staticmethod
    def _burned_result(call: StepToolCall) -> ToolResult:
        """被烧签名拒绝的调用产出的指导性错误结果。"""
        try:
            args = call.parsed_args
        except ValueError:
            args = {}
        return ToolResult(
            tool_name=call.name,
            args=args,
            success=False,
            output=None,
            error=_BURNED_REJECT_ERROR,
            latency_ms=0,
        )

    @staticmethod
    def _budget_skipped_result(call: StepToolCall) -> ToolResult:
        """预算余量不足时,为被跳过的工具调用产出的指导性占位结果。"""
        try:
            args = call.parsed_args
        except ValueError:
            args = {}
        return ToolResult(
            tool_name=call.name,
            args=args,
            success=False,
            output=None,
            error=_BUDGET_SKIP_ERROR,
            latency_ms=0,
        )

    @staticmethod
    def _steer_interrupted_result(call: StepToolCall) -> ToolResult:
        """分发前插话到达时,为被取消的工具调用产出的占位结果(守协议红线)。"""
        try:
            args = call.parsed_args
        except ValueError:
            args = {}
        return ToolResult(
            tool_name=call.name,
            args=args,
            success=False,
            output=None,
            error=_STEER_INTERRUPT_ERROR,
            latency_ms=0,
        )

    # ------------------------------------------------------------------
    # 熔断收尾:喂回系统指令 + tool_choice=none 收尾圈
    # ------------------------------------------------------------------

    async def _force_conclude(self, state: ChatLoopState, reason: str) -> ChatLoopState:
        """撞闸后逼模型基于已有信息收尾(spec § 1.3)。"""
        state.halt_reason = reason
        reason_text = _HALT_REASON_TEXT.get(reason, reason)
        state.messages.append(
            {
                "role": "user",
                "content": (
                    f"(系统:已达执行上限({reason_text}),请基于已有信息直接给出最终回答,"
                    "不要再调用任何工具。)"
                ),
            }
        )
        state.tool_choice = "none"
        messages = assemble_context(state, self._deps)
        step_result = await self._llm.stream_step(
            messages=messages,
            tools=self._schemas,
            tool_choice="none",
            tier=self._tier,
            model=self._model,
            request_id=state.request_id,
            on_delta=self._make_on_delta(state.step + 1),
        )
        state = apply_step(state, step_result)
        # 修法 A:撞闸后若 escalate 也已提议(边角:升级提议后下一圈又撞闸),
        # done 仍交给 runner 唯一补发,避免与升级链路双 done。
        if not state.escalate_offered:
            await self._emit("done", state.step, stop_reason=reason, **turn_summary(state))
        return state


__all__ = [
    "CancelledByUser",
    "EmitFn",
    "SteerSourceProtocol",
    "ToolHubProtocol",
    "ToolLoop",
]

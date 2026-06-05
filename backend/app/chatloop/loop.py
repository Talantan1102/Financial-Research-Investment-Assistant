"""ToolLoop — 裸 while 工具调用循环本体(spec § 1.2)。

唯一有副作用的编排者:LLM 调用、工具分发、事件发射、取消/插话检查。
判定逻辑全在纯函数模块(gates/context/state),本模块只编排。
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from app.agents.schemas import ToolResult
from app.chatloop.context import ContextDeps, assemble_context
from app.chatloop.events import EventType, LoopEvent
from app.chatloop.gates import GateConfig, check_gates, filter_burned, update_burned
from app.chatloop.state import ChatLoopState, apply_results, apply_step
from app.services.llm_step import StepDelta, StepResult, StepToolCall

# 烧签名后被拒调用喂回模型的指导性错误文案(协议红线:rejected 也要有 tool 消息)。
# apply_results 对 success=False 的结果产出 "[ERROR] {error}",故此处不带 [ERROR] 前缀。
_BURNED_REJECT_ERROR = "该调用已连续失败 3 次被熔断,请换方法或基于已有信息作答"


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
    ) -> None:
        self._llm = llm
        self._tool_hub = tool_hub
        self._deps = context_deps
        self._gate_cfg = gate_cfg or GateConfig()
        self._emit_fn = emit
        self._steer = steer_source
        self._cancel = cancel_event
        self._tier = tier
        # 工具 schema 会话内恒定,turn 开始时取一次。
        self._schemas: list[dict[str, Any]] = tool_hub.schemas_for_llm()
        self._seq = 0

    # ------------------------------------------------------------------
    # 事件 / 增量发射
    # ------------------------------------------------------------------

    async def _emit(self, type_: EventType, event_step: int, /, **data: Any) -> None:
        """构造 LoopEvent(带自增 seq 与当前 step)并发射;emit 为 None 时静默。

        event_step 为位置-only(/ 之后才是 data),故 data 里可携带同名 ``step`` 键
        (如 step_start{step,max_steps})而不与事件级 step 冲突。
        """
        self._seq += 1
        if self._emit_fn is None:
            return
        await self._emit_fn(
            LoopEvent(type=type_, seq=self._seq, step=event_step, data=data)
        )

    def _make_on_delta(
        self, step: int
    ) -> Callable[[StepDelta], Awaitable[None]]:
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
                    await self._emit(
                        "steer_merged", state.step + 1, preview=msg[:80]
                    )

            # 4. step_start(事件 step 与 data.step 同为即将执行的 1-based 步号)
            await self._emit(
                "step_start", state.step + 1, step=state.step + 1, max_steps=max_steps
            )

            # 5. 组窗口(纯函数)
            messages = assemble_context(state, self._deps)

            # 6. 单 LLM 流式调用
            step_result: StepResult = await self._llm.stream_step(
                messages=messages,
                tools=self._schemas,
                tool_choice=state.tool_choice,
                tier=self._tier,
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
            )

            # 9. 闸一:自然停
            if not step_result.tool_calls:
                state.halt_reason = state.halt_reason or "natural"
                await self._emit("done", state.step, stop_reason=state.halt_reason)
                return state

            # 10. 熔断收尾圈竟然还出 tool_calls?协议异常,fail loud
            if state.tool_choice == "none":
                raise RuntimeError(
                    "tool_choice=none 下模型仍产出 tool_calls — 协议违例"
                )

            # 11. 烧签名过滤(rejected 的签名列表此处不直接用 —
            #     _merge_results 以 allowed 的 id 集合判定每个 call 是否放行)
            allowed, _rejected = filter_burned(step_result.tool_calls, state)

            # 12. 工具分发(hub 负责 gather/缓存/记账/tool_start/tool_end)
            results = await self._tool_hub.dispatch(allowed, state)

            # 13. 按原顺序合并 allowed 的 results 与 rejected 的熔断错误,
            #     再折叠 tool 消息(协议红线:每个 tool_call_id 都要有 tool 消息)
            merged = self._merge_results(
                step_result.tool_calls, allowed, results
            )
            state = apply_results(state, merged, step_result.tool_calls)

            # 14. 烧签名记账
            update_burned(state, self._gate_cfg)

            # 15. 回到圈首

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

    # ------------------------------------------------------------------
    # 熔断收尾:喂回系统指令 + tool_choice=none 收尾圈
    # ------------------------------------------------------------------

    async def _force_conclude(
        self, state: ChatLoopState, reason: str
    ) -> ChatLoopState:
        """撞闸后逼模型基于已有信息收尾(spec § 1.3)。"""
        state.halt_reason = reason
        state.messages.append(
            {
                "role": "user",
                "content": (
                    f"(系统:已达执行上限({reason}),请基于已有信息直接给出最终回答,"
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
            request_id=state.request_id,
            on_delta=self._make_on_delta(state.step + 1),
        )
        state = apply_step(state, step_result)
        await self._emit("done", state.step, stop_reason=reason)
        return state


__all__ = [
    "CancelledByUser",
    "EmitFn",
    "SteerSourceProtocol",
    "ToolHubProtocol",
    "ToolLoop",
]

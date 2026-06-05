"""ScriptedStepClient — L1 测试用脚本化 LLM 客户端。

按预排剧本逐圈返回 StepResult,记录收到的 messages/tool_choice 供断言。
与 MockLLMClient(fixture 驱动,服务于旧 chat() 接口)互补,不替代。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.services.llm_step import StepDelta, StepResult


class ScriptedStepClient:
    """L1 测试用脚本化 LLM 客户端 — 按预排剧本逐圈返回 StepResult。

    用法示例::

        client = ScriptedStepClient(
            steps=[
                StepResult(
                    content="",
                    tool_calls=[StepToolCall(id="c1", name="search", arguments='{"q":"test"}')],
                    finish_reason="tool_calls",
                    prompt_tokens=10, completion_tokens=5, cached_tokens=0, cost_cny=0.001,
                ),
                StepResult(
                    content="最终回答",
                    tool_calls=[],
                    finish_reason="stop",
                    prompt_tokens=20, completion_tokens=10, cached_tokens=0, cost_cny=0.002,
                ),
            ]
        )
        # 第一圈返回 tool_calls,第二圈返回 stop — 两圈剧本覆盖完整 tool-use 循环。

    ``received_messages`` 与 ``received_tool_choice`` 在每次 ``stream_chat`` 调用后
    追加,可用于断言循环发出的 messages 和 tool_choice 是否符合预期。
    """

    def __init__(self, steps: list[StepResult]) -> None:
        self._steps = list(steps)
        self.received_messages: list[list[dict]] = []
        self.received_tool_choice: list[str] = []

    async def stream_chat(
        self,
        *,
        messages: list[dict],
        model: str,
        tools: list[dict] | None,
        tool_choice: str,
        on_delta: Callable[[StepDelta], Awaitable[None]] | None = None,
    ) -> StepResult:
        if not self._steps:
            raise AssertionError("ScriptedStepClient 剧本已耗尽 — 测试剧本步数与循环圈数不符")
        self.received_messages.append([dict(m) for m in messages])
        self.received_tool_choice.append(tool_choice)
        step = self._steps.pop(0)
        if on_delta is not None and step.content:
            await on_delta(StepDelta(kind="content", text=step.content))
        return step

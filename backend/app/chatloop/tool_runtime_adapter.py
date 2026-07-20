"""Adapter from chat-loop ``Tool`` objects to the unified runtime contract."""

from __future__ import annotations

from typing import Any

from app.chatloop.inprocess import InProcessTool
from app.chatloop.state import ChatLoopState
from app.runtime.models import ExecutionContext, ExecutionStatus, RuntimeResult
from app.services.tool_result_cache import CacheHit, ToolResultCache
from app.tools.base import Tool


class ChatloopToolAdapter:
    def __init__(
        self,
        *,
        tool: Tool,
        state: ChatLoopState,
        cache: ToolResultCache | None,
    ) -> None:
        self._tool = tool
        self._state = state
        self._cache = cache
        self.last_input: dict[str, Any] | None = None
        self.cache_key: str | None = None

    async def execute(self, input: dict[str, Any], context: ExecutionContext) -> RuntimeResult:
        del context
        self.last_input = input
        validated = self._tool.args_schema.model_validate(input)

        if isinstance(self._tool, InProcessTool):
            output = await self._tool.run_with_state(validated, self._state)
            return RuntimeResult(status=ExecutionStatus.SUCCEEDED, output=output)

        async def compute() -> dict[str, Any]:
            return await self._tool.run(validated)

        cached = False
        if self._cache is not None:
            self.cache_key = ToolResultCache.cache_key(self._state.user_id, self._tool.name, input)
            output, cache_status = await self._cache.get_or_compute(
                user_id=self._state.user_id,
                tool_name=self._tool.name,
                args=input,
                compute_fn=compute,
            )
            cached = cache_status == CacheHit.HIT
        else:
            output = await compute()
        return RuntimeResult(
            status=ExecutionStatus.SUCCEEDED,
            output=output,
            audit={"cached": cached},
        )


__all__ = ["ChatloopToolAdapter"]

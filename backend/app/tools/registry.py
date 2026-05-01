"""ToolRegistry — central registry + uniform execute path with timing + error wrap."""

from __future__ import annotations

import time
from typing import Any

from pydantic import ValidationError

from app.agents.schemas import ToolCall, ToolResult
from app.tools.base import Tool, ToolError, ToolNotFoundError


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise ToolNotFoundError(f"no tool registered with name={name!r}")
        return self._tools[name]

    def list_for_llm(self) -> list[dict[str, Any]]:
        return [tool.schema_for_llm() for tool in self._tools.values()]

    async def execute(self, call: ToolCall) -> ToolResult:
        started = time.perf_counter()
        try:
            tool = self.get(call.tool_name)
        except ToolNotFoundError as e:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return ToolResult(
                tool_name=call.tool_name,
                args=call.args,
                success=False,
                error=str(e),
                latency_ms=latency_ms,
            )

        try:
            args = tool.args_schema.model_validate(call.args)
        except ValidationError as e:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return ToolResult(
                tool_name=call.tool_name,
                args=call.args,
                success=False,
                error=f"args validation failed: {e}",
                latency_ms=latency_ms,
            )

        try:
            output = await tool.run(args)
        except ToolError as e:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return ToolResult(
                tool_name=call.tool_name,
                args=call.args,
                success=False,
                error=str(e),
                latency_ms=latency_ms,
            )

        latency_ms = int((time.perf_counter() - started) * 1000)
        return ToolResult(
            tool_name=call.tool_name,
            args=call.args,
            success=True,
            output=output,
            latency_ms=latency_ms,
        )

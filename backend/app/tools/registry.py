"""ToolRegistry — central registry + uniform execute path with timing + error wrap."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ValidationError

from app.agents.schemas import ToolCall, ToolResult
from app.tools.base import Tool, ToolError, ToolNotFoundError

if TYPE_CHECKING:
    from app.services.mcp_client import MCPClient


class _MCPToolProxy(Tool):
    """Wraps an MCP-exposed tool to satisfy the in-process Tool interface.

    The MCP server validates input schema on its side; we use a permissive
    Pydantic model so that ToolRegistry.execute() can call model_validate()
    without schema conflicts.
    """

    def __init__(self, client: MCPClient, manifest: dict[str, Any]) -> None:
        self.name: str = manifest["name"]
        self.description: str = manifest["description"]
        self._client = client
        # 真实 MCP inputSchema —— 供 schema_for_llm 暴露给模型(否则模型不知参数名)。
        # 缺它时 CORE 工具靠模型从训练数据"背"参数,新工具(模型没见过)必传错参。
        self._input_schema: dict[str, Any] = manifest.get("inputSchema") or {
            "type": "object",
            "properties": {},
        }
        self.output_schema = manifest.get("outputSchema") or Tool.output_schema
        self.args_schema: type[BaseModel] = self._build_args_model()

    @staticmethod
    def _build_args_model() -> type[BaseModel]:
        # Permissive — MCP server validates schema on its side
        class _Args(BaseModel):
            model_config = {"extra": "allow"}

        return _Args

    def schema_for_llm(self) -> dict[str, Any]:
        # 用真实 MCP inputSchema(非空 _Args),让模型看到参数名/必填/描述。
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self._input_schema,
            },
        }

    async def run(self, args: BaseModel) -> dict[str, Any]:
        return await self._client.call_tool(self.name, args.model_dump())


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

    def items(self) -> tuple[tuple[str, Tool], ...]:
        """Return an immutable snapshot of registered tool entries."""
        return tuple(self._tools.items())

    async def register_mcp_client_async(self, client: MCPClient) -> None:
        """Register all tools exposed by an MCPClient (via stdio MCP server)."""
        tools = await client.list_tools()
        for t in tools:
            proxy = _MCPToolProxy(client, t)
            self._tools[proxy.name] = proxy

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
        except Exception as e:  # C53: wrap unexpected errors; prevents gather cancellation
            latency_ms = int((time.perf_counter() - started) * 1000)
            return ToolResult(
                tool_name=call.tool_name,
                args=call.args,
                success=False,
                error=f"unexpected error in {call.tool_name}: {e!r}",
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

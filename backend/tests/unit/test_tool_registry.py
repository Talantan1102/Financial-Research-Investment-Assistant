"""L0 — Tool registration / get / execute / list_for_llm."""

import asyncio

import pytest
from app.agents.schemas import ToolCall
from app.tools.base import Tool, ToolError, ToolNotFoundError
from app.tools.registry import ToolRegistry
from pydantic import BaseModel


class _EchoArgs(BaseModel):
    text: str


class _EchoTool(Tool):
    name = "echo"
    description = "Echo back the input."
    args_schema = _EchoArgs

    async def run(self, args: BaseModel) -> dict:
        assert isinstance(args, _EchoArgs)
        return {"echoed": args.text}


class _FailTool(Tool):
    name = "always_fail"
    description = "Always raises ToolError."
    args_schema = _EchoArgs

    async def run(self, args: BaseModel) -> dict:
        raise ToolError("intentional fail")


class _RuntimeErrorTool(Tool):
    """Simulates a tool that raises an unexpected non-ToolError (e.g. network/pandas error)."""

    name = "runtime_error_tool"
    description = "Raises RuntimeError unexpectedly."
    args_schema = _EchoArgs

    async def run(self, args: BaseModel) -> dict:
        raise RuntimeError("simulated network failure")


class _KeyErrorTool(Tool):
    """Simulates a tool that raises KeyError (e.g. missing column in tushare response)."""

    name = "key_error_tool"
    description = "Raises KeyError unexpectedly."
    args_schema = _EchoArgs

    async def run(self, args: BaseModel) -> dict:
        d: dict = {}
        return {"value": d["missing_key"]}  # KeyError


def test_register_then_get() -> None:
    reg = ToolRegistry()
    reg.register(_EchoTool())
    assert reg.get("echo").name == "echo"


def test_duplicate_register_rejected() -> None:
    reg = ToolRegistry()
    reg.register(_EchoTool())
    with pytest.raises(ValueError, match="duplicate"):
        reg.register(_EchoTool())


def test_get_unknown_raises() -> None:
    reg = ToolRegistry()
    with pytest.raises(ToolNotFoundError):
        reg.get("nonexistent")


@pytest.mark.asyncio
async def test_execute_success() -> None:
    reg = ToolRegistry()
    reg.register(_EchoTool())
    call = ToolCall(tool_name="echo", args={"text": "hi"}, rationale="r")
    result = await reg.execute(call)
    assert result.success
    assert result.output == {"echoed": "hi"}
    assert result.latency_ms >= 0


@pytest.mark.asyncio
async def test_execute_tool_error_caught() -> None:
    reg = ToolRegistry()
    reg.register(_FailTool())
    call = ToolCall(tool_name="always_fail", args={"text": "x"}, rationale="r")
    result = await reg.execute(call)
    assert not result.success
    assert "intentional fail" in (result.error or "")


@pytest.mark.asyncio
async def test_execute_invalid_args_caught() -> None:
    reg = ToolRegistry()
    reg.register(_EchoTool())
    call = ToolCall(tool_name="echo", args={"wrong_field": 1}, rationale="r")
    result = await reg.execute(call)
    assert not result.success
    assert "validation" in (result.error or "").lower()


def test_list_for_llm() -> None:
    reg = ToolRegistry()
    reg.register(_EchoTool())
    schemas = reg.list_for_llm()
    assert len(schemas) == 1
    assert schemas[0]["function"]["name"] == "echo"
    assert "parameters" in schemas[0]["function"]


# C53: unexpected non-ToolError exceptions must be wrapped, not propagated


@pytest.mark.asyncio
async def test_execute_unexpected_runtime_error_caught() -> None:
    """C53: RuntimeError inside run() must return ToolResult(success=False), not raise."""
    reg = ToolRegistry()
    reg.register(_RuntimeErrorTool())
    call = ToolCall(tool_name="runtime_error_tool", args={"text": "x"}, rationale="r")
    result = await reg.execute(call)
    assert not result.success
    assert result.error is not None
    assert "unexpected error in runtime_error_tool" in result.error
    assert "RuntimeError" in result.error
    assert result.latency_ms >= 0


@pytest.mark.asyncio
async def test_execute_unexpected_key_error_caught() -> None:
    """C53: KeyError (common tushare/pandas error) inside run() must be caught."""
    reg = ToolRegistry()
    reg.register(_KeyErrorTool())
    call = ToolCall(tool_name="key_error_tool", args={"text": "x"}, rationale="r")
    result = await reg.execute(call)
    assert not result.success
    assert result.error is not None
    assert "unexpected error in key_error_tool" in result.error


@pytest.mark.asyncio
async def test_execute_gather_survives_one_unexpected_error() -> None:
    """C53: when gather runs two tools and one raises unexpectedly, both results are returned.

    This is the data_collector path: asyncio.gather(*[registry.execute(c) for c in calls]).
    Before the fix, a non-ToolError from one tool would cancel the gather and lose the other.
    """
    reg = ToolRegistry()
    reg.register(_EchoTool())
    reg.register(_RuntimeErrorTool())

    calls = [
        ToolCall(tool_name="echo", args={"text": "hello"}, rationale="r"),
        ToolCall(tool_name="runtime_error_tool", args={"text": "x"}, rationale="r"),
    ]
    tasks = [reg.execute(c) for c in calls]
    results = list(await asyncio.gather(*tasks))

    assert len(results) == 2
    success_results = [r for r in results if r.success]
    failure_results = [r for r in results if not r.success]
    assert len(success_results) == 1
    assert len(failure_results) == 1
    assert success_results[0].output == {"echoed": "hello"}
    assert "unexpected error" in (failure_results[0].error or "")

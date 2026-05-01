"""L0 — Tool registration / get / execute / list_for_llm."""

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

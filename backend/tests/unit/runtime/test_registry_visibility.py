from __future__ import annotations

import pytest
from app.runtime.models import (
    CapabilityDefinition,
    CapabilityType,
    ExecutionContext,
    RiskLevel,
)
from app.runtime.registry import CapabilityRegistry
from app.runtime.visibility import CapabilityNotVisibleError
from app.tools.base import Tool
from app.tools.registry import ToolRegistry
from pydantic import BaseModel


class _Args(BaseModel):
    value: int


class _Tool(Tool):
    name = "market.quote"
    description = "Get a quote"
    args_schema = _Args

    async def run(self, args: BaseModel) -> dict[str, object]:
        assert isinstance(args, _Args)
        return {"value": args.value}


class _SideEffectTool(Tool):
    name = "orders.submit"
    description = "Submit an order"
    args_schema = _Args

    async def run(self, args: BaseModel) -> dict[str, object]:
        assert isinstance(args, _Args)
        return {"submitted": True}


def _definition(name: str) -> CapabilityDefinition:
    return CapabilityDefinition(
        name=name,
        type=CapabilityType.DATA_TOOL,
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        minimum_risk=RiskLevel.LOW,
        read_only=True,
        idempotent=True,
        default_timeout_s=10,
        max_attempts=1,
    )


def _context(*visible: str) -> ExecutionContext:
    return ExecutionContext(
        request_id="request-1",
        turn_id="turn-1",
        task_id="task-1",
        user_id="user-1",
        visible_capabilities=frozenset(visible),
    )


def test_register_rejects_duplicate_capability_name() -> None:
    registry = CapabilityRegistry()
    registry.register(_definition("market.quote"), object())

    with pytest.raises(ValueError, match="duplicate capability name: market.quote"):
        registry.register(_definition("market.quote"), object())


def test_list_visible_intersects_allowlist_with_registered_capabilities() -> None:
    registry = CapabilityRegistry()
    quote = _definition("market.quote")
    hidden = _definition("memory.delete")
    registry.register(quote, object())
    registry.register(hidden, object())

    assert registry.list_visible(_context("market.quote", "not.registered")) == [quote]


def test_require_visible_rejects_direct_access_to_hidden_capability() -> None:
    registry = CapabilityRegistry()
    registry.register(_definition("memory.delete"), object())

    with pytest.raises(CapabilityNotVisibleError, match="memory.delete"):
        registry.require_visible("memory.delete", _context("market.quote"))


def test_from_tool_registry_adapts_tools_without_private_access() -> None:
    legacy = ToolRegistry()
    tool = _Tool()
    legacy.register(tool)

    registry = CapabilityRegistry.from_tool_registry(legacy)
    definition, adapter = registry.require_visible("market.quote", _context("market.quote"))

    assert adapter is tool
    assert definition.name == tool.name
    assert definition.input_schema == _Args.model_json_schema()
    assert legacy.items() == ((tool.name, tool),)


def test_from_tool_registry_fails_closed_for_unknown_side_effect_tool() -> None:
    legacy = ToolRegistry()
    tool = _SideEffectTool()
    legacy.register(tool)

    registry = CapabilityRegistry.from_tool_registry(legacy)
    definition, adapter = registry.get(tool.name)

    assert adapter is tool
    assert definition.minimum_risk is RiskLevel.HIGH
    assert definition.read_only is False
    assert definition.idempotent is False

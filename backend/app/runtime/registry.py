"""Registry for unified runtime capability metadata and adapters."""

from __future__ import annotations

from typing import TypeAlias

from app.runtime.models import CapabilityDefinition, CapabilityType, ExecutionContext, RiskLevel
from app.runtime.visibility import ensure_capability_visible
from app.tools.base import Tool
from app.tools.registry import ToolRegistry

CapabilityAdapter: TypeAlias = object
RegisteredCapability: TypeAlias = tuple[CapabilityDefinition, CapabilityAdapter]


class CapabilityRegistry:
    """Stores registered capabilities and enforces request visibility."""

    def __init__(self) -> None:
        self._capabilities: dict[str, RegisteredCapability] = {}

    def register(self, definition: CapabilityDefinition, adapter: CapabilityAdapter) -> None:
        if definition.name in self._capabilities:
            raise ValueError(f"duplicate capability name: {definition.name}")
        self._capabilities[definition.name] = (definition, adapter)

    def get(self, name: str) -> RegisteredCapability:
        try:
            return self._capabilities[name]
        except KeyError:
            raise KeyError(f"no capability registered with name={name!r}") from None

    def list_visible(self, context: ExecutionContext) -> list[CapabilityDefinition]:
        return [
            definition
            for name, (definition, _) in self._capabilities.items()
            if name in context.visible_capabilities
        ]

    def require_visible(self, name: str, context: ExecutionContext) -> RegisteredCapability:
        ensure_capability_visible(name, context)
        return self.get(name)

    @classmethod
    def from_tool_registry(cls, registry: ToolRegistry) -> CapabilityRegistry:
        """Adapt legacy tools with conservative execution-policy defaults."""
        capabilities = cls()
        for name, tool in registry.items():
            capabilities.register(cls._definition_for_tool(name, tool), tool)
        return capabilities

    @staticmethod
    def _definition_for_tool(name: str, tool: Tool) -> CapabilityDefinition:
        return CapabilityDefinition(
            name=name,
            type=CapabilityType.DATA_TOOL,
            input_schema=tool.args_schema.model_json_schema(),
            output_schema={"type": "object"},
            minimum_risk=RiskLevel.LOW,
            read_only=True,
            idempotent=True,
            default_timeout_s=30,
            max_attempts=1,
        )

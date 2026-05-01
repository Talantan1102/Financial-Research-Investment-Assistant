"""Tool ABC + tool-related exceptions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class ToolError(Exception):
    """Raised by Tool.run on a recoverable execution failure (network /
    parse / domain error). ToolRegistry.execute catches this and wraps
    in ToolResult(success=False)."""


class ToolNotFoundError(LookupError):
    """Raised by ToolRegistry.get when a tool name isn't registered."""


class Tool(ABC):
    name: str
    description: str
    args_schema: type[BaseModel]

    @abstractmethod
    async def run(self, args: BaseModel) -> dict[str, Any]:
        """Execute the tool. args is a Pydantic-validated instance of args_schema."""

    def schema_for_llm(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args_schema.model_json_schema(),
            },
        }

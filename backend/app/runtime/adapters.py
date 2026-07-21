"""Adapter protocol implemented by all unified runtime capabilities."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from app.runtime.models import ExecutionContext, RuntimeResult


class CapabilityAdapter(Protocol):
    """Capability execution boundary consumed by :class:`ToolRuntime`."""

    async def execute(self, input: dict[str, Any], context: ExecutionContext) -> RuntimeResult: ...


@runtime_checkable
class SupportsCancellation(Protocol):
    """Optional extension for adapters that own cancellable background work."""

    async def cancel(self, task_id: str) -> None:
        """Cancel adapter-owned work for ``task_id``."""

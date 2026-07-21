"""Capability visibility checks shared by discovery and execution paths."""

from __future__ import annotations

from app.runtime.models import ExecutionContext


class CapabilityNotVisibleError(PermissionError):
    """Raised when a request attempts to use a capability outside its allowlist."""


def is_capability_visible(name: str, context: ExecutionContext) -> bool:
    """Return whether ``name`` is allowed in this request context."""
    return name in context.visible_capabilities


def ensure_capability_visible(name: str, context: ExecutionContext) -> None:
    """Enforce request-scoped visibility at the execution boundary."""
    if not is_capability_visible(name, context):
        raise CapabilityNotVisibleError(f"capability is not visible: {name}")

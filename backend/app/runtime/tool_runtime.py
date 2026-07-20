"""Complete policy and execution pipeline for registered capabilities."""

from __future__ import annotations

from typing import Any

from app.runtime.hooks import HookEvent, HookInvocation, HookPipeline
from app.runtime.models import (
    ErrorCategory,
    ExecutionContext,
    ExecutionStatus,
    RuntimeErrorInfo,
    RuntimeResult,
)
from app.runtime.permissions import PermissionDecision, PermissionEngine
from app.runtime.redaction import scrub_text
from app.runtime.registry import CapabilityRegistry
from app.runtime.safe_executor import SafeExecutor
from app.runtime.validation import InputGuard, InputValidationError
from app.runtime.visibility import CapabilityNotVisibleError


class ToolRuntime:
    """Run the fail-closed unified capability pipeline in canonical order."""

    def __init__(
        self,
        registry: CapabilityRegistry,
        *,
        hooks: HookPipeline | None = None,
        permissions: PermissionEngine | None = None,
        executor: SafeExecutor | None = None,
        input_guard: InputGuard | None = None,
    ) -> None:
        self._registry = registry
        self._hooks = hooks or HookPipeline()
        self._permissions = permissions or PermissionEngine()
        self._executor = executor or SafeExecutor()
        self._input_guard = input_guard or InputGuard()

    async def execute(
        self,
        name: str,
        requested_input: dict[str, Any],
        context: ExecutionContext,
    ) -> RuntimeResult:
        try:
            definition, untyped_adapter = self._registry.require_visible(name, context)
        except (CapabilityNotVisibleError, KeyError) as exc:
            return self._failure(
                "capability_not_visible", ErrorCategory.PERMISSION_DENIED, str(exc)
            )

        invocation = HookInvocation(
            event=HookEvent.PRE, definition=definition, input=requested_input
        )
        try:
            pre = await self._hooks.run_pre(invocation, validate_input=False)
        except InputValidationError as exc:
            return self._failure(
                "input_validation_failed", ErrorCategory.VALIDATION_ERROR, str(exc)
            )
        except Exception as exc:
            return self._failure("pre_hook_failed", ErrorCategory.SYSTEM_ERROR, str(exc))

        effective_input = pre.updated_input or requested_input
        try:
            permission = await self._permissions.authorize(
                definition,
                effective_input,
                context,
                (pre.permission,),
            )
        except Exception as exc:
            return self._failure("permission_check_failed", ErrorCategory.SYSTEM_ERROR, str(exc))
        if permission is not PermissionDecision.ALLOW:
            return self._failure(
                "permission_denied",
                ErrorCategory.PERMISSION_DENIED,
                f"permission decision was {permission.value}",
            )

        try:
            self._input_guard.validate(definition, effective_input)
        except InputValidationError as exc:
            return self._failure(
                "input_validation_failed", ErrorCategory.VALIDATION_ERROR, str(exc)
            )

        adapter = untyped_adapter  # registry adapters are checked structurally at execution.
        result = await self._executor.execute(
            adapter,  # type: ignore[arg-type]
            effective_input,
            context,
            timeout_s=definition.default_timeout_s,
        )
        if not result.success:
            return result

        try:
            await self._hooks.run_post(
                HookInvocation(
                    event=HookEvent.POST,
                    definition=definition,
                    input=effective_input,
                    output=result.output,
                )
            )
        except Exception as exc:
            return self._failure(
                "post_hook_failed",
                ErrorCategory.SYSTEM_ERROR,
                str(exc) or type(exc).__name__,
                latency_ms=result.latency_ms,
            )
        return result

    @staticmethod
    def _failure(
        code: str,
        category: ErrorCategory,
        message: str,
        *,
        latency_ms: int = 0,
    ) -> RuntimeResult:
        return RuntimeResult(
            status=ExecutionStatus.FAILED,
            error=RuntimeErrorInfo(
                code=code,
                category=category,
                message=scrub_text(message or code),
                retryable=False,
            ),
            latency_ms=latency_ms,
        )

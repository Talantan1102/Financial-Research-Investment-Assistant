"""Bounded, exception-safe adapter execution."""

from __future__ import annotations

import asyncio
import json
from time import monotonic
from typing import Any

from jsonschema import Draft202012Validator, SchemaError
from jsonschema import ValidationError as JsonSchemaError
from pydantic import ValidationError

from app.runtime.adapters import CapabilityAdapter
from app.runtime.models import (
    ErrorCategory,
    ExecutionContext,
    ExecutionStatus,
    RuntimeErrorInfo,
    RuntimeResult,
)
from app.runtime.redaction import scrub_result, scrub_text

_LEDGER_REFERENCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "cached_digest": {"type": "string"},
        "note": {"type": "string"},
        "ref": {"type": ["string", "null"]},
    },
    "required": ["cached_digest", "note", "ref"],
    "additionalProperties": False,
}


class SafeExecutor:
    """Execute an adapter with stable failure categories and output bounds."""

    def __init__(self, *, max_output_bytes: int = 1_048_576) -> None:
        if max_output_bytes < 1:
            raise ValueError("max_output_bytes must be positive")
        self._max_output_bytes = max_output_bytes

    async def execute(
        self,
        adapter: CapabilityAdapter,
        input: dict[str, Any],
        context: ExecutionContext,
        *,
        timeout_s: float,
        output_schema: dict[str, Any] | None = None,
    ) -> RuntimeResult:
        started = monotonic()
        try:
            async with asyncio.timeout(timeout_s):
                result = await adapter.execute(input, context)
            effective_output_schema = (
                _LEDGER_REFERENCE_SCHEMA
                if result.audit.get("trusted_ledger_reference") is True
                else output_schema
            )
            if effective_output_schema is not None:
                try:
                    Draft202012Validator.check_schema(effective_output_schema)
                    Draft202012Validator(effective_output_schema).validate(result.output)
                except (SchemaError, JsonSchemaError) as exc:
                    return self._failure(
                        code="output_schema_validation_failed",
                        category=ErrorCategory.RESULT_INVALID,
                        message=str(exc),
                        latency_ms=self._latency_ms(started),
                    )
            if result.output is not None:
                try:
                    encoded = json.dumps(
                        result.output, ensure_ascii=False, separators=(",", ":")
                    ).encode("utf-8")
                except (TypeError, ValueError) as exc:
                    return self._failure(
                        code="output_not_json_serializable",
                        category=ErrorCategory.RESULT_INVALID,
                        message=str(exc),
                        latency_ms=self._latency_ms(started),
                    )
                size = len(encoded)
                if size > self._max_output_bytes:
                    return self._failure(
                        code="output_limit_exceeded",
                        category=ErrorCategory.RESULT_INVALID,
                        message=(
                            f"adapter output is {size} bytes; limit is "
                            f"{self._max_output_bytes} bytes"
                        ),
                        latency_ms=self._latency_ms(started),
                    )
            return scrub_result(result.model_copy(update={"latency_ms": self._latency_ms(started)}))
        except TimeoutError:
            return self._failure(
                code="execution_timeout",
                category=ErrorCategory.TIMEOUT,
                message=f"adapter execution exceeded {timeout_s:g}s timeout",
                latency_ms=self._latency_ms(started),
                retryable=True,
            )
        except asyncio.CancelledError:
            # Cancellation is control flow owned by ToolLoop/chat_runner. Turning
            # it into an ordinary result makes the loop continue after the user
            # cancelled the request and can persist misleading ledger entries.
            raise
        except ValidationError as exc:
            return self._failure(
                code="pydantic_input_validation_failed",
                category=ErrorCategory.VALIDATION_ERROR,
                message=str(exc),
                latency_ms=self._latency_ms(started),
            )
        except Exception as exc:
            return self._failure(
                code="adapter_execution_error",
                category=ErrorCategory.EXECUTION_ERROR,
                message=scrub_text(str(exc) or type(exc).__name__),
                latency_ms=self._latency_ms(started),
            )

    @staticmethod
    def _latency_ms(started: float) -> int:
        return max(0, int((monotonic() - started) * 1000))

    @staticmethod
    def _failure(
        *,
        code: str,
        category: ErrorCategory,
        message: str,
        latency_ms: int,
        retryable: bool = False,
        status: ExecutionStatus = ExecutionStatus.FAILED,
    ) -> RuntimeResult:
        return RuntimeResult(
            status=status,
            error=RuntimeErrorInfo(
                code=code, category=category, message=message, retryable=retryable
            ),
            latency_ms=latency_ms,
        )

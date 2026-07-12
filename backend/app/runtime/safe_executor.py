"""Bounded, exception-safe adapter execution."""

from __future__ import annotations

import asyncio
import json
from time import monotonic
from typing import Any

from app.runtime.adapters import CapabilityAdapter
from app.runtime.models import (
    ErrorCategory,
    ExecutionContext,
    ExecutionStatus,
    RuntimeErrorInfo,
    RuntimeResult,
)


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
    ) -> RuntimeResult:
        started = monotonic()
        try:
            async with asyncio.timeout(timeout_s):
                result = await adapter.execute(input, context)
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
            return result.model_copy(update={"latency_ms": self._latency_ms(started)})
        except TimeoutError:
            return self._failure(
                code="execution_timeout",
                category=ErrorCategory.TIMEOUT,
                message=f"adapter execution exceeded {timeout_s:g}s timeout",
                latency_ms=self._latency_ms(started),
                retryable=True,
            )
        except asyncio.CancelledError:
            return self._failure(
                code="execution_cancelled",
                category=ErrorCategory.CANCELLED,
                message="adapter execution was cancelled",
                latency_ms=self._latency_ms(started),
                status=ExecutionStatus.CANCELLED,
            )
        except Exception as exc:
            return self._failure(
                code="adapter_execution_error",
                category=ErrorCategory.EXECUTION_ERROR,
                message=str(exc) or type(exc).__name__,
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

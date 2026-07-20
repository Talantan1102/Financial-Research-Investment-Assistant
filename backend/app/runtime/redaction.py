"""Small deterministic scrubber for runtime boundary data."""

from __future__ import annotations

import re
from typing import Any

from app.runtime.models import RuntimeErrorInfo, RuntimeResult

_SENSITIVE_KEY = re.compile(
    r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|password|secret)",
    re.IGNORECASE,
)
_SECRET_VALUE = re.compile(
    r"(?i)(?:bearer\s+\S+|sk-[a-z0-9_-]{8,}|(?:password|secret|token)\s*[=:]\s*\S+)"
)


def scrub_text(value: str) -> str:
    return _SECRET_VALUE.sub("[REDACTED]", value)


def scrub_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if _SENSITIVE_KEY.search(str(key)) else scrub_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [scrub_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(scrub_value(item) for item in value)
    if isinstance(value, str):
        return scrub_text(value)
    return value


def scrub_result(result: RuntimeResult) -> RuntimeResult:
    error = result.error
    if error is not None:
        error = RuntimeErrorInfo(
            code=error.code,
            category=error.category,
            message=scrub_text(error.message),
            retryable=error.retryable,
        )
    return result.model_copy(
        update={
            "output": scrub_value(result.output),
            "error": error,
            "audit": scrub_value(result.audit),
        }
    )

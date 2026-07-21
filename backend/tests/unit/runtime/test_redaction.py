from __future__ import annotations

from app.runtime.models import (
    ErrorCategory,
    ExecutionStatus,
    RuntimeErrorInfo,
    RuntimeResult,
)
from app.runtime.redaction import scrub_result, scrub_text, scrub_value


def test_scrub_value_redacts_sensitive_keys_and_inline_tokens() -> None:
    value = {
        "authorization": "Bearer visible-token",
        "nested": {
            "api_key": "sk-abcdefgh1234",
            "message": "provider token=visible-token failed",
        },
    }

    assert scrub_value(value) == {
        "authorization": "[REDACTED]",
        "nested": {"api_key": "[REDACTED]", "message": "provider [REDACTED] failed"},
    }
    assert scrub_text("Bearer visible-token") == "[REDACTED]"


def test_scrub_result_redacts_output_audit_and_error_message() -> None:
    result = RuntimeResult(
        status=ExecutionStatus.FAILED,
        output={"password": "visible-password"},
        error=RuntimeErrorInfo(
            code="provider_error",
            category=ErrorCategory.EXECUTION_ERROR,
            message="secret=visible-secret",
            retryable=False,
        ),
        audit={"access_token": "visible-token"},
    )

    scrubbed = scrub_result(result)

    assert scrubbed.output == {"password": "[REDACTED]"}
    assert scrubbed.error is not None
    assert scrubbed.error.message == "[REDACTED]"
    assert scrubbed.audit == {"access_token": "[REDACTED]"}

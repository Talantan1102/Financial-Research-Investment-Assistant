"""Local validation of capability inputs against MCP JSON Schema."""

from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator, SchemaError, ValidationError

from app.runtime.models import CapabilityDefinition


class InputValidationError(ValueError):
    """Raised when a capability schema or invocation input is invalid."""


class InputGuard:
    def validate(
        self, definition: CapabilityDefinition, invocation_input: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            Draft202012Validator.check_schema(definition.input_schema)
            Draft202012Validator(definition.input_schema).validate(invocation_input)
        except (SchemaError, ValidationError) as exc:
            location = ".".join(str(part) for part in exc.absolute_path)
            message = f"{location}: {exc.message}" if location else exc.message
            raise InputValidationError(message) from exc
        return invocation_input

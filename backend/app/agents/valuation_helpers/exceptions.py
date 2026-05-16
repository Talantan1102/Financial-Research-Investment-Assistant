"""v1.x A5a: Valuation helper exceptions."""

from __future__ import annotations


class InsufficientDataForModel(Exception):  # noqa: N818
    """raised when a Python valuation helper cannot compute due to missing/invalid input.

    Caller (ValuationCalculator) catches this and removes the failing model from
    `active_models`, then continues with the remaining models. Narrative will reflect
    which models were skipped and why (Writer prompt has explicit instruction).
    """

    def __init__(self, *, model: str, missing_field: str, reason: str) -> None:
        self.model = model
        self.missing_field = missing_field
        self.reason = reason
        super().__init__(f"model={model} missing_field={missing_field}: {reason}")

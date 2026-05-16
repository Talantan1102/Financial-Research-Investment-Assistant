"""v1.x A5a: Valuation helper exceptions."""

from __future__ import annotations


class InsufficientDataForModelError(ValueError):
    """Raised when a Python valuation helper cannot compute due to missing/invalid input.

    Caller (ValuationCalculator) catches this and removes the failing model from
    `active_models`, then continues with the remaining models. Narrative will reflect
    which models were skipped and why (Writer prompt has explicit instruction).

    Attributes:
        model: One of the str values in :class:`ValuationModel` ("pe" / "pb" / "ev_ebitda" / "dcf").
            Loose-typed to ``str`` to avoid circular import with investment_dd_schema;
            callers SHOULD pass ``ValuationModel.X.value`` or the matching literal.
        missing_field: Which input field was missing/invalid (e.g. "eps", "industry_pe").
        reason: Human-readable reason for skip (shown in trace / Writer narrative).
    """

    def __init__(self, *, model: str, missing_field: str, reason: str) -> None:
        self.model = model
        self.missing_field = missing_field
        self.reason = reason
        super().__init__(f"model={model} missing_field={missing_field}: {reason}")

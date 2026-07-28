"""Chat-loop risk metadata and fail-closed permission policy.

The mapping is deliberately explicit for every production chat tool.  Unknown
plain ``Tool`` instances inherit the read-only data-tool baseline; unknown
``InProcessTool`` instances are treated as state-changing and require approval.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.chatloop.inprocess import InProcessTool
from app.runtime.models import CapabilityDefinition, CapabilityType, RiskLevel
from app.runtime.permissions import AuthorizationCallback, PermissionRequest
from app.tools.base import Tool


@dataclass(frozen=True)
class ToolRiskMetadata:
    risk: RiskLevel
    capability_type: CapabilityType
    read_only: bool
    idempotent: bool
    system_allow_reason: str | None = None
    concurrency_group: str | None = None
    max_attempts: int = 1


_READ = ToolRiskMetadata(RiskLevel.LOW, CapabilityType.DATA_TOOL, True, True, max_attempts=2)
_APPROVED_PAPER_WRITES = frozenset(
    {"place_paper_order", "cancel_paper_order", "reset_paper_account"}
)


async def authorize_approved_paper_write(request: PermissionRequest) -> bool:
    """Allow only the exact effective payload bound to this trusted call id."""
    if request.capability_name not in _APPROVED_PAPER_WRITES:
        return False
    approved = request.context.approved_input
    if approved is None:
        return False
    try:
        requested = json.dumps(
            request.input,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        effective = json.dumps(
            dict(approved.effective),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        return False
    return requested == effective


TOOL_RISK_METADATA: dict[str, ToolRiskMetadata] = {
    # Structured/public data and retrieval tools.
    **dict.fromkeys(
        (
            "lookup_ts_code",
            "get_stock_quote",
            "get_financial_statements",
            "get_market_indicators",
            "get_corporate_actions",
            "get_news",
            "web_search",
            "compare_stocks",
            "kb_search",
            "get_daily",
            "get_daily_basic",
            "get_stock_daily",
            "get_index_daily",
            "get_fund_nav",
            "get_sector_daily",
            "get_portfolio_positions",
            "trade_cal",
            "get_pe_history",
            "get_forecast",
            "get_financials",
            "get_dividend_history",
            "get_balance_sheet",
            "get_cashflow",
            "get_holder_change",
            "get_money_flow",
            "read_cached_result",
            "search_tools",
        ),
        _READ,
    ),
    "memory_search": ToolRiskMetadata(RiskLevel.LOW, CapabilityType.MEMORY, True, True),
    "get_paper_account": _READ,
    "list_paper_orders": _READ,
    "get_paper_order": _READ,
    "get_market_entitlements": _READ,
    "check_order_eligibility": _READ,
    "get_entitlement_application_link": _READ,
    "manage_watchlist": ToolRiskMetadata(
        RiskLevel.LOW,
        CapabilityType.DATA_TOOL,
        False,
        True,
        concurrency_group="paper_state_mutation",
    ),
    "place_paper_order": ToolRiskMetadata(
        RiskLevel.HIGH,
        CapabilityType.DATA_TOOL,
        False,
        False,
        concurrency_group="paper_state_mutation",
    ),
    "cancel_paper_order": ToolRiskMetadata(
        RiskLevel.HIGH,
        CapabilityType.DATA_TOOL,
        False,
        False,
        concurrency_group="paper_state_mutation",
    ),
    "reset_paper_account": ToolRiskMetadata(
        RiskLevel.HIGH,
        CapabilityType.DATA_TOOL,
        False,
        False,
        concurrency_group="paper_state_mutation",
    ),
    "load_skill": ToolRiskMetadata(
        RiskLevel.LOW,
        CapabilityType.SKILL,
        False,
        False,
        concurrency_group="chat_state_mutation",
    ),
    "dispatch_subagents": ToolRiskMetadata(RiskLevel.LOW, CapabilityType.SUBAGENT, True, False),
    # These mutate state or execute code, but already have a concrete system
    # control that is independently enforced by the tool implementation.
    "memory_write": ToolRiskMetadata(
        RiskLevel.HIGH,
        CapabilityType.MEMORY,
        False,
        False,
        "evidence_quote_validation",
        "chat_state_mutation",
    ),
    "run_skill_script": ToolRiskMetadata(
        RiskLevel.HIGH,
        CapabilityType.SKILL,
        False,
        False,
        "sandboxed_execution",
        "sandbox",
    ),
    "run_python": ToolRiskMetadata(
        RiskLevel.HIGH,
        CapabilityType.DATA_TOOL,
        False,
        False,
        "sandboxed_execution",
        "sandbox",
    ),
    "offer_deep_research": ToolRiskMetadata(
        RiskLevel.MEDIUM,
        CapabilityType.DATA_TOOL,
        False,
        False,
        "bounded_state_transition",
        "chat_state_mutation",
    ),
}


class ToolRiskPolicy:
    """Build runtime definitions and resolve ASK without pretending a UI exists."""

    def __init__(self, authorization_callback: AuthorizationCallback | None = None) -> None:
        self._authorization_callback = authorization_callback

    def metadata_for(self, tool: Tool) -> ToolRiskMetadata:
        known = TOOL_RISK_METADATA.get(tool.name)
        if known is not None:
            return known
        declared = getattr(tool, "runtime_risk_metadata", None)
        if isinstance(declared, ToolRiskMetadata):
            return declared
        if isinstance(tool, InProcessTool):
            return ToolRiskMetadata(
                RiskLevel.MEDIUM,
                CapabilityType.DATA_TOOL,
                False,
                False,
                concurrency_group="chat_state_mutation",
            )
        return ToolRiskMetadata(RiskLevel.MEDIUM, CapabilityType.DATA_TOOL, False, False)

    def definition_for(self, tool: Tool, *, timeout_s: float) -> CapabilityDefinition:
        metadata = self.metadata_for(tool)
        return CapabilityDefinition(
            name=tool.name,
            type=metadata.capability_type,
            input_schema=tool.args_schema.model_json_schema(),
            output_schema=getattr(tool, "output_schema", Tool.output_schema),
            minimum_risk=metadata.risk,
            read_only=metadata.read_only,
            idempotent=metadata.idempotent,
            default_timeout_s=timeout_s,
            max_attempts=metadata.max_attempts,
            concurrency_group=metadata.concurrency_group,
        )

    async def authorize(self, request: PermissionRequest) -> bool:
        metadata = TOOL_RISK_METADATA.get(request.capability_name)
        if metadata is not None and metadata.system_allow_reason is not None:
            return True
        if self._authorization_callback is None:
            return False
        return await self._authorization_callback(request)

    def needs_interactive_permission(self, tool: Tool) -> bool:
        metadata = self.metadata_for(tool)
        return metadata.risk in {RiskLevel.MEDIUM, RiskLevel.HIGH} and not (
            metadata.system_allow_reason
        )

    def should_emit_permission_required(self, _tool: Tool, source: object) -> bool:
        """Only an unresolved ASK without a callback is user-actionable."""
        return source == "interactive_ask" and self._authorization_callback is None


__all__ = [
    "TOOL_RISK_METADATA",
    "ToolRiskMetadata",
    "ToolRiskPolicy",
    "authorize_approved_paper_write",
]


def production_visible_capabilities(_state: object) -> frozenset[str]:
    """Explicit worker policy; registration is intersected again by ToolHub."""
    return frozenset(TOOL_RISK_METADATA)


__all__.append("production_visible_capabilities")

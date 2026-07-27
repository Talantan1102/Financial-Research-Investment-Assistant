"""Legacy module — see backend/LEGACY_LAYOUT.md for module-by-module status and v1.x evolution plan.

New features should prefer importing from `app/services/*` (plural, v0.8.x main path).
"""

import os

# The run-control image intentionally carries only control-plane dependencies.
# Normal web/test imports retain the complete legacy barrel below.
_RUN_CONTROL_MINIMAL = os.getenv("RUN_CONTROL_MINIMAL_IMPORTS") == "1"

# c5 memory schema (Plan 1A) — note: physical location is app/memory/, NOT
# app/models/. Absolute import keeps barrel decoupled from c5 directory layout.
if not _RUN_CONTROL_MINIMAL:
    from app.memory.models import (  # noqa: E402  (import after relative imports)
        ChatMemoryEdge,
        ChatMemoryEpisode,
        ChatMemoryNode,
        ChatMemoryWorkingBlock,
    )

if not _RUN_CONTROL_MINIMAL:
    from .chat import (
        ChatAttachment,
        ChatMessage,
        ChatSession,
        ChatSessionContext,
        LongTermMemory,
    )
    from .escalation_record import EscalationRecord  # noqa: F401
    from .industry_data import CompanyData, IndustryStats, PolicyData
    from .knowledge import Document, KnowledgeBase
    from .memory_calibration import ChatMemoryCalibrationRun  # noqa: F401  (Plan 5)
    from .monitoring import (
        DetailStatus,
        MonitoringAlert,
        MonitoringRun,
        MonitoringSignal,
        Notification,
    )
    from .news import BiddingInfo, IndustryNews, NewsCollectionTask
    from .position import Position
    from .position_snapshot import PositionSnapshot  # noqa: F401
    from .research import ResearchCheckpoint
    from .research_report import ResearchReport
else:
    # User's legacy relationships are configured globally by SQLAlchemy even
    # though run-control never queries these tables. Register only their named
    # mapper targets; these modules have no heavyweight runtime dependencies.
    from .chat import ChatSession, LongTermMemory
    from .knowledge import Document, KnowledgeBase
from .paper_account import (
    PaperAccount,
    PaperAccountResetAudit,
    PaperCashLedger,
    PaperHoldingLot,
)
from .paper_order import (
    OrderSide,
    OrderStatus,
    OrderType,
    PaperActionAudit,
    PaperDispatchRecoveryState,
    PaperFill,
    PaperLotReservation,
    PaperMatchPass,
    PaperOrder,
)
from .investor_suitability import (
    ApplicationStatus,
    EntitlementApplication,
    EntitlementStatus,
    InvestorSuitabilityProfile,
    Market,
    MarketAccessRule,
    MarketEntitlement,
    RiskDisclosureAcceptance,
    SuitabilityAssessment,
)
from .run import Run, RunAttempt, RunEvent, RunMessage, RunPause, RunSession
from .run_execution import RunToolExecution, RunUsageRecord
from .run_scheduling import RunOutbox, RunTenantScheduling, RunWorker
from .tenant import Tenant, TenantAuditLog, TenantMembership
from .user import User
from .watchlist import WatchlistAudit, WatchlistItem

if not _RUN_CONTROL_MINIMAL:
    from .subagent_dispatch import SubagentDispatchRun  # noqa: F401
    from .tool_result_cache import ToolResultCacheRow  # noqa: F401
    from .trade import Trade, TradeType

__all__ = [
    "User",
    "Tenant",
    "TenantMembership",
    "TenantAuditLog",
    "RunSession",
    "RunMessage",
    "Run",
    "RunAttempt",
    "RunPause",
    "RunEvent",
    "RunToolExecution",
    "RunUsageRecord",
    "RunWorker",
    "RunTenantScheduling",
    "RunOutbox",
    "PaperAccount",
    "PaperAccountResetAudit",
    "PaperCashLedger",
    "PaperHoldingLot",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "PaperOrder",
    "PaperActionAudit",
    "PaperDispatchRecoveryState",
    "PaperFill",
    "PaperLotReservation",
    "PaperMatchPass",
    "Market",
    "EntitlementStatus",
    "ApplicationStatus",
    "InvestorSuitabilityProfile",
    "MarketAccessRule",
    "SuitabilityAssessment",
    "RiskDisclosureAcceptance",
    "MarketEntitlement",
    "EntitlementApplication",
    "WatchlistItem",
    "WatchlistAudit",
]

if not _RUN_CONTROL_MINIMAL:
    __all__ += [
        "ChatSession",
        "ChatSessionContext",
        "ChatMessage",
        "ChatAttachment",
        "LongTermMemory",
        "KnowledgeBase",
        "Document",
        "IndustryStats",
        "CompanyData",
        "PolicyData",
        "ResearchCheckpoint",
        "ResearchReport",
        "Position",
        "Trade",
        "TradeType",
        "IndustryNews",
        "BiddingInfo",
        "NewsCollectionTask",
        "DetailStatus",
        "MonitoringAlert",
        "MonitoringRun",
        "MonitoringSignal",
        "Notification",
        "EscalationRecord",
        "ChatMemoryEpisode",
        "ChatMemoryNode",
        "ChatMemoryEdge",
        "ChatMemoryWorkingBlock",
        "ChatMemoryCalibrationRun",
        "SubagentDispatchRun",
        "PositionSnapshot",
    ]

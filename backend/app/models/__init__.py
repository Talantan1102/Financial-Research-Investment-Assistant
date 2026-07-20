"""Legacy module — see backend/LEGACY_LAYOUT.md for module-by-module status and v1.x evolution plan.

New features should prefer importing from `app/services/*` (plural, v0.8.x main path).
"""

# c5 memory schema (Plan 1A) — note: physical location is app/memory/, NOT
# app/models/. Absolute import keeps barrel decoupled from c5 directory layout.
from app.memory.models import (  # noqa: E402  (import after relative imports)
    ChatMemoryEdge,
    ChatMemoryEpisode,
    ChatMemoryNode,
    ChatMemoryWorkingBlock,
)

from .chat import (
    ChatAttachment,
    ChatMessage,
    ChatSession,
    ChatSessionContext,
    ChatTask,
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
    PaperFill,
    PaperLotReservation,
    PaperMatchPass,
    PaperOrder,
)
from .position import Position
from .position_snapshot import PositionSnapshot  # noqa: F401
from .research import ResearchCheckpoint
from .research_report import ResearchReport
from .subagent_dispatch import SubagentDispatchRun  # noqa: F401
from .tool_result_cache import ToolResultCacheRow  # noqa: F401
from .trade import Trade, TradeType
from .user import User

__all__ = [
    "User",
    "ChatSession",
    "ChatSessionContext",
    "ChatMessage",
    "ChatAttachment",
    "ChatTask",
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
    "PaperAccount",
    "PaperAccountResetAudit",
    "PaperCashLedger",
    "PaperHoldingLot",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "PaperOrder",
    "PaperFill",
    "PaperLotReservation",
    "PaperMatchPass",
    "DetailStatus",
    "MonitoringAlert",
    "MonitoringRun",
    "MonitoringSignal",
    "Notification",
    "EscalationRecord",
    # c5 memory(Plan 1A)
    "ChatMemoryEpisode",
    "ChatMemoryNode",
    "ChatMemoryEdge",
    "ChatMemoryWorkingBlock",
    # c5 memory Plan 5 audit
    "ChatMemoryCalibrationRun",
    # chat 子 agent 派发审计(2026-06-11)
    "SubagentDispatchRun",
    # portfolio 每日持仓快照(Task 2)
    "PositionSnapshot",
]

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

from .chat import ChatAttachment, ChatMessage, ChatSession, ChatTask, LongTermMemory
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
from .research import ResearchCheckpoint
from .research_report import ResearchReport
from .tool_result_cache import ToolResultCacheRow  # noqa: F401
from .trade import Trade, TradeType
from .user import User

__all__ = [
    "User",
    "ChatSession",
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
]

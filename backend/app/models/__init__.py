"""Legacy module — see backend/LEGACY_LAYOUT.md for module-by-module status and v1.x evolution plan.

New features should prefer importing from `app/services/*` (plural, v0.8.x main path).
"""

from .chat import ChatAttachment, ChatMessage, ChatSession, LongTermMemory
from .industry_data import CompanyData, IndustryStats, PolicyData
from .knowledge import Document, KnowledgeBase
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
]

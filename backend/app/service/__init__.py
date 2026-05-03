"""Legacy module — see backend/LEGACY_LAYOUT.md for module-by-module status and v1.x evolution plan.

New features should prefer importing from `app/services/*` (plural, v0.8.x main path).
"""

from .chart_generator import ChartGenerator, create_chart_generator

# TODO(v0 plan Task 1): chat_service deleted (replaced by Task 11 chat agent)
# from .chat_service import ChatService
from .config import ServiceConfig
from .document_service import DocumentService

# TODO(v0 plan Task 1): dr_g deleted (ResearchService archived)
# from .dr_g import ResearchService
from .policy_search_service import PolicySearchService

# TODO(v0 plan Task 1): react_controller deleted
# from .react_controller import ReActController, create_default_tools
from .session_service import SessionService

# TODO(v0 plan Task 1): smart_analyzer deleted
# from .smart_analyzer import SmartDataAnalyzer, create_smart_analyzer
from .text2sql_service import Text2SQLService, create_text2sql_service
from .tool_executor import ToolExecutor, create_tool_executor
from .web_search_service import WebSearchService

__all__ = [
    "DocumentService",
    "ServiceConfig",
    "WebSearchService",
    # "ChatService",  # TODO(v0 plan Task 1): deleted
    "SessionService",
    "PolicySearchService",
    # "ResearchService",  # TODO(v0 plan Task 1): deleted
    # ReAct 组件 — TODO(v0 plan Task 1): deleted
    # "ReActController",
    # "create_default_tools",
    "ToolExecutor",
    "create_tool_executor",
    "Text2SQLService",
    "create_text2sql_service",
    # "SmartDataAnalyzer",  # TODO(v0 plan Task 1): deleted
    # "create_smart_analyzer",  # TODO(v0 plan Task 1): deleted
    "ChartGenerator",
    "create_chart_generator",
]

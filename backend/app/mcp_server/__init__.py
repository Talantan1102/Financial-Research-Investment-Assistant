"""MCP Server 初始化模块"""

from app.mcp_server.server import FinancialResearchMCPServer, get_mcp_server
from app.mcp_server.control_flow.engine import (
    ControlFlowEngine,
    ControlFlowContext,
    ControlFlowType,
    ToolCall,
    ExecutionResult
)
from app.mcp_server.error_handler import (
    ErrorHandler,
    ErrorInfo,
    ErrorType,
    ErrorSeverity,
    get_error_handler,
    handle_error
)

# Skills
from app.mcp_server.skills.base import BaseSkill, ToolParameter, ToolResult, ToolDefinition
from app.mcp_server.skills.market_data import MarketDataSkill
from app.mcp_server.skills.financial_analysis import FinancialAnalysisSkill
from app.mcp_server.skills.sector_analysis import SectorAnalysisSkill
from app.mcp_server.skills.risk_assessment import RiskAssessmentSkill
from app.mcp_server.skills.deep_research import DeepResearchSkill
from app.mcp_server.skills.web_research import WebResearchSkill
from app.mcp_server.skills.data_analysis import DataAnalysisSkill

__all__ = [
    # Server
    "FinancialResearchMCPServer",
    "get_mcp_server",
    
    # Control Flow
    "ControlFlowEngine",
    "ControlFlowContext",
    "ControlFlowType",
    "ToolCall",
    "ExecutionResult",
    
    # Error Handler
    "ErrorHandler",
    "ErrorInfo",
    "ErrorType",
    "ErrorSeverity",
    "get_error_handler",
    "handle_error",
    
    # Skills
    "BaseSkill",
    "ToolParameter",
    "ToolResult",
    "ToolDefinition",
    "MarketDataSkill",
    "FinancialAnalysisSkill",
    "SectorAnalysisSkill",
    "RiskAssessmentSkill",
    "DeepResearchSkill",
    "WebResearchSkill",
    "DataAnalysisSkill",
]

__version__ = "2.0.0"

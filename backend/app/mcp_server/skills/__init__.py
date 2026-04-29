"""Skills 模块初始化"""

from app.mcp_server.skills.base import BaseSkill, ToolDefinition, ToolParameter, ToolResult, tool
from app.mcp_server.skills.data_analysis import DataAnalysisSkill
from app.mcp_server.skills.deep_research import DeepResearchSkill
from app.mcp_server.skills.financial_analysis import FinancialAnalysisSkill
from app.mcp_server.skills.market_data import MarketDataSkill
from app.mcp_server.skills.risk_assessment import RiskAssessmentSkill
from app.mcp_server.skills.sector_analysis import SectorAnalysisSkill
from app.mcp_server.skills.web_research import WebResearchSkill

__all__ = [
    "BaseSkill",
    "ToolParameter",
    "ToolResult",
    "ToolDefinition",
    "tool",
    "MarketDataSkill",
    "FinancialAnalysisSkill",
    "SectorAnalysisSkill",
    "RiskAssessmentSkill",
    "DeepResearchSkill",
    "WebResearchSkill",
    "DataAnalysisSkill",
]

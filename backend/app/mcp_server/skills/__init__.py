"""Skills 模块初始化"""

from app.mcp_server.skills.base import BaseSkill, ToolParameter, ToolResult, ToolDefinition, tool
from app.mcp_server.skills.market_data import MarketDataSkill
from app.mcp_server.skills.financial_analysis import FinancialAnalysisSkill
from app.mcp_server.skills.sector_analysis import SectorAnalysisSkill
from app.mcp_server.skills.risk_assessment import RiskAssessmentSkill
from app.mcp_server.skills.deep_research import DeepResearchSkill
from app.mcp_server.skills.web_research import WebResearchSkill
from app.mcp_server.skills.data_analysis import DataAnalysisSkill

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

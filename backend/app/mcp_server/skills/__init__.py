# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""MCP Server Skills 包"""

from app.mcp_server.skills.base import BaseSkill, ToolDefinition, ToolParameter, ToolResult
from app.mcp_server.skills.market_data import MarketDataSkill
from app.mcp_server.skills.financial_analysis import FinancialAnalysisSkill
from app.mcp_server.skills.risk_assessment import RiskAssessmentSkill
from app.mcp_server.skills.deep_research import DeepResearchSkill
from app.mcp_server.skills.deep_research_split import DeepResearchSkillSplit
from app.mcp_server.skills.web_research import WebResearchSkill
from app.mcp_server.skills.data_analysis import DataAnalysisSkill
from app.mcp_server.skills.sector_analysis import SectorAnalysisSkill

__all__ = [
    "BaseSkill",
    "ToolDefinition",
    "ToolParameter",
    "ToolResult",
    "MarketDataSkill",
    "FinancialAnalysisSkill",
    "RiskAssessmentSkill",
    "DeepResearchSkill",
    "DeepResearchSkillSplit",
    "WebResearchSkill",
    "DataAnalysisSkill",
    "SectorAnalysisSkill",
]

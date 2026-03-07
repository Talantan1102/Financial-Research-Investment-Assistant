"""
MCP Server Skills 包

包含所有Financial Skills的实现
"""

from app.mcp_server.skills.base import Skill, tool, ToolResult
from app.mcp_server.skills.market_data import MarketDataSkill

__all__ = [
    "Skill",
    "tool",
    "ToolResult",
    "MarketDataSkill",
]

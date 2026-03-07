# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""MCP Server Skills 包"""

from .base import BaseSkill, ToolDefinition, ToolParameter, ToolResult, Skill, tool
from .market_data import MarketDataSkill

__all__ = [
    "BaseSkill",
    "Skill",  # 别名
    "tool",
    "ToolDefinition", 
    "ToolParameter",
    "ToolResult",
    "MarketDataSkill",
]
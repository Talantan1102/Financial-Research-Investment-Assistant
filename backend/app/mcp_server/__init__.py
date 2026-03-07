# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""MCP Server 包

金融研投助手 MCP Server 实现，基于 Model Context Protocol。
"""

from .server import FinancialMCPServer, create_server, main
from .config import get_config, MCPServerConfig
from .skills import BaseSkill, MarketDataSkill, ToolDefinition, ToolParameter, ToolResult

__version__ = "1.0.0"

__all__ = [
    "FinancialMCPServer",
    "create_server",
    "main",
    "get_config",
    "MCPServerConfig",
    "BaseSkill",
    "MarketDataSkill",
    "ToolDefinition",
    "ToolParameter", 
    "ToolResult",
]
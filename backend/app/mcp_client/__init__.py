"""
MCP Client 包

提供 MCP Client 和 ToolAdapter，用于连接 MCP Server 并集成到应用中。

主要组件：
- MCPClient: 通过 STDIO 连接到 MCP Server 的客户端
- ToolAdapter: 封装 MCPClient，提供与 StockService 兼容的接口

使用示例：
    from app.mcp_client import MCPClient, ToolAdapter

    # 创建客户端
    client = MCPClient("backend/app/mcp_server/server.py")
    await client.connect()

    # 创建适配器（支持降级）
    adapter = ToolAdapter(mcp_client=client, fallback_enabled=True)
    result = await adapter.get_stock_by_code("600519")

    # 清理
    await client.disconnect()
"""

from app.mcp_client.adapter import ToolAdapter
from app.mcp_client.client import MCPClient

__all__ = ["MCPClient", "ToolAdapter"]

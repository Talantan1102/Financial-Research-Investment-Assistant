#!/usr/bin/env python3
"""
AgentFlow MCP Server 启动脚本

原生 MCP Resources + Tools 架构
与金融研投助手 MCP Server 保持完全一致

使用方法:
    python -m sandbox.server.mcp_server

或:
    python sandbox/server/mcp_server.py
"""

import sys
import asyncio
import logging
from pathlib import Path

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("AgentFlowMCPServer")

# 添加项目路径
_current_file = Path(__file__).resolve()
_project_root = _current_file.parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

async def main():
    """主入口"""
    try:
        from mcp.server.stdio import stdio_server
        from sandbox.server.backends.resources import AgentFlowMCPServer
        
        # 创建并配置 MCP Server
        server = AgentFlowMCPServer(server_name="AgentFlow")
        
        # Warmup - 初始化所有 Skills
        await server.warmup()
        
        logger.info("=" * 60)
        logger.info("AgentFlow MCP Server 启动成功")
        logger.info("架构: 原生 MCP Resources + Tools")
        logger.info("流程: list_resources() -> read_resource() -> list_tools() -> call_tool()")
        logger.info("=" * 60)
        
        # 启动 MCP Server (stdio 模式)
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream)
            
    except ImportError as e:
        logger.error(f"导入错误: {e}")
        logger.error("请确保已安装 mcp SDK: pip install mcp")
        sys.exit(1)
    except Exception as e:
        logger.error(f"启动失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

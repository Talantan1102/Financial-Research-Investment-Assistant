#!/usr/bin/env python3
"""
MCP Server 主入口

Financial Research Assistant 的 MCP Server 实现
支持 STDIO 传输协议
"""

import asyncio
import json
import logging
import sys
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional

# MCP SDK 导入
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import (
        TextContent,
        Tool,
        EmptyResult,
        CallToolRequestParams,
    )
except ImportError:
    print("Error: mcp package not installed. Run: pip install mcp", file=sys.stderr)
    sys.exit(1)

# 项目导入
from app.mcp_server.config import get_config, Config
from app.mcp_server.skills import MarketDataSkill, Skill


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("mcp-server")


class FinancialMCPServer:
    """
    Financial Research Assistant MCP Server
    
    管理所有Financial Skills的注册和调用
    """
    
    def __init__(self, config: Config):
        """
        初始化MCP Server
        
        Args:
            config: 服务器配置
        """
        self.config = config
        self.server = Server(config.mcp_server.name)
        self.skills: Dict[str, Skill] = {}
        self._initialized = False
        
        # 注册MCP协议处理器
        self._register_handlers()
    
    def _register_handlers(self) -> None:
        """注册MCP协议处理器"""
        
        @self.server.list_tools()
        async def list_tools() -> List[Tool]:
            """列出所有可用工具"""
            tools = []
            for skill in self.skills.values():
                for tool_def in skill.get_tools():
                    tools.append(Tool(
                        name=tool_def["name"],
                        description=tool_def["description"],
                        inputSchema=tool_def["inputSchema"]
                    ))
            return tools
        
        @self.server.call_tool()
        async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
            """调用指定工具"""
            logger.info(f"Calling tool: {name} with args: {arguments}")
            
            # 查找工具所属Skill
            skill = self._find_skill_for_tool(name)
            if not skill:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": f"Tool '{name}' not found"
                    }, ensure_ascii=False)
                )]
            
            # 执行工具
            result = await skill.execute_tool(name, arguments)
            
            return [TextContent(
                type="text",
                text=json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
            )]
    
    def _find_skill_for_tool(self, tool_name: str) -> Optional[Skill]:
        """
        查找工具所属的Skill
        
        Args:
            tool_name: 工具名称
            
        Returns:
            Skill实例或None
        """
        for skill in self.skills.values():
            if skill.has_tool(tool_name):
                return skill
        return None
    
    def register_skill(self, skill: Skill) -> None:
        """
        注册Skill
        
        Args:
            skill: Skill实例
        """
        self.skills[skill.name] = skill
        logger.info(f"Registered skill: {skill.name} with tools: {skill.get_tool_names()}")
    
    async def initialize(self) -> bool:
        """
        初始化Server和所有Skills
        
        Returns:
            是否初始化成功
        """
        try:
            logger.info(f"Initializing {self.config.mcp_server.name} v{self.config.mcp_server.version}")
            logger.info(f"Transport: {self.config.mcp_server.transport}")
            
            # 注册所有Skills
            await self._register_skills()
            
            # 初始化所有Skills
            for name, skill in self.skills.items():
                success = await skill.initialize()
                if not success:
                    logger.error(f"Failed to initialize skill: {name}")
                    return False
            
            self._initialized = True
            logger.info(f"Server initialized successfully with {len(self.skills)} skills")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize server: {e}")
            return False
    
    async def _register_skills(self) -> None:
        """注册所有内置Skills"""
        # 注册MarketData Skill
        market_data_skill = MarketDataSkill()
        self.register_skill(market_data_skill)
        
        # 可以在这里注册更多Skills
        # e.g., self.register_skill(DeepResearchSkill())
        
        logger.info(f"Total skills registered: {len(self.skills)}")
    
    async def cleanup(self) -> None:
        """清理资源"""
        logger.info("Cleaning up server...")
        for name, skill in self.skills.items():
            try:
                await skill.cleanup()
                logger.info(f"Cleaned up skill: {name}")
            except Exception as e:
                logger.error(f"Error cleaning up skill {name}: {e}")
        
        self._initialized = False
        logger.info("Server cleanup completed")
    
    async def run_stdio(self) -> None:
        """
        运行STDIO传输模式的Server
        """
        if not self._initialized:
            success = await self.initialize()
            if not success:
                logger.error("Server initialization failed")
                sys.exit(1)
        
        logger.info("Starting STDIO server...")
        
        try:
            async with stdio_server(server=self.server) as (read_stream, write_stream):
                logger.info("STDIO server started, waiting for connections...")
                # Server 会自动处理连接，这里保持运行
                await asyncio.Future()  # 永远等待
        except Exception as e:
            logger.error(f"Server error: {e}")
        finally:
            await self.cleanup()
    
    def get_server_info(self) -> Dict[str, Any]:
        """
        获取Server信息
        
        Returns:
            Server信息字典
        """
        return {
            "name": self.config.mcp_server.name,
            "version": self.config.mcp_server.version,
            "initialized": self._initialized,
            "skills": {name: skill.to_dict() for name, skill in self.skills.items()},
            "total_tools": sum(len(skill.get_tool_names()) for skill in self.skills.values())
        }


async def main():
    """
    MCP Server 入口函数
    """
    # 加载配置
    config = get_config()
    
    # 检查Tushare配置
    if not config.tushare.is_valid():
        logger.warning("Tushare API token not configured. Market data features will not work.")
        logger.warning("Set TUSHARE_API_TOKEN environment variable.")
    
    # 创建并启动Server
    server = FinancialMCPServer(config)
    
    # 根据配置选择传输模式
    transport = config.mcp_server.transport.lower()
    
    if transport == "stdio":
        await server.run_stdio()
    else:
        logger.error(f"Unsupported transport: {transport}")
        logger.error("Currently only 'stdio' transport is supported")
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)

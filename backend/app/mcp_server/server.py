# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""MCP Server 主入口

使用 MCP Python SDK 实现，支持 STDIO 传输。
注册 MarketData Skill 提供股票行情查询能力。
"""

import sys
import os
import json
import asyncio
import logging
from typing import Dict, Any, List, Optional

# 添加项目根目录到 Python 路径
# 这样可以在作为独立进程启动时正确导入 app 模块
_current_dir = os.path.dirname(os.path.abspath(__file__))
_backend_dir = os.path.dirname(os.path.dirname(_current_dir))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

# MCP SDK
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# 本地导入
from app.mcp_server.skills import (
    MarketDataSkill,
    BaseSkill,
    FinancialAnalysisSkill,
    RiskAssessmentSkill,
    DeepResearchSkill
)
from app.mcp_server.config import get_config


# 配置日志 - 只输出到文件，避免干扰 STDIO 通信
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(os.path.dirname(__file__), 'mcp_server.log'))
        # 移除 StreamHandler(sys.stderr) 以避免干扰 MCP STDIO 通信
    ]
)
logger = logging.getLogger("MCP Server")


class FinancialMCPServer:
    """
    金融研投助手 MCP Server
    
    管理多个 Skill，提供统一的工具发现和调用接口。
    """
    
    def __init__(self):
        self.config = get_config()
        self.skills: Dict[str, BaseSkill] = {}
        self.server = Server(self.config.server_name)
        self._register_handlers()
    
    def register_skill(self, skill: BaseSkill):
        """
        注册 Skill
        
        Args:
            skill: Skill 实例
        """
        self.skills[skill.name] = skill
        logger.info(f"已注册 Skill: {skill.name} ({skill.tool_count} 个工具)")
    
    def _register_handlers(self):
        """注册 MCP Server 处理器"""
        
        @self.server.list_tools()
        async def list_tools() -> List[Tool]:
            """列出所有可用的工具"""
            tools = []
            for skill in self.skills.values():
                for tool_def in skill.discover_tools():
                    tools.append(Tool(
                        name=f"{skill.name}.{tool_def.name}",
                        description=tool_def.description,
                        inputSchema=tool_def.to_json_schema()["parameters"]
                    ))
            logger.info(f"返回工具列表: {len(tools)} 个工具")
            return tools
        
        @self.server.call_tool()
        async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
            """调用指定工具"""
            logger.info(f"调用工具: {name}, 参数: {arguments}")
            
            # 解析 tool name（格式: skill_name.tool_name）
            if "." not in name:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": f"无效的工具名称格式: {name}，期望格式: skill_name.tool_name"
                    }, ensure_ascii=False)
                )]
            
            skill_name, tool_name = name.split(".", 1)
            
            # 查找 Skill
            skill = self.skills.get(skill_name)
            if not skill:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": f"Skill '{skill_name}' 不存在"
                    }, ensure_ascii=False)
                )]
            
            # 检查工具是否存在
            if not skill.has_tool(tool_name):
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": f"工具 '{tool_name}' 不存在于 Skill '{skill_name}'"
                    }, ensure_ascii=False)
                )]
            
            # 执行工具
            try:
                result = await skill.execute_tool(tool_name, arguments)
                return [TextContent(
                    type="text",
                    text=json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
                )]
            except Exception as e:
                logger.error(f"工具执行异常: {e}")
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": f"工具执行异常: {str(e)}"
                    }, ensure_ascii=False)
                )]
    
    async def run(self):
        """运行 MCP Server"""
        logger.info(f"启动 MCP Server: {self.config.server_name} v{self.config.server_version}")
        logger.info(f"已注册 {len(self.skills)} 个 Skill")
        
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options()
            )


def create_server() -> FinancialMCPServer:
    """
    创建并配置 MCP Server
    
    Returns:
        配置好的 FinancialMCPServer 实例
    """
    server = FinancialMCPServer()
    
    # 注册 MarketData Skill
    try:
        market_data_skill = MarketDataSkill()
        server.register_skill(market_data_skill)
    except Exception as e:
        logger.warning(f"MarketData Skill 注册失败: {e}")
    
    # 注册 FinancialAnalysis Skill
    try:
        financial_analysis_skill = FinancialAnalysisSkill()
        server.register_skill(financial_analysis_skill)
    except Exception as e:
        logger.warning(f"FinancialAnalysis Skill 注册失败: {e}")
    
    # 注册 RiskAssessment Skill
    try:
        risk_assessment_skill = RiskAssessmentSkill()
        server.register_skill(risk_assessment_skill)
    except Exception as e:
        logger.warning(f"RiskAssessment Skill 注册失败: {e}")

    # 注册 DeepResearch Skill
    try:
        deep_research_skill = DeepResearchSkill()
        server.register_skill(deep_research_skill)
    except Exception as e:
        logger.warning(f"DeepResearch Skill 注册失败: {e}")

    return server


async def main():
    """主入口"""
    server = create_server()
    await server.run()


if __name__ == "__main__":
    asyncio.run(main())

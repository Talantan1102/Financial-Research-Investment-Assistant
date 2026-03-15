"""
统一版金融研投助手 Backend for AgentFlow

提供与金融研投助手 MCP Server 一致的调用方式：
- 统一入口: execute_skill_tool(skill_name, tool_name, arguments)
- 支持所有 7 个 Skill 共 40 个工具
- 完全复用金融研投助手的 Skill 实现
"""

import os
import sys
import json
import asyncio
import logging
from typing import Dict, Any, List, Optional
from pathlib import Path

# 添加金融研投助手到路径
FRA_PATH = Path(__file__).parent.parent.parent / "financial-research-assistant" / "backend"
sys.path.insert(0, str(FRA_PATH))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("UnifiedFinanceBackend")


class UnifiedSkillClient:
    """
    统一 Skill 客户端
    
    直接调用金融研投助手的所有 MCP Server Skills，
    提供与 MCP Server 一致的 execute_skill_tool 接口
    """
    
    def __init__(self):
        self.skills = {}
        self._initialized = False
        self._skill_tools_cache = {}  # 缓存每个 skill 的工具列表
    
    async def initialize(self):
        """初始化所有 7 个 Skills"""
        if self._initialized:
            return
        
        try:
            from app.mcp_server.skills import (
                MarketDataSkill,
                FinancialAnalysisSkill,
                RiskAssessmentSkill,
                SectorAnalysisSkill,
                DataAnalysisSkill,
                WebResearchSkill,
                DeepResearchSkillSplit
            )
            
            # 注册所有 7 个 Skills
            self.skills['market_data'] = MarketDataSkill()
            self.skills['financial_analysis'] = FinancialAnalysisSkill()
            self.skills['risk_assessment'] = RiskAssessmentSkill()
            self.skills['sector_analysis'] = SectorAnalysisSkill()
            self.skills['data_analysis'] = DataAnalysisSkill()
            self.skills['web_research'] = WebResearchSkill()
            self.skills['deep_research'] = DeepResearchSkillSplit()
            
            # 预加载所有工具定义到缓存
            for skill_name, skill in self.skills.items():
                self._skill_tools_cache[skill_name] = list(skill._tools.keys())
            
            self._initialized = True
            logger.info(f"✅ 统一 Skill 客户端初始化完成: {list(self.skills.keys())}")
            
        except Exception as e:
            logger.error(f"❌ 初始化 Skills 失败: {e}")
            raise
    
    async def execute_skill_tool(self, skill_name: str, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        统一工具调用接口（与金融研投助手 MCP Server 完全一致）
        
        Args:
            skill_name: Skill 名称，如 'market_data', 'financial_analysis' 等
            tool_name: 工具名称，如 'get_quote', 'calculate_financial_ratios' 等
            arguments: 工具参数字典
            
        Returns:
            工具执行结果，格式: {"success": bool, "result": Any, "error": str}
        """
        if not self._initialized:
            await self.initialize()
        
        # 检查 Skill 是否存在
        skill = self.skills.get(skill_name)
        if not skill:
            return {
                "success": False,
                "error": f"Skill '{skill_name}' 不存在。可用 Skills: {list(self.skills.keys())}",
                "result": None
            }
        
        # 检查工具是否存在
        tool_handler = skill._tools.get(tool_name)
        if not tool_handler:
            available_tools = list(skill._tools.keys())
            return {
                "success": False,
                "error": f"工具 '{tool_name}' 在 Skill '{skill_name}' 中不存在。可用工具: {available_tools}",
                "result": None
            }
        
        # 执行工具
        try:
            logger.info(f"🛠️  执行工具: {skill_name}:{tool_name}, 参数: {arguments}")
            result = await tool_handler(**arguments)
            
            # 统一返回格式
            return {
                "success": True,
                "result": result.data if hasattr(result, 'data') else result,
                "skill": skill_name,
                "tool": tool_name,
                "error": None
            }
            
        except Exception as e:
            logger.error(f"❌ 工具执行失败 {skill_name}:{tool_name}: {e}")
            return {
                "success": False,
                "error": str(e),
                "skill": skill_name,
                "tool": tool_name,
                "result": None
            }
    
    def get_skill_tools(self, skill_name: str) -> List[Dict[str, Any]]:
        """
        获取指定 Skill 的所有工具定义
        
        Args:
            skill_name: Skill 名称
            
        Returns:
            工具定义列表
        """
        if not self._initialized:
            return []
        
        skill = self.skills.get(skill_name)
        if not skill:
            return []
        
        tools = []
        for tool_name, tool_def in skill._tool_definitions.items():
            tools.append({
                "name": tool_name,
                "description": tool_def.description,
                "parameters": [
                    {
                        "name": param.name,
                        "type": param.type,
                        "description": param.description,
                        "required": param.required,
                        "default": param.default,
                        "enum": param.enum
                    }
                    for param in tool_def.parameters
                ]
            })
        
        return tools
    
    def get_all_skills(self) -> List[str]:
        """获取所有可用的 Skill 名称列表"""
        return list(self.skills.keys())
    
    def get_all_tools(self) -> List[Dict[str, Any]]:
        """
        获取所有 Skill 的所有工具定义
        
        Returns:
            完整的工具定义列表，格式: [{"skill": str, "tool": str, "description": str, ...}]
        """
        if not self._initialized:
            return []
        
        all_tools = []
        for skill_name, skill in self.skills.items():
            for tool_name, tool_def in skill._tool_definitions.items():
                all_tools.append({
                    "name": f"{skill_name}:{tool_name}",
                    "skill": skill_name,
                    "tool": tool_name,
                    "description": tool_def.description,
                    "parameters": [
                        {
                            "name": param.name,
                            "type": param.type,
                            "description": param.description,
                            "required": param.required,
                            "default": param.default,
                            "enum": param.enum
                        }
                        for param in tool_def.parameters
                    ]
                })
        
        return all_tools


class UnifiedFinanceBackend:
    """
    统一版金融研投助手 Backend for AgentFlow
    
    提供与金融研投助手 MCP Server 完全一致的调用方式：
    - execute_skill_tool(skill_name, tool_name, arguments)
    
    支持所有 7 个 Skill 共 40 个工具：
    - market_data (11个工具)
    - financial_analysis (7个工具)  
    - sector_analysis (7个工具)
    - risk_assessment (3个工具)
    - data_analysis (4个工具)
    - web_research (5个工具)
    - deep_research (7个工具)
    """
    
    config_class = None  # 不需要额外配置类
    
    def __init__(self):
        self.skill_client = UnifiedSkillClient()
        self._initialized = False
    
    async def initialize(self, config: Dict[str, Any] = None):
        """
        初始化 Backend
        
        Args:
            config: 配置字典（可选，用于兼容性）
        """
        await self.skill_client.initialize()
        self._initialized = True
        logger.info("✅ UnifiedFinanceBackend 初始化完成")
    
    # ============ 统一工具调用接口 ============
    
    async def execute_skill_tool(self, skill_name: str, tool_name: str, arguments: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        统一工具调用接口（与金融研投助手 MCP Server 完全一致）
        
        Args:
            skill_name: Skill 名称，如 'market_data', 'financial_analysis'
            tool_name: 工具名称，如 'get_quote', 'calculate_financial_ratios'
            arguments: 工具参数字典（可选，默认为空字典）
            
        Returns:
            工具执行结果
            
        Examples:
            >>> await backend.execute_skill_tool(
            ...     skill_name='market_data',
            ...     tool_name='get_quote',
            ...     arguments={'symbol': '600519'}
            ... )
            
            >>> await backend.execute_skill_tool(
            ...     skill_name='financial_analysis',
            ...     tool_name='get_financial_report',
            ...     arguments={'symbol': '600519', 'report_type': 'income'}
            ... )
        """
        if arguments is None:
            arguments = {}
        
        return await self.skill_client.execute_skill_tool(skill_name, tool_name, arguments)
    
    # ============ 工具定义导出 ============
    
    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """
        获取所有工具定义（用于 AgentFlow 配置）
        
        Returns:
            工具定义列表，格式与金融研投助手一致
        """
        return self.skill_client.get_all_tools()


# ============ AgentFlow 兼容接口 ============

class AgentFlowUnifiedFinanceBackend:
    """
    AgentFlow 兼容的 Backend 包装器
    
    直接代理到 UnifiedFinanceBackend
    """
    
    def __init__(self):
        self.backend = UnifiedFinanceBackend()
    
    async def initialize(self, config: Dict[str, Any] = None):
        await self.backend.initialize(config)
    
    async def execute_skill_tool(self, skill_name: str, tool_name: str, arguments: Dict[str, Any] = None):
        """统一工具调用接口"""
        return await self.backend.execute_skill_tool(skill_name, tool_name, arguments)
    
    def get_tool_definitions(self):
        return self.backend.get_tool_definitions()


# ============ 工具定义导出 ============

def get_tool_definitions() -> List[Dict[str, Any]]:
    """
    获取统一版工具定义列表（用于 AgentFlow 配置）
    
    Returns:
        完整的工具定义列表，包含所有 7 个 Skill 共 40 个工具
    """
    # 创建临时客户端获取工具定义（不初始化 Skill）
    client = UnifiedSkillClient()
    
    # 手动初始化以获取工具定义
    async def _get_tools():
        await client.initialize()
        return client.get_all_tools()
    
    # 同步运行获取结果
    try:
        return asyncio.run(_get_tools())
    except:
        # 如果无法异步运行，返回空列表
        return []


if __name__ == "__main__":
    # 测试代码
    async def test():
        backend = UnifiedFinanceBackend()
        await backend.initialize()
        
        # 测试调用 market_data:get_quote
        result = await backend.execute_skill_tool(
            skill_name='market_data',
            tool_name='search_stock',
            arguments={'keyword': '茅台'}
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        
        # 获取所有工具定义
        tools = backend.get_tool_definitions()
        print(f"\n总共 {len(tools)} 个工具")
        for tool in tools[:5]:
            print(f"  - {tool['name']}: {tool['description'][:50]}...")
    
    asyncio.run(test())

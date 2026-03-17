"""
统一版金融研投助手 Backend for AgentFlow

提供与金融研投助手 MCP Server 完全一致的三轮渐进式披露流程：
1. skill(name) — 获取 SKILL.md 文档
2. get_skill_tools(name) — 获取 Skill 的工具列表
3. execute_skill_tool(skill_name, tool_name, arguments) — 执行具体工具

支持所有 7 个 Skill 共 40+ 工具
"""

import os
import sys
import json
import asyncio
import logging
from typing import Dict, Any, List, Optional
from pathlib import Path

# 添加金融研投助手到路径
# unified_finance.py 位置: sandbox/server/backends/resources/unified_finance.py
# external 目录: AgentFlow 的 parent 目录
_EXTERNAL_PATH = Path(__file__).parent.parent.parent.parent.parent.parent
FRA_PATH = _EXTERNAL_PATH / "financial-research-assistant" / "backend"
sys.path.insert(0, str(FRA_PATH))

from sandbox.server.backends.base import Backend
from sandbox.server.core import tool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("UnifiedFinanceBackend")


class UnifiedFinanceBackend(Backend):
    """
    金融研投助手 Backend for AgentFlow — 渐进式披露三轮架构
    
    与金融研投助手 MCP Server 完全一致：
    - skill(name) — 加载 SKILL.md
    - get_skill_tools(name) — 获取工具 JSON Schema
    - execute_skill_tool(skill_name, tool_name, arguments) — 执行工具
    """
    
    name = "unified_finance"
    description = "金融研投助手统一 Backend - 渐进式披露三轮架构"
    config_class = None
    
    def __init__(self, config=None):
        super().__init__(config)
        self.skills = {}
        self.skills_dir = Path(FRA_PATH) / "claude_skills"
    
    async def warmup(self):
        """Warmup - 初始化所有 7 个 Skills"""
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
            
            self.skills = {
                'market_data': MarketDataSkill(),
                'financial_analysis': FinancialAnalysisSkill(),
                'risk_assessment': RiskAssessmentSkill(),
                'sector_analysis': SectorAnalysisSkill(),
                'data_analysis': DataAnalysisSkill(),
                'web_research': WebResearchSkill(),
                'deep_research': DeepResearchSkillSplit(),
            }
            
            logger.info(f"✅ UnifiedFinanceBackend warmup 完成: {list(self.skills.keys())}")
            
        except Exception as e:
            logger.error(f"❌ warmup 失败: {e}")
            # 不抛出异常，让 server 可以继续启动
            # 工具方法会在调用时处理错误
            logger.warning("⚠️ Backend 以降级模式运行，部分功能可能不可用")
    
    # ============ Round 1: Skill 选择 ============
    
    @tool("unified_finance:skill")
    def skill(self, name: str) -> Dict[str, Any]:
        """
        加载指定 Skill 的详细说明文档（SKILL.md）
        
        可用 skills: market_data(市场数据), financial_analysis(财务分析), 
        sector_analysis(行业分析), risk_assessment(风险评估), 
        data_analysis(数据分析), web_research(网络研究), deep_research(深度研究)
        
        Args:
            name: Skill 名称
        """
        skill_path = self.skills_dir / name / "SKILL.md"
        
        if not skill_path.exists():
            available = [d.name for d in self.skills_dir.iterdir() if d.is_dir()]
            return {
                "code": -1,
                "message": f"Skill '{name}' 不存在。可用: {available}",
                "data": None
            }
        
        try:
            content = skill_path.read_text(encoding='utf-8')
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "skill": name,
                    "content": content
                }
            }
        except Exception as e:
            return {
                "code": -1,
                "message": str(e),
                "data": None
            }
    
    # ============ Round 2: 工具发现 ============
    
    @tool("unified_finance:get_skill_tools")
    def get_skill_tools(self, name: str) -> Dict[str, Any]:
        """
        获取指定 Skill 下所有工具的 JSON Schema 定义
        
        建议先调用 skill 了解业务，再调用此工具获取具体工具
        
        Args:
            name: Skill 名称
        """
        skill = self.skills.get(name)
        if not skill:
            return {
                "code": -1,
                "message": f"Skill '{name}' 未注册。可用: {list(self.skills.keys())}",
                "data": None
            }
        
        try:
            tools = skill.discover_tools_json()
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "skill": name,
                    "tools": tools,
                    "count": len(tools)
                }
            }
        except Exception as e:
            return {
                "code": -1,
                "message": str(e),
                "data": None
            }
    
    # ============ Round 3: 工具执行 ============
    
    @tool("unified_finance:execute_skill_tool")
    async def execute_skill_tool(self, skill_name: str, tool_name: str, arguments: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        执行指定 Skill 下的具体工具
        
        建议先调用 skill 和 get_skill_tools 了解可用工具后再执行
        
        Args:
            skill_name: Skill 名称，如 'market_data', 'financial_analysis'
            tool_name: 工具名称（不含 skill 前缀），如 'get_quote', 'calculate_financial_ratios'
            arguments: 工具参数，如股票代码、查询条件等
        """
        if arguments is None:
            arguments = {}
        
        skill = self.skills.get(skill_name)
        if not skill:
            return {
                "code": -1,
                "message": f"Skill '{skill_name}' 不存在。可用: {list(self.skills.keys())}",
                "data": None
            }
        
        tool_handler = skill._tools.get(tool_name)
        if not tool_handler:
            available = list(skill._tools.keys())
            return {
                "code": -1,
                "message": f"工具 '{tool_name}' 不存在于 '{skill_name}'。可用: {available}",
                "data": None
            }
        
        try:
            logger.info(f"🛠️ 执行: {skill_name}:{tool_name}, 参数: {arguments}")
            result = await tool_handler(**arguments)
            
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "skill": skill_name,
                    "tool": tool_name,
                    "result": result.data if hasattr(result, 'data') else result
                }
            }
        except Exception as e:
            logger.error(f"❌ 执行失败 {skill_name}:{tool_name}: {e}")
            return {
                "code": -1,
                "message": str(e),
                "data": None
            }


# 兼容导出
AgentFlowUnifiedFinanceBackend = UnifiedFinanceBackend

__all__ = ["UnifiedFinanceBackend", "AgentFlowUnifiedFinanceBackend"]

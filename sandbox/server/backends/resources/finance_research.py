"""
金融研投助手 MCP Server - 金融研投助手模式实现

基于金融研投助手的 3 轮交互流程：
- Round 1: select_skill(skill_name, reason) 选择合适的 Skill
- Round 2: get_skill_tools(name) 获取指定 Skill 的工具列表  
- Round 3: execute_skill_tool(skill_name, tool_name, arguments) 执行具体工具

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
_EXTERNAL_PATH = Path(__file__).parent.parent.parent.parent.parent.parent
FRA_PATH = _EXTERNAL_PATH / "financial-research-assistant" / "backend"
sys.path.insert(0, str(FRA_PATH))

# MCP SDK
from mcp.server import Server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("FinanceResearchBackend")


# 所有可用的 Skills 定义
ALL_SKILLS = {
    "market_data": {
        "description": "股票市场行情数据查询，提供实时股价、PE/PB估值、历史K线、资金流向等",
        "use_when": "股价、行情、涨跌幅、成交量、市盈率(PE)、市净率(PB)、市值、K线、历史走势、资金流向、股票代码查询"
    },
    "financial_analysis": {
        "description": "财务报表分析，计算ROE、ROA、毛利率、净利率等财务指标",
        "use_when": "ROE(净资产收益率)、ROA、营收、净利润、毛利率、资产负债表、现金流量表、同比/环比增长率"
    },
    "sector_analysis": {
        "description": "行业与概念板块分析，支持行业对比、龙头识别、估值对比",
        "use_when": "行业板块、产业链、行业对比、龙头识别、行业估值"
    },
    "risk_assessment": {
        "description": "风险评估，提供波动率、最大回撤、夏普比率等风险指标",
        "use_when": "风险、波动率、最大回撤、夏普比率、投资风险"
    },
    "data_analysis": {
        "description": "数据分析，支持统计计算、对比分析、趋势分析",
        "use_when": "统计、计算、对比、趋势、相关性、均值、标准差"
    },
    "web_research": {
        "description": "网络搜索，获取新闻、公告、舆情等信息",
        "use_when": "新闻、公告、舆情、热点、最新资讯"
    },
    "deep_research": {
        "description": "深度研究，生成研报、综合分析",
        "use_when": "研报、研究报告、深度分析、竞争格局、投资价值"
    }
}


class FinanceResearchBackend:
    """
    金融研投助手 MCP Server（金融研投助手模式）

    3 轮交互流程：
    - Round 1: select_skill(skill_name, reason) -> 选择合适的 Skill
    - Round 2: get_skill_tools(name) -> 获取该 Skill 的所有可用工具
    - Round 3: execute_skill_tool(skill_name, tool_name, arguments) -> 执行具体工具
    """

    name = "finance_research"
    description = "金融研投助手 MCP Server - 支持7个Skill共40+工具"
    version = "2.0.0"

    def __init__(self, config=None):
        self.skills: Dict[str, Any] = {}
        self.skills_dir = Path(FRA_PATH) / "claude_skills"
        self.config = config or {}
        self._server = None
        # 创建原生 MCP Server
        self.server = Server("finance_research")
        self._register_handlers()

    def bind_server(self, server):
        """绑定 HTTPServiceServer 实例（由 Server 调用）"""
        self._server = server

    # ========================================================================
    # Backend 生命周期方法（Server 调用）
    # ========================================================================

    def get_default_config(self) -> Dict[str, Any]:
        """获取默认配置（Server 调用）"""
        return self.config.get("default_config", {}) if isinstance(self.config, dict) else {}

    def get_info(self) -> Dict[str, Any]:
        """获取 Backend 信息（Server 调用）"""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "skills_count": len(self.skills),
            "skills": list(self.skills.keys()) if self.skills else []
        }

    async def initialize(self, worker_id: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """初始化 worker session（Server 调用）"""
        logger.info(f"FinanceResearchBackend initialize for worker: {worker_id}")
        return {
            "worker_id": worker_id,
            "skills_available": list(self.skills.keys())
        }

    async def cleanup(self, worker_id: str, session_info: Dict[str, Any]):
        """清理 worker 资源（Server 调用）"""
        logger.info(f"FinanceResearchBackend cleanup for worker: {worker_id}")

    async def shutdown(self):
        """关闭 Backend（Server 调用）"""
        logger.info("FinanceResearchBackend shutdown")

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
                DeepResearchSkill
            )

            self.skills = {
                'market_data': MarketDataSkill(),
                'financial_analysis': FinancialAnalysisSkill(),
                'risk_assessment': RiskAssessmentSkill(),
                'sector_analysis': SectorAnalysisSkill(),
                'data_analysis': DataAnalysisSkill(),
                'web_research': WebResearchSkill(),
                'deep_research': DeepResearchSkill(),
            }

            logger.info(f"✅ FinanceResearchServer warmup 完成: {list(self.skills.keys())}")

        except Exception as e:
            logger.error(f"❌ warmup 失败: {e}")
            logger.warning("⚠️ Server 以降级模式运行，部分功能可能不可用")

    def _register_handlers(self):
        """注册工具处理函数 - 金融研投助手模式（3个工具）
        
        注意：实际的 HTTP 路由在 HTTPServiceServer._register_mcp_routes() 中定义
        这里只定义处理方法，供 HTTPServiceServer 调用
        """
        pass
    
    async def skill(self, name: str, **kwargs) -> Dict[str, Any]:
        """
        Round 1: 根据用户问题选择合适的 Skill（与金融研投助手一致）

        Args:
            name: Skill 名称
            **kwargs: 额外参数（兼容性支持）

        Returns:
            SKILL.md 文档内容 + 工具列表
        """
        if name not in ALL_SKILLS:
            available = list(ALL_SKILLS.keys())
            return {
                "success": False,
                "error": f"Skill '{name}' 不存在。可用 Skills: {available}"
            }

        skill_info = ALL_SKILLS[name]
        
        # 获取该 Skill 的工具列表
        skill_tools = []
        if name in self.skills:
            skill = self.skills[name]
            skill_tools = skill.discover_tools_json()
        
        return {
            "success": True,
            "skill_name": name,
            "description": skill_info["description"],
            "use_when": skill_info["use_when"],
            "tools_count": len(skill_tools),
            "tools": skill_tools,
            "message": f"已选择 Skill: {name}，包含 {len(skill_tools)} 个工具。可直接调用具体工具如 {name}.xxx"
        }
    
    # 向后兼容的别名
    async def select_skill(self, skill_name: str, reason: str = "", **kwargs) -> Dict[str, Any]:
        """向后兼容 - 映射到 skill()"""
        return await self.skill(name=skill_name)
    
    async def get_skill_tools(self, name: str) -> Dict[str, Any]:
        """
        Round 2: 获取指定 Skill 的所有可用工具列表

        Args:
            name: Skill 名称

        Returns:
            工具列表
        """
        if name not in self.skills:
            available = list(self.skills.keys())
            return {
                "success": False,
                "error": f"Skill '{name}' 不存在。可用 Skills: {available}"
            }

        skill = self.skills[name]
        tools = skill.discover_tools_json()

        return {
            "success": True,
            "skill_name": name,
            "tools_count": len(tools),
            "tools": tools,
            "message": f"Skill '{name}' 有 {len(tools)} 个可用工具。接下来可以调用 execute_skill_tool(skill_name='{name}', tool_name='xxx', arguments={{...}}) 执行具体工具。"
        }
    
    async def execute_skill_tool(self, skill_name: str, tool_name: str, arguments: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Round 3: 执行指定 Skill 的具体工具

        Args:
            skill_name: Skill 名称
            tool_name: 工具名称（不含 skill 前缀）
            arguments: 工具参数，默认为空字典

        Returns:
            工具执行结果
        """
        if arguments is None:
            arguments = {}

        # 检查 Skill 是否存在
        if skill_name not in self.skills:
            available = list(self.skills.keys())
            return {
                "success": False,
                "error": f"Skill '{skill_name}' 不存在。可用 Skills: {available}"
            }

        skill = self.skills[skill_name]

        # 检查工具是否存在
        if not skill.has_tool(tool_name):
            available_tools = [t.get("name") for t in skill.discover_tools_json()]
            return {
                "success": False,
                "error": f"工具 '{tool_name}' 不存在于 Skill '{skill_name}'。可用工具: {available_tools}"
            }

        # 执行工具
        try:
            logger.info(f"🛠️ 执行: {skill_name}.{tool_name}, 参数: {arguments}")
            result = await skill.execute_tool(tool_name, arguments)
            return result.to_dict()

        except Exception as e:
            logger.error(f"❌ 执行失败: {skill_name}.{tool_name} - {e}")
            return {
                "success": False,
                "error": str(e),
                "skill_name": skill_name,
                "tool_name": tool_name
            }

    async def __call__(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        """
        直接调用工具（支持 skill_name.tool_name 格式）
        
        例如: backend("market_data.get_quote", symbol="600519")
        """
        if "." in tool_name:
            skill_name, actual_tool_name = tool_name.split(".", 1)
            arguments = kwargs.get("arguments", kwargs)
            return await self.execute_skill_tool(skill_name, actual_tool_name, arguments)
        elif tool_name == "skill":
            return await self.skill(**kwargs)
        elif tool_name == "select_skill":
            return await self.select_skill(**kwargs)
        elif tool_name == "get_skill_tools":
            return await self.get_skill_tools(**kwargs)
        elif tool_name == "execute_skill_tool":
            return await self.execute_skill_tool(**kwargs)
        else:
            return {"success": False, "error": f"未知工具: {tool_name}"}

    def get_server(self):
        """获取 MCP Server 实例"""
        return self.server


# 向后兼容的别名
FinanceResearchServer = FinanceResearchBackend

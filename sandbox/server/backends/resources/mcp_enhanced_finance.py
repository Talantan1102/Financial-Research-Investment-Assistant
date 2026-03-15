"""
MCP Server 集成模块

让 AgentFlow Backend 能够调用金融研投助手的 MCP Server Skills
"""

import os
import sys
import json
import asyncio
from typing import Dict, Any, List, Optional
from pathlib import Path

# 添加金融研投助手路径
FRA_PATH = Path(__file__).parent.parent.parent / "financial-research-assistant" / "backend"
sys.path.insert(0, str(FRA_PATH))


class MCPSkillClient:
    """
    MCP Skill 客户端
    
    直接调用金融研投助手的 MCP Server Skills，无需启动独立 Server
    """
    
    def __init__(self):
        self.skills = {}
        self._initialized = False
    
    async def initialize(self):
        """初始化所有 Skills"""
        if self._initialized:
            return
        
        try:
            from app.mcp_server.skills import (
                MarketDataSkill,
                FinancialAnalysisSkill,
                RiskAssessmentSkill
            )
            
            # 注册 Skills
            self.skills['market_data'] = MarketDataSkill()
            self.skills['financial_analysis'] = FinancialAnalysisSkill()
            self.skills['risk_assessment'] = RiskAssessmentSkill()
            
            self._initialized = True
            print(f"✅ MCP Skills initialized: {list(self.skills.keys())}")
            
        except Exception as e:
            print(f"❌ Failed to initialize MCP Skills: {e}")
            raise
    
    async def call_tool(self, skill_name: str, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        调用指定 Skill 的工具
        
        Args:
            skill_name: skill 名称 (market_data/financial_analysis/risk_assessment)
            tool_name: 工具名称
            params: 工具参数
            
        Returns:
            工具执行结果
        """
        if not self._initialized:
            await self.initialize()
        
        skill = self.skills.get(skill_name)
        if not skill:
            return {
                "success": False,
                "error": f"Skill not found: {skill_name}"
            }
        
        # 获取工具 handler
        tool = skill.tools.get(tool_name)
        if not tool:
            return {
                "success": False,
                "error": f"Tool not found: {tool_name} in skill {skill_name}"
            }
        
        # 执行工具
        try:
            result = await tool.handler(**params)
            return {
                "success": True,
                "result": result.data if hasattr(result, 'data') else result,
                "skill": skill_name,
                "tool": tool_name
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "skill": skill_name,
                "tool": tool_name
            }
    
    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """获取所有工具的 JSON Schema 定义"""
        if not self._initialized:
            # 同步初始化检查
            pass
        
        definitions = []
        for skill_name, skill in self.skills.items():
            for tool_name, tool in skill.tools.items():
                definitions.append({
                    "name": f"{skill_name}:{tool_name}",
                    "skill": skill_name,
                    "tool": tool_name,
                    "description": tool.description,
                    "parameters": [
                        {
                            "name": param.name,
                            "type": param.type,
                            "description": param.description,
                            "required": param.required,
                            "default": param.default,
                            "enum": param.enum
                        }
                        for param in tool.parameters
                    ]
                })
        
        return definitions


class MCPEnhancedFinanceBackend:
    """
    增强版金融研投助手 Backend
    
    整合 ToolExecutor 和 MCP Server Skills
    """
    
    def __init__(self):
        self.tool_executor_backend = None
        self.mcp_client = None
        self._initialized = False
    
    async def initialize(self, config: Dict[str, Any] = None):
        """初始化所有工具"""
        # 1. 初始化 ToolExecutor Backend
        from finance_research import FinanceResearchBackend
        self.tool_executor_backend = FinanceResearchBackend()
        await self.tool_executor_backend.initialize(config)
        
        # 2. 初始化 MCP Client
        self.mcp_client = MCPSkillClient()
        await self.mcp_client.initialize()
        
        self._initialized = True
        print("✅ MCPEnhancedFinanceBackend initialized")
    
    # ============ ToolExecutor 工具（已有） ============
    
    async def action_web_search(self, **kwargs):
        return await self.tool_executor_backend.action_web_search(**kwargs)
    
    async def action_knowledge_search(self, **kwargs):
        return await self.tool_executor_backend.action_knowledge_search(**kwargs)
    
    async def action_text2sql(self, **kwargs):
        return await self.tool_executor_backend.action_text2sql(**kwargs)
    
    async def action_data_analyzer(self, **kwargs):
        return await self.tool_executor_backend.action_data_analyzer(**kwargs)
    
    async def action_chart_generator(self, **kwargs):
        return await self.tool_executor_backend.action_chart_generator(**kwargs)
    
    async def action_stock_query(self, **kwargs):
        return await self.tool_executor_backend.action_stock_query(**kwargs)
    
    async def action_bidding_search(self, **kwargs):
        return await self.tool_executor_backend.action_bidding_search(**kwargs)
    
    async def action_finish(self, **kwargs):
        return await self.tool_executor_backend.action_finish(**kwargs)
    
    # ============ MCP Server Skills（新增） ============
    
    async def action_market_data_get_quote(self, symbol: str) -> Dict[str, Any]:
        """
        获取股票实时行情（MCP Skill）
        
        Args:
            symbol: 股票代码，如 '600519'、'sh600519'、'600519.SH'
        """
        return await self.mcp_client.call_tool(
            skill_name='market_data',
            tool_name='get_quote',
            params={'symbol': symbol}
        )
    
    async def action_market_data_search_stock(self, keyword: str) -> Dict[str, Any]:
        """
        搜索股票（MCP Skill）
        
        Args:
            keyword: 搜索关键词，可以是股票代码或名称
        """
        return await self.mcp_client.call_tool(
            skill_name='market_data',
            tool_name='search_stock',
            params={'keyword': keyword}
        )
    
    async def action_market_data_get_history(self, symbol: str, period: str = "daily",
                                              start_date: str = None, end_date: str = None) -> Dict[str, Any]:
        """
        获取历史K线数据（MCP Skill）
        
        Args:
            symbol: 股票代码
            period: 周期类型：daily(日线)、weekly(周线)、monthly(月线)
            start_date: 开始日期，格式YYYYMMDD
            end_date: 结束日期，格式YYYYMMDD
        """
        params = {'symbol': symbol, 'period': period}
        if start_date:
            params['start_date'] = start_date
        if end_date:
            params['end_date'] = end_date
        
        return await self.mcp_client.call_tool(
            skill_name='market_data',
            tool_name='get_history',
            params=params
        )
    
    async def action_market_data_get_financial_data(self, symbol: str, data_type: str = "daily") -> Dict[str, Any]:
        """
        获取股票财务数据（MCP Skill）
        
        Args:
            symbol: 股票代码
            data_type: 数据类型：daily(每日指标)、express(业绩快报)、forecast(业绩预告)
        """
        return await self.mcp_client.call_tool(
            skill_name='market_data',
            tool_name='get_financial_data',
            params={'symbol': symbol, 'data_type': data_type}
        )
    
    async def action_financial_analysis_get_financial_report(self, symbol: str, report_type: str,
                                                              period: str = None, report_count: int = 1) -> Dict[str, Any]:
        """
        获取财务报表（MCP Skill）
        
        Args:
            symbol: 股票代码
            report_type: 报表类型：income(利润表)、balance(资产负债表)、cashflow(现金流量表)
            period: 报告期，格式YYYYMMDD
            report_count: 返回报告期数量，最多10期
        """
        params = {'symbol': symbol, 'report_type': report_type, 'report_count': report_count}
        if period:
            params['period'] = period
        
        return await self.mcp_client.call_tool(
            skill_name='financial_analysis',
            tool_name='get_financial_report',
            params=params
        )
    
    async def action_financial_analysis_calculate_financial_ratios(self, symbol: str,
                                                                    ratios: List[str] = None) -> Dict[str, Any]:
        """
        计算财务比率（MCP Skill）
        
        Args:
            symbol: 股票代码
            ratios: 要计算的比率列表，如 ["roe", "roa", "gross_margin"]
        """
        params = {'symbol': symbol}
        if ratios:
            params['ratios'] = ratios
        
        return await self.mcp_client.call_tool(
            skill_name='financial_analysis',
            tool_name='calculate_financial_ratios',
            params=params
        )
    
    async def action_financial_analysis_compare_financials(self, symbols: List[str],
                                                            metrics: List[str] = None) -> Dict[str, Any]:
        """
        对比多家公司财务指标（MCP Skill）
        
        Args:
            symbols: 股票代码列表
            metrics: 要对比的指标列表
        """
        params = {'symbols': symbols}
        if metrics:
            params['metrics'] = metrics
        
        return await self.mcp_client.call_tool(
            skill_name='financial_analysis',
            tool_name='compare_financials',
            params=params
        )
    
    async def action_risk_assessment_assess_risk(self, symbol: str,
                                                  risk_types: List[str] = None) -> Dict[str, Any]:
        """
        风险评估（MCP Skill）
        
        Args:
            symbol: 股票代码
            risk_types: 风险类型列表，如 ["market", "credit", "liquidity"]
        """
        params = {'symbol': symbol}
        if risk_types:
            params['risk_types'] = risk_types
        
        return await self.mcp_client.call_tool(
            skill_name='risk_assessment',
            tool_name='assess_risk',
            params=params
        )
    
    def get_all_tool_definitions(self) -> List[Dict[str, Any]]:
        """获取所有工具的完整定义"""
        from finance_research import get_tool_definitions
        
        # ToolExecutor 工具
        tool_executor_tools = get_tool_definitions()
        
        # MCP Skills 工具
        mcp_tools = self.mcp_client.get_tool_definitions()
        
        return {
            'tool_executor': tool_executor_tools,
            'mcp_skills': mcp_tools,
            'total': len(tool_executor_tools) + len(mcp_tools)
        }


# ============ 导出 ============

def get_enhanced_tool_definitions() -> List[Dict[str, Any]]:
    """
    获取增强版工具定义列表（ToolExecutor + MCP Skills）
    
    Returns:
        完整的工具定义列表
    """
    # ToolExecutor 工具（8个）
    from finance_research import get_tool_definitions
    tool_executor_tools = get_tool_definitions()
    
    # MCP Skills 工具
    mcp_tools = [
        # MarketDataSkill
        {
            "name": "market_data:get_quote",
            "skill": "market_data",
            "tool": "get_quote",
            "description": "获取指定股票的实时行情数据，包括当前价格、涨跌幅、成交量等信息",
            "parameters": [{"name": "symbol", "type": "string", "required": True}]
        },
        {
            "name": "market_data:search_stock",
            "skill": "market_data",
            "tool": "search_stock",
            "description": "根据股票代码或名称关键词搜索股票信息",
            "parameters": [{"name": "keyword", "type": "string", "required": True}]
        },
        {
            "name": "market_data:get_history",
            "skill": "market_data",
            "tool": "get_history",
            "description": "获取股票历史K线数据，支持日线、周线、月线",
            "parameters": [
                {"name": "symbol", "type": "string", "required": True},
                {"name": "period", "type": "string", "required": False, "default": "daily"},
                {"name": "start_date", "type": "string", "required": False},
                {"name": "end_date", "type": "string", "required": False}
            ]
        },
        {
            "name": "market_data:get_financial_data",
            "skill": "market_data",
            "tool": "get_financial_data",
            "description": "获取股票财务数据，包括每日指标、业绩快报、业绩预告",
            "parameters": [
                {"name": "symbol", "type": "string", "required": True},
                {"name": "data_type", "type": "string", "required": False, "default": "daily"}
            ]
        },
        # FinancialAnalysisSkill
        {
            "name": "financial_analysis:get_financial_report",
            "skill": "financial_analysis",
            "tool": "get_financial_report",
            "description": "获取指定公司的财务报表数据，包括利润表、资产负债表、现金流量表",
            "parameters": [
                {"name": "symbol", "type": "string", "required": True},
                {"name": "report_type", "type": "string", "required": True},
                {"name": "period", "type": "string", "required": False},
                {"name": "report_count", "type": "integer", "required": False, "default": 1}
            ]
        },
        {
            "name": "financial_analysis:calculate_financial_ratios",
            "skill": "financial_analysis",
            "tool": "calculate_financial_ratios",
            "description": "计算财务比率，包括ROE、ROA、毛利率、净利率等",
            "parameters": [
                {"name": "symbol", "type": "string", "required": True},
                {"name": "ratios", "type": "array", "required": False}
            ]
        },
        {
            "name": "financial_analysis:compare_financials",
            "skill": "financial_analysis",
            "tool": "compare_financials",
            "description": "对比多家公司的财务指标",
            "parameters": [
                {"name": "symbols", "type": "array", "required": True},
                {"name": "metrics", "type": "array", "required": False}
            ]
        },
        # RiskAssessmentSkill
        {
            "name": "risk_assessment:assess_risk",
            "skill": "risk_assessment",
            "tool": "assess_risk",
            "description": "评估股票风险，包括市场风险、信用风险、流动性风险等",
            "parameters": [
                {"name": "symbol", "type": "string", "required": True},
                {"name": "risk_types", "type": "array", "required": False}
            ]
        }
    ]
    
    return tool_executor_tools + mcp_tools


if __name__ == "__main__":
    # 测试
    async def test():
        client = MCPSkillClient()
        await client.initialize()
        
        # 测试调用
        result = await client.call_tool(
            skill_name='market_data',
            tool_name='search_stock',
            params={'keyword': '茅台'}
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
    
    asyncio.run(test())

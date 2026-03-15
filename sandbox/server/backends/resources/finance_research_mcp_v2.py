"""
Finance Research MCP Backend for AgentFlow (v2)

支持调整后金融研投助手的 MCP Server Skills：
- web_research
- market_data  
- financial_analysis
- risk_assessment
- data_analysis
- deep_research

直接通过 ToolAdapter 调用，统一接口格式。
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
logger = logging.getLogger("FinanceResearchMCPBackend")


class FinanceResearchMCPBackend:
    """
    金融研投助手 MCP Backend for AgentFlow
    
    直接通过 ToolAdapter 调用所有 MCP Server Skills
    工具格式: skill_name.tool_name
    
    支持的 Skills:
    - web_research: web_search, knowledge_search, deep_search, extract_webpage, batch_search
    - market_data: get_quote, search_stock, get_history, get_financial_data
    - financial_analysis: get_financial_report, calculate_financial_ratios, compare_financials, analyze_revenue, analyze_profitability
    - risk_assessment: assess_risk, analyze_volatility, check_abnormal_signals
    - data_analysis: analyze_data, generate_chart, calculate_statistics, trend_analysis
    - deep_research: research_plan, execute_research, generate_report
    """
    
    def __init__(self):
        self.tool_adapter = None
        self.mcp_client = None
        self._initialized = False
    
    async def initialize(self, config: Dict[str, Any] = None):
        """初始化 Backend，创建 MCP Client 和 ToolAdapter"""
        try:
            from app.mcp_client.client import MCPClient
            from app.mcp_client.adapter import ToolAdapter
            
            # 创建 MCP Client
            self.mcp_client = MCPClient()
            await self.mcp_client.connect()
            
            # 创建 ToolAdapter
            self.tool_adapter = ToolAdapter(mcp_client=self.mcp_client)
            
            self._initialized = True
            logger.info("FinanceResearchMCPBackend initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize: {e}")
            raise
    
    # ============ WebResearch Tools ============
    
    async def action_web_research_web_search(self, query: str, count: int = 5, freshness: str = None) -> Dict[str, Any]:
        """网络搜索"""
        return await self.tool_adapter.web_search(query=query, count=count, freshness=freshness)
    
    async def action_web_research_knowledge_search(self, query: str, kb_name: str = "", top_k: int = 5) -> Dict[str, Any]:
        """知识库搜索"""
        return await self.tool_adapter.knowledge_search(query=query, kb_name=kb_name, top_k=top_k)
    
    async def action_web_research_deep_search(self, query: str, sub_queries: List[str] = None, 
                                               max_depth: int = 2, cross_verify: bool = True) -> Dict[str, Any]:
        """深度搜索"""
        return await self.tool_adapter.deep_search(
            query=query, sub_queries=sub_queries, max_depth=max_depth, cross_verify=cross_verify
        )
    
    async def action_web_research_extract_webpage(self, url: str, extract_type: str = "article") -> Dict[str, Any]:
        """网页内容提取"""
        return await self.tool_adapter.extract_webpage(url=url, extract_type=extract_type)
    
    async def action_web_research_batch_search(self, queries: List[Dict], search_type: str = "web") -> Dict[str, Any]:
        """批量搜索"""
        return await self.tool_adapter.batch_search(queries=queries, search_type=search_type)
    
    # ============ MarketData Tools ============
    
    async def action_market_data_get_quote(self, symbol: str) -> Dict[str, Any]:
        """获取股票行情"""
        return await self.tool_adapter.get_stock_by_code(symbol)
    
    async def action_market_data_search_stock(self, keyword: str) -> Dict[str, Any]:
        """搜索股票"""
        return await self.tool_adapter.search_stock(keyword)
    
    async def action_market_data_get_history(self, symbol: str, period: str = "daily",
                                              start_date: str = None, end_date: str = None) -> Dict[str, Any]:
        """获取历史K线"""
        return await self.tool_adapter.get_stock_history(
            symbol=symbol, period=period, start_date=start_date, end_date=end_date
        )
    
    async def action_market_data_get_financial_data(self, symbol: str, data_type: str = "daily") -> Dict[str, Any]:
        """获取财务数据"""
        return await self.tool_adapter.get_financial_data(symbol=symbol, data_type=data_type)
    
    # ============ FinancialAnalysis Tools ============
    
    async def action_financial_analysis_get_financial_report(self, symbol: str, report_type: str,
                                                              period: str = None, report_count: int = 1) -> Dict[str, Any]:
        """获取财务报表"""
        return await self.tool_adapter.get_financial_report(
            symbol=symbol, report_type=report_type, period=period, report_count=report_count
        )
    
    async def action_financial_analysis_calculate_financial_ratios(self, symbol: str, 
                                                                    ratios: List[str] = None) -> Dict[str, Any]:
        """计算财务比率"""
        return await self.tool_adapter.calculate_financial_ratios(symbol=symbol, ratios=ratios)
    
    async def action_financial_analysis_compare_financials(self, symbols: List[str], 
                                                            metrics: List[str] = None) -> Dict[str, Any]:
        """对比财务指标"""
        return await self.tool_adapter.compare_financials(symbols=symbols, metrics=metrics)
    
    async def action_financial_analysis_analyze_revenue(self, symbol: str, period: str = "quarterly") -> Dict[str, Any]:
        """营收分析"""
        return await self.tool_adapter.analyze_revenue(symbol=symbol, period=period)
    
    async def action_financial_analysis_analyze_profitability(self, symbol: str) -> Dict[str, Any]:
        """盈利能力分析"""
        return await self.tool_adapter.analyze_profitability(symbol=symbol)
    
    # ============ RiskAssessment Tools ============
    
    async def action_risk_assessment_assess_risk(self, symbol: str, risk_types: List[str] = None) -> Dict[str, Any]:
        """风险评估"""
        return await self.tool_adapter.assess_risk(symbol=symbol, risk_types=risk_types)
    
    async def action_risk_assessment_analyze_volatility(self, symbol: str, period: str = "1y") -> Dict[str, Any]:
        """波动率分析"""
        return await self.tool_adapter.analyze_volatility(symbol=symbol, period=period)
    
    async def action_risk_assessment_check_abnormal_signals(self, symbol: str) -> Dict[str, Any]:
        """异常信号检测"""
        return await self.tool_adapter.check_abnormal_signals(symbol=symbol)
    
    # ============ DataAnalysis Tools ============
    
    async def action_data_analysis_analyze_data(self, data: List[Dict], analysis_type: str = "comprehensive") -> Dict[str, Any]:
        """数据分析"""
        return await self.tool_adapter.analyze_data(data=data, analysis_type=analysis_type)
    
    async def action_data_analysis_generate_chart(self, data: Any, chart_type: str = "bar", title: str = "") -> Dict[str, Any]:
        """生成图表"""
        return await self.tool_adapter.generate_chart(data=data, chart_type=chart_type, title=title)
    
    async def action_data_analysis_calculate_statistics(self, data: List[float], metrics: List[str] = None) -> Dict[str, Any]:
        """计算统计指标"""
        return await self.tool_adapter.calculate_statistics(data=data, metrics=metrics)
    
    async def action_data_analysis_trend_analysis(self, data: List[Dict], trend_type: str = "linear") -> Dict[str, Any]:
        """趋势分析"""
        return await self.tool_adapter.trend_analysis(data=data, trend_type=trend_type)
    
    # ============ DeepResearch Tools ============
    
    async def action_deep_research_research_plan(self, topic: str, depth: int = 3, 
                                                  focus_areas: List[str] = None) -> Dict[str, Any]:
        """研究规划"""
        return await self.tool_adapter.research_plan(topic=topic, depth=depth, focus_areas=focus_areas)
    
    async def action_deep_research_execute_research(self, plan_id: str, steps: List[Dict]) -> Dict[str, Any]:
        """执行研究"""
        return await self.tool_adapter.execute_research(plan_id=plan_id, steps=steps)
    
    async def action_deep_research_generate_report(self, research_id: str, report_type: str = "comprehensive") -> Dict[str, Any]:
        """生成报告"""
        return await self.tool_adapter.generate_report(research_id=research_id, report_type=report_type)


def get_mcp_tool_definitions() -> List[Dict[str, Any]]:
    """
    获取所有 MCP 工具的 JSON Schema 定义
    
    Returns:
        完整的工具定义列表，用于 AgentFlow 配置
    """
    return [
        # WebResearch
        {
            "name": "web_research.web_search",
            "description": "搜索互联网获取最新信息，适用于查找实时数据、新闻、市场信息等",
            "parameters": {
                "query": {"type": "string", "description": "搜索关键词", "required": True},
                "count": {"type": "integer", "description": "返回结果数量", "default": 5},
                "freshness": {"type": "string", "description": "结果时效性: day/week/month/year"}
            }
        },
        {
            "name": "web_research.knowledge_search",
            "description": "搜索本地知识库获取专业文档，适用于查找研报、公告等",
            "parameters": {
                "query": {"type": "string", "description": "搜索问题或关键词", "required": True},
                "kb_name": {"type": "string", "description": "知识库名称"},
                "top_k": {"type": "integer", "description": "返回结果数量", "default": 5}
            }
        },
        {
            "name": "web_research.deep_search",
            "description": "深度搜索，支持递归搜索和交叉验证，适用于复杂研究",
            "parameters": {
                "query": {"type": "string", "description": "搜索主题", "required": True},
                "sub_queries": {"type": "array", "description": "子查询列表"},
                "max_depth": {"type": "integer", "description": "最大搜索深度", "default": 2},
                "cross_verify": {"type": "boolean", "description": "是否交叉验证", "default": True}
            }
        },
        
        # MarketData
        {
            "name": "market_data.get_quote",
            "description": "获取股票实时行情数据，包括当前价格、涨跌幅、成交量等",
            "parameters": {
                "symbol": {"type": "string", "description": "股票代码，如600519", "required": True}
            }
        },
        {
            "name": "market_data.search_stock",
            "description": "根据关键词搜索股票",
            "parameters": {
                "keyword": {"type": "string", "description": "搜索关键词，可以是代码或名称", "required": True}
            }
        },
        {
            "name": "market_data.get_history",
            "description": "获取股票历史K线数据",
            "parameters": {
                "symbol": {"type": "string", "description": "股票代码", "required": True},
                "period": {"type": "string", "description": "周期: daily/weekly/monthly", "default": "daily"},
                "start_date": {"type": "string", "description": "开始日期 YYYYMMDD"},
                "end_date": {"type": "string", "description": "结束日期 YYYYMMDD"}
            }
        },
        
        # FinancialAnalysis
        {
            "name": "financial_analysis.get_financial_report",
            "description": "获取财务报表数据（利润表、资产负债表、现金流量表）",
            "parameters": {
                "symbol": {"type": "string", "description": "股票代码", "required": True},
                "report_type": {"type": "string", "description": "报表类型: income/balance/cashflow", "required": True},
                "period": {"type": "string", "description": "报告期 YYYYMMDD"},
                "report_count": {"type": "integer", "description": "返回报告期数量", "default": 1}
            }
        },
        {
            "name": "financial_analysis.calculate_financial_ratios",
            "description": "计算财务比率（ROE、ROA、毛利率、净利率等）",
            "parameters": {
                "symbol": {"type": "string", "description": "股票代码", "required": True},
                "ratios": {"type": "array", "description": "要计算的比率列表"}
            }
        },
        {
            "name": "financial_analysis.compare_financials",
            "description": "对比多家公司的财务指标",
            "parameters": {
                "symbols": {"type": "array", "description": "股票代码列表", "required": True},
                "metrics": {"type": "array", "description": "要对比的指标列表"}
            }
        },
        
        # RiskAssessment
        {
            "name": "risk_assessment.assess_risk",
            "description": "评估股票风险（市场风险、信用风险、流动性风险等）",
            "parameters": {
                "symbol": {"type": "string", "description": "股票代码", "required": True},
                "risk_types": {"type": "array", "description": "风险类型列表"}
            }
        },
        
        # DataAnalysis
        {
            "name": "data_analysis.analyze_data",
            "description": "数据分析，提取洞察和统计信息",
            "parameters": {
                "data": {"type": "array", "description": "数据列表", "required": True},
                "analysis_type": {"type": "string", "description": "分析类型", "default": "comprehensive"}
            }
        },
        {
            "name": "data_analysis.generate_chart",
            "description": "生成数据可视化图表",
            "parameters": {
                "data": {"type": "any", "description": "图表数据", "required": True},
                "chart_type": {"type": "string", "description": "图表类型: bar/line/pie/scatter", "default": "bar"},
                "title": {"type": "string", "description": "图表标题"}
            }
        },
        
        # DeepResearch
        {
            "name": "deep_research.research_plan",
            "description": "生成研究规划方案",
            "parameters": {
                "topic": {"type": "string", "description": "研究主题", "required": True},
                "depth": {"type": "integer", "description": "研究深度", "default": 3},
                "focus_areas": {"type": "array", "description": "重点研究方向"}
            }
        }
    ]


if __name__ == "__main__":
    # 测试
    async def test():
        backend = FinanceResearchMCPBackend()
        await backend.initialize()
        
        # 测试调用
        result = await backend.action_market_data_search_stock(keyword="茅台")
        print(json.dumps(result, indent=2, ensure_ascii=False))
    
    asyncio.run(test())

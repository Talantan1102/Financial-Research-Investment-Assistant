# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""DeepResearch Skill - 深度研报工具

提供深度研究报告生成功能。
"""

from typing import Dict, Any, Optional, List
from app.mcp_server.skills.base import BaseSkill, ToolParameter, ToolResult
from app.data.tushare_client import get_tushare_client, TushareClient


class DeepResearchSkill(BaseSkill):
    """
    深度研报 Skill

    提供深度研究报告生成，综合多维度数据生成研报。
    """

    name = "deep_research"
    description = "深度研究报告生成，综合多维度数据生成研报"

    def __init__(self):
        self._tushare_client: Optional[TushareClient] = None
        super().__init__()

    def get_tushare_client(self) -> TushareClient:
        """获取 TushareClient 实例（延迟初始化）"""
        if self._tushare_client is None:
            self._tushare_client = get_tushare_client()
        return self._tushare_client

    def _register_tools(self):
        """注册 DeepResearch 相关工具"""

        # 1. 生成个股深度研报
        self.register_tool(
            name="generate_stock_report",
            handler=self.generate_stock_report,
            description="生成个股深度研究报告，综合财务、估值、行业等多维度数据",
            parameters=[
                ToolParameter(
                    name="ts_code",
                    type="string",
                    description="TS股票代码，如 600519.SH",
                    required=True
                ),
                ToolParameter(
                    name="report_type",
                    type="string",
                    description="报告类型：comprehensive(综合), valuation(估值), financial(财务)",
                    required=False,
                    default="comprehensive"
                )
            ]
        )

        # 2. 生成行业深度研报
        self.register_tool(
            name="generate_industry_report",
            handler=self.generate_industry_report,
            description="生成行业深度研究报告",
            parameters=[
                ToolParameter(
                    name="industry",
                    type="string",
                    description="行业名称，如'白酒'、'银行'",
                    required=True
                ),
                ToolParameter(
                    name="focus",
                    type="string",
                    description="分析重点：overview(全景), leaders(龙头), valuation(估值), trend(趋势)",
                    required=False,
                    default="overview"
                )
            ]
        )

        # 3. 生成对比分析报告
        self.register_tool(
            name="generate_comparison_report",
            handler=self.generate_comparison_report,
            description="生成股票对比分析报告",
            parameters=[
                ToolParameter(
                    name="symbols",
                    type="array",
                    description="TS股票代码列表，如['600519.SH', '000858.SZ']",
                    required=True
                ),
                ToolParameter(
                    name="dimensions",
                    type="array",
                    description="对比维度：valuation(估值), profitability(盈利), growth(成长), risk(风险)",
                    required=False,
                    default=None
                )
            ]
        )

    async def generate_stock_report(self, ts_code: str, report_type: str = "comprehensive") -> ToolResult:
        """生成个股深度研报"""
        if not ts_code:
            return ToolResult(success=False, error="股票代码不能为空")

        try:
            # 获取基础信息
            basic_result = self.get_tushare_client().get_stock_basic(ts_code)
            company_result = self.get_tushare_client().get_stock_company_info(ts_code)
            
            # 获取行情数据
            quote_result = self.get_tushare_client().get_quote(ts_code)
            daily_basic_result = self.get_tushare_client().get_daily_basic(ts_code)
            
            # 获取财务数据
            fina_result = self.get_tushare_client().get_fina_indicator(ts_code)

            report = {
                "ts_code": ts_code,
                "report_type": report_type,
                "generated_at": "2026-03-20",
                "sections": {}
            }

            # 公司概况
            if company_result.get("success"):
                report["sections"]["company_overview"] = {
                    "name": company_result["data"].get("name"),
                    "fullname": company_result["data"].get("fullname"),
                    "industry": company_result["data"].get("industry"),
                    "area": company_result["data"].get("area"),
                    "list_date": company_result["data"].get("list_date"),
                    "introduction": company_result["data"].get("introduction", "")[:500]
                }

            # 估值分析
            if daily_basic_result.get("success"):
                data = daily_basic_result["data"]
                if data:
                    latest = data[0]
                    report["sections"]["valuation"] = {
                        "pe": latest.get("pe"),
                        "pe_ttm": latest.get("pe_ttm"),
                        "pb": latest.get("pb"),
                        "ps": latest.get("ps"),
                        "total_mv": latest.get("total_mv"),
                        "assessment": self._assess_valuation(latest)
                    }

            # 财务分析
            if fina_result.get("success"):
                data = fina_result.get("data", [])
                if data:
                    latest = data[0]
                    report["sections"]["financial"] = {
                        "roe": latest.get("roe"),
                        "roa": latest.get("roa"),
                        "gross_margin": latest.get("gross_margin"),
                        "debt_to_assets": latest.get("debt_to_assets"),
                        "trend_roe": [d.get("roe") for d in data[:4]]
                    }

            # 行情概况
            if quote_result.get("success"):
                report["sections"]["market"] = {
                    "current_price": quote_result["data"].get("nowPri"),
                    "change_percent": quote_result["data"].get("increPer"),
                    "volume": quote_result["data"].get("traAmount")
                }

            return ToolResult(success=True, data=report)

        except Exception as e:
            return ToolResult(success=False, error=f"生成个股研报失败: {str(e)}")

    def _assess_valuation(self, data: Dict[str, Any]) -> str:
        """评估估值"""
        pe = data.get("pe", 0) or 0
        pb = data.get("pb", 0) or 0
        
        if pe < 0:
            return "亏损"
        elif pe < 15:
            return "低估"
        elif pe < 30:
            return "合理"
        elif pe < 50:
            return "偏高"
        else:
            return "高估"

    async def generate_industry_report(self, industry: str, focus: str = "overview") -> ToolResult:
        """生成行业深度研报"""
        if not industry:
            return ToolResult(success=False, error="行业名称不能为空")

        try:
            # 获取行业龙头股
            leaders_result = self.get_tushare_client().get_industry_leaders(industry)
            
            # 获取行业估值对比
            valuation_result = self.get_tushare_client().compare_industry_valuation([industry])
            
            # 获取行业表现
            performance_result = self.get_tushare_client().get_industry_performance()

            report = {
                "industry": industry,
                "focus": focus,
                "generated_at": "2026-03-20",
                "sections": {}
            }

            # 行业概况
            if leaders_result.get("success"):
                report["sections"]["leaders"] = {
                    "top_companies": leaders_result["data"][:5],
                    "leader_count": len(leaders_result["data"])
                }

            # 估值分析
            if valuation_result.get("success"):
                data = valuation_result.get("data", [])
                if data:
                    report["sections"]["valuation"] = data[0]

            # 近期表现
            if performance_result.get("success"):
                data = performance_result.get("data", [])
                for d in data:
                    if d.get("industry") == industry:
                        report["sections"]["performance"] = d
                        break

            return ToolResult(success=True, data=report)

        except Exception as e:
            return ToolResult(success=False, error=f"生成行业研报失败: {str(e)}")

    async def generate_comparison_report(self, symbols: List[str], dimensions: List[str] = None) -> ToolResult:
        """生成对比分析报告"""
        if not symbols or len(symbols) < 2:
            return ToolResult(success=False, error="请提供至少2只股票进行对比")

        dimensions = dimensions or ["valuation", "profitability", "risk"]

        try:
            comparison = {
                "symbols": symbols,
                "dimensions": dimensions,
                "generated_at": "2026-03-20",
                "data": {}
            }

            # 获取每只股票的数据
            stock_data = {}
            for ts_code in symbols:
                stock_info = {}
                
                # 基础信息
                basic = self.get_tushare_client().get_stock_basic(ts_code)
                if basic.get("success"):
                    stock_info["name"] = basic["data"].get("name")
                    stock_info["industry"] = basic["data"].get("industry")
                
                # 估值数据
                if "valuation" in dimensions:
                    daily = self.get_tushare_client().get_daily_basic(ts_code)
                    if daily.get("success") and daily["data"]:
                        latest = daily["data"][0]
                        stock_info["valuation"] = {
                            "pe": latest.get("pe"),
                            "pb": latest.get("pb"),
                            "total_mv": latest.get("total_mv")
                        }
                
                # 财务数据
                if "profitability" in dimensions:
                    fina = self.get_tushare_client().get_fina_indicator(ts_code)
                    if fina.get("success") and fina["data"]:
                        latest = fina["data"][0]
                        stock_info["profitability"] = {
                            "roe": latest.get("roe"),
                            "gross_margin": latest.get("gross_margin"),
                            "net_margin": latest.get("netprofit_margin")
                        }
                
                stock_data[ts_code] = stock_info

            comparison["data"] = stock_data

            # 生成对比结论
            comparison["summary"] = self._generate_comparison_summary(stock_data, dimensions)

            return ToolResult(success=True, data=comparison)

        except Exception as e:
            return ToolResult(success=False, error=f"生成对比报告失败: {str(e)}")

    def _generate_comparison_summary(self, stock_data: Dict[str, Any], dimensions: List[str]) -> Dict[str, Any]:
        """生成对比总结"""
        summary = {}

        if "valuation" in dimensions:
            pe_values = {s: d.get("valuation", {}).get("pe", float('inf')) 
                        for s, d in stock_data.items()}
            summary["lowest_pe"] = min(pe_values.items(), key=lambda x: x[1] if x[1] > 0 else float('inf'))

        if "profitability" in dimensions:
            roe_values = {s: d.get("profitability", {}).get("roe", 0) 
                         for s, d in stock_data.items()}
            summary["highest_roe"] = max(roe_values.items(), key=lambda x: x[1] or 0)

        return summary

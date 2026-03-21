# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""FinancialAnalysis Skill - 财务分析工具

提供财务报表分析功能，包括ROE、ROA、毛利率、净利率等指标计算。
"""

from typing import Dict, Any, Optional, List
from app.mcp_server.skills.base import BaseSkill, ToolParameter, ToolResult
from app.data.tushare_client import get_tushare_client, TushareClient


class FinancialAnalysisSkill(BaseSkill):
    """
    财务分析 Skill

    提供财务报表分析功能，计算各类财务指标。
    """

    name = "financial_analysis"
    description = "财务报表分析，计算ROE、ROA、毛利率、净利率等财务指标"

    def __init__(self):
        self._tushare_client: Optional[TushareClient] = None
        super().__init__()

    def get_tushare_client(self) -> TushareClient:
        """获取 TushareClient 实例（延迟初始化）"""
        if self._tushare_client is None:
            self._tushare_client = get_tushare_client()
        return self._tushare_client

    def _register_tools(self):
        """注册 FinancialAnalysis 相关工具"""

        # 1. 计算财务比率
        self.register_tool(
            name="calculate_financial_ratios",
            handler=self.calculate_financial_ratios,
            description="计算ROE、ROA、毛利率、净利率、资产负债率等核心财务指标",
            parameters=[
                ToolParameter(
                    name="ts_code",
                    type="string",
                    description="TS股票代码，如 600519.SH",
                    required=True
                ),
                ToolParameter(
                    name="period",
                    type="string",
                    description="报告期，如'20231231'，不填则取最新",
                    required=False,
                    default=None
                )
            ]
        )

        # 2. 获取利润表
        self.register_tool(
            name="get_income_statement",
            handler=self.get_income_statement,
            description="获取利润表数据，包括营收、成本、利润等",
            parameters=[
                ToolParameter(
                    name="ts_code",
                    type="string",
                    description="TS股票代码，如 600519.SH",
                    required=True
                ),
                ToolParameter(
                    name="start_date",
                    type="string",
                    description="开始日期，格式YYYYMMDD",
                    required=False,
                    default=None
                ),
                ToolParameter(
                    name="end_date",
                    type="string",
                    description="结束日期，格式YYYYMMDD",
                    required=False,
                    default=None
                ),
                ToolParameter(
                    name="period",
                    type="string",
                    description="报告期类型，如'2023Q4'，可选",
                    required=False,
                    default=None
                )
            ]
        )

        # 3. 获取资产负债表
        self.register_tool(
            name="get_balance_sheet",
            handler=self.get_balance_sheet,
            description="获取资产负债表数据，包括资产、负债、股东权益等",
            parameters=[
                ToolParameter(
                    name="ts_code",
                    type="string",
                    description="TS股票代码，如 600519.SH",
                    required=True
                ),
                ToolParameter(
                    name="start_date",
                    type="string",
                    description="开始日期，格式YYYYMMDD",
                    required=False,
                    default=None
                ),
                ToolParameter(
                    name="end_date",
                    type="string",
                    description="结束日期，格式YYYYMMDD",
                    required=False,
                    default=None
                ),
                ToolParameter(
                    name="period",
                    type="string",
                    description="报告期类型，如'2023Q4'，可选",
                    required=False,
                    default=None
                )
            ]
        )

        # 4. 获取现金流量表
        self.register_tool(
            name="get_cash_flow",
            handler=self.get_cash_flow,
            description="获取现金流量表数据，包括经营、投资、筹资活动现金流",
            parameters=[
                ToolParameter(
                    name="ts_code",
                    type="string",
                    description="TS股票代码，如 600519.SH",
                    required=True
                ),
                ToolParameter(
                    name="start_date",
                    type="string",
                    description="开始日期，格式YYYYMMDD",
                    required=False,
                    default=None
                ),
                ToolParameter(
                    name="end_date",
                    type="string",
                    description="结束日期，格式YYYYMMDD",
                    required=False,
                    default=None
                ),
                ToolParameter(
                    name="period",
                    type="string",
                    description="报告期类型，如'2023Q4'，可选",
                    required=False,
                    default=None
                )
            ]
        )

        # 5. 获取财务指标
        self.register_tool(
            name="get_fina_indicator",
            handler=self.get_fina_indicator,
            description="获取一站式财务指标数据，包含ROE、ROA、毛利率等100+指标",
            parameters=[
                ToolParameter(
                    name="ts_code",
                    type="string",
                    description="TS股票代码，如 600519.SH",
                    required=True
                ),
                ToolParameter(
                    name="start_date",
                    type="string",
                    description="开始日期，格式YYYYMMDD",
                    required=False,
                    default=None
                ),
                ToolParameter(
                    name="end_date",
                    type="string",
                    description="结束日期，格式YYYYMMDD",
                    required=False,
                    default=None
                ),
                ToolParameter(
                    name="period",
                    type="string",
                    description="报告期类型，如'2023Q4'，可选",
                    required=False,
                    default=None
                )
            ]
        )

        # 6. 分析盈利能力
        self.register_tool(
            name="analyze_profitability",
            handler=self.analyze_profitability,
            description="分析公司盈利能力，包括毛利率、净利率、ROE趋势等",
            parameters=[
                ToolParameter(
                    name="ts_code",
                    type="string",
                    description="TS股票代码，如 600519.SH",
                    required=True
                ),
                ToolParameter(
                    name="periods",
                    type="integer",
                    description="分析期数（季度），默认8个季度",
                    required=False,
                    default=8
                )
            ]
        )

        # 7. 分析偿债能力
        self.register_tool(
            name="analyze_solvency",
            handler=self.analyze_solvency,
            description="分析公司偿债能力，包括流动比率、速动比率、资产负债率等",
            parameters=[
                ToolParameter(
                    name="ts_code",
                    type="string",
                    description="TS股票代码，如 600519.SH",
                    required=True
                ),
                ToolParameter(
                    name="period",
                    type="string",
                    description="报告期，如'20231231'，不填则取最新",
                    required=False,
                    default=None
                )
            ]
        )

    async def calculate_financial_ratios(self, ts_code: str, period: str = None) -> ToolResult:
        """
        计算核心财务比率
        """
        if not ts_code:
            return ToolResult(success=False, error="股票代码不能为空")

        try:
            # 获取财务指标数据
            result = self.get_tushare_client().get_fina_indicator(ts_code)

            if not result.get("success"):
                return ToolResult(success=False, error=result.get("error"))

            data = result.get("data", [])
            if not data:
                return ToolResult(success=False, error="未找到财务指标数据")

            # 取最新一期数据
            latest = data[0] if not period else next(
                (d for d in data if d.get("end_date") == period), data[0]
            )

            # 提取核心财务比率
            ratios = {
                "ts_code": ts_code,
                "period": latest.get("end_date"),
                "roe": latest.get("roe"),
                "roe_dt": latest.get("roe_dt"),  # 扣非ROE
                "roa": latest.get("roa"),
                "gross_margin": latest.get("gross_margin"),
                "net_profit_margin": self._calculate_net_margin(latest),
                "debt_to_assets": latest.get("debt_to_assets"),
                "current_ratio": latest.get("current_ratio"),
                "quick_ratio": latest.get("quick_ratio"),
                "inventory_turnover": latest.get("inv_turn"),
                "receivables_turnover": latest.get("ar_turn"),
                "assets_turnover": latest.get("assets_turn"),
            }

            return ToolResult(success=True, data=ratios)

        except Exception as e:
            return ToolResult(success=False, error=f"计算财务比率失败: {str(e)}")

    def _calculate_net_margin(self, data: Dict[str, Any]) -> Optional[float]:
        """计算净利率"""
        # 简化计算，实际应从利润表获取
        return data.get("netprofit_margin") or data.get("npta")

    async def get_income_statement(self, ts_code: str, start_date: str = None, end_date: str = None, period: str = None) -> ToolResult:
        """
        获取利润表
        """
        if not ts_code:
            return ToolResult(success=False, error="股票代码不能为空")

        try:
            result = self.get_tushare_client().get_income_statement(ts_code, start_date, end_date)

            if not result.get("success"):
                return ToolResult(success=False, error=result.get("error"))

            data = result.get("data", [])
            
            # 如果指定了period，过滤数据
            if period and data:
                data = [d for d in data if period in str(d.get("end_date", "")) or period in str(d.get("period", ""))]

            return ToolResult(success=True, data=data, meta=result.get("meta"))

        except Exception as e:
            return ToolResult(success=False, error=f"获取利润表失败: {str(e)}")

    async def get_balance_sheet(self, ts_code: str, start_date: str = None, end_date: str = None, period: str = None) -> ToolResult:
        """
        获取资产负债表
        """
        if not ts_code:
            return ToolResult(success=False, error="股票代码不能为空")

        try:
            result = self.get_tushare_client().get_balance_sheet(ts_code, start_date, end_date)

            if not result.get("success"):
                return ToolResult(success=False, error=result.get("error"))

            data = result.get("data", [])
            
            # 如果指定了period，过滤数据
            if period and data:
                data = [d for d in data if period in str(d.get("end_date", "")) or period in str(d.get("period", ""))]

            return ToolResult(success=True, data=data, meta=result.get("meta"))

        except Exception as e:
            return ToolResult(success=False, error=f"获取资产负债表失败: {str(e)}")

    async def get_cash_flow(self, ts_code: str, start_date: str = None, end_date: str = None, period: str = None) -> ToolResult:
        """
        获取现金流量表
        """
        if not ts_code:
            return ToolResult(success=False, error="股票代码不能为空")

        try:
            result = self.get_tushare_client().get_cash_flow(ts_code, start_date, end_date)

            if not result.get("success"):
                return ToolResult(success=False, error=result.get("error"))

            data = result.get("data", [])
            
            # 如果指定了period，过滤数据
            if period and data:
                data = [d for d in data if period in str(d.get("end_date", "")) or period in str(d.get("period", ""))]

            return ToolResult(success=True, data=data, meta=result.get("meta"))

        except Exception as e:
            return ToolResult(success=False, error=f"获取现金流量表失败: {str(e)}")

    async def get_fina_indicator(self, ts_code: str, start_date: str = None, end_date: str = None, period: str = None) -> ToolResult:
        """
        获取财务指标
        """
        if not ts_code:
            return ToolResult(success=False, error="股票代码不能为空")

        try:
            result = self.get_tushare_client().get_fina_indicator(ts_code, start_date, end_date)

            if not result.get("success"):
                return ToolResult(success=False, error=result.get("error"))

            data = result.get("data", [])
            
            # 如果指定了period，过滤数据
            if period and data:
                data = [d for d in data if period in str(d.get("end_date", "")) or period in str(d.get("period", ""))]

            return ToolResult(success=True, data=data, meta=result.get("meta"))

        except Exception as e:
            return ToolResult(success=False, error=f"获取财务指标失败: {str(e)}")

    async def analyze_profitability(self, ts_code: str, periods: int = 8) -> ToolResult:
        """
        分析盈利能力
        """
        if not ts_code:
            return ToolResult(success=False, error="股票代码不能为空")

        try:
            result = self.get_tushare_client().get_fina_indicator(ts_code)

            if not result.get("success"):
                return ToolResult(success=False, error=result.get("error"))

            data = result.get("data", [])[:periods]
            if not data:
                return ToolResult(success=False, error="未找到财务指标数据")

            # 计算趋势
            trends = []
            for d in data:
                trends.append({
                    "period": d.get("end_date"),
                    "roe": d.get("roe"),
                    "gross_margin": d.get("gross_margin"),
                    "operating_margin": d.get("op_of_gr"),
                    "net_margin": d.get("netprofit_margin"),
                    "roa": d.get("roa"),
                })

            # 计算平均值
            avg_roe = sum(d.get("roe", 0) or 0 for d in data) / len(data) if data else 0
            avg_gross_margin = sum(d.get("gross_margin", 0) or 0 for d in data) / len(data) if data else 0

            # 判断趋势
            roe_trend = "up" if len(data) > 1 and data[0].get("roe", 0) > data[-1].get("roe", 0) else "down"

            analysis = {
                "ts_code": ts_code,
                "avg_roe": round(avg_roe, 2),
                "avg_gross_margin": round(avg_gross_margin, 2),
                "roe_trend": roe_trend,
                "trends": trends,
                "assessment": self._assess_profitability(avg_roe, avg_gross_margin)
            }

            return ToolResult(success=True, data=analysis)

        except Exception as e:
            return ToolResult(success=False, error=f"分析盈利能力失败: {str(e)}")

    def _assess_profitability(self, roe: float, gross_margin: float) -> str:
        """评估盈利能力"""
        if roe > 20:
            return "优秀"
        elif roe > 15:
            return "良好"
        elif roe > 10:
            return "一般"
        else:
            return "较弱"

    async def analyze_solvency(self, ts_code: str, period: str = None) -> ToolResult:
        """
        分析偿债能力
        """
        if not ts_code:
            return ToolResult(success=False, error="股票代码不能为空")

        try:
            result = self.get_tushare_client().get_fina_indicator(ts_code)

            if not result.get("success"):
                return ToolResult(success=False, error=result.get("error"))

            data = result.get("data", [])
            if not data:
                return ToolResult(success=False, error="未找到财务指标数据")

            latest = data[0] if not period else next(
                (d for d in data if d.get("end_date") == period), data[0]
            )

            solvency = {
                "ts_code": ts_code,
                "period": latest.get("end_date"),
                "current_ratio": latest.get("current_ratio"),
                "quick_ratio": latest.get("quick_ratio"),
                "cash_ratio": latest.get("cash_ratio"),
                "debt_to_assets": latest.get("debt_to_assets"),
                "debt_to_equity": latest.get("debt_to_eqt"),
                "equity_to_debt": latest.get("eqt_to_debt"),
                "interest_coverage": latest.get("ebit_to_interest"),
            }

            # 评估偿债能力
            solvency["assessment"] = self._assess_solvency(solvency)

            return ToolResult(success=True, data=solvency)

        except Exception as e:
            return ToolResult(success=False, error=f"分析偿债能力失败: {str(e)}")

    def _assess_solvency(self, ratios: Dict[str, Any]) -> str:
        """评估偿债能力"""
        current_ratio = ratios.get("current_ratio") or 0
        debt_ratio = ratios.get("debt_to_assets") or 0

        if current_ratio > 2 and debt_ratio < 0.5:
            return "优秀"
        elif current_ratio > 1.5 and debt_ratio < 0.6:
            return "良好"
        elif current_ratio > 1 and debt_ratio < 0.7:
            return "一般"
        else:
            return "较弱"

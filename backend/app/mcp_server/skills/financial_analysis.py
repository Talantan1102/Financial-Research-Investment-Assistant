# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""FinancialAnalysis Skill - 财务分析工具

提供 A 股上市公司财务报表分析能力，包括财报数据获取、财务指标计算、财报对比分析。
"""

from typing import Dict, Any, Optional, List
from datetime import datetime
from app.mcp_server.skills.base import BaseSkill, ToolParameter, ToolResult
from app.data.tushare_client import get_tushare_client, TushareClient


class FinancialAnalysisSkill(BaseSkill):
    """
    财务分析 Skill

    提供 A 股上市公司财务报表查询和分析功能，基于 Tushare 数据源。
    """

    name = "financial_analysis"
    description = "A股上市公司财务分析，支持财报查询、财务指标计算、财报对比分析"

    def __init__(self):
        self.tushare_client: TushareClient = get_tushare_client()
        super().__init__()

    def _register_tools(self):
        """注册财务分析相关工具"""

        # 1. 获取财务报表
        self.register_tool(
            name="get_financial_report",
            handler=self.get_financial_report,
            description="获取指定公司的财务报表数据，包括利润表、资产负债表、现金流量表",
            parameters=[
                ToolParameter(
                    name="symbol",
                    type="string",
                    description="股票代码，支持多种格式：'600519'、'sh600519'、'600519.SH'",
                    required=True
                ),
                ToolParameter(
                    name="report_type",
                    type="string",
                    description="报表类型：income(利润表)、balance(资产负债表)、cashflow(现金流量表)",
                    required=True,
                    enum=["income", "balance", "cashflow"]
                ),
                ToolParameter(
                    name="period",
                    type="string",
                    description="报告期，格式：YYYYMMDD，如 20231231。不填则返回最新报告期",
                    required=False
                ),
                ToolParameter(
                    name="report_count",
                    type="integer",
                    description="返回报告期数量，默认为1（最新一期），最多返回10期",
                    required=False,
                    default=1
                )
            ]
        )

        # 2. 计算财务比率
        self.register_tool(
            name="calculate_financial_ratios",
            handler=self.calculate_financial_ratios,
            description="计算关键财务指标和比率，如 ROE、ROA、毛利率、净利率、资产负债率等",
            parameters=[
                ToolParameter(
                    name="symbol",
                    type="string",
                    description="股票代码，支持多种格式：'600519'、'sh600519'、'600519.SH'",
                    required=True
                ),
                ToolParameter(
                    name="period",
                    type="string",
                    description="报告期，格式：YYYYMMDD，如 20231231。不填则返回最新报告期",
                    required=False
                )
            ]
        )

        # 3. 对比财务数据
        self.register_tool(
            name="compare_financial_data",
            handler=self.compare_financial_data,
            description="对比分析财务数据的同比/环比变化，支持营收、净利润等关键指标对比",
            parameters=[
                ToolParameter(
                    name="symbol",
                    type="string",
                    description="股票代码，支持多种格式：'600519'、'sh600519'、'600519.SH'",
                    required=True
                ),
                ToolParameter(
                    name="indicator",
                    type="string",
                    description="对比指标：revenue(营收)、net_profit(净利润)、roe(ROE)、roa(ROA)",
                    required=True,
                    enum=["revenue", "net_profit", "roe", "roa"]
                ),
                ToolParameter(
                    name="periods",
                    type="integer",
                    description="对比期数，默认为4（最近4个报告期），用于计算同比/环比",
                    required=False,
                    default=4
                )
            ]
        )

    async def get_financial_report(
        self,
        symbol: str,
        report_type: str,
        period: Optional[str] = None,
        report_count: int = 1
    ) -> ToolResult:
        """
        获取财务报表

        Args:
            symbol: 股票代码
            report_type: 报表类型（income/balance/cashflow）
            period: 报告期（YYYYMMDD格式）
            report_count: 返回报告期数量

        Returns:
            ToolResult 包含财务报表数据
        """
        if not symbol:
            return ToolResult(success=False, error="股票代码不能为空")

        if report_type not in ["income", "balance", "cashflow"]:
            return ToolResult(
                success=False,
                error=f"不支持的报表类型: {report_type}，仅支持 income、balance、cashflow"
            )

        if report_count < 1 or report_count > 10:
            return ToolResult(success=False, error="报告期数量必须在 1-10 之间")

        try:
            # 标准化股票代码
            ts_code = self.tushare_client._normalize_stock_code(symbol)

            # 检查 API 是否初始化
            if not self.tushare_client.api:
                return ToolResult(
                    success=False,
                    error="Tushare API 未初始化，请检查 TUSHARE_API_TOKEN 环境变量"
                )

            # 根据报表类型选择 API 接口
            if report_type == "income":
                df = self.tushare_client.api.income(
                    ts_code=ts_code,
                    period=period,
                    fields='ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,'
                           'total_revenue,revenue,operate_profit,total_profit,n_income,'
                           'n_income_attr_p,basic_eps,diluted_eps'
                )
                report_name = "利润表"
            elif report_type == "balance":
                df = self.tushare_client.api.balancesheet(
                    ts_code=ts_code,
                    period=period,
                    fields='ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,'
                           'total_assets,total_cur_assets,total_nca,total_liab,'
                           'total_cur_liab,total_ncl,total_hldr_eqy_exc_min_int,'
                           'total_hldr_eqy_inc_min_int'
                )
                report_name = "资产负债表"
            else:  # cashflow
                df = self.tushare_client.api.cashflow(
                    ts_code=ts_code,
                    period=period,
                    fields='ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,'
                           'n_cashflow_act,n_cashflow_inv_act,n_cashflow_fnc_act,'
                           'c_cash_equ_end_period,c_cash_equ_beg_period'
                )
                report_name = "现金流量表"

            if df is None or df.empty:
                return ToolResult(
                    success=False,
                    error=f"未找到股票 {symbol} 的{report_name}数据"
                )

            # 限制返回数量
            df = df.head(report_count)

            # 转换为字典列表
            reports = df.to_dict('records')

            # 格式化数据
            formatted_reports = []
            for report in reports:
                formatted_report = {
                    "ts_code": report.get("ts_code"),
                    "end_date": report.get("end_date"),
                    "ann_date": report.get("ann_date"),
                    "report_type": self._format_report_type(report.get("report_type")),
                }

                # 根据报表类型添加特定字段
                if report_type == "income":
                    formatted_report.update({
                        "total_revenue": self._format_number(report.get("total_revenue")),
                        "revenue": self._format_number(report.get("revenue")),
                        "operate_profit": self._format_number(report.get("operate_profit")),
                        "total_profit": self._format_number(report.get("total_profit")),
                        "net_income": self._format_number(report.get("n_income")),
                        "net_income_parent": self._format_number(report.get("n_income_attr_p")),
                        "basic_eps": self._format_number(report.get("basic_eps"), precision=4),
                        "diluted_eps": self._format_number(report.get("diluted_eps"), precision=4),
                    })
                elif report_type == "balance":
                    formatted_report.update({
                        "total_assets": self._format_number(report.get("total_assets")),
                        "total_current_assets": self._format_number(report.get("total_cur_assets")),
                        "total_non_current_assets": self._format_number(report.get("total_nca")),
                        "total_liabilities": self._format_number(report.get("total_liab")),
                        "total_current_liabilities": self._format_number(report.get("total_cur_liab")),
                        "total_non_current_liabilities": self._format_number(report.get("total_ncl")),
                        "total_equity": self._format_number(report.get("total_hldr_eqy_exc_min_int")),
                    })
                else:  # cashflow
                    formatted_report.update({
                        "operating_cashflow": self._format_number(report.get("n_cashflow_act")),
                        "investing_cashflow": self._format_number(report.get("n_cashflow_inv_act")),
                        "financing_cashflow": self._format_number(report.get("n_cashflow_fnc_act")),
                        "cash_end": self._format_number(report.get("c_cash_equ_end_period")),
                        "cash_begin": self._format_number(report.get("c_cash_equ_beg_period")),
                    })

                formatted_reports.append(formatted_report)

            return ToolResult(
                success=True,
                data={
                    "symbol": ts_code,
                    "report_type": report_name,
                    "report_count": len(formatted_reports),
                    "reports": formatted_reports
                }
            )

        except Exception as e:
            return ToolResult(
                success=False,
                error=f"获取财务报表失败: {str(e)}"
            )

    async def calculate_financial_ratios(
        self,
        symbol: str,
        period: Optional[str] = None
    ) -> ToolResult:
        """
        计算财务比率

        Args:
            symbol: 股票代码
            period: 报告期（YYYYMMDD格式）

        Returns:
            ToolResult 包含财务指标数据
        """
        if not symbol:
            return ToolResult(success=False, error="股票代码不能为空")

        try:
            # 标准化股票代码
            ts_code = self.tushare_client._normalize_stock_code(symbol)

            # 检查 API 是否初始化
            if not self.tushare_client.api:
                return ToolResult(
                    success=False,
                    error="Tushare API 未初始化，请检查 TUSHARE_API_TOKEN 环境变量"
                )

            # 获取财务指标数据
            df = self.tushare_client.api.fina_indicator(
                ts_code=ts_code,
                period=period,
                fields='ts_code,ann_date,end_date,eps,roe,roe_waa,roe_dt,roa,'
                       'grossprofit_margin,netprofit_margin,debt_to_assets,'
                       'current_ratio,quick_ratio,ocf_to_or,or_last_year,'
                       'op_yoy,ebt_yoy,netprofit_yoy,dt_netprofit_yoy'
            )

            if df is None or df.empty:
                return ToolResult(
                    success=False,
                    error=f"未找到股票 {symbol} 的财务指标数据"
                )

            # 获取最新一期数据
            latest = df.iloc[0]

            # 格式化财务指标
            ratios = {
                "ts_code": latest.get("ts_code"),
                "end_date": latest.get("end_date"),
                "ann_date": latest.get("ann_date"),

                # 盈利能力指标
                "eps": self._format_number(latest.get("eps"), precision=4),
                "roe": self._format_percentage(latest.get("roe")),
                "roe_weighted": self._format_percentage(latest.get("roe_waa")),
                "roe_diluted": self._format_percentage(latest.get("roe_dt")),
                "roa": self._format_percentage(latest.get("roa")),
                "gross_profit_margin": self._format_percentage(latest.get("grossprofit_margin")),
                "net_profit_margin": self._format_percentage(latest.get("netprofit_margin")),

                # 偿债能力指标
                "debt_to_assets": self._format_percentage(latest.get("debt_to_assets")),
                "current_ratio": self._format_number(latest.get("current_ratio"), precision=2),
                "quick_ratio": self._format_number(latest.get("quick_ratio"), precision=2),

                # 增长能力指标
                "revenue_yoy": self._format_percentage(latest.get("or_last_year")),
                "operating_profit_yoy": self._format_percentage(latest.get("op_yoy")),
                "profit_before_tax_yoy": self._format_percentage(latest.get("ebt_yoy")),
                "net_profit_yoy": self._format_percentage(latest.get("netprofit_yoy")),

                # 现金流指标
                "ocf_to_revenue": self._format_percentage(latest.get("ocf_to_or")),
            }

            return ToolResult(
                success=True,
                data={
                    "symbol": ts_code,
                    "ratios": ratios,
                    "summary": self._generate_ratio_summary(ratios)
                }
            )

        except Exception as e:
            return ToolResult(
                success=False,
                error=f"计算财务指标失败: {str(e)}"
            )

    async def compare_financial_data(
        self,
        symbol: str,
        indicator: str,
        periods: int = 4
    ) -> ToolResult:
        """
        对比财务数据

        Args:
            symbol: 股票代码
            indicator: 对比指标
            periods: 对比期数

        Returns:
            ToolResult 包含对比分析数据
        """
        if not symbol:
            return ToolResult(success=False, error="股票代码不能为空")

        if indicator not in ["revenue", "net_profit", "roe", "roa"]:
            return ToolResult(
                success=False,
                error=f"不支持的指标: {indicator}，仅支持 revenue、net_profit、roe、roa"
            )

        if periods < 2 or periods > 20:
            return ToolResult(success=False, error="对比期数必须在 2-20 之间")

        try:
            # 标准化股票代码
            ts_code = self.tushare_client._normalize_stock_code(symbol)

            # 检查 API 是否初始化
            if not self.tushare_client.api:
                return ToolResult(
                    success=False,
                    error="Tushare API 未初始化，请检查 TUSHARE_API_TOKEN 环境变量"
                )

            # 根据指标类型选择数据源
            if indicator in ["revenue", "net_profit"]:
                # 从利润表获取数据
                df = self.tushare_client.api.income(
                    ts_code=ts_code,
                    fields='ts_code,end_date,total_revenue,n_income_attr_p'
                )

                if df is None or df.empty:
                    return ToolResult(
                        success=False,
                        error=f"未找到股票 {symbol} 的利润表数据"
                    )

                # 限制期数
                df = df.head(periods)

                # 选择指标字段
                if indicator == "revenue":
                    field_name = "total_revenue"
                    indicator_name = "营业总收入"
                    unit = "万元"
                else:
                    field_name = "n_income_attr_p"
                    indicator_name = "归母净利润"
                    unit = "万元"

            else:  # roe, roa
                # 从财务指标获取数据
                df = self.tushare_client.api.fina_indicator(
                    ts_code=ts_code,
                    fields='ts_code,end_date,roe,roa'
                )

                if df is None or df.empty:
                    return ToolResult(
                        success=False,
                        error=f"未找到股票 {symbol} 的财务指标数据"
                    )

                # 限制期数
                df = df.head(periods)

                # 选择指标字段
                field_name = indicator
                indicator_name = indicator.upper()
                unit = "%"

            # 提取数据
            data_points = []
            for idx, row in df.iterrows():
                value = row.get(field_name)
                if value is not None:
                    data_points.append({
                        "end_date": row.get("end_date"),
                        "value": float(value),
                        "formatted_value": self._format_number(value, precision=2) if unit == "万元" else self._format_percentage(value)
                    })

            if len(data_points) < 2:
                return ToolResult(
                    success=False,
                    error=f"数据不足，至少需要2期数据进行对比"
                )

            # 计算同比/环比变化
            comparisons = []
            for i in range(len(data_points) - 1):
                current = data_points[i]
                previous = data_points[i + 1]

                # 环比变化
                qoq_change = current["value"] - previous["value"]
                qoq_rate = (qoq_change / previous["value"] * 100) if previous["value"] != 0 else 0

                comparisons.append({
                    "current_period": current["end_date"],
                    "previous_period": previous["end_date"],
                    "current_value": current["formatted_value"],
                    "previous_value": previous["formatted_value"],
                    "change": self._format_number(qoq_change, precision=2),
                    "change_rate": f"{qoq_rate:.2f}%",
                    "trend": "上升" if qoq_change > 0 else "下降" if qoq_change < 0 else "持平"
                })

            # 计算同比变化（如果数据足够）
            yoy_comparisons = []
            if len(data_points) >= 5:  # 至少需要5期数据（4个季度 + 1）
                for i in range(len(data_points) - 4):
                    current = data_points[i]
                    year_ago = data_points[i + 4]

                    yoy_change = current["value"] - year_ago["value"]
                    yoy_rate = (yoy_change / year_ago["value"] * 100) if year_ago["value"] != 0 else 0

                    yoy_comparisons.append({
                        "current_period": current["end_date"],
                        "year_ago_period": year_ago["end_date"],
                        "current_value": current["formatted_value"],
                        "year_ago_value": year_ago["formatted_value"],
                        "change": self._format_number(yoy_change, precision=2),
                        "change_rate": f"{yoy_rate:.2f}%",
                        "trend": "上升" if yoy_change > 0 else "下降" if yoy_change < 0 else "持平"
                    })

            return ToolResult(
                success=True,
                data={
                    "symbol": ts_code,
                    "indicator": indicator_name,
                    "unit": unit,
                    "data_points": data_points,
                    "qoq_comparisons": comparisons,
                    "yoy_comparisons": yoy_comparisons,
                    "summary": self._generate_comparison_summary(
                        indicator_name,
                        data_points,
                        comparisons
                    )
                }
            )

        except Exception as e:
            return ToolResult(
                success=False,
                error=f"对比财务数据失败: {str(e)}"
            )

    # 辅助方法

    def _format_number(self, value: Any, precision: int = 2) -> str:
        """格式化数字"""
        if value is None or value == "":
            return "N/A"
        try:
            return f"{float(value):.{precision}f}"
        except (ValueError, TypeError):
            return "N/A"

    def _format_percentage(self, value: Any) -> str:
        """格式化百分比"""
        if value is None or value == "":
            return "N/A"
        try:
            return f"{float(value):.2f}%"
        except (ValueError, TypeError):
            return "N/A"

    def _format_report_type(self, code: Any) -> str:
        """格式化报告类型"""
        type_map = {
            "1": "年报",
            "2": "半年报",
            "3": "一季报",
            "4": "三季报",
            1: "年报",
            2: "半年报",
            3: "一季报",
            4: "三季报"
        }
        return type_map.get(code, "未知")

    def _generate_ratio_summary(self, ratios: Dict[str, Any]) -> str:
        """生成财务指标摘要"""
        summary_parts = []

        # ROE 分析
        roe = ratios.get("roe", "N/A")
        if roe != "N/A":
            roe_value = float(roe.rstrip('%'))
            if roe_value >= 15:
                summary_parts.append(f"ROE {roe}（优秀）")
            elif roe_value >= 10:
                summary_parts.append(f"ROE {roe}（良好）")
            else:
                summary_parts.append(f"ROE {roe}（一般）")

        # 毛利率分析
        gross_margin = ratios.get("gross_profit_margin", "N/A")
        if gross_margin != "N/A":
            summary_parts.append(f"毛利率 {gross_margin}")

        # 净利率分析
        net_margin = ratios.get("net_profit_margin", "N/A")
        if net_margin != "N/A":
            summary_parts.append(f"净利率 {net_margin}")

        # 资产负债率分析
        debt_ratio = ratios.get("debt_to_assets", "N/A")
        if debt_ratio != "N/A":
            debt_value = float(debt_ratio.rstrip('%'))
            if debt_value <= 40:
                summary_parts.append(f"资产负债率 {debt_ratio}（低风险）")
            elif debt_value <= 60:
                summary_parts.append(f"资产负债率 {debt_ratio}（中等风险）")
            else:
                summary_parts.append(f"资产负债率 {debt_ratio}（高风险）")

        return "；".join(summary_parts) if summary_parts else "财务指标数据不足"

    def _generate_comparison_summary(
        self,
        indicator_name: str,
        data_points: List[Dict[str, Any]],
        comparisons: List[Dict[str, Any]]
    ) -> str:
        """生成对比分析摘要"""
        if not data_points or not comparisons:
            return "数据不足"

        # 最新期数据
        latest = data_points[0]

        # 环比变化
        latest_comparison = comparisons[0]
        trend = latest_comparison["trend"]
        change_rate = latest_comparison["change_rate"]

        # 计算平均增长率
        total_rate = sum(
            float(comp["change_rate"].rstrip('%'))
            for comp in comparisons
        )
        avg_rate = total_rate / len(comparisons)

        summary = (
            f"{indicator_name}最新值为 {latest['formatted_value']}，"
            f"环比{trend} {change_rate}。"
            f"近{len(comparisons)}期平均增长率为 {avg_rate:.2f}%"
        )

        return summary

    def get_cache_info(self) -> Dict[str, Any]:
        """获取缓存信息"""
        return self.tushare_client.get_cache_info()

    def clear_cache(self):
        """清空缓存"""
        self.tushare_client.clear_cache()

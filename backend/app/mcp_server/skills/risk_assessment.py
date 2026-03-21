# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""RiskAssessment Skill - 风险评估工具

提供投资风险评估功能。
"""

from typing import Dict, Any, Optional, List
from app.mcp_server.skills.base import BaseSkill, ToolParameter, ToolResult
from app.data.tushare_client import get_tushare_client, TushareClient


class RiskAssessmentSkill(BaseSkill):
    """
    风险评估 Skill

    提供投资风险评估，评估个股风险等级、提供预警。
    """

    name = "risk_assessment"
    description = "投资风险评估，评估个股风险等级、提供预警"

    def __init__(self):
        self._tushare_client: Optional[TushareClient] = None
        super().__init__()

    def get_tushare_client(self) -> TushareClient:
        """获取 TushareClient 实例（延迟初始化）"""
        if self._tushare_client is None:
            self._tushare_client = get_tushare_client()
        return self._tushare_client

    def _register_tools(self):
        """注册 RiskAssessment 相关工具"""

        # 1. 综合风险评估
        self.register_tool(
            name="assess_stock_risk",
            handler=self.assess_stock_risk,
            description="综合评估股票风险等级，包括市场风险、财务风险、估值风险等",
            parameters=[
                ToolParameter(
                    name="ts_code",
                    type="string",
                    description="TS股票代码，如 600519.SH",
                    required=True
                )
            ]
        )

        # 2. 估值风险评估
        self.register_tool(
            name="assess_valuation_risk",
            handler=self.assess_valuation_risk,
            description="评估估值风险，分析PE/PB是否过高",
            parameters=[
                ToolParameter(
                    name="ts_code",
                    type="string",
                    description="TS股票代码，如 600519.SH",
                    required=True
                ),
                ToolParameter(
                    name="industry_pe_avg",
                    type="number",
                    description="行业平均PE，用于对比",
                    required=False,
                    default=None
                )
            ]
        )

        # 3. 财务风险评估
        self.register_tool(
            name="assess_financial_risk",
            handler=self.assess_financial_risk,
            description="评估财务风险，分析资产负债率、现金流等",
            parameters=[
                ToolParameter(
                    name="ts_code",
                    type="string",
                    description="TS股票代码，如 600519.SH",
                    required=True
                )
            ]
        )

        # 4. 波动率风险评估
        self.register_tool(
            name="assess_volatility_risk",
            handler=self.assess_volatility_risk,
            description="评估股价波动风险，分析历史波动率",
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
                    description="计算周期：20d(20日), 60d(60日), 120d(120日)",
                    required=False,
                    default="60d"
                )
            ]
        )

        # 5. 风险预警检查
        self.register_tool(
            name="check_risk_warnings",
            handler=self.check_risk_warnings,
            description="检查股票的风险预警信号",
            parameters=[
                ToolParameter(
                    name="ts_code",
                    type="string",
                    description="TS股票代码，如 600519.SH",
                    required=True
                )
            ]
        )

    async def assess_stock_risk(self, ts_code: str) -> ToolResult:
        """综合风险评估"""
        if not ts_code:
            return ToolResult(success=False, error="股票代码不能为空")

        try:
            # 获取估值数据
            valuation_result = await self.assess_valuation_risk(ts_code)
            financial_result = await self.assess_financial_risk(ts_code)
            volatility_result = await self.assess_volatility_risk(ts_code)

            # 综合评分
            risk_score = 0
            risk_factors = []

            if valuation_result.success:
                v_data = valuation_result.data
                risk_score += v_data.get("risk_score", 0) * 0.3
                risk_factors.extend(v_data.get("risk_factors", []))

            if financial_result.success:
                f_data = financial_result.data
                risk_score += f_data.get("risk_score", 0) * 0.4
                risk_factors.extend(f_data.get("risk_factors", []))

            if volatility_result.success:
                vol_data = volatility_result.data
                risk_score += vol_data.get("risk_score", 0) * 0.3
                risk_factors.extend(vol_data.get("risk_factors", []))

            # 确定风险等级
            risk_level = self._determine_risk_level(risk_score)

            assessment = {
                "ts_code": ts_code,
                "risk_score": round(risk_score, 2),
                "risk_level": risk_level,
                "risk_factors": list(set(risk_factors)),
                "components": {
                    "valuation": valuation_result.data if valuation_result.success else None,
                    "financial": financial_result.data if financial_result.success else None,
                    "volatility": volatility_result.data if volatility_result.success else None
                }
            }

            return ToolResult(success=True, data=assessment)

        except Exception as e:
            return ToolResult(success=False, error=f"风险评估失败: {str(e)}")

    def _determine_risk_level(self, score: float) -> str:
        """确定风险等级"""
        if score <= 30:
            return "低风险"
        elif score <= 50:
            return "中低风险"
        elif score <= 70:
            return "中风险"
        elif score <= 85:
            return "中高风险"
        else:
            return "高风险"

    async def assess_valuation_risk(self, ts_code: str, industry_pe_avg: float = None) -> ToolResult:
        """估值风险评估"""
        if not ts_code:
            return ToolResult(success=False, error="股票代码不能为空")

        try:
            # 获取每日指标
            result = self.get_tushare_client().get_daily_basic(ts_code)

            if not result.get("success"):
                return ToolResult(success=False, error=result.get("error"))

            data = result.get("data", [])
            if not data:
                return ToolResult(success=False, error="未找到估值数据")

            latest = data[0]
            pe = latest.get("pe", 0) or 0
            pe_ttm = latest.get("pe_ttm", 0) or 0
            pb = latest.get("pb", 0) or 0

            # 计算风险分数 (0-100)
            risk_score = 0
            risk_factors = []

            # PE风险
            if pe > 100:
                risk_score += 40
                risk_factors.append("PE超过100，估值极高")
            elif pe > 50:
                risk_score += 25
                risk_factors.append("PE超过50，估值偏高")
            elif pe > 30:
                risk_score += 10
                risk_factors.append("PE超过30，估值略高")

            # PB风险
            if pb > 10:
                risk_score += 30
                risk_factors.append("PB超过10，市净率极高")
            elif pb > 5:
                risk_score += 15
                risk_factors.append("PB超过5，市净率偏高")

            # 行业对比
            if industry_pe_avg and pe > industry_pe_avg * 1.5:
                risk_score += 20
                risk_factors.append(f"PE高于行业平均({industry_pe_avg:.2f})50%以上")

            assessment = {
                "ts_code": ts_code,
                "pe": pe,
                "pe_ttm": pe_ttm,
                "pb": pb,
                "risk_score": min(risk_score, 100),
                "risk_factors": risk_factors,
                "assessment": "估值合理" if risk_score < 20 else "估值偏高" if risk_score < 50 else "估值过高"
            }

            return ToolResult(success=True, data=assessment)

        except Exception as e:
            return ToolResult(success=False, error=f"估值风险评估失败: {str(e)}")

    async def assess_financial_risk(self, ts_code: str) -> ToolResult:
        """财务风险评估"""
        if not ts_code:
            return ToolResult(success=False, error="股票代码不能为空")

        try:
            # 获取财务指标
            result = self.get_tushare_client().get_fina_indicator(ts_code)

            if not result.get("success"):
                return ToolResult(success=False, error=result.get("error"))

            data = result.get("data", [])
            if not data:
                return ToolResult(success=False, error="未找到财务数据")

            latest = data[0]

            # 计算风险分数
            risk_score = 0
            risk_factors = []

            debt_ratio = latest.get("debt_to_assets", 0) or 0
            current_ratio = latest.get("current_ratio", 0) or 0
            quick_ratio = latest.get("quick_ratio", 0) or 0

            # 资产负债率风险
            if debt_ratio > 0.8:
                risk_score += 35
                risk_factors.append("资产负债率超过80%，偿债压力极大")
            elif debt_ratio > 0.6:
                risk_score += 20
                risk_factors.append("资产负债率超过60%，偿债压力较大")
            elif debt_ratio > 0.4:
                risk_score += 10
                risk_factors.append("资产负债率超过40%，需关注")

            # 流动比率风险
            if current_ratio < 1:
                risk_score += 30
                risk_factors.append("流动比率低于1，短期偿债能力不足")
            elif current_ratio < 1.5:
                risk_score += 15
                risk_factors.append("流动比率低于1.5，短期偿债能力偏弱")

            # 速动比率风险
            if quick_ratio < 0.8:
                risk_score += 20
                risk_factors.append("速动比率低于0.8")

            assessment = {
                "ts_code": ts_code,
                "debt_to_assets": debt_ratio,
                "current_ratio": current_ratio,
                "quick_ratio": quick_ratio,
                "risk_score": min(risk_score, 100),
                "risk_factors": risk_factors,
                "assessment": "财务状况良好" if risk_score < 20 else "存在一定财务风险" if risk_score < 50 else "财务风险较高"
            }

            return ToolResult(success=True, data=assessment)

        except Exception as e:
            return ToolResult(success=False, error=f"财务风险评估失败: {str(e)}")

    async def assess_volatility_risk(self, ts_code: str, period: str = "60d") -> ToolResult:
        """波动率风险评估"""
        if not ts_code:
            return ToolResult(success=False, error="股票代码不能为空")

        try:
            # 获取历史数据
            days = int(period.replace("d", ""))
            result = self.get_tushare_client().get_history(ts_code, limit=days)

            if not result.get("success"):
                return ToolResult(success=False, error=result.get("error"))

            data = result.get("data", [])
            if len(data) < 20:
                return ToolResult(success=False, error="历史数据不足")

            # 计算日收益率
            returns = []
            for i in range(len(data) - 1):
                if data[i].get("pre_close", 0) > 0:
                    daily_return = (data[i]["close"] - data[i]["pre_close"]) / data[i]["pre_close"]
                    returns.append(daily_return)

            if not returns:
                return ToolResult(success=False, error="无法计算收益率")

            # 计算波动率（标准差）
            import statistics
            volatility = statistics.stdev(returns) * (252 ** 0.5)  # 年化波动率

            # 计算风险分数
            risk_score = 0
            risk_factors = []

            if volatility > 0.8:
                risk_score += 50
                risk_factors.append("年化波动率超过80%，波动极大")
            elif volatility > 0.5:
                risk_score += 35
                risk_factors.append("年化波动率超过50%，波动较大")
            elif volatility > 0.3:
                risk_score += 20
                risk_factors.append("年化波动率超过30%，存在一定波动")

            # 计算最大回撤
            max_drawdown = self._calculate_max_drawdown(data)
            if max_drawdown > 0.3:
                risk_score += 25
                risk_factors.append(f"最大回撤超过30%({max_drawdown:.2%})")

            assessment = {
                "ts_code": ts_code,
                "annual_volatility": round(volatility * 100, 2),
                "max_drawdown": round(max_drawdown * 100, 2),
                "risk_score": min(risk_score, 100),
                "risk_factors": risk_factors,
                "assessment": "波动适中" if risk_score < 30 else "波动较大" if risk_score < 60 else "波动极大"
            }

            return ToolResult(success=True, data=assessment)

        except Exception as e:
            return ToolResult(success=False, error=f"波动率风险评估失败: {str(e)}")

    def _calculate_max_drawdown(self, data: List[Dict]) -> float:
        """计算最大回撤"""
        if not data:
            return 0

        max_price = 0
        max_dd = 0

        for d in data:
            price = d.get("close", 0)
            if price > max_price:
                max_price = price
            if max_price > 0:
                dd = (max_price - price) / max_price
                if dd > max_dd:
                    max_dd = dd

        return max_dd

    async def check_risk_warnings(self, ts_code: str) -> ToolResult:
        """风险预警检查"""
        if not ts_code:
            return ToolResult(success=False, error="股票代码不能为空")

        try:
            warnings = []

            # 获取综合风险
            risk_result = await self.assess_stock_risk(ts_code)
            if risk_result.success:
                risk_data = risk_result.data
                if risk_data.get("risk_level") in ["中高风险", "高风险"]:
                    warnings.append({
                        "level": "high",
                        "type": "综合风险",
                        "message": f"综合风险等级：{risk_data.get('risk_level')}"
                    })

            # 获取估值风险
            valuation_result = await self.assess_valuation_risk(ts_code)
            if valuation_result.success:
                v_data = valuation_result.data
                if v_data.get("pe", 0) > 50:
                    warnings.append({
                        "level": "medium",
                        "type": "估值风险",
                        "message": f"PE({v_data.get('pe'):.2f})偏高"
                    })

            # 获取财务风险
            financial_result = await self.assess_financial_risk(ts_code)
            if financial_result.success:
                f_data = financial_result.data
                if f_data.get("debt_to_assets", 0) > 0.6:
                    warnings.append({
                        "level": "medium",
                        "type": "财务风险",
                        "message": f"资产负债率({f_data.get('debt_to_assets'):.2%})较高"
                    })

            return ToolResult(success=True, data={
                "ts_code": ts_code,
                "warning_count": len(warnings),
                "warnings": warnings,
                "has_critical_warning": any(w["level"] == "high" for w in warnings)
            })

        except Exception as e:
            return ToolResult(success=False, error=f"风险预警检查失败: {str(e)}")

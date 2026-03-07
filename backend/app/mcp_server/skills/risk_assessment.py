# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权,禁止转售或仿制。

"""RiskAssessment Skill - 投资组合风险评估工具

提供投资组合风险评估能力,包括风险指标计算、投资组合分析、风险报告生成。
"""

import re
import numpy as np
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta
from app.mcp_server.skills.base import BaseSkill, ToolParameter, ToolResult
from app.data.tushare_client import get_tushare_client, TushareClient


class RiskAssessmentSkill(BaseSkill):
    """
    投资组合风险评估 Skill

    提供投资组合风险分析功能,基于历史数据计算各类风险指标。
    """

    name = "risk_assessment"
    description = "投资组合风险评估,支持风险指标计算、投资组合分析、风险报告生成"

    def __init__(self):
        self.tushare_client: TushareClient = get_tushare_client()
        # 无风险收益率(年化),默认3%(中国国债收益率)
        self.risk_free_rate = 0.03
        super().__init__()

    def _register_tools(self):
        """注册风险评估相关工具"""

        # 1. 评估投资组合风险
        self.register_tool(
            name="assess_portfolio_risk",
            handler=self.assess_portfolio_risk,
            description="评估投资组合的整体风险,基于历史数据计算预期收益、波动率、夏普比率等指标",
            parameters=[
                ToolParameter(
                    name="portfolio",
                    type="string",
                    description="投资组合描述,格式: '股票代码1:权重1,股票代码2:权重2,...' 例如: '600519:0.4,000001:0.3,600036:0.3'",
                    required=True
                ),
                ToolParameter(
                    name="days",
                    type="integer",
                    description="历史数据天数,用于计算风险指标,默认252天(一个交易年)",
                    required=False,
                    default=252
                ),
                ToolParameter(
                    name="benchmark",
                    type="string",
                    description="基准指数代码(可选),用于计算Beta值,例如: '000001'(上证指数)、'399001'(深证成指)",
                    required=False
                )
            ]
        )

        # 2. 计算单项资产风险指标
        self.register_tool(
            name="calculate_risk_metrics",
            handler=self.calculate_risk_metrics,
            description="计算单项资产的风险指标,包括波动率、Beta、最大回撤等",
            parameters=[
                ToolParameter(
                    name="symbol",
                    type="string",
                    description="股票代码,支持多种格式: '600519'、'sh600519'、'600519.SH'",
                    required=True
                ),
                ToolParameter(
                    name="days",
                    type="integer",
                    description="历史数据天数,默认252天(一个交易年)",
                    required=False,
                    default=252
                ),
                ToolParameter(
                    name="benchmark",
                    type="string",
                    description="基准指数代码(可选),用于计算Beta值",
                    required=False
                )
            ]
        )

        # 3. 生成风险报告
        self.register_tool(
            name="generate_risk_report",
            handler=self.generate_risk_report,
            description="生成详细的风险评估报告,包括风险等级、投资建议、风险提示",
            parameters=[
                ToolParameter(
                    name="symbol",
                    type="string",
                    description="股票代码或投资组合描述",
                    required=True
                ),
                ToolParameter(
                    name="days",
                    type="integer",
                    description="历史数据天数,默认252天",
                    required=False,
                    default=252
                ),
                ToolParameter(
                    name="is_portfolio",
                    type="boolean",
                    description="是否为投资组合(True)或单一股票(False),默认False",
                    required=False,
                    default=False
                )
            ]
        )

    async def assess_portfolio_risk(
        self,
        portfolio: str,
        days: int = 252,
        benchmark: Optional[str] = None
    ) -> ToolResult:
        """
        评估投资组合风险

        Args:
            portfolio: 投资组合描述 "代码1:权重1,代码2:权重2,..."
            days: 历史数据天数
            benchmark: 基准指数代码

        Returns:
            ToolResult 包含投资组合风险评估结果
        """
        if not portfolio:
            return ToolResult(success=False, error="投资组合描述不能为空")

        try:
            # 解析投资组合
            holdings = self._parse_portfolio(portfolio)
            if not holdings:
                return ToolResult(
                    success=False,
                    error="投资组合格式错误,请使用格式: '代码1:权重1,代码2:权重2,...'"
                )

            # 验证权重和为1
            total_weight = sum(holdings.values())
            if abs(total_weight - 1.0) > 0.01:
                return ToolResult(
                    success=False,
                    error=f"投资组合权重之和必须为1,当前为{total_weight:.2f}"
                )

            # 获取各资产的历史价格数据
            returns_data = {}
            stock_names = {}

            for symbol, weight in holdings.items():
                price_result = await self._get_historical_prices(symbol, days)
                if not price_result["success"]:
                    return ToolResult(
                        success=False,
                        error=f"获取{symbol}历史数据失败: {price_result['error']}"
                    )

                returns_data[symbol] = price_result["returns"]
                stock_names[symbol] = price_result["name"]

            # 对齐所有资产的交易日期
            aligned_returns = self._align_returns(returns_data)
            if not aligned_returns:
                return ToolResult(
                    success=False,
                    error="无法对齐投资组合的历史数据,可能数据不足"
                )

            # 计算投资组合收益率
            portfolio_returns = self._calculate_portfolio_returns(
                aligned_returns, holdings
            )

            # 计算投资组合风险指标
            metrics = self._calculate_portfolio_metrics(
                portfolio_returns, aligned_returns, holdings
            )

            # 如果提供了基准,计算相对指标
            if benchmark:
                benchmark_result = await self._get_historical_prices(benchmark, days)
                if benchmark_result["success"]:
                    metrics["benchmark"] = {
                        "name": benchmark_result["name"],
                        "return": self._calculate_annualized_return(
                            benchmark_result["returns"]
                        ),
                        "volatility": self._calculate_volatility(
                            benchmark_result["returns"]
                        )
                    }

                    # 计算Beta
                    portfolio_returns_array = np.array(portfolio_returns)
                    benchmark_returns_array = np.array(benchmark_result["returns"])

                    # 对齐长度
                    min_len = min(len(portfolio_returns_array), len(benchmark_returns_array))
                    portfolio_returns_array = portfolio_returns_array[:min_len]
                    benchmark_returns_array = benchmark_returns_array[:min_len]

                    if len(portfolio_returns_array) > 1:
                        covariance = np.cov(portfolio_returns_array, benchmark_returns_array)[0, 1]
                        benchmark_variance = np.var(benchmark_returns_array, ddof=1)
                        if benchmark_variance > 0:
                            metrics["beta"] = covariance / benchmark_variance

            # 组装返回数据
            return ToolResult(
                success=True,
                data={
                    "portfolio": {
                        "holdings": [
                            {
                                "symbol": symbol,
                                "name": stock_names.get(symbol, "未知"),
                                "weight": f"{weight * 100:.2f}%"
                            }
                            for symbol, weight in holdings.items()
                        ],
                        "data_period": f"{days}天",
                        "data_points": len(portfolio_returns)
                    },
                    "metrics": metrics,
                    "risk_assessment": self._assess_risk_level(metrics)
                }
            )

        except Exception as e:
            return ToolResult(
                success=False,
                error=f"评估投资组合风险失败: {str(e)}"
            )

    async def calculate_risk_metrics(
        self,
        symbol: str,
        days: int = 252,
        benchmark: Optional[str] = None
    ) -> ToolResult:
        """
        计算单项资产风险指标

        Args:
            symbol: 股票代码
            days: 历史数据天数
            benchmark: 基准指数代码

        Returns:
            ToolResult 包含风险指标数据
        """
        if not symbol:
            return ToolResult(success=False, error="股票代码不能为空")

        try:
            # 获取历史价格数据
            price_result = await self._get_historical_prices(symbol, days)
            if not price_result["success"]:
                return ToolResult(
                    success=False,
                    error=f"获取历史数据失败: {price_result['error']}"
                )

            returns = price_result["returns"]
            prices = price_result["prices"]

            # 计算基本风险指标
            metrics = {
                "expected_return": self._calculate_annualized_return(returns),
                "volatility": self._calculate_volatility(returns),
                "sharpe_ratio": self._calculate_sharpe_ratio(returns),
                "max_drawdown": self._calculate_max_drawdown(prices),
                "var_95": self._calculate_var(returns, 0.95),
                "cvar_95": self._calculate_cvar(returns, 0.95),
                "downside_deviation": self._calculate_downside_deviation(returns)
            }

            # 如果提供了基准,计算Beta和相关性
            if benchmark:
                benchmark_result = await self._get_historical_prices(benchmark, days)
                if benchmark_result["success"]:
                    benchmark_returns = benchmark_result["returns"]

                    # 对齐长度
                    min_len = min(len(returns), len(benchmark_returns))
                    returns_array = np.array(returns[:min_len])
                    benchmark_returns_array = np.array(benchmark_returns[:min_len])

                    if len(returns_array) > 1:
                        # 计算Beta
                        covariance = np.cov(returns_array, benchmark_returns_array)[0, 1]
                        benchmark_variance = np.var(benchmark_returns_array, ddof=1)
                        if benchmark_variance > 0:
                            metrics["beta"] = covariance / benchmark_variance
                        else:
                            metrics["beta"] = None

                        # 计算相关系数
                        correlation = np.corrcoef(returns_array, benchmark_returns_array)[0, 1]
                        metrics["correlation"] = correlation

                        # Alpha (年化超额收益)
                        if metrics["beta"] is not None:
                            benchmark_return = self._calculate_annualized_return(benchmark_returns)
                            expected_return_capm = self.risk_free_rate + metrics["beta"] * (
                                benchmark_return - self.risk_free_rate
                            )
                            metrics["alpha"] = metrics["expected_return"] - expected_return_capm

                    metrics["benchmark"] = {
                        "name": benchmark_result["name"],
                        "return": self._calculate_annualized_return(benchmark_returns),
                        "volatility": self._calculate_volatility(benchmark_returns)
                    }

            return ToolResult(
                success=True,
                data={
                    "symbol": symbol,
                    "name": price_result["name"],
                    "data_period": f"{days}天",
                    "data_points": len(returns),
                    "metrics": metrics,
                    "risk_assessment": self._assess_risk_level(metrics)
                }
            )

        except Exception as e:
            return ToolResult(
                success=False,
                error=f"计算风险指标失败: {str(e)}"
            )

    async def generate_risk_report(
        self,
        symbol: str,
        days: int = 252,
        is_portfolio: bool = False
    ) -> ToolResult:
        """
        生成风险报告

        Args:
            symbol: 股票代码或投资组合描述
            days: 历史数据天数
            is_portfolio: 是否为投资组合

        Returns:
            ToolResult 包含风险报告
        """
        if not symbol:
            return ToolResult(success=False, error="股票代码或投资组合描述不能为空")

        try:
            # 根据类型调用相应的方法
            if is_portfolio:
                result = await self.assess_portfolio_risk(symbol, days)
            else:
                result = await self.calculate_risk_metrics(symbol, days)

            if not result.success:
                return result

            # 提取数据
            data = result.data
            metrics = data["metrics"]
            risk_assessment = data["risk_assessment"]

            # 生成报告
            report = {
                "title": "投资风险评估报告" if is_portfolio else "资产风险评估报告",
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "subject": symbol,
                "data_period": data.get("data_period", "未知"),

                # 风险评级
                "risk_rating": {
                    "level": risk_assessment["level"],
                    "score": risk_assessment["score"],
                    "description": risk_assessment["description"]
                },

                # 关键指标
                "key_metrics": {
                    "预期年化收益率": f"{metrics.get('expected_return', 0) * 100:.2f}%",
                    "波动率(年化)": f"{metrics.get('volatility', 0) * 100:.2f}%",
                    "夏普比率": f"{metrics.get('sharpe_ratio', 0):.2f}",
                    "最大回撤": f"{metrics.get('max_drawdown', 0) * 100:.2f}%",
                    "95% VaR": f"{metrics.get('var_95', 0) * 100:.2f}%",
                    "95% CVaR": f"{metrics.get('cvar_95', 0) * 100:.2f}%"
                },

                # 投资建议
                "recommendations": self._generate_recommendations(metrics, risk_assessment),

                # 风险提示
                "risk_warnings": self._generate_risk_warnings(metrics, risk_assessment),

                # 详细数据
                "detailed_metrics": metrics
            }

            # 如果是投资组合,添加持仓信息
            if is_portfolio and "portfolio" in data:
                report["portfolio_holdings"] = data["portfolio"]["holdings"]

            return ToolResult(success=True, data=report)

        except Exception as e:
            return ToolResult(
                success=False,
                error=f"生成风险报告失败: {str(e)}"
            )

    # ========== 辅助方法 ==========

    def _parse_portfolio(self, portfolio: str) -> Dict[str, float]:
        """
        解析投资组合描述

        Args:
            portfolio: "代码1:权重1,代码2:权重2,..."

        Returns:
            {代码: 权重} 字典
        """
        holdings = {}
        try:
            for item in portfolio.split(","):
                item = item.strip()
                if ":" in item:
                    symbol, weight = item.split(":")
                    symbol = symbol.strip()
                    weight = float(weight.strip())
                    if 0 < weight <= 1:
                        holdings[symbol] = weight
            return holdings
        except Exception:
            return {}

    async def _get_historical_prices(
        self, symbol: str, days: int
    ) -> Dict[str, Any]:
        """
        获取历史价格数据

        Args:
            symbol: 股票代码
            days: 天数

        Returns:
            包含价格、收益率等数据的字典
        """
        try:
            # 标准化代码
            ts_code = self.tushare_client._normalize_stock_code(symbol)

            if not self.tushare_client.api:
                return {
                    "success": False,
                    "error": "Tushare API 未初始化"
                }

            # 计算日期范围(考虑非交易日,取更大范围)
            end_date = datetime.now()
            start_date = end_date - timedelta(days=int(days * 1.5))

            # 获取日线数据
            df = self.tushare_client.api.daily(
                ts_code=ts_code,
                start_date=start_date.strftime('%Y%m%d'),
                end_date=end_date.strftime('%Y%m%d')
            )

            if df is None or df.empty:
                return {
                    "success": False,
                    "error": f"未找到{symbol}的历史数据"
                }

            # 按日期升序排序
            df = df.sort_values('trade_date')

            # 取最近的days天数据
            df = df.tail(days)

            if len(df) < 30:  # 至少需要30个交易日
                return {
                    "success": False,
                    "error": f"历史数据不足(仅{len(df)}天)"
                }

            # 提取收盘价
            prices = df['close'].values.tolist()

            # 计算日收益率
            returns = []
            for i in range(1, len(prices)):
                ret = (prices[i] - prices[i-1]) / prices[i-1]
                returns.append(ret)

            # 获取股票名称
            stock_basic = self.tushare_client.api.stock_basic(
                ts_code=ts_code,
                fields='ts_code,name'
            )
            stock_name = "未知"
            if stock_basic is not None and not stock_basic.empty:
                stock_name = stock_basic.iloc[0]['name']

            return {
                "success": True,
                "prices": prices,
                "returns": returns,
                "dates": df['trade_date'].values.tolist(),
                "name": stock_name
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def _align_returns(
        self, returns_data: Dict[str, List[float]]
    ) -> Dict[str, np.ndarray]:
        """
        对齐多个资产的收益率数据(使用相同长度)

        Args:
            returns_data: {代码: [收益率列表]}

        Returns:
            {代码: 对齐后的收益率数组}
        """
        if not returns_data:
            return {}

        # 找到最短的序列长度
        min_length = min(len(returns) for returns in returns_data.values())

        if min_length < 30:  # 至少需要30个数据点
            return {}

        # 截取所有序列为相同长度(取最新的数据)
        aligned = {}
        for symbol, returns in returns_data.items():
            aligned[symbol] = np.array(returns[-min_length:])

        return aligned

    def _calculate_portfolio_returns(
        self,
        aligned_returns: Dict[str, np.ndarray],
        holdings: Dict[str, float]
    ) -> np.ndarray:
        """
        计算投资组合收益率

        Args:
            aligned_returns: 对齐后的收益率数据
            holdings: 持仓权重

        Returns:
            投资组合收益率数组
        """
        portfolio_returns = None

        for symbol, weight in holdings.items():
            returns = aligned_returns[symbol]
            weighted_returns = returns * weight

            if portfolio_returns is None:
                portfolio_returns = weighted_returns
            else:
                portfolio_returns += weighted_returns

        return portfolio_returns

    def _calculate_portfolio_metrics(
        self,
        portfolio_returns: np.ndarray,
        aligned_returns: Dict[str, np.ndarray],
        holdings: Dict[str, float]
    ) -> Dict[str, Any]:
        """
        计算投资组合风险指标

        Args:
            portfolio_returns: 投资组合收益率
            aligned_returns: 各资产收益率
            holdings: 持仓权重

        Returns:
            风险指标字典
        """
        # 构造价格序列(用于计算最大回撤)
        cumulative_returns = np.cumprod(1 + portfolio_returns)
        prices = cumulative_returns * 100  # 假设初始价格为100

        metrics = {
            "expected_return": self._calculate_annualized_return(portfolio_returns),
            "volatility": self._calculate_volatility(portfolio_returns),
            "sharpe_ratio": self._calculate_sharpe_ratio(portfolio_returns),
            "max_drawdown": self._calculate_max_drawdown(prices),
            "var_95": self._calculate_var(portfolio_returns, 0.95),
            "cvar_95": self._calculate_cvar(portfolio_returns, 0.95),
            "downside_deviation": self._calculate_downside_deviation(portfolio_returns)
        }

        # 计算各资产的贡献度
        contributions = {}
        for symbol, weight in holdings.items():
            asset_return = self._calculate_annualized_return(aligned_returns[symbol])
            contributions[symbol] = {
                "weight": f"{weight * 100:.2f}%",
                "return": f"{asset_return * 100:.2f}%",
                "contribution": f"{asset_return * weight * 100:.2f}%"
            }

        metrics["asset_contributions"] = contributions

        return metrics

    def _calculate_annualized_return(self, returns: np.ndarray) -> float:
        """计算年化收益率"""
        if len(returns) == 0:
            return 0.0

        total_return = np.prod(1 + np.array(returns)) - 1
        days = len(returns)
        annualized = (1 + total_return) ** (252 / days) - 1
        return float(annualized)

    def _calculate_volatility(self, returns: np.ndarray) -> float:
        """计算年化波动率"""
        if len(returns) < 2:
            return 0.0

        daily_vol = np.std(returns, ddof=1)
        annualized_vol = daily_vol * np.sqrt(252)
        return float(annualized_vol)

    def _calculate_sharpe_ratio(self, returns: np.ndarray) -> float:
        """计算夏普比率"""
        if len(returns) < 2:
            return 0.0

        annual_return = self._calculate_annualized_return(returns)
        annual_vol = self._calculate_volatility(returns)

        if annual_vol == 0:
            return 0.0

        sharpe = (annual_return - self.risk_free_rate) / annual_vol
        return float(sharpe)

    def _calculate_max_drawdown(self, prices: List[float]) -> float:
        """计算最大回撤"""
        if len(prices) < 2:
            return 0.0

        prices = np.array(prices)
        cummax = np.maximum.accumulate(prices)
        drawdowns = (prices - cummax) / cummax
        max_dd = np.min(drawdowns)
        return float(max_dd)

    def _calculate_var(self, returns: np.ndarray, confidence: float = 0.95) -> float:
        """计算VaR (Value at Risk)"""
        if len(returns) < 2:
            return 0.0

        var = np.percentile(returns, (1 - confidence) * 100)
        return float(var)

    def _calculate_cvar(self, returns: np.ndarray, confidence: float = 0.95) -> float:
        """计算CVaR (Conditional Value at Risk)"""
        if len(returns) < 2:
            return 0.0

        var = self._calculate_var(returns, confidence)
        cvar = np.mean(returns[returns <= var])
        return float(cvar) if not np.isnan(cvar) else 0.0

    def _calculate_downside_deviation(self, returns: np.ndarray) -> float:
        """计算下行标准差(年化)"""
        if len(returns) < 2:
            return 0.0

        # 只考虑负收益
        negative_returns = returns[returns < 0]

        if len(negative_returns) == 0:
            return 0.0

        downside_vol = np.std(negative_returns, ddof=1)
        annualized_downside = downside_vol * np.sqrt(252)
        return float(annualized_downside)

    def _assess_risk_level(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """
        评估风险等级

        Args:
            metrics: 风险指标

        Returns:
            风险评级字典
        """
        volatility = metrics.get("volatility", 0)
        sharpe = metrics.get("sharpe_ratio", 0)
        max_dd = abs(metrics.get("max_drawdown", 0))

        # 计算风险分数 (0-100, 越高风险越大)
        vol_score = min(volatility * 100, 40)  # 波动率权重40%
        sharpe_score = max(0, (1 - sharpe) * 20)  # 夏普比率权重20%
        dd_score = min(max_dd * 100, 40)  # 最大回撤权重40%

        risk_score = vol_score + sharpe_score + dd_score

        # 确定风险等级
        if risk_score < 20:
            level = "低风险"
            description = "资产波动较小,适合稳健型投资者"
        elif risk_score < 40:
            level = "中低风险"
            description = "资产波动适中,风险可控"
        elif risk_score < 60:
            level = "中等风险"
            description = "资产存在一定波动,需要风险承受能力"
        elif risk_score < 80:
            level = "中高风险"
            description = "资产波动较大,需谨慎投资"
        else:
            level = "高风险"
            description = "资产波动剧烈,不建议风险承受能力较低的投资者参与"

        return {
            "level": level,
            "score": round(risk_score, 2),
            "description": description
        }

    def _generate_recommendations(
        self, metrics: Dict[str, Any], risk_assessment: Dict[str, Any]
    ) -> List[str]:
        """生成投资建议"""
        recommendations = []

        # 基于风险等级
        risk_level = risk_assessment["level"]
        if risk_level in ["高风险", "中高风险"]:
            recommendations.append("建议控制仓位,不宜重仓投资")
            recommendations.append("建议设置止损点,控制最大损失")

        # 基于夏普比率
        sharpe = metrics.get("sharpe_ratio", 0)
        if sharpe > 1:
            recommendations.append("夏普比率较高,风险调整后收益表现良好")
        elif sharpe < 0:
            recommendations.append("夏普比率为负,收益未能覆盖风险,建议谨慎投资")

        # 基于最大回撤
        max_dd = abs(metrics.get("max_drawdown", 0))
        if max_dd > 0.3:
            recommendations.append(f"最大回撤达{max_dd*100:.1f}%,需要较强的心理承受能力")

        # 基于波动率
        volatility = metrics.get("volatility", 0)
        if volatility > 0.4:
            recommendations.append("波动率较高,适合短期交易,不建议长期持有")
        elif volatility < 0.2:
            recommendations.append("波动率较低,适合长期价值投资")

        # 基于Beta(如果有)
        beta = metrics.get("beta")
        if beta is not None:
            if beta > 1.2:
                recommendations.append(f"Beta值{beta:.2f},对市场波动敏感度高")
            elif beta < 0.8:
                recommendations.append(f"Beta值{beta:.2f},与市场相关性较低,可用于分散风险")

        if not recommendations:
            recommendations.append("建议根据个人风险偏好合理配置")

        return recommendations

    def _generate_risk_warnings(
        self, metrics: Dict[str, Any], risk_assessment: Dict[str, Any]
    ) -> List[str]:
        """生成风险提示"""
        warnings = []

        # 高风险警告
        if risk_assessment["level"] in ["高风险", "中高风险"]:
            warnings.append("⚠️ 高风险资产,投资需谨慎")

        # VaR警告
        var_95 = metrics.get("var_95", 0)
        if var_95 < -0.05:  # 单日可能损失超过5%
            warnings.append(
                f"⚠️ 95%置信度下单日最大损失可能达{abs(var_95)*100:.2f}%"
            )

        # CVaR警告
        cvar_95 = metrics.get("cvar_95", 0)
        if cvar_95 < -0.08:  # 极端情况损失超过8%
            warnings.append(
                f"⚠️ 极端情况下平均损失可能达{abs(cvar_95)*100:.2f}%"
            )

        # 最大回撤警告
        max_dd = abs(metrics.get("max_drawdown", 0))
        if max_dd > 0.5:
            warnings.append(f"⚠️ 历史最大回撤达{max_dd*100:.1f}%,存在大幅亏损风险")

        # 负收益警告
        expected_return = metrics.get("expected_return", 0)
        if expected_return < 0:
            warnings.append(
                f"⚠️ 预期收益率为负({expected_return*100:.2f}%),不建议投资"
            )

        # 通用风险提示
        warnings.append("📌 历史数据不代表未来表现,投资有风险,入市需谨慎")

        return warnings

    def get_cache_info(self) -> Dict[str, Any]:
        """获取缓存信息"""
        return self.tushare_client.get_cache_info()

    def clear_cache(self):
        """清空缓存"""
        self.tushare_client.clear_cache()

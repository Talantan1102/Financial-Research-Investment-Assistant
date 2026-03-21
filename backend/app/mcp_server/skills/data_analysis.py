# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""DataAnalysis Skill - 数据分析可视化工具

提供数据分析与可视化功能。
"""

from typing import Dict, Any, Optional, List
from app.mcp_server.skills.base import BaseSkill, ToolParameter, ToolResult
import statistics


class DataAnalysisSkill(BaseSkill):
    """
    数据分析 Skill

    提供纯数据分析与可视化，支持统计分析、趋势分析、图表生成。
    注：本 Skill 不直接调用 Tushare，只处理传入的数据数组。
    """

    name = "data_analysis"
    description = "纯数据分析与可视化，支持统计分析、趋势预测、图表生成（需传入数据数组）"

    def __init__(self):
        super().__init__()

    def _register_tools(self):
        """注册 DataAnalysis 相关工具"""

        # 1. 计算统计指标
        self.register_tool(
            name="calculate_statistics",
            handler=self.calculate_statistics,
            description="计算数据的统计指标（均值、标准差、最大值、最小值等）",
            parameters=[
                ToolParameter(
                    name="data",
                    type="array",
                    description="数值数组",
                    required=True
                ),
                ToolParameter(
                    name="metrics",
                    type="array",
                    description="需要计算的指标：mean(均值), std(标准差), min(最小值), max(最大值), median(中位数)",
                    required=False,
                    default=None
                )
            ]
        )

        # 2. 价格趋势分析（纯数据分析）
        self.register_tool(
            name="analyze_price_trend",
            handler=self.analyze_price_trend,
            description="分析价格数据趋势，传入价格数组进行分析",
            parameters=[
                ToolParameter(
                    name="data",
                    type="array",
                    description="价格数据数组，每个元素包含close(收盘价)、date(日期)等字段",
                    required=True
                ),
                ToolParameter(
                    name="price_field",
                    type="string",
                    description="价格字段名，默认为'close'",
                    required=False,
                    default="close"
                )
            ]
        )

        # 3. 相关性分析（纯数据分析）
        self.register_tool(
            name="calculate_correlation",
            handler=self.calculate_correlation,
            description="计算两组数据的相关性",
            parameters=[
                ToolParameter(
                    name="data1",
                    type="array",
                    description="第一组数值数组",
                    required=True
                ),
                ToolParameter(
                    name="data2",
                    type="array",
                    description="第二组数值数组",
                    required=True
                )
            ]
        )

        # 4. 技术指标计算（纯数据分析）
        self.register_tool(
            name="calculate_technical_indicators",
            handler=self.calculate_technical_indicators,
            description="计算技术指标（MA、RSI、MACD等），传入价格数据数组",
            parameters=[
                ToolParameter(
                    name="data",
                    type="array",
                    description="价格数据数组，每个元素需包含close(收盘价)、high(最高价)、low(最低价)等字段",
                    required=True
                ),
                ToolParameter(
                    name="indicators",
                    type="array",
                    description="指标列表：ma(移动平均线), rsi(相对强弱指标), macd, boll(布林带)",
                    required=False,
                    default=None
                )
            ]
        )

        # 5. 数据标准化
        self.register_tool(
            name="normalize_data",
            handler=self.normalize_data,
            description="对数据进行标准化处理（Min-Max或Z-Score）",
            parameters=[
                ToolParameter(
                    name="data",
                    type="array",
                    description="数值数组",
                    required=True
                ),
                ToolParameter(
                    name="method",
                    type="string",
                    description="标准化方法：minmax(最小-最大), zscore(Z-Score)",
                    required=False,
                    default="minmax"
                )
            ]
        )

        # 6. 生成图表数据（纯数据分析）
        self.register_tool(
            name="generate_chart_data",
            handler=self.generate_chart_data,
            description="生成图表数据（K线、折线图、柱状图等），传入数据数组进行转换",
            parameters=[
                ToolParameter(
                    name="data",
                    type="array",
                    description="数据数组，每个元素包含日期、价格等字段",
                    required=True
                ),
                ToolParameter(
                    name="chart_type",
                    type="string",
                    description="图表类型：candlestick(K线), line(折线), bar(柱状), area(面积)",
                    required=False,
                    default="line"
                ),
                ToolParameter(
                    name="date_field",
                    type="string",
                    description="日期字段名，默认为'trade_date'或'date'",
                    required=False,
                    default="trade_date"
                ),
                ToolParameter(
                    name="value_field",
                    type="string",
                    description="数值字段名，默认为'close'",
                    required=False,
                    default="close"
                )
            ]
        )

    async def calculate_statistics(self, data: List[float], metrics: List[str] = None) -> ToolResult:
        """计算统计指标"""
        if not data:
            return ToolResult(success=False, error="数据不能为空")

        metrics = metrics or ["mean", "std", "min", "max", "median"]

        try:
            result = {}

            if "mean" in metrics:
                result["mean"] = statistics.mean(data)
            if "std" in metrics:
                result["std"] = statistics.stdev(data) if len(data) > 1 else 0
            if "min" in metrics:
                result["min"] = min(data)
            if "max" in metrics:
                result["max"] = max(data)
            if "median" in metrics:
                result["median"] = statistics.median(data)
            if "variance" in metrics:
                result["variance"] = statistics.variance(data) if len(data) > 1 else 0

            result["count"] = len(data)

            return ToolResult(success=True, data=result)

        except Exception as e:
            return ToolResult(success=False, error=f"计算统计指标失败: {str(e)}")

    async def analyze_price_trend(self, data: List[Dict[str, Any]], price_field: str = "close") -> ToolResult:
        """
        分析价格趋势（纯数据分析）
        
        Args:
            data: 价格数据数组，每个元素包含价格字段
            price_field: 价格字段名，默认为'close'
        """
        if not data:
            return ToolResult(success=False, error="数据不能为空")

        try:
            # 提取收盘价
            closes = [d.get(price_field) for d in data if d.get(price_field) is not None]
            
            if len(closes) < 5:
                return ToolResult(success=False, error="价格数据不足，至少需要5条数据")

            # 计算趋势
            if len(closes) < 2:
                return ToolResult(success=False, error="数据不足")

            # 简单线性回归计算趋势
            trend = self._calculate_trend(closes)

            # 计算波动率
            returns = []
            for i in range(len(closes) - 1):
                if closes[i+1] > 0:
                    returns.append((closes[i] - closes[i+1]) / closes[i+1])

            volatility = statistics.stdev(returns) * (252 ** 0.5) if len(returns) > 1 else 0

            # 提取日期字段用于返回
            dates = [d.get("trade_date") or d.get("date") for d in data if d.get("trade_date") or d.get("date")]
            
            analysis = {
                "data_points": len(closes),
                "date_range": {"from": dates[-1] if dates else None, "to": dates[0] if dates else None},
                "current_price": closes[0],
                "period_high": max(closes),
                "period_low": min(closes),
                "price_change": closes[0] - closes[-1],
                "price_change_percent": (closes[0] - closes[-1]) / closes[-1] * 100 if closes[-1] else 0,
                "trend_direction": trend["direction"],
                "trend_strength": trend["strength"],
                "volatility": round(volatility * 100, 2)
            }

            return ToolResult(success=True, data=analysis)

        except Exception as e:
            return ToolResult(success=False, error=f"分析价格趋势失败: {str(e)}")

    def _calculate_trend(self, prices: List[float]) -> Dict[str, Any]:
        """计算趋势方向和强度"""
        n = len(prices)
        if n < 2:
            return {"direction": "unknown", "strength": 0}

        # 简单线性回归
        x = list(range(n))
        mean_x = sum(x) / n
        mean_y = sum(prices) / n

        numerator = sum((x[i] - mean_x) * (prices[i] - mean_y) for i in range(n))
        denominator = sum((x[i] - mean_x) ** 2 for i in range(n))

        slope = numerator / denominator if denominator else 0

        # 确定趋势方向
        if slope > prices[-1] * 0.001:
            direction = "up"
        elif slope < -prices[-1] * 0.001:
            direction = "down"
        else:
            direction = "sideways"

        # 计算趋势强度 (R²近似)
        ss_res = sum((prices[i] - (mean_y + slope * (x[i] - mean_x))) ** 2 for i in range(n))
        ss_tot = sum((prices[i] - mean_y) ** 2 for i in range(n))
        r_squared = 1 - (ss_res / ss_tot) if ss_tot else 0

        return {
            "direction": direction,
            "strength": round(abs(r_squared) * 100, 2)
        }

    async def calculate_correlation(self, data1: List[float], data2: List[float]) -> ToolResult:
        """
        计算相关性（纯数据分析）
        
        Args:
            data1: 第一组数值数组
            data2: 第二组数值数组
        """
        if not data1 or not data2:
            return ToolResult(success=False, error="两组数据都不能为空")

        try:
            # 确保长度一致
            min_len = min(len(data1), len(data2))
            if min_len < 5:
                return ToolResult(success=False, error="数据不足，每组至少需要5个数据点")
            
            arr1 = data1[:min_len]
            arr2 = data2[:min_len]

            # 计算相关系数
            correlation = self._pearson_correlation(arr1, arr2)

            return ToolResult(success=True, data={
                "data_points": min_len,
                "correlation": round(correlation, 4),
                "interpretation": self._interpret_correlation(correlation)
            })

        except Exception as e:
            return ToolResult(success=False, error=f"计算相关性失败: {str(e)}")

    def _calculate_returns(self, prices: List[float]) -> List[float]:
        """计算收益率序列"""
        returns = []
        for i in range(len(prices) - 1):
            if prices[i+1] > 0:
                returns.append((prices[i] - prices[i+1]) / prices[i+1])
        return returns

    def _pearson_correlation(self, x: List[float], y: List[float]) -> float:
        """计算皮尔逊相关系数"""
        n = len(x)
        if n != len(y) or n == 0:
            return 0

        mean_x = sum(x) / n
        mean_y = sum(y) / n

        numerator = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
        denom_x = sum((x[i] - mean_x) ** 2 for i in range(n)) ** 0.5
        denom_y = sum((y[i] - mean_y) ** 2 for i in range(n)) ** 0.5

        if denom_x == 0 or denom_y == 0:
            return 0

        return numerator / (denom_x * denom_y)

    def _interpret_correlation(self, corr: float) -> str:
        """解释相关系数"""
        abs_corr = abs(corr)
        if abs_corr >= 0.8:
            return "强相关" if corr > 0 else "强负相关"
        elif abs_corr >= 0.5:
            return "中等相关" if corr > 0 else "中等负相关"
        elif abs_corr >= 0.3:
            return "弱相关" if corr > 0 else "弱负相关"
        else:
            return "几乎无关"

    async def calculate_technical_indicators(self, data: List[Dict[str, Any]], indicators: List[str] = None) -> ToolResult:
        """
        计算技术指标（纯数据分析）
        
        Args:
            data: 价格数据数组，需包含close/high/low等字段
            indicators: 要计算的指标列表
        """
        if not data:
            return ToolResult(success=False, error="数据不能为空")

        indicators = indicators or ["ma", "rsi"]

        try:
            if len(data) < 30:
                return ToolResult(success=False, error="历史数据不足，至少需要30条数据")

            closes = [d.get("close") for d in data if d.get("close") is not None]
            highs = [d.get("high") for d in data if d.get("high") is not None]
            lows = [d.get("low") for d in data if d.get("low") is not None]

            if len(closes) < 30:
                return ToolResult(success=False, error="有效收盘价数据不足")

            result_data = {}

            if "ma" in indicators:
                result_data["ma"] = {
                    "ma5": sum(closes[:5]) / 5,
                    "ma10": sum(closes[:10]) / 10,
                    "ma20": sum(closes[:20]) / 20,
                    "ma60": sum(closes[:60]) / 60 if len(closes) >= 60 else None
                }

            if "rsi" in indicators:
                result_data["rsi"] = self._calculate_rsi(closes, 14)

            if "macd" in indicators:
                result_data["macd"] = self._calculate_macd(closes)

            if "boll" in indicators:
                result_data["boll"] = self._calculate_bollinger(closes)

            return ToolResult(success=True, data=result_data)

        except Exception as e:
            return ToolResult(success=False, error=f"计算技术指标失败: {str(e)}")

    def _calculate_rsi(self, prices: List[float], period: int = 14) -> Dict[str, float]:
        """计算RSI"""
        if len(prices) < period + 1:
            return {"rsi": 50}

        gains = []
        losses = []

        for i in range(1, period + 1):
            change = prices[i-1] - prices[i]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))

        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period

        if avg_loss == 0:
            return {"rsi": 100}

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        return {"rsi": round(rsi, 2)}

    def _calculate_macd(self, prices: List[float]) -> Dict[str, Any]:
        """计算MACD"""
        # 简化计算，使用EMA近似
        ema12 = self._calculate_ema(prices, 12)
        ema26 = self._calculate_ema(prices, 26)

        if ema12 is None or ema26 is None:
            return {"macd": 0, "signal": 0, "histogram": 0}

        macd_line = ema12 - ema26
        signal_line = self._calculate_ema([macd_line] + prices[:-1], 9) or macd_line

        return {
            "macd": round(macd_line, 4),
            "signal": round(signal_line, 4),
            "histogram": round(macd_line - signal_line, 4)
        }

    def _calculate_ema(self, prices: List[float], period: int) -> Optional[float]:
        """计算EMA"""
        if len(prices) < period:
            return None

        multiplier = 2 / (period + 1)
        ema = sum(prices[:period]) / period

        for price in prices[period:]:
            ema = (price - ema) * multiplier + ema

        return ema

    def _calculate_bollinger(self, prices: List[float], period: int = 20) -> Dict[str, float]:
        """计算布林带"""
        if len(prices) < period:
            return {"upper": None, "middle": None, "lower": None}

        recent = prices[:period]
        middle = sum(recent) / period
        std = statistics.stdev(recent)

        return {
            "upper": round(middle + 2 * std, 2),
            "middle": round(middle, 2),
            "lower": round(middle - 2 * std, 2)
        }

    async def normalize_data(self, data: List[float], method: str = "minmax") -> ToolResult:
        """数据标准化"""
        if not data:
            return ToolResult(success=False, error="数据不能为空")

        try:
            if method == "minmax":
                min_val = min(data)
                max_val = max(data)
                range_val = max_val - min_val

                if range_val == 0:
                    normalized = [0.5] * len(data)
                else:
                    normalized = [(x - min_val) / range_val for x in data]

                result = {
                    "method": "minmax",
                    "original_range": {"min": min_val, "max": max_val},
                    "normalized": normalized
                }

            elif method == "zscore":
                mean = statistics.mean(data)
                std = statistics.stdev(data) if len(data) > 1 else 1

                if std == 0:
                    normalized = [0] * len(data)
                else:
                    normalized = [(x - mean) / std for x in data]

                result = {
                    "method": "zscore",
                    "original_stats": {"mean": mean, "std": std},
                    "normalized": normalized
                }
            else:
                return ToolResult(success=False, error=f"不支持的标准化方法: {method}")

            return ToolResult(success=True, data=result)

        except Exception as e:
            return ToolResult(success=False, error=f"数据标准化失败: {str(e)}")

    async def generate_chart_data(self, data: List[Dict[str, Any]], chart_type: str = "line",
                                   date_field: str = "trade_date", value_field: str = "close") -> ToolResult:
        """
        生成图表数据（纯数据分析）
        
        Args:
            data: 数据数组
            chart_type: 图表类型
            date_field: 日期字段名
            value_field: 数值字段名
        """
        if not data:
            return ToolResult(success=False, error="数据不能为空")

        try:
            if chart_type == "candlestick":
                chart_data = [
                    {
                        "date": d.get(date_field) or d.get("date"),
                        "open": d.get("open"),
                        "high": d.get("high"),
                        "low": d.get("low"),
                        "close": d.get("close"),
                        "volume": d.get("vol") or d.get("volume")
                    }
                    for d in data
                ]
            elif chart_type == "line":
                chart_data = [
                    {"date": d.get(date_field) or d.get("date"), "value": d.get(value_field)}
                    for d in data
                ]
            elif chart_type == "bar":
                chart_data = [
                    {"date": d.get(date_field) or d.get("date"), "value": d.get("vol") or d.get("volume")}
                    for d in data
                ]
            elif chart_type == "area":
                chart_data = [
                    {"date": d.get(date_field) or d.get("date"), "value": d.get(value_field), 
                     "volume": d.get("vol") or d.get("volume")}
                    for d in data
                ]
            else:
                return ToolResult(success=False, error=f"不支持的图表类型: {chart_type}")

            return ToolResult(success=True, data={
                "chart_type": chart_type,
                "data_points": len(chart_data),
                "data": chart_data
            })

        except Exception as e:
            return ToolResult(success=False, error=f"生成图表数据失败: {str(e)}")

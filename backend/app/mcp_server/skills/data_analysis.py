# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""DataAnalysis Skill - 数据分析与可视化 (MCP 专用版)

纯 MCP 工具实现，通过 MCP Client 调用，无降级逻辑。
"""

import os
import re
import json
import logging
from typing import Dict, Any, List, Optional
from collections import Counter

from app.mcp_server.skills.base import BaseSkill, ToolParameter, ToolResult
from app.service.smart_analyzer import SmartDataAnalyzer
from app.service.chart_generator import ChartGenerator
from app.config.llm_config import get_config
from app.service.text2sql_service import Text2SQLService


logger = logging.getLogger("DataAnalysisSkill")


class DataAnalysisSkill(BaseSkill):
    """
    数据分析 Skill (MCP 专用版)

    提供以下工具：
    1. analyze_data - 智能数据分析
    2. generate_chart - 图表生成
    3. text_to_sql - 自然语言转 SQL
    4. calculate_metrics - 计算金融指标
    """

    name = "data_analysis"
    description = "数据分析与可视化，支持智能分析、图表生成和 Text2SQL"

    def __init__(self):
        # 直接初始化服务
        self.chart_generator = ChartGenerator()
        self.smart_analyzer = SmartDataAnalyzer()

        config = get_config()
        self.text2sql_service = Text2SQLService(
            llm_api_key=config.api_key,
            llm_base_url=config.base_url
        )
        super().__init__()

    def _register_tools(self):
        """注册 DataAnalysis 相关工具"""

        # 1. 智能数据分析
        self.register_tool(
            name="analyze_data",
            handler=self.analyze_data,
            description="智能数据分析，识别模式、趋势、异常，自动推荐可视化方式",
            parameters=[
                ToolParameter(
                    name="data",
                    type="array",
                    description="待分析的数据列表，每个元素是一个字典",
                    required=True
                ),
                ToolParameter(
                    name="analysis_type",
                    type="string",
                    description="分析类型：auto(自动), trend(趋势), distribution(分布), comparison(对比), correlation(相关性)",
                    required=False,
                    default="auto"
                ),
                ToolParameter(
                    name="context",
                    type="string",
                    description="分析上下文/问题，帮助理解数据背景",
                    required=False,
                    default=""
                )
            ]
        )

        # 2. 图表生成
        self.register_tool(
            name="generate_chart",
            handler=self.generate_chart,
            description="生成 ECharts 兼容的图表配置，支持折线图、柱状图、饼图、散点图等",
            parameters=[
                ToolParameter(
                    name="data",
                    type="object",
                    description="图表数据，格式取决于图表类型",
                    required=True
                ),
                ToolParameter(
                    name="chart_type",
                    type="string",
                    description="图表类型：line(折线), bar(柱状), pie(饼图), scatter(散点), radar(雷达), heatmap(热力)",
                    required=False,
                    default="bar"
                ),
                ToolParameter(
                    name="title",
                    type="string",
                    description="图表标题",
                    required=False,
                    default="数据图表"
                ),
                ToolParameter(
                    name="options",
                    type="object",
                    description="额外配置选项，如颜色、图例位置等",
                    required=False,
                    default=None
                )
            ]
        )

        # 3. Text2SQL
        self.register_tool(
            name="text_to_sql",
            handler=self.text_to_sql,
            description="将自然语言问题转换为 SQL 查询，支持金融数据库查询",
            parameters=[
                ToolParameter(
                    name="question",
                    type="string",
                    description="自然语言问题，例如：'查询2024年贵州茅台的营收'",
                    required=True
                ),
                ToolParameter(
                    name="intent",
                    type="string",
                    description="查询意图：stats(统计), trend(趋势), comparison(对比), detail(详情)",
                    required=False,
                    default="stats"
                ),
                ToolParameter(
                    name="table_hints",
                    type="array",
                    description="表名提示，帮助定位相关数据表",
                    required=False,
                    default=None
                )
            ]
        )

        # 4. 计算金融指标
        self.register_tool(
            name="calculate_metrics",
            handler=self.calculate_metrics,
            description="计算金融指标，如 CAGR、同比、环比、波动率等",
            parameters=[
                ToolParameter(
                    name="data",
                    type="array",
                    description="时间序列数据，每个元素包含时间和数值",
                    required=True
                ),
                ToolParameter(
                    name="metrics",
                    type="array",
                    description="要计算的指标列表：cagr(复合增长), yoy(同比), mom(环比), volatility(波动率), ma(移动平均)",
                    required=True
                ),
                ToolParameter(
                    name="value_field",
                    type="string",
                    description="数值字段名",
                    required=False,
                    default="value"
                ),
                ToolParameter(
                    name="time_field",
                    type="string",
                    description="时间字段名",
                    required=False,
                    default="time"
                )
            ]
        )

    # ========== 工具实现 ==========

    async def analyze_data(
        self,
        data: List[Dict],
        analysis_type: str = "auto",
        context: str = ""
    ) -> ToolResult:
        """智能数据分析"""
        if not data or not isinstance(data, list):
            return ToolResult(success=False, error="数据不能为空且必须是列表")

        import asyncio
        result = await asyncio.to_thread(
            self.smart_analyzer.analyze,
            data,
            analysis_type
        )
        return ToolResult(success=True, data=result)

    async def generate_chart(
        self,
        data: Dict,
        chart_type: str = "bar",
        title: str = "数据图表",
        options: Optional[Dict] = None
    ) -> ToolResult:
        """生成图表配置"""
        import asyncio
        config = await asyncio.to_thread(
            self.chart_generator.generate,
            data,
            chart_type,
            title
        )
        return ToolResult(success=True, data=config)

    async def text_to_sql(
        self,
        question: str,
        intent: str = "stats",
        table_hints: Optional[List[str]] = None
    ) -> ToolResult:
        """自然语言转 SQL"""
        if not question:
            return ToolResult(success=False, error="问题不能为空")

        import asyncio
        result = await self.text2sql_service.query(question, intent)
        return ToolResult(success=True, data=result)

    async def calculate_metrics(
        self,
        data: List[Dict],
        metrics: List[str],
        value_field: str = "value",
        time_field: str = "time"
    ) -> ToolResult:
        """计算金融指标"""
        if not data or not isinstance(data, list):
            return ToolResult(success=False, error="数据不能为空且必须是列表")

        if not metrics:
            return ToolResult(success=False, error="指标列表不能为空")

        # 按时间排序
        sorted_data = sorted(data, key=lambda x: x.get(time_field, ""))
        values = [float(item.get(value_field, 0)) for item in sorted_data if value_field in item]

        if len(values) < 2:
            return ToolResult(success=False, error="数据点不足，至少需要2个数据点")

        results = {}

        for metric in metrics:
            if metric == "cagr":
                if len(values) >= 2:
                    beginning_value = values[0]
                    ending_value = values[-1]
                    n_years = len(values) - 1
                    if beginning_value > 0:
                        cagr = (ending_value / beginning_value) ** (1 / n_years) - 1
                        results["cagr"] = round(cagr * 100, 2)

            elif metric == "yoy":
                yoy_values = []
                for i in range(len(values)):
                    if i >= len(values) // 2:
                        prev_value = values[i - len(values) // 2]
                        if prev_value > 0:
                            yoy = (values[i] - prev_value) / prev_value * 100
                            yoy_values.append(round(yoy, 2))
                results["yoy"] = yoy_values if yoy_values else None

            elif metric == "mom":
                mom_values = []
                for i in range(1, len(values)):
                    if values[i-1] > 0:
                        mom = (values[i] - values[i-1]) / values[i-1] * 100
                        mom_values.append(round(mom, 2))
                results["mom"] = mom_values if mom_values else None

            elif metric == "volatility":
                import statistics
                if len(values) >= 2:
                    mean = statistics.mean(values)
                    std = statistics.stdev(values)
                    if mean > 0:
                        volatility = std / mean * 100
                        results["volatility"] = round(volatility, 2)

            elif metric == "ma":
                ma_periods = [3, 5, 10]
                ma_results = {}
                for period in ma_periods:
                    if len(values) >= period:
                        ma = sum(values[-period:]) / period
                        ma_results[f"MA{period}"] = round(ma, 2)
                results["moving_average"] = ma_results

        return ToolResult(success=True, data={
            "metrics": results,
            "data_points": len(values),
            "calculated_metrics": list(results.keys())
        })

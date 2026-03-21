# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""SectorAnalysis Skill - 行业板块分析工具

提供行业与概念板块分析功能。
"""

from typing import Dict, Any, Optional, List
from app.mcp_server.skills.base import BaseSkill, ToolParameter, ToolResult
from app.data.tushare_client import get_tushare_client, TushareClient


class SectorAnalysisSkill(BaseSkill):
    """
    行业板块分析 Skill

    提供行业与概念板块分析，支持行业对比、龙头识别、估值对比。
    """

    name = "sector_analysis"
    description = "行业与概念板块分析，支持行业对比、龙头识别、估值对比"

    def __init__(self):
        self._tushare_client: Optional[TushareClient] = None
        super().__init__()

    def get_tushare_client(self) -> TushareClient:
        """获取 TushareClient 实例（延迟初始化）"""
        if self._tushare_client is None:
            self._tushare_client = get_tushare_client()
        return self._tushare_client

    def _register_tools(self):
        """注册 SectorAnalysis 相关工具"""

        # 1. 获取行业列表
        self.register_tool(
            name="get_industry_list",
            handler=self.get_industry_list,
            description="获取所有行业分类列表",
            parameters=[]
        )

        # 2. 获取行业表现
        self.register_tool(
            name="get_industry_performance",
            handler=self.get_industry_performance,
            description="获取各行业涨跌幅排名",
            parameters=[
                ToolParameter(
                    name="period",
                    type="string",
                    description="周期：1d(日), 5d(周), 20d(月)",
                    required=False,
                    default="1d"
                )
            ]
        )

        # 3. 获取行业龙头股
        self.register_tool(
            name="get_industry_leaders",
            handler=self.get_industry_leaders,
            description="获取指定行业的龙头股",
            parameters=[
                ToolParameter(
                    name="industry",
                    type="string",
                    description="行业名称，如'白酒'、'银行'",
                    required=True
                ),
                ToolParameter(
                    name="by",
                    type="string",
                    description="排序依据：market_cap(市值), revenue(营收), profit(利润)",
                    required=False,
                    default="market_cap"
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="返回数量",
                    required=False,
                    default=10
                )
            ]
        )

        # 4. 对比行业财务指标
        self.register_tool(
            name="compare_industry_metrics",
            handler=self.compare_industry_metrics,
            description="对比不同行业的财务指标",
            parameters=[
                ToolParameter(
                    name="industries",
                    type="array",
                    description="行业列表，如['白酒', '银行', '医药']",
                    required=False,
                    default=None
                ),
                ToolParameter(
                    name="metric",
                    type="string",
                    description="对比指标：roe, gross_margin, net_margin, debt_ratio",
                    required=False,
                    default="roe"
                )
            ]
        )

        # 5. 对比行业估值
        self.register_tool(
            name="compare_industry_valuation",
            handler=self.compare_industry_valuation,
            description="对比不同行业的估值水平(PE、PB、PS)",
            parameters=[
                ToolParameter(
                    name="industries",
                    type="array",
                    description="行业列表",
                    required=False,
                    default=None
                )
            ]
        )

        # 6. 获取概念列表
        self.register_tool(
            name="get_concept_list",
            handler=self.get_concept_list,
            description="获取所有概念分类列表",
            parameters=[]
        )

        # 7. 获取概念成分股
        self.register_tool(
            name="get_concept_stocks",
            handler=self.get_concept_stocks,
            description="获取指定概念的成分股",
            parameters=[
                ToolParameter(
                    name="concept_code",
                    type="string",
                    description="概念代码",
                    required=False,
                    default=None
                ),
                ToolParameter(
                    name="concept_name",
                    type="string",
                    description="概念名称，如'AI芯片'、'新能源汽车'",
                    required=False,
                    default=None
                )
            ]
        )

    async def get_industry_list(self) -> ToolResult:
        """获取行业列表"""
        try:
            result = self.get_tushare_client().get_industry_list()

            if not result.get("success"):
                return ToolResult(success=False, error=result.get("error"))

            return ToolResult(success=True, data=result.get("data"), meta=result.get("meta"))

        except Exception as e:
            return ToolResult(success=False, error=f"获取行业列表失败: {str(e)}")

    async def get_industry_performance(self, period: str = "1d") -> ToolResult:
        """获取行业表现"""
        try:
            result = self.get_tushare_client().get_industry_performance(period)

            if not result.get("success"):
                return ToolResult(success=False, error=result.get("error"))

            return ToolResult(success=True, data=result.get("data"), meta=result.get("meta"))

        except Exception as e:
            return ToolResult(success=False, error=f"获取行业表现失败: {str(e)}")

    async def get_industry_leaders(self, industry: str, by: str = "market_cap", limit: int = 10) -> ToolResult:
        """获取行业龙头股"""
        if not industry:
            return ToolResult(success=False, error="行业名称不能为空")

        try:
            result = self.get_tushare_client().get_industry_leaders(industry, by)

            if not result.get("success"):
                return ToolResult(success=False, error=result.get("error"))

            data = result.get("data", [])[:limit]

            return ToolResult(success=True, data=data, meta={"industry": industry, "sort_by": by, "count": len(data)})

        except Exception as e:
            return ToolResult(success=False, error=f"获取行业龙头股失败: {str(e)}")

    async def compare_industry_metrics(self, industries: List[str] = None, metric: str = "roe") -> ToolResult:
        """对比行业财务指标"""
        try:
            result = self.get_tushare_client().compare_industry_metrics(industries, metric)

            if not result.get("success"):
                return ToolResult(success=False, error=result.get("error"))

            return ToolResult(success=True, data=result.get("data"), meta=result.get("meta"))

        except Exception as e:
            return ToolResult(success=False, error=f"对比行业指标失败: {str(e)}")

    async def compare_industry_valuation(self, industries: List[str] = None) -> ToolResult:
        """对比行业估值"""
        try:
            result = self.get_tushare_client().compare_industry_valuation(industries)

            if not result.get("success"):
                return ToolResult(success=False, error=result.get("error"))

            return ToolResult(success=True, data=result.get("data"), meta=result.get("meta"))

        except Exception as e:
            return ToolResult(success=False, error=f"对比行业估值失败: {str(e)}")

    async def get_concept_list(self) -> ToolResult:
        """获取概念列表"""
        try:
            result = self.get_tushare_client().get_concept_list()

            if not result.get("success"):
                return ToolResult(success=False, error=result.get("error"))

            return ToolResult(success=True, data=result.get("data"), meta=result.get("meta"))

        except Exception as e:
            return ToolResult(success=False, error=f"获取概念列表失败: {str(e)}")

    async def get_concept_stocks(self, concept_code: str = None, concept_name: str = None) -> ToolResult:
        """获取概念成分股"""
        if not concept_code and not concept_name:
            return ToolResult(success=False, error="请提供概念代码或概念名称")

        try:
            result = self.get_tushare_client().get_concept_stocks(concept_code, concept_name)

            if not result.get("success"):
                return ToolResult(success=False, error=result.get("error"))

            return ToolResult(success=True, data=result.get("data"), meta=result.get("meta"))

        except Exception as e:
            return ToolResult(success=False, error=f"获取概念成分股失败: {str(e)}")

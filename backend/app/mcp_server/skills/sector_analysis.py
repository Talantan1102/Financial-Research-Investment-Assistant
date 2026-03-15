# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""SectorAnalysis Skill - 行业与概念分析工具

提供 A 股行业分类和概念板块分析能力，包括行业列表、概念列表、成分股查询等。
"""

from typing import Dict, Any, Optional, List
from app.mcp_server.skills.base import BaseSkill, ToolParameter, ToolResult
from app.data.tushare_client import get_tushare_client, TushareClient


class SectorAnalysisSkill(BaseSkill):
    """
    行业与概念分析 Skill

    提供 A 股行业分类和概念板块分析功能，基于 Tushare 数据源。
    """

    name = "sector_analysis"
    description = "A股行业与概念板块分析，支持行业分类、概念板块、成分股查询"

    def __init__(self):
        # 延迟初始化：不立即获取 TushareClient 实例
        self._tushare_client: Optional[TushareClient] = None
        super().__init__()

    def get_tushare_client(self) -> TushareClient:
        """
        获取 TushareClient 实例（延迟初始化）

        Returns:
            TushareClient 实例
        """
        if self._tushare_client is None:
            self._tushare_client = get_tushare_client()
        return self._tushare_client

    def _register_tools(self):
        """注册行业与概念分析相关工具"""

        # 1. 获取行业列表
        self.register_tool(
            name="get_industry_list",
            handler=self.get_industry_list,
            description="获取A股行业分类列表，包括各行业包含的股票数量",
            parameters=[]
        )

        # 2. 获取概念列表
        self.register_tool(
            name="get_concept_list",
            handler=self.get_concept_list,
            description="获取A股概念板块列表，包括概念代码和名称",
            parameters=[]
        )

        # 3. 获取概念成分股
        self.register_tool(
            name="get_concept_stocks",
            handler=self.get_concept_stocks,
            description="获取指定概念板块的成分股列表",
            parameters=[
                ToolParameter(
                    name="concept_code",
                    type="string",
                    description="概念代码，如 'TS0' 表示国产芯片概念",
                    required=False,
                    default=None
                ),
                ToolParameter(
                    name="concept_name",
                    type="string",
                    description="概念名称，如 '国产芯片'、'人工智能'等（如果不提供代码，可以通过名称搜索）",
                    required=False,
                    default=None
                )
            ]
        )

        # ==================== 行业深度分析工具 ====================

        # 4. 行业财务指标对比
        self.register_tool(
            name="compare_industry_metrics",
            handler=self.compare_industry_metrics,
            description="对比不同行业的财务指标（ROE、毛利率、净利率、资产负债率等）",
            parameters=[
                ToolParameter(
                    name="industries",
                    type="array",
                    description="要对比的行业列表，如 ['白酒', '银行', '医药']，不传则对比所有行业",
                    required=False,
                    default=None
                ),
                ToolParameter(
                    name="metric",
                    type="string",
                    description="对比指标：roe(净资产收益率)、gross_margin(毛利率)、net_margin(净利率)、debt_ratio(资产负债率)",
                    required=False,
                    default="roe",
                    enum=["roe", "gross_margin", "net_margin", "debt_ratio"]
                )
            ]
        )

        # 5. 行业估值对比
        self.register_tool(
            name="compare_industry_valuation",
            handler=self.compare_industry_valuation,
            description="对比不同行业的估值水平（PE、PB、PS），识别高估/低估行业",
            parameters=[
                ToolParameter(
                    name="industries",
                    type="array",
                    description="要对比的行业列表，不传则对比所有行业",
                    required=False,
                    default=None
                )
            ]
        )

        # 6. 行业涨跌幅排名
        self.register_tool(
            name="get_industry_performance",
            handler=self.get_industry_performance,
            description="获取行业涨跌幅排名，追踪市场热点和冷门行业",
            parameters=[
                ToolParameter(
                    name="period",
                    type="string",
                    description="时间周期：1d(日)、5d(周)、20d(月)",
                    required=False,
                    default="1d",
                    enum=["1d", "5d", "20d"]
                )
            ]
        )

        # 7. 行业龙头股
        self.register_tool(
            name="get_industry_leaders",
            handler=self.get_industry_leaders,
            description="获取指定行业的龙头股（按市值、营收、利润排序）",
            parameters=[
                ToolParameter(
                    name="industry",
                    type="string",
                    description="行业名称，如 '白酒'、'银行'、'半导体'等",
                    required=True
                ),
                ToolParameter(
                    name="by",
                    type="string",
                    description="排序依据：market_cap(市值)、revenue(营收)、profit(净利润)",
                    required=False,
                    default="market_cap",
                    enum=["market_cap", "revenue", "profit"]
                )
            ]
        )

    async def get_industry_list(self) -> ToolResult:
        """
        获取行业分类列表

        Returns:
            ToolResult 包含行业分类数据
        """
        try:
            result = self.get_tushare_client().get_industry_list()

            if result.get("success"):
                return ToolResult(
                    success=True,
                    data=result.get("data"),
                    meta=result.get("meta")
                )
            else:
                return ToolResult(
                    success=False,
                    error=result.get("error", "获取行业列表失败")
                )
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"获取行业列表失败: {str(e)}"
            )

    async def get_concept_list(self) -> ToolResult:
        """
        获取概念板块列表

        Returns:
            ToolResult 包含概念板块数据
        """
        try:
            result = self.get_tushare_client().get_concept_list()

            if result.get("success"):
                return ToolResult(
                    success=True,
                    data=result.get("data"),
                    meta=result.get("meta")
                )
            else:
                return ToolResult(
                    success=False,
                    error=result.get("error", "获取概念列表失败")
                )
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"获取概念列表失败: {str(e)}"
            )

    async def get_concept_stocks(self, concept_code: str = None, concept_name: str = None) -> ToolResult:
        """
        获取概念成分股

        Args:
            concept_code: 概念代码
            concept_name: 概念名称

        Returns:
            ToolResult 包含概念成分股数据
        """
        if not concept_code and not concept_name:
            return ToolResult(
                success=False,
                error="请提供概念代码或概念名称"
            )

        try:
            result = self.get_tushare_client().get_concept_stocks(concept_code, concept_name)

            if result.get("success"):
                return ToolResult(
                    success=True,
                    data=result.get("data"),
                    meta=result.get("meta")
                )
            else:
                return ToolResult(
                    success=False,
                    error=result.get("error", "获取概念成分股失败")
                )
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"获取概念成分股失败: {str(e)}"
            )

    def get_cache_info(self) -> Dict[str, Any]:
        """获取缓存信息"""
        return self.get_tushare_client().get_cache_info()

    def clear_cache(self):
        """清空缓存"""
        self.get_tushare_client().clear_cache()

    # ==================== 行业深度分析方法 ====================

    async def compare_industry_metrics(self, industries: List[str] = None, metric: str = "roe") -> ToolResult:
        """
        对比行业财务指标

        Args:
            industries: 行业列表
            metric: 对比指标

        Returns:
            ToolResult 包含对比结果
        """
        try:
            result = self.get_tushare_client().compare_industry_metrics(industries, metric)

            if result.get("success"):
                return ToolResult(
                    success=True,
                    data=result.get("data"),
                    meta=result.get("meta")
                )
            else:
                return ToolResult(
                    success=False,
                    error=result.get("error", "行业指标对比失败")
                )
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"行业指标对比失败: {str(e)}"
            )

    async def compare_industry_valuation(self, industries: List[str] = None) -> ToolResult:
        """
        对比行业估值

        Args:
            industries: 行业列表

        Returns:
            ToolResult 包含估值对比结果
        """
        try:
            result = self.get_tushare_client().compare_industry_valuation(industries)

            if result.get("success"):
                return ToolResult(
                    success=True,
                    data=result.get("data"),
                    meta=result.get("meta")
                )
            else:
                return ToolResult(
                    success=False,
                    error=result.get("error", "行业估值对比失败")
                )
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"行业估值对比失败: {str(e)}"
            )

    async def get_industry_performance(self, period: str = "1d") -> ToolResult:
        """
        获取行业涨跌幅排名

        Args:
            period: 时间周期

        Returns:
            ToolResult 包含行业涨跌幅
        """
        try:
            result = self.get_tushare_client().get_industry_performance(period)

            if result.get("success"):
                return ToolResult(
                    success=True,
                    data=result.get("data"),
                    meta=result.get("meta")
                )
            else:
                return ToolResult(
                    success=False,
                    error=result.get("error", "获取行业涨跌幅失败")
                )
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"获取行业涨跌幅失败: {str(e)}"
            )

    async def get_industry_leaders(self, industry: str, by: str = "market_cap") -> ToolResult:
        """
        获取行业龙头股

        Args:
            industry: 行业名称
            by: 排序依据

        Returns:
            ToolResult 包含龙头股数据
        """
        if not industry:
            return ToolResult(
                success=False,
                error="行业名称不能为空"
            )

        try:
            result = self.get_tushare_client().get_industry_leaders(industry, by)

            if result.get("success"):
                return ToolResult(
                    success=True,
                    data=result.get("data"),
                    meta=result.get("meta")
                )
            else:
                return ToolResult(
                    success=False,
                    error=result.get("error", "获取行业龙头股失败")
                )
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"获取行业龙头股失败: {str(e)}"
            )

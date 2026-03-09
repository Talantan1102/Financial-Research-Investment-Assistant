# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""MarketData Skill - 市场行情数据工具

基于 stock_service.py 和 tushare_client.py 改造，提供股票行情查询能力。
"""

from typing import Dict, Any, Optional
from app.mcp_server.skills.base import BaseSkill, ToolParameter, ToolResult
from app.data.tushare_client import get_tushare_client, TushareClient


class MarketDataSkill(BaseSkill):
    """
    市场行情数据 Skill

    提供股票行情查询功能，基于 Tushare 数据源。
    """

    name = "market_data"
    description = "股票市场行情数据查询，支持A股实时行情获取"

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
        """注册 MarketData 相关工具"""
        
        # 1. 获取股票行情
        self.register_tool(
            name="get_quote",
            handler=self.get_quote,
            description="获取指定股票的实时行情数据，包括当前价格、涨跌幅、成交量等信息",
            parameters=[
                ToolParameter(
                    name="symbol",
                    type="string",
                    description="股票代码，支持多种格式：'600519'(纯数字)、'sh600519'(带市场前缀)、'600519.SH'(Tushare格式)",
                    required=True
                )
            ]
        )
        
        # 2. 搜索股票
        self.register_tool(
            name="search_stock",
            handler=self.search_stock,
            description="根据股票代码或名称关键词搜索股票信息",
            parameters=[
                ToolParameter(
                    name="keyword",
                    type="string",
                    description="搜索关键词，可以是股票代码（如'600519'）或股票名称（如'贵州茅台'）",
                    required=True
                )
            ]
        )

        # 3. 获取历史K线数据
        self.register_tool(
            name="get_history",
            handler=self.get_history,
            description="获取股票历史K线数据，支持日线、周线、月线",
            parameters=[
                ToolParameter(
                    name="symbol",
                    type="string",
                    description="股票代码，如'600519'或'600519.SH'",
                    required=True
                ),
                ToolParameter(
                    name="period",
                    type="string",
                    description="周期类型：daily(日线)、weekly(周线)、monthly(月线)",
                    required=False,
                    default="daily"
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
                    name="limit",
                    type="integer",
                    description="返回数据条数限制",
                    required=False,
                    default=100
                )
            ]
        )

        # 4. 获取股票基础信息
        self.register_tool(
            name="get_stock_basic_info",
            handler=self.get_stock_basic_info,
            description="获取股票基础信息（行业、地区、上市日期等）",
            parameters=[
                ToolParameter(
                    name="symbol",
                    type="string",
                    description="股票代码",
                    required=True
                )
            ]
        )

        # 5. 获取龙虎榜数据
        self.register_tool(
            name="get_top_list",
            handler=self.get_top_list,
            description="获取龙虎榜每日明细，包含机构买卖数据",
            parameters=[
                ToolParameter(
                    name="trade_date",
                    type="string",
                    description="交易日期，格式YYYYMMDD，默认最近交易日",
                    required=False,
                    default=None
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="返回条数限制",
                    required=False,
                    default=50
                )
            ]
        )

        # 6. 获取资金流向
        self.register_tool(
            name="get_money_flow",
            handler=self.get_money_flow,
            description="获取个股资金流向数据（主力、散户净流入等）",
            parameters=[
                ToolParameter(
                    name="symbol",
                    type="string",
                    description="股票代码",
                    required=True
                ),
                ToolParameter(
                    name="trade_date",
                    type="string",
                    description="交易日期，格式YYYYMMDD",
                    required=False,
                    default=None
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
                )
            ]
        )

        # 7. 获取涨跌停统计
        self.register_tool(
            name="get_limit_list",
            handler=self.get_limit_list,
            description="获取每日涨跌停统计",
            parameters=[
                ToolParameter(
                    name="trade_date",
                    type="string",
                    description="交易日期，格式YYYYMMDD，默认最近交易日",
                    required=False,
                    default=None
                ),
                ToolParameter(
                    name="limit_type",
                    type="string",
                    description="涨跌停类型：U(涨停)、D(跌停)，默认全部",
                    required=False,
                    default=None
                )
            ]
        )

        # 8. 获取公司详细信息
        self.register_tool(
            name="get_company_info",
            handler=self.get_company_info,
            description="获取上市公司详细信息（公司简介、联系方式、办公地址等）",
            parameters=[
                ToolParameter(
                    name="symbol",
                    type="string",
                    description="股票代码",
                    required=True
                )
            ]
        )
    
    async def get_quote(self, symbol: str) -> ToolResult:
        """
        获取股票实时行情
        
        Args:
            symbol: 股票代码
        
        Returns:
            ToolResult 包含股票行情数据
            
        示例返回数据：
            {
                "gid": "sh600519",
                "ts_code": "600519.SH",
                "name": "贵州茅台",
                "nowPri": "1850.50",
                "increase": "25.30",
                "increPer": "1.39",
                "todayStartPri": "1840.00",
                "yestodEndPri": "1825.20",
                "todayMax": "1865.00",
                "todayMin": "1835.00",
                "traAmount": "125000",
                "traNumber": "231250000",
                "update_time": "20260308"
            }
        """
        if not symbol:
            return ToolResult(
                success=False,
                error="股票代码不能为空"
            )
        
        try:
            # 使用 Tushare 客户端获取行情
            result = self.get_tushare_client().get_quote(symbol)
            
            if result.get("success"):
                return ToolResult(
                    success=True,
                    data=result.get("data")
                )
            else:
                return ToolResult(
                    success=False,
                    error=result.get("error", "获取股票数据失败")
                )
                
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"获取股票行情失败: {str(e)}"
            )
    
    async def search_stock(self, keyword: str) -> ToolResult:
        """
        搜索股票
        
        Args:
            keyword: 搜索关键词（股票代码或名称）
        
        Returns:
            ToolResult 包含搜索结果
        """
        if not keyword:
            return ToolResult(
                success=False,
                error="搜索关键词不能为空"
            )
        
        try:
            # 如果看起来像股票代码，直接查询
            if keyword.isdigit() or keyword.startswith(("sh", "sz", "SH", "SZ")):
                result = self.get_tushare_client().get_quote(keyword)
                if result.get("success"):
                    return ToolResult(
                        success=True,
                        data={
                            "results": [result.get("data")],
                            "count": 1
                        }
                    )

            # 纯数字代码，尝试上证和深证
            if keyword.isdigit():
                for prefix in ["sh", "sz"]:
                    result = self.get_tushare_client().get_quote(f"{prefix}{keyword}")
                    if result.get("success"):
                        return ToolResult(
                            success=True,
                            data={
                                "results": [result.get("data")],
                                "count": 1
                            }
                        )
            
            return ToolResult(
                success=False,
                error=f"未找到匹配的股票: {keyword}"
            )
            
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"搜索股票失败: {str(e)}"
            )

    async def get_history(self, symbol: str, period: str = "daily", 
                          start_date: str = None, end_date: str = None,
                          limit: int = 100) -> ToolResult:
        """
        获取股票历史K线数据
        
        Args:
            symbol: 股票代码
            period: 周期类型
            start_date: 开始日期
            end_date: 结束日期
            limit: 返回条数限制
        
        Returns:
            ToolResult 包含K线数据
        """
        if not symbol:
            return ToolResult(
                success=False,
                error="股票代码不能为空"
            )
        
        try:
            result = self.get_tushare_client().get_history(
                symbol=symbol,
                period=period,
                start_date=start_date,
                end_date=end_date,
                limit=limit
            )
            
            if result.get("success"):
                # 将数据和meta合并返回
                response_data = {
                    "records": result.get("data"),
                    "meta": result.get("meta")
                }
                return ToolResult(
                    success=True,
                    data=response_data
                )
            else:
                return ToolResult(
                    success=False,
                    error=result.get("error", "获取历史数据失败")
                )
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"获取历史数据失败: {str(e)}"
            )

    async def get_stock_basic_info(self, symbol: str) -> ToolResult:
        """
        获取股票基础信息
        
        Args:
            symbol: 股票代码
        
        Returns:
            ToolResult 包含股票基础信息
        """
        if not symbol:
            return ToolResult(
                success=False,
                error="股票代码不能为空"
            )
        
        try:
            result = self.get_tushare_client().get_stock_basic(symbol)
            
            if result.get("success"):
                return ToolResult(
                    success=True,
                    data=result.get("data")
                )
            else:
                return ToolResult(
                    success=False,
                    error=result.get("error", "获取股票基础信息失败")
                )
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"获取股票基础信息失败: {str(e)}"
            )

    async def get_top_list(self, trade_date: str = None, limit: int = 50) -> ToolResult:
        """
        获取龙虎榜数据
        
        Args:
            trade_date: 交易日期
            limit: 返回条数限制
        
        Returns:
            ToolResult 包含龙虎榜数据
        """
        try:
            result = self.get_tushare_client().get_top_list(
                trade_date=trade_date,
                limit=limit
            )
            
            if result.get("success"):
                response_data = {
                    "records": result.get("data"),
                    "meta": result.get("meta")
                }
                return ToolResult(
                    success=True,
                    data=response_data
                )
            else:
                return ToolResult(
                    success=False,
                    error=result.get("error", "获取龙虎榜数据失败")
                )
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"获取龙虎榜数据失败: {str(e)}"
            )

    async def get_money_flow(self, symbol: str, trade_date: str = None,
                             start_date: str = None, end_date: str = None) -> ToolResult:
        """
        获取个股资金流向
        
        Args:
            symbol: 股票代码
            trade_date: 交易日期
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            ToolResult 包含资金流向数据
        """
        if not symbol:
            return ToolResult(
                success=False,
                error="股票代码不能为空"
            )
        
        try:
            result = self.get_tushare_client().get_money_flow(
                symbol=symbol,
                trade_date=trade_date,
                start_date=start_date,
                end_date=end_date
            )
            
            if result.get("success"):
                response_data = {
                    "records": result.get("data"),
                    "meta": result.get("meta")
                }
                return ToolResult(
                    success=True,
                    data=response_data
                )
            else:
                return ToolResult(
                    success=False,
                    error=result.get("error", "获取资金流向数据失败")
                )
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"获取资金流向数据失败: {str(e)}"
            )

    async def get_limit_list(self, trade_date: str = None, limit_type: str = None) -> ToolResult:
        """
        获取涨跌停统计
        
        Args:
            trade_date: 交易日期
            limit_type: 涨跌停类型
        
        Returns:
            ToolResult 包含涨跌停统计
        """
        try:
            result = self.get_tushare_client().get_limit_list(
                trade_date=trade_date,
                limit_type=limit_type
            )
            
            if result.get("success"):
                response_data = {
                    "records": result.get("data"),
                    "meta": result.get("meta")
                }
                return ToolResult(
                    success=True,
                    data=response_data
                )
            else:
                return ToolResult(
                    success=False,
                    error=result.get("error", "获取涨跌停数据失败")
                )
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"获取涨跌停数据失败: {str(e)}"
            )

    async def get_company_info(self, symbol: str) -> ToolResult:
        """
        获取公司详细信息
        
        Args:
            symbol: 股票代码
        
        Returns:
            ToolResult 包含公司详细信息
        """
        if not symbol:
            return ToolResult(
                success=False,
                error="股票代码不能为空"
            )
        
        try:
            result = self.get_tushare_client().get_stock_company_info(symbol)
            
            if result.get("success"):
                return ToolResult(
                    success=True,
                    data=result.get("data")
                )
            else:
                return ToolResult(
                    success=False,
                    error=result.get("error", "获取公司信息失败")
                )
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"获取公司信息失败: {str(e)}"
            )
    
    def get_cache_info(self) -> Dict[str, Any]:
        """获取缓存信息"""
        return self.get_tushare_client().get_cache_info()

    def clear_cache(self):
        """清空缓存"""
        self.get_tushare_client().clear_cache()

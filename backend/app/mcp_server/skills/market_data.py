# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""MarketData Skill - 市场行情数据工具

基于 stock_service.py 和 tushare_client.py 改造，提供股票行情查询能力。
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from typing import Dict, Any, Optional
from .base import BaseSkill, ToolParameter, ToolResult, Skill, tool
from app.data.tushare_client import get_tushare_client, TushareClient


class MarketDataSkill(BaseSkill):
    """
    市场行情数据 Skill
    
    提供股票行情查询功能，基于 Tushare 数据源。
    """
    
    name = "market_data"
    description = "股票市场行情数据查询，支持A股实时行情获取"
    
    def __init__(self):
        self.tushare_client: TushareClient = get_tushare_client()
        super().__init__()
    
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
            result = self.tushare_client.get_quote(symbol)
            
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
                result = self.tushare_client.get_quote(keyword)
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
                    result = self.tushare_client.get_quote(f"{prefix}{keyword}")
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
    
    def get_cache_info(self) -> Dict[str, Any]:
        """获取缓存信息"""
        return self.tushare_client.get_cache_info()
    
    def clear_cache(self):
        """清空缓存"""
        self.tushare_client.clear_cache()

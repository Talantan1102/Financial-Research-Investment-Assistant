"""
MarketData Skill 模块

提供股票市场数据查询功能
基于原 stock_service.py 改造为MCP Skill
"""

from typing import Any, Dict, Optional
from datetime import datetime
import logging

from app.mcp_server.skills.base import Skill, tool, ToolResult
from app.data.tushare_client import get_tushare_client, TushareClient


logger = logging.getLogger(__name__)


class MarketDataSkill(Skill):
    """
    市场数据Skill
    
    提供股票实时行情、历史数据等市场数据查询功能
    """
    
    def __init__(self):
        """初始化市场数据Skill"""
        super().__init__(
            name="market_data",
            description="股票市场数据查询Skill，提供实时行情、历史数据等功能"
        )
        self._client: Optional[TushareClient] = None
    
    async def initialize(self) -> bool:
        """
        初始化MarketData Skill
        
        Returns:
            是否初始化成功
        """
        try:
            self._client = get_tushare_client()
            logger.info("MarketDataSkill initialized successfully")
            self._initialized = True
            return True
        except Exception as e:
            logger.error(f"Failed to initialize MarketDataSkill: {e}")
            self._initialized = False
            return False
    
    async def cleanup(self) -> None:
        """清理资源"""
        self._client = None
        self._initialized = False
        logger.info("MarketDataSkill cleaned up")
    
    def _ensure_initialized(self) -> None:
        """
        确保Skill已初始化
        
        Raises:
            RuntimeError: 未初始化
        """
        if not self._initialized or not self._client:
            raise RuntimeError("MarketDataSkill not initialized. Call initialize() first.")
    
    def _format_quote_response(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        格式化行情数据响应
        
        Args:
            raw_data: 原始数据
            
        Returns:
            格式化后的数据
        """
        # 保持与原StockInfo模型兼容的字段
        return {
            "code": raw_data.get("code", ""),
            "name": raw_data.get("name", ""),
            "market": raw_data.get("market", ""),
            "nowPri": raw_data.get("nowPri", "0"),
            "todayMax": raw_data.get("todayMax", "0"),
            "todayMin": raw_data.get("todayMin", "0"),
            "todayStartPri": raw_data.get("todayStartPri", "0"),
            "yestodEndPri": raw_data.get("yestodEndPri", "0"),
            "traAmount": raw_data.get("traAmount", "0"),
            "traNumber": raw_data.get("traNumber", "0"),
            "buy": raw_data.get("buy", "0"),
            "sell": raw_data.get("sell", "0"),
            "updown": raw_data.get("updown", "0"),
            "percent": raw_data.get("percent", "0"),
            "priearn": raw_data.get("priearn", "0"),
            "high52week": raw_data.get("high52week", "0"),
            "low52week": raw_data.get("low52week", "0"),
            "time": raw_data.get("time", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        }
    
    @tool(
        name="get_quote",
        description="获取股票实时行情数据。支持A股股票，自动识别上海/深圳市场。",
        timeout=30
    )
    async def get_quote(
        self,
        symbol: str,
        include_details: bool = False
    ) -> Dict[str, Any]:
        """
        获取股票实时行情
        
        Args:
            symbol: 股票代码，支持多种格式：
                   - 600519 (纯代码，自动识别市场)
                   - sh600519 (带市场前缀)
                   - 600519.SH (Tushare格式)
            include_details: 是否包含详细信息（如52周高低点、市盈率等）
            
        Returns:
            股票行情数据字典
        """
        self._ensure_initialized()
        
        logger.info(f"Getting quote for symbol: {symbol}")
        
        result = self._client.get_quote(symbol)
        
        if not result["success"]:
            error_msg = result.get("error", "Unknown error")
            logger.error(f"Failed to get quote for {symbol}: {error_msg}")
            raise Exception(error_msg)
        
        data = result["data"]
        formatted_data = self._format_quote_response(data)
        
        # 如果不包含详细信息，移除部分字段
        if not include_details:
            detail_fields = ["priearn", "high52week", "low52week"]
            for field in detail_fields:
                if field in formatted_data:
                    del formatted_data[field]
        
        logger.info(f"Successfully got quote for {symbol}: {formatted_data.get('name')}")
        
        return {
            "symbol": symbol,
            "data": formatted_data,
            "source": "tushare",
            "timestamp": datetime.now().isoformat()
        }
    
    @tool(
        name="search_stock",
        description="根据股票名称或代码搜索股票信息",
        timeout=30
    )
    async def search_stock(
        self,
        keyword: str,
        limit: int = 10
    ) -> Dict[str, Any]:
        """
        搜索股票
        
        Args:
            keyword: 搜索关键词（股票名称或代码）
            limit: 返回结果数量限制，默认10条
            
        Returns:
            搜索结果列表
        """
        self._ensure_initialized()
        
        logger.info(f"Searching stock with keyword: {keyword}")
        
        # 注意：Tushare API本身没有搜索功能，
        # 这里模拟搜索逻辑，实际实现可能需要结合其他数据源
        # 或者维护一个本地股票列表
        
        # 如果是纯数字，尝试作为股票代码查询
        if keyword.isdigit():
            try:
                result = self._client.get_quote(keyword)
                if result["success"]:
                    return {
                        "keyword": keyword,
                        "results": [{
                            "code": result["data"]["code"],
                            "name": result["data"]["name"],
                            "market": result["data"]["market"]
                        }],
                        "total": 1
                    }
            except Exception:
                pass
        
        # TODO: 实现基于名称的搜索
        # 这需要本地维护股票列表或使用其他API
        
        return {
            "keyword": keyword,
            "results": [],
            "total": 0,
            "note": "目前仅支持股票代码精确查询，名称搜索功能待完善"
        }
    
    @tool(
        name="get_market_overview",
        description="获取市场概况，包括主要指数行情",
        timeout=30
    )
    async def get_market_overview(
        self,
        market: str = "all"
    ) -> Dict[str, Any]:
        """
        获取市场概况
        
        Args:
            market: 市场类型，可选值：
                   - "all": 所有主要市场
                   - "sh": 上海证券交易所
                   - "sz": 深圳证券交易所
            
        Returns:
            市场概况数据
        """
        self._ensure_initialized()
        
        logger.info(f"Getting market overview for: {market}")
        
        # 主要指数代码
        index_codes = {
            "sh": ["000001.SH", "000300.SH", "000016.SH"],  # 上证指数、沪深300、上证50
            "sz": ["399001.SZ", "399006.SZ", "399005.SZ"]   # 深证成指、创业板指、中小板指
        }
        
        codes_to_query = []
        if market == "all":
            codes_to_query = index_codes["sh"] + index_codes["sz"]
        elif market in index_codes:
            codes_to_query = index_codes[market]
        
        results = []
        errors = []
        
        for code in codes_to_query:
            try:
                result = self._client.get_quote(code)
                if result["success"]:
                    results.append(self._format_quote_response(result["data"]))
            except Exception as e:
                logger.warning(f"Failed to get quote for {code}: {e}")
                errors.append(f"{code}: {str(e)}")
        
        return {
            "market": market,
            "indices": results,
            "count": len(results),
            "errors": errors if errors else None,
            "timestamp": datetime.now().isoformat()
        }
    
    @tool(
        name="batch_get_quotes",
        description="批量获取多只股票行情",
        timeout=60
    )
    async def batch_get_quotes(
        self,
        symbols: list,
        include_details: bool = False
    ) -> Dict[str, Any]:
        """
        批量获取股票行情
        
        Args:
            symbols: 股票代码列表，如 ["600519", "000001"]
            include_details: 是否包含详细信息
            
        Returns:
            批量查询结果
        """
        self._ensure_initialized()
        
        logger.info(f"Batch getting quotes for {len(symbols)} symbols")
        
        results = []
        errors = []
        
        for symbol in symbols:
            try:
                result = self._client.get_quote(symbol)
                if result["success"]:
                    data = self._format_quote_response(result["data"])
                    if not include_details:
                        detail_fields = ["priearn", "high52week", "low52week"]
                        for field in detail_fields:
                            if field in data:
                                del data[field]
                    results.append(data)
                else:
                    errors.append({"symbol": symbol, "error": result.get("error")})
            except Exception as e:
                errors.append({"symbol": symbol, "error": str(e)})
        
        return {
            "requested_count": len(symbols),
            "success_count": len(results),
            "failed_count": len(errors),
            "data": results,
            "errors": errors if errors else None,
            "timestamp": datetime.now().isoformat()
        }

"""
Tool Adapter - MCP Client 到 StockService 的适配器

提供与 StockService 兼容的接口，优先使用 MCP Client，
失败时自动降级到原有的 StockService 实现。
"""

import logging
from typing import Any, Dict, Optional


class ToolAdapter:
    """
    MCP Tool 适配器

    封装 MCPClient，提供与 StockService 完全兼容的接口。
    MCP 调用失败时自动降级到原有 StockService。

    特性：
    - 透明的接口兼容（与 StockService 相同）
    - 自动降级机制（MCP 失败时使用 StockService）
    - 延迟加载 StockService（避免循环依赖）
    - 降级状态缓存（异常时永久切换到降级模式）

    使用示例：
        adapter = ToolAdapter(mcp_client=mcp_client, fallback_enabled=True)
        result = await adapter.get_stock_by_code("600519")
    """

    def __init__(
        self,
        mcp_client=None,
        fallback_enabled: bool = True
    ):
        """
        初始化 ToolAdapter

        Args:
            mcp_client: MCPClient 实例（可选，为 None 时直接使用降级）
            fallback_enabled: 是否启用降级到 StockService（默认 True）
        """
        self.mcp_client = mcp_client
        self.fallback_enabled = fallback_enabled

        # 延迟加载的降级服务
        self._fallback_service = None

        # 降级标志（异常时永久切换到降级模式）
        self._degraded = False

        # 日志
        self.logger = logging.getLogger("ToolAdapter")

    def _get_fallback_service(self):
        """
        延迟加载 StockService（避免循环依赖）

        Returns:
            StockService 实例或 None（加载失败时）
        """
        if self._fallback_service is None:
            try:
                # 尝试相对导入
                try:
                    from service.stock_service import get_stock_service
                except ImportError:
                    # 回退到绝对导入
                    from app.service.stock_service import get_stock_service

                self._fallback_service = get_stock_service()
                self.logger.info("已加载 StockService 作为降级方案")

            except ImportError as e:
                self.logger.warning(f"无法导入 StockService: {e}")
                self._fallback_service = None

        return self._fallback_service

    async def get_stock_by_code(self, stock_code: str) -> Dict[str, Any]:
        """
        获取股票行情数据（兼容 StockService 接口）

        优先使用 MCP Client，失败时降级到 StockService。

        Args:
            stock_code: 股票代码（如 "600519", "sh600519", "sz000858" 等）

        Returns:
            Dict[str, Any]: 标准返回格式
            {
                "success": bool,
                "data": {
                    "gid": str,
                    "name": str,
                    "nowPri": str,
                    "increase": str,
                    "increPer": str,
                    "todayStartPri": str,
                    "yestodEndPri": str,
                    "todayMax": str,
                    "todayMin": str,
                    "traAmount": str,
                    "traNumber": str
                },
                "error": str
            }
        """
        # 1. 尝试使用 MCP Client
        if self.mcp_client and self.mcp_client.is_connected and not self._degraded:
            try:
                self.logger.debug(f"尝试使用 MCP 获取股票数据: {stock_code}")

                result = await self.mcp_client.call_tool(
                    "market_data.get_quote",
                    {"symbol": stock_code}
                )

                if result.get("success"):
                    self.logger.info(f"MCP 获取股票数据成功: {stock_code}")
                    return result
                else:
                    self.logger.warning(
                        f"MCP 获取股票数据失败: {stock_code} - {result.get('error')}"
                    )
                    # 单次失败不触发降级，继续尝试降级方案

            except Exception as e:
                self.logger.error(f"MCP 调用异常: {type(e).__name__}: {e}")
                # 异常时触发降级模式
                if self.fallback_enabled:
                    self._degraded = True
                    self.logger.warning("MCP 调用异常，永久切换到降级模式")

        # 2. 降级到 StockService
        if self.fallback_enabled:
            fallback_service = self._get_fallback_service()
            if fallback_service:
                self.logger.info(f"使用 StockService 获取股票数据: {stock_code}")
                try:
                    return await fallback_service.get_stock_by_code(stock_code)
                except Exception as e:
                    self.logger.error(f"StockService 调用失败: {e}")
                    return {
                        "success": False,
                        "data": None,
                        "error": f"StockService 调用失败: {e}"
                    }

        # 3. 都不可用
        self.logger.error(f"无法获取股票数据: {stock_code} - MCP 和 StockService 都不可用")
        return {
            "success": False,
            "data": None,
            "error": "MCP 和 StockService 都不可用"
        }

    async def search_stock(self, keyword: str) -> Dict[str, Any]:
        """
        搜索股票（兼容 StockService 接口）

        Args:
            keyword: 搜索关键词

        Returns:
            Dict[str, Any]: 标准返回格式
            {
                "success": bool,
                "data": [...],  # 股票列表
                "error": str
            }
        """
        # 1. 尝试使用 MCP Client
        if self.mcp_client and self.mcp_client.is_connected and not self._degraded:
            try:
                self.logger.debug(f"尝试使用 MCP 搜索股票: {keyword}")

                result = await self.mcp_client.call_tool(
                    "market_data.search_stock",
                    {"keyword": keyword}
                )

                if result.get("success"):
                    self.logger.info(f"MCP 搜索股票成功: {keyword}")
                    return result
                else:
                    self.logger.warning(
                        f"MCP 搜索股票失败: {keyword} - {result.get('error')}"
                    )

            except Exception as e:
                self.logger.error(f"MCP 搜索异常: {type(e).__name__}: {e}")
                if self.fallback_enabled:
                    self._degraded = True
                    self.logger.warning("MCP 调用异常，永久切换到降级模式")

        # 2. 降级到 StockService
        if self.fallback_enabled:
            fallback_service = self._get_fallback_service()
            if fallback_service:
                self.logger.info(f"使用 StockService 搜索股票: {keyword}")
                try:
                    return await fallback_service.search_stock(keyword)
                except Exception as e:
                    self.logger.error(f"StockService 搜索失败: {e}")
                    return {
                        "success": False,
                        "data": None,
                        "error": f"StockService 搜索失败: {e}"
                    }

        # 3. 都不可用
        self.logger.error(f"无法搜索股票: {keyword} - 搜索服务不可用")
        return {
            "success": False,
            "data": None,
            "error": "搜索服务不可用"
        }

    async def get_market_stocks(
        self,
        market: str = "shanghai",
        page: int = 1
    ) -> Dict[str, Any]:
        """
        获取市场股票列表（兼容 StockService 接口）

        Args:
            market: 市场名称（"shanghai" 或 "shenzhen"）
            page: 页码

        Returns:
            Dict[str, Any]: 标准返回格式
            {
                "success": bool,
                "data": [...],  # 股票列表
                "error": str
            }
        """
        # 1. 尝试使用 MCP Client
        if self.mcp_client and self.mcp_client.is_connected and not self._degraded:
            try:
                self.logger.debug(f"尝试使用 MCP 获取市场股票: {market}, page {page}")

                result = await self.mcp_client.call_tool(
                    "market_data.get_market_list",
                    {"market": market, "page": page}
                )

                if result.get("success"):
                    self.logger.info(f"MCP 获取市场股票成功: {market}")
                    return result
                else:
                    self.logger.warning(
                        f"MCP 获取市场股票失败: {market} - {result.get('error')}"
                    )

            except Exception as e:
                self.logger.error(f"MCP 获取市场股票异常: {type(e).__name__}: {e}")
                if self.fallback_enabled:
                    self._degraded = True
                    self.logger.warning("MCP 调用异常，永久切换到降级模式")

        # 2. 降级到 StockService
        if self.fallback_enabled:
            fallback_service = self._get_fallback_service()
            if fallback_service:
                self.logger.info(f"使用 StockService 获取市场股票: {market}")
                try:
                    return await fallback_service.get_market_stocks(market, page)
                except Exception as e:
                    self.logger.error(f"StockService 获取市场股票失败: {e}")
                    return {
                        "success": False,
                        "data": None,
                        "error": f"StockService 获取市场股票失败: {e}"
                    }

        # 3. 都不可用
        self.logger.error(f"无法获取市场股票: {market} - 服务不可用")
        return {
            "success": False,
            "data": None,
            "error": "市场股票服务不可用"
        }

    @property
    def is_using_mcp(self) -> bool:
        """
        检查是否正在使用 MCP（未降级）

        Returns:
            bool: True 表示正在使用 MCP，False 表示已降级或 MCP 不可用
        """
        return (
            self.mcp_client is not None
            and self.mcp_client.is_connected
            and not self._degraded
        )

    @property
    def is_degraded(self) -> bool:
        """
        检查是否已降级

        Returns:
            bool: True 表示已降级到 StockService
        """
        return self._degraded

    def reset_degraded_state(self):
        """
        重置降级状态（用于恢复尝试 MCP）

        注意：仅在确认 MCP 已修复后调用
        """
        self._degraded = False
        self.logger.info("已重置降级状态，将重新尝试使用 MCP")

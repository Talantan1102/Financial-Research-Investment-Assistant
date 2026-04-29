# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""Tushare API 封装客户端"""

import logging
import os
import time
from datetime import datetime, timedelta
from threading import Lock
from typing import Any, Optional

import pandas as pd
import tushare as ts

# 配置日志只输出到文件，避免干扰 MCP STDIO 通信
_log_file = os.path.join(os.path.dirname(__file__), "tushare.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(_log_file)],
)
logger = logging.getLogger(__name__)


class TushareRateLimitError(Exception):
    """API 限流异常"""

    pass


class TushareInvalidCodeError(Exception):
    """无效股票代码异常"""

    pass


class TushareNetworkError(Exception):
    """网络异常"""

    pass


class TushareClient:
    """
    Tushare API 客户端（单例模式）

    功能：
    - 从环境变量读取 Token
    - 获取股票实时行情数据
    - 股票代码自动识别（6开头=上证，0/3开头=深证）
    - 错误处理（限流、无效代码、网络异常）
    - 缓存机制（5分钟TTL）
    """

    _instance: Optional["TushareClient"] = None
    _lock = Lock()

    # 缓存设置
    CACHE_TTL = 300  # 5分钟（秒）

    def __new__(cls):
        """单例模式实现"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """初始化客户端（延迟初始化模式）"""
        # 避免重复初始化
        if hasattr(self, "_initialized"):
            return

        # 从环境变量读取 Token
        self.token = os.getenv("TUSHARE_API_TOKEN", "")
        # 从环境变量读取自定义 API URL
        self.api_url = os.getenv("TUSHARE_API_URL", "https://api.tushare.pro")

        # 是否使用 Mock 模式
        self.use_mock = os.getenv("USE_MOCK_TUSHARE", "false").lower() == "true"
        self._mock_service = None
        if self.use_mock:
            from app.service.mock_tushare_service import MockTushareService

            self._mock_service = MockTushareService()
            logger.info("TushareClient 已启用 Mock 模式")

        # 延迟初始化：不立即创建 api 实例
        self.api = None
        self._api_initialized = False

        # 缓存存储: {ts_code: (data, timestamp)}
        self._cache: dict[str, tuple[dict[str, Any], float]] = {}
        self._cache_lock = Lock()

        # 用户积分（延迟加载）
        self._user_points: int | None = None
        self._points_checked = False

        self._initialized = True

    def get_api(self):
        """
        获取 Tushare API 实例（延迟初始化）

        Returns:
            Tushare pro_api 实例，如果初始化失败返回 None
            如果启用了 Mock 模式，返回 MockTushareAPI 实例
        """
        # 如果已经初始化过，直接返回
        if self._api_initialized:
            return self.api

        # Mock 模式下返回 Mock API
        if self.use_mock and self._mock_service:
            self.api = MockTushareAPI(self._mock_service)
            self._api_initialized = True
            logger.info("使用 Mock Tushare API")
            return self.api

        # 首次调用时初始化
        if not self.token:
            logger.warning("TUSHARE_API_TOKEN 环境变量未设置")
            self.api = None
            self._api_initialized = True
            return None

        try:
            ts.set_token(self.token)
            # 创建 pro_api 实例
            self.api = ts.pro_api()
            # 设置自定义 API URL（如果指定了非默认 URL）
            if self.api_url and self.api_url != "https://api.tushare.pro":
                self.api._DataApi__token = self.token
                self.api._DataApi__http_url = self.api_url
                logger.info(f"使用自定义 Tushare API URL: {self.api_url}")
            self._api_initialized = True
            return self.api
        except Exception as e:
            logger.warning(f"Tushare API 初始化失败: {e}")
            self.api = None
            self._api_initialized = True
            return None

    def _safe_float(self, value, default=0.0):
        """安全转换数值，处理 None/NaN/Infinity，返回数值避免类型错误"""
        if value is None:
            return default
        try:
            f = float(value)
            # 检查 NaN 和 Infinity
            import math

            if math.isnan(f) or math.isinf(f):
                return default
            return f
        except (TypeError, ValueError):
            return default

    def _normalize_stock_code(self, symbol: str) -> str:
        """
        标准化股票代码为 Tushare 格式

        Args:
            symbol: 股票代码，如 "600519", "000001", "sh600519", "sz000001"

        Returns:
            Tushare 格式代码，如 "600519.SH", "000001.SZ"

        Examples:
            >>> client._normalize_stock_code("600519")
            "600519.SH"
            >>> client._normalize_stock_code("000001")
            "000001.SZ"
            >>> client._normalize_stock_code("sh600519")
            "600519.SH"
        """
        symbol = symbol.strip().upper()

        # 如果已经是 Tushare 格式（如 "600519.SH"）
        if "." in symbol:
            return symbol

        # 去除可能的 sh/sz 前缀
        if symbol.startswith("SH"):
            code = symbol[2:]
            return f"{code}.SH"
        elif symbol.startswith("SZ"):
            code = symbol[2:]
            return f"{code}.SZ"

        # 纯数字代码，根据首位数字判断市场
        if symbol.isdigit():
            # 6 开头 = 上海证券交易所
            if symbol.startswith("6"):
                return f"{symbol}.SH"
            # 0 或 3 开头 = 深圳证券交易所
            elif symbol.startswith(("0", "3")):
                return f"{symbol}.SZ"
            else:
                raise TushareInvalidCodeError(f"无法识别的股票代码: {symbol}")

        raise TushareInvalidCodeError(f"无效的股票代码格式: {symbol}")

    def _get_from_cache(self, ts_code: str) -> dict[str, Any] | None:
        """
        从缓存获取数据

        Args:
            ts_code: Tushare 格式股票代码

        Returns:
            缓存的数据，如果不存在或过期返回 None
        """
        with self._cache_lock:
            if ts_code in self._cache:
                data, timestamp = self._cache[ts_code]
                # 检查是否过期
                if time.time() - timestamp < self.CACHE_TTL:
                    return data
                else:
                    # 删除过期缓存
                    del self._cache[ts_code]
        return None

    def _set_cache(self, ts_code: str, data: dict[str, Any]):
        """
        设置缓存

        Args:
            ts_code: Tushare 格式股票代码
            data: 要缓存的数据
        """
        with self._cache_lock:
            self._cache[ts_code] = (data, time.time())

    def _clear_expired_cache(self):
        """清理过期缓存"""
        with self._cache_lock:
            current_time = time.time()
            expired_keys = [
                key
                for key, (_, timestamp) in self._cache.items()
                if current_time - timestamp >= self.CACHE_TTL
            ]
            for key in expired_keys:
                del self._cache[key]

    def get_user_points(self) -> int | None:
        """
        获取用户积分

        Returns:
            用户积分，如果无法获取返回 None
        """
        if self._points_checked:
            return self._user_points

        api = self.get_api()
        if not api:
            self._points_checked = True
            return None

        try:
            # 调用 user 接口获取用户信息
            user_info = api.user()
            if user_info is not None and not user_info.empty:
                # user() 返回 DataFrame，取第一行的 points 字段
                self._user_points = int(user_info.iloc[0].get("points", 0))
                logger.info(f"Tushare 账号积分: {self._user_points}")
            else:
                logger.warning("无法获取 Tushare 用户积分信息")
                self._user_points = None
        except Exception as e:
            logger.warning(f"获取 Tushare 用户积分失败: {e}")
            self._user_points = None

        self._points_checked = True
        return self._user_points

    def get_stock_basic(self, symbol: str) -> dict[str, Any]:
        """
        获取股票基本信息（低积分可用接口）

        Args:
            symbol: 股票代码

        Returns:
            格式化的股票基本信息字典
        """
        api = self.get_api()
        if not api:
            return {
                "success": False,
                "data": None,
                "error": "Tushare API 未初始化，请检查 TUSHARE_API_TOKEN 环境变量",
            }

        try:
            # 标准化股票代码
            ts_code = self._normalize_stock_code(symbol)

            # 调用 stock_basic 接口获取基本信息
            df = api.stock_basic(
                ts_code=ts_code, fields="ts_code,symbol,name,area,industry,list_date"
            )

            if df is None or df.empty:
                raise TushareInvalidCodeError(f"未找到股票: {symbol}")

            # 获取第一条记录
            stock_info = df.iloc[0]

            # 构造返回数据
            stock_data = {
                "ts_code": stock_info["ts_code"],
                "symbol": stock_info["symbol"],
                "name": stock_info["name"],
                "area": stock_info.get("area", ""),
                "industry": stock_info.get("industry", ""),
                "list_date": stock_info.get("list_date", ""),
            }

            return {"success": True, "data": stock_data, "error": None}

        except TushareInvalidCodeError as e:
            return {"success": False, "data": None, "error": f"无效股票代码: {str(e)}"}
        except Exception as e:
            return {"success": False, "data": None, "error": f"获取股票基本信息失败: {str(e)}"}

    def get_quote(self, symbol: str) -> dict[str, Any]:
        """
        获取股票实时行情数据

        Args:
            symbol: 股票代码，支持多种格式：
                   - "600519" (纯数字)
                   - "sh600519" (带市场前缀)
                   - "600519.SH" (Tushare格式)

        Returns:
            格式化的股票数据字典：
            {
                "success": True/False,
                "data": {
                    "gid": "sh600519",           # 股票编号
                    "ts_code": "600519.SH",      # Tushare代码
                    "name": "贵州茅台",           # 股票名称
                    "nowPri": "1850.50",         # 当前价格
                    "increase": "25.30",         # 涨跌额
                    "increPer": "1.39",          # 涨跌幅(%)
                    "todayStartPri": "1840.00",  # 今日开盘价
                    "yestodEndPri": "1825.20",   # 昨日收盘价
                    "todayMax": "1865.00",       # 今日最高价
                    "todayMin": "1835.00",       # 今日最低价
                    "traAmount": "125000",       # 成交量(手)
                    "traNumber": "231250000",    # 成交额(元)
                    "update_time": "2026-03-08 15:00:00"  # 更新时间
                },
                "error": None  # 错误信息（成功时为None）
            }

        注意:
            - 积分 >= 200: 使用 daily 接口获取完整行情数据
            - 积分 < 200: 仅返回股票基本信息（不含价格数据）

        Raises:
            TushareInvalidCodeError: 无效股票代码
            TushareRateLimitError: API 限流
            TushareNetworkError: 网络异常
        """
        api = self.get_api()
        if not api:
            return {
                "success": False,
                "data": None,
                "error": "Tushare API 未初始化，请检查 TUSHARE_API_TOKEN 环境变量",
            }

        try:
            # 标准化股票代码
            ts_code = self._normalize_stock_code(symbol)

            # 尝试从缓存获取
            cached_data = self._get_from_cache(ts_code)
            if cached_data:
                return {"success": True, "data": cached_data, "error": None}

            # 检查用户积分
            points = self.get_user_points()

            # 积分 < 200 时使用低积分替代方案
            if points is not None and points < 200:
                logger.info(f"积分不足 ({points} < 200)，使用 stock_basic 接口获取基本信息")

                # 获取股票基本信息
                basic_result = self.get_stock_basic(symbol)
                if not basic_result["success"]:
                    return basic_result

                basic_data = basic_result["data"]

                # 构造简化数据（仅基本信息，无价格数据）
                stock_data = {
                    "gid": self._to_legacy_code(ts_code),
                    "ts_code": basic_data["ts_code"],
                    "name": basic_data["name"],
                    "area": basic_data.get("area", ""),
                    "industry": basic_data.get("industry", ""),
                    "list_date": basic_data.get("list_date", ""),
                    # 价格数据标记为不可用
                    "nowPri": "N/A",
                    "increase": "N/A",
                    "increPer": "N/A",
                    "todayStartPri": "N/A",
                    "yestodEndPri": "N/A",
                    "todayMax": "N/A",
                    "todayMin": "N/A",
                    "traAmount": "N/A",
                    "traNumber": "N/A",
                    "update_time": datetime.now().strftime("%Y-%m-%d"),
                    "_low_points_mode": True,  # 标记为低积分模式
                }

                # 缓存数据
                self._set_cache(ts_code, stock_data)

                return {
                    "success": True,
                    "data": stock_data,
                    "error": None,
                    "warning": f"账号积分 {points} < 200，仅返回基本信息",
                }

            # 积分 >= 200 或无法获取积分时，使用 daily 接口获取完整数据
            # 调用 Tushare API 获取实时行情
            # 使用 daily 接口获取最新交易日数据
            df = api.daily(
                ts_code=ts_code,
                start_date=(datetime.now() - timedelta(days=7)).strftime("%Y%m%d"),
                end_date=datetime.now().strftime("%Y%m%d"),
            )

            if df is None or df.empty:
                raise TushareInvalidCodeError(f"未找到股票数据: {symbol}")

            # 获取最新一条数据
            latest = df.iloc[0]

            # 获取股票基本信息（股票名称）
            stock_basic = api.stock_basic(ts_code=ts_code, fields="ts_code,symbol,name")

            stock_name = "未知"
            if stock_basic is not None and not stock_basic.empty:
                stock_name = stock_basic.iloc[0]["name"]

            # 计算涨跌额和涨跌幅
            close_price = float(latest["close"])
            pre_close = float(latest["pre_close"])
            increase = close_price - pre_close
            incre_per = (increase / pre_close * 100) if pre_close > 0 else 0

            # 构造返回数据（兼容 StockInfo 格式）
            stock_data = {
                "gid": self._to_legacy_code(ts_code),  # sh600519 格式
                "ts_code": ts_code,  # 600519.SH 格式
                "name": stock_name,
                "nowPri": f"{close_price:.2f}",
                "increase": f"{increase:.2f}",
                "increPer": f"{incre_per:.2f}",
                "todayStartPri": f"{float(latest['open']):.2f}",
                "yestodEndPri": f"{pre_close:.2f}",
                "todayMax": f"{float(latest['high']):.2f}",
                "todayMin": f"{float(latest['low']):.2f}",
                "traAmount": f"{int(latest['vol'])}",  # 成交量(手)
                "traNumber": f"{float(latest['amount']) * 1000:.2f}",  # 成交额(千元转元)
                "update_time": latest["trade_date"],
            }

            # 缓存数据
            self._set_cache(ts_code, stock_data)

            # 定期清理过期缓存
            self._clear_expired_cache()

            return {"success": True, "data": stock_data, "error": None}

        except TushareInvalidCodeError as e:
            return {"success": False, "data": None, "error": f"无效股票代码: {str(e)}"}
        except Exception as e:
            error_msg = str(e).lower()

            # 判断错误类型
            if "rate limit" in error_msg or "too many requests" in error_msg:
                return {"success": False, "data": None, "error": "API 调用频率超限，请稍后再试"}
            elif "network" in error_msg or "timeout" in error_msg or "connection" in error_msg:
                return {"success": False, "data": None, "error": f"网络异常: {str(e)}"}
            else:
                return {"success": False, "data": None, "error": f"获取股票数据失败: {str(e)}"}

    def _to_legacy_code(self, ts_code: str) -> str:
        """
        将 Tushare 格式代码转换为传统格式

        Args:
            ts_code: Tushare 格式，如 "600519.SH"

        Returns:
            传统格式，如 "sh600519"
        """
        if "." not in ts_code:
            return ts_code

        code, market = ts_code.split(".")
        return f"{market.lower()}{code}"

    def clear_cache(self):
        """清空所有缓存"""
        with self._cache_lock:
            self._cache.clear()

    def get_cache_info(self) -> dict[str, Any]:
        """
        获取缓存信息

        Returns:
            缓存统计信息
        """
        with self._cache_lock:
            current_time = time.time()
            valid_count = sum(
                1
                for _, timestamp in self._cache.values()
                if current_time - timestamp < self.CACHE_TTL
            )

            return {
                "total_cached": len(self._cache),
                "valid_cached": valid_count,
                "cache_ttl": self.CACHE_TTL,
            }

    def get_history(
        self,
        symbol: str,
        period: str = "daily",
        start_date: str = None,
        end_date: str = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """
        获取股票历史K线数据

        Args:
            symbol: 股票代码，如 "600519" 或 "600519.SH"
            period: 周期类型，可选 daily(日线)、weekly(周线)、monthly(月线)
            start_date: 开始日期，格式 "YYYYMMDD"
            end_date: 结束日期，格式 "YYYYMMDD"
            limit: 返回数据条数限制（默认100条）

        Returns:
            格式化的K线数据字典：
            {
                "success": True/False,
                "data": [
                    {
                        "trade_date": "20260307",
                        "open": 1800.00,
                        "high": 1850.00,
                        "low": 1790.00,
                        "close": 1825.00,
                        "pre_close": 1800.00,
                        "change": 25.00,
                        "pct_chg": 1.39,
                        "vol": 125000,
                        "amount": 231250.00
                    },
                    ...
                ],
                "error": None
            }
        """
        api = self.get_api()
        if not api:
            return {
                "success": False,
                "data": None,
                "error": "Tushare API 未初始化，请检查 TUSHARE_API_TOKEN 环境变量",
            }

        try:
            # 标准化股票代码
            ts_code = self._normalize_stock_code(symbol)

            # 构建缓存键
            cache_key = f"history_{ts_code}_{period}_{start_date}_{end_date}"
            cached_data = self._get_from_cache(cache_key)
            if cached_data:
                return {"success": True, "data": cached_data, "error": None}

            # 设置默认日期范围
            if not end_date:
                end_date = datetime.now().strftime("%Y%m%d")
            if not start_date:
                start_dt = datetime.strptime(end_date, "%Y%m%d") - timedelta(days=limit)
                start_date = start_dt.strftime("%Y%m%d")

            # 根据周期选择API
            api_func_map = {"daily": api.daily, "weekly": api.weekly, "monthly": api.monthly}

            if period not in api_func_map:
                return {
                    "success": False,
                    "data": None,
                    "error": f"不支持的周期类型: {period}，可选: daily, weekly, monthly",
                }

            api_func = api_func_map[period]

            # 调用API
            df = api_func(ts_code=ts_code, start_date=start_date, end_date=end_date)

            if df is None or df.empty:
                return {"success": False, "data": None, "error": f"未找到历史数据: {symbol}"}

            # 转换为列表格式
            records = []
            for _, row in df.iterrows():
                records.append(
                    {
                        "trade_date": row["trade_date"],
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                        "pre_close": float(row["pre_close"]),
                        "change": float(row["change"]),
                        "pct_chg": float(row["pct_chg"]),
                        "vol": float(row["vol"]),
                        "amount": float(row["amount"]),
                    }
                )

            # 限制返回数量
            records = records[:limit]

            # 缓存数据
            self._set_cache(cache_key, records)

            return {
                "success": True,
                "data": records,
                "meta": {
                    "symbol": ts_code,
                    "period": period,
                    "count": len(records),
                    "start_date": records[-1]["trade_date"] if records else None,
                    "end_date": records[0]["trade_date"] if records else None,
                },
                "error": None,
            }

        except Exception as e:
            return {"success": False, "data": None, "error": f"获取历史数据失败: {str(e)}"}

    def get_top_list(self, trade_date: str = None, limit: int = 50) -> dict[str, Any]:
        """
        获取龙虎榜每日明细

        Args:
            trade_date: 交易日期，格式 "YYYYMMDD"，默认最近交易日
            limit: 返回条数限制

        Returns:
            龙虎榜数据字典：
            {
                "success": True/False,
                "data": [
                    {
                        "trade_date": "20260307",
                        "ts_code": "000001.SZ",
                        "name": "平安银行",
                        "close": 10.50,
                        "pct_chg": 10.02,
                        "turnover_rate": 5.23,
                        "amount": 1250000000.00,
                        "l_buy": 85000000.00,
                        "l_sell": 32000000.00,
                        "net_amount": 53000000.00,
                        "reason": "日涨幅偏离值达到7%的前5只证券"
                    },
                    ...
                ],
                "error": None
            }
        """
        api = self.get_api()
        if not api:
            return {
                "success": False,
                "data": None,
                "error": "Tushare API 未初始化，请检查 TUSHARE_API_TOKEN 环境变量",
            }

        try:
            # 设置默认日期为最近交易日
            if not trade_date:
                trade_date = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")

            # 构建缓存键
            cache_key = f"top_list_{trade_date}"
            cached_data = self._get_from_cache(cache_key)
            if cached_data:
                return {"success": True, "data": cached_data, "error": None}

            # 调用top_list接口
            df = api.top_list(trade_date=trade_date)

            if df is None or df.empty:
                return {"success": False, "data": None, "error": f"未找到龙虎榜数据: {trade_date}"}

            # 获取股票名称映射
            stock_names = {}
            try:
                basic_df = api.stock_basic(fields="ts_code,name")
                if basic_df is not None and not basic_df.empty:
                    stock_names = dict(zip(basic_df["ts_code"], basic_df["name"]))
            except:
                pass

            # 转换为列表格式
            records = []
            for _, row in df.head(limit).iterrows():
                ts_code = row["ts_code"]
                l_buy = self._safe_float(row.get("l_buy"))
                l_sell = self._safe_float(row.get("l_sell"))
                net_amount = (
                    (l_buy - l_sell)
                    if not isinstance(l_buy, str) and not isinstance(l_sell, str)
                    else "数据缺失"
                )
                records.append(
                    {
                        "trade_date": row["trade_date"],
                        "ts_code": ts_code,
                        "name": stock_names.get(ts_code, ""),
                        "close": self._safe_float(row.get("close")),
                        "pct_chg": self._safe_float(row.get("pct_chg")),
                        "turnover_rate": self._safe_float(row.get("turnover_rate")),
                        "amount": self._safe_float(row.get("amount")),
                        "l_buy": l_buy,
                        "l_sell": l_sell,
                        "net_amount": net_amount,
                        "reason": row.get("reason", ""),
                    }
                )

            # 缓存数据
            self._set_cache(cache_key, records)

            return {
                "success": True,
                "data": records,
                "meta": {"trade_date": trade_date, "count": len(records)},
                "error": None,
            }

        except Exception as e:
            error_msg = str(e).lower()
            if "points" in error_msg or "积分" in error_msg:
                return {
                    "success": False,
                    "data": None,
                    "error": "积分不足，龙虎榜数据需要至少5000积分",
                }
            return {"success": False, "data": None, "error": f"获取龙虎榜数据失败: {str(e)}"}

    def get_money_flow(
        self, symbol: str, trade_date: str = None, start_date: str = None, end_date: str = None
    ) -> dict[str, Any]:
        """
        获取个股资金流向数据

        Args:
            symbol: 股票代码
            trade_date: 交易日期，格式 "YYYYMMDD"
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            资金流向数据字典：
            {
                "success": True/False,
                "data": [
                    {
                        "trade_date": "20260307",
                        "ts_code": "600519.SH",
                        "name": "贵州茅台",
                        "buy_sm_amount": 1000000.00,    # 小单买入金额
                        "sell_sm_amount": 800000.00,    # 小单卖出金额
                        "buy_md_amount": 2000000.00,    # 中单买入金额
                        "sell_md_amount": 1500000.00,   # 中单卖出金额
                        "buy_lg_amount": 3000000.00,    # 大单买入金额
                        "sell_lg_amount": 2000000.00,   # 大单卖出金额
                        "buy_elg_amount": 5000000.00,   # 特大单买入金额
                        "sell_elg_amount": 3000000.00,  # 特大单卖出金额
                        "net_mf_amount": 3700000.00,    # 净流入金额
                        "trade_count": 12500            # 交易笔数
                    },
                    ...
                ],
                "error": None
            }
        """
        api = self.get_api()
        if not api:
            return {
                "success": False,
                "data": None,
                "error": "Tushare API 未初始化，请检查 TUSHARE_API_TOKEN 环境变量",
            }

        try:
            # 标准化股票代码
            ts_code = self._normalize_stock_code(symbol)

            # 构建缓存键
            date_key = trade_date or f"{start_date}_{end_date}"
            cache_key = f"money_flow_{ts_code}_{date_key}"
            cached_data = self._get_from_cache(cache_key)
            if cached_data:
                return {"success": True, "data": cached_data, "error": None}

            # 构建参数
            params = {"ts_code": ts_code}
            if trade_date:
                params["trade_date"] = trade_date
            if start_date:
                params["start_date"] = start_date
            if end_date:
                params["end_date"] = end_date

            # 调用moneyflow接口
            df = api.moneyflow(**params)

            if df is None or df.empty:
                return {"success": False, "data": None, "error": f"未找到资金流向数据: {symbol}"}

            # 获取股票名称
            stock_name = ""
            try:
                basic_df = api.stock_basic(ts_code=ts_code, fields="name")
                if basic_df is not None and not basic_df.empty:
                    stock_name = basic_df.iloc[0]["name"]
            except:
                pass

            # 转换为列表格式
            records = []
            for _, row in df.iterrows():
                records.append(
                    {
                        "trade_date": row["trade_date"],
                        "ts_code": ts_code,
                        "name": stock_name,
                        "buy_sm_amount": self._safe_float(row.get("buy_sm_amount")),
                        "sell_sm_amount": self._safe_float(row.get("sell_sm_amount")),
                        "buy_md_amount": self._safe_float(row.get("buy_md_amount")),
                        "sell_md_amount": self._safe_float(row.get("sell_md_amount")),
                        "buy_lg_amount": self._safe_float(row.get("buy_lg_amount")),
                        "sell_lg_amount": self._safe_float(row.get("sell_lg_amount")),
                        "buy_elg_amount": self._safe_float(row.get("buy_elg_amount")),
                        "sell_elg_amount": self._safe_float(row.get("sell_elg_amount")),
                        "net_mf_amount": self._safe_float(row.get("net_mf_amount")),
                        "trade_count": int(row.get("trade_count", 0))
                        if row.get("trade_count") is not None
                        else "数据缺失",
                    }
                )

            # 缓存数据
            self._set_cache(cache_key, records)

            return {
                "success": True,
                "data": records,
                "meta": {"symbol": ts_code, "count": len(records)},
                "error": None,
            }

        except Exception as e:
            return {"success": False, "data": None, "error": f"获取资金流向数据失败: {str(e)}"}

    def get_limit_list(self, trade_date: str = None, limit_type: str = None) -> dict[str, Any]:
        """
        获取每日涨跌停统计

        Args:
            trade_date: 交易日期，格式 "YYYYMMDD"
            limit_type: 涨跌停类型，可选 "U"(涨停)、"D"(跌停)，默认全部

        Returns:
            涨跌停统计字典：
            {
                "success": True/False,
                "data": [
                    {
                        "trade_date": "20260307",
                        "ts_code": "600519.SH",
                        "name": "贵州茅台",
                        "name": "贵州茅台",
                        "close": 1850.50,
                        "pre_close": 1682.27,
                        "pct_chg": 10.00,
                        "amount": 1250000000.00,
                        "limit_amount": 85000000.00,
                        "float_mv": 2325000000000.00,
                        "total_mv": 2325000000000.00,
                        "turnover_ratio": 0.53,
                        "fd_amount": 32000000.00,       # 封单金额
                        "first_time": "09:30:00",       # 首次涨停时间
                        "last_time": "15:00:00",        # 最后涨停时间
                        "open_times": 0,                # 打开次数
                        "up_stat": "U",                 # 涨跌停状态
                        "limit_type": "T"               # 涨停类型
                    },
                    ...
                ],
                "error": None
            }
        """
        api = self.get_api()
        if not api:
            return {
                "success": False,
                "data": None,
                "error": "Tushare API 未初始化，请检查 TUSHARE_API_TOKEN 环境变量",
            }

        try:
            # 构建缓存键
            cache_key = f"limit_list_{trade_date or 'latest'}_{limit_type or 'all'}"
            cached_data = self._get_from_cache(cache_key)
            if cached_data:
                return {"success": True, "data": cached_data, "error": None}

            # 构建参数 - 第三方代理只支持最新一天数据，不传trade_date
            params = {}
            if trade_date:
                params["trade_date"] = trade_date
            if limit_type:
                params["limit_type"] = limit_type

            # 调用limit_list接口
            df = api.limit_list(**params)

            if df is None or df.empty:
                return {"success": False, "data": None, "error": f"未找到涨跌停数据: {trade_date}"}

            # 获取股票名称映射
            stock_names = {}
            try:
                ts_codes = df["ts_code"].tolist()
                basic_df = api.stock_basic(fields="ts_code,name")
                if basic_df is not None and not basic_df.empty:
                    stock_names = dict(zip(basic_df["ts_code"], basic_df["name"]))
            except:
                pass

            # 转换为列表格式
            records = []
            for _, row in df.iterrows():
                ts_code = row["ts_code"]
                record = {
                    "trade_date": row["trade_date"],
                    "ts_code": ts_code,
                    "name": stock_names.get(ts_code, ""),
                    "close": self._safe_float(row.get("close")),
                    "pre_close": self._safe_float(row.get("pre_close")),
                    "pct_chg": self._safe_float(row.get("pct_chg")),
                    "amount": self._safe_float(row.get("amount")),
                    "limit_amount": self._safe_float(row.get("limit_amount")),
                    "float_mv": self._safe_float(row.get("float_mv")),
                    "total_mv": self._safe_float(row.get("total_mv")),
                    "turnover_ratio": self._safe_float(row.get("turnover_ratio")),
                    "fd_amount": self._safe_float(row.get("fd_amount")),
                    "first_time": row.get("first_time", ""),
                    "last_time": row.get("last_time", ""),
                    "open_times": int(row.get("open_times", 0)),
                    "up_stat": row.get("up_stat", ""),
                    "limit_type": row.get("limit_type", ""),
                }
                records.append(record)

            # 缓存数据
            self._set_cache(cache_key, records)

            return {
                "success": True,
                "data": records,
                "meta": {
                    "trade_date": trade_date,
                    "limit_type": limit_type or "all",
                    "count": len(records),
                    "limit_up_count": sum(1 for r in records if r["up_stat"] == "U"),
                    "limit_down_count": sum(1 for r in records if r["up_stat"] == "D"),
                },
                "error": None,
            }

        except Exception as e:
            return {"success": False, "data": None, "error": f"获取涨跌停数据失败: {str(e)}"}

    def get_stock_company_info(self, symbol: str) -> dict[str, Any]:
        """
        获取上市公司详细信息

        Args:
            symbol: 股票代码

        Returns:
            公司详细信息字典：
            {
                "success": True/False,
                "data": {
                    "ts_code": "600519.SH",
                    "symbol": "600519",
                    "name": "贵州茅台",
                    "fullname": "贵州茅台酒股份有限公司",
                    "enname": "Kweichow Moutai Co., Ltd.",
                    "exchange": "SSE",
                    "curr_type": "CNY",
                    "list_status": "L",
                    "list_date": "20010827",
                    "delist_date": null,
                    "is_hs": "N",
                    "area": "贵州",
                    "industry": "白酒",
                    "province": "贵州",
                    "city": "遵义",
                    "introduction": "公司是国内白酒行业的标志性企业...",
                    "website": "www.moutaichina.com",
                    "email": "moutai@moutaichina.com",
                    "office": "贵州省仁怀市茅台镇"
                },
                "error": None
            }
        """
        api = self.get_api()
        if not api:
            return {
                "success": False,
                "data": None,
                "error": "Tushare API 未初始化，请检查 TUSHARE_API_TOKEN 环境变量",
            }

        try:
            # 标准化股票代码
            ts_code = self._normalize_stock_code(symbol)

            # 构建缓存键
            cache_key = f"company_info_{ts_code}"
            cached_data = self._get_from_cache(cache_key)
            if cached_data:
                return {"success": True, "data": cached_data, "error": None}

            # 调用stock_company接口获取详细信息
            df = api.stock_company(ts_code=ts_code)

            if df is None or df.empty:
                return {"success": False, "data": None, "error": f"未找到公司信息: {symbol}"}

            # 获取基础信息补充
            basic_df = api.stock_basic(ts_code=ts_code)
            basic_info = {}
            if basic_df is not None and not basic_df.empty:
                basic_row = basic_df.iloc[0]
                basic_info = {
                    "area": basic_row.get("area", ""),
                    "industry": basic_row.get("industry", ""),
                    "list_date": basic_row.get("list_date", ""),
                }

            # 构造返回数据
            row = df.iloc[0]
            company_data = {
                "ts_code": ts_code,
                "symbol": row.get("symbol", ""),
                "name": row.get("name", ""),
                "fullname": row.get("fullname", ""),
                "enname": row.get("enname", ""),
                "exchange": row.get("exchange", ""),
                "curr_type": row.get("curr_type", ""),
                "list_status": row.get("list_status", ""),
                "list_date": basic_info.get("list_date", row.get("list_date", "")),
                "delist_date": row.get("delist_date") if pd.notna(row.get("delist_date")) else None,
                "is_hs": row.get("is_hs", ""),
                "area": basic_info.get("area", row.get("area", "")),
                "industry": basic_info.get("industry", row.get("industry", "")),
                "province": row.get("province", ""),
                "city": row.get("city", ""),
                "introduction": row.get("introduction", ""),
                "website": row.get("website", ""),
                "email": row.get("email", ""),
                "office": row.get("office", ""),
            }

            # 缓存数据
            self._set_cache(cache_key, company_data)

            return {"success": True, "data": company_data, "error": None}

        except Exception as e:
            return {"success": False, "data": None, "error": f"获取公司信息失败: {str(e)}"}


# 单例获取函数
_client_instance: TushareClient | None = None


def get_tushare_client() -> TushareClient:
    """
    获取 Tushare 客户端单例

    Returns:
        TushareClient 实例
    """
    global _client_instance
    if _client_instance is None:
        _client_instance = TushareClient()
    return _client_instance


# ==================== Tier 2 API 实现 ====================


def get_daily_basic(self, symbol: str = None, trade_date: str = None) -> dict[str, Any]:
    """
    获取每日指标数据（PE、PB、换手率、市值等）

    Args:
        symbol: 股票代码，可选，不提供则返回全市场
        trade_date: 交易日期，格式 "YYYYMMDD"，默认最近交易日

    Returns:
        每日指标数据字典：
        {
            "success": True/False,
            "data": [
                {
                    "ts_code": "600519.SH",
                    "trade_date": "20250314",
                    "close": 1850.50,
                    "turnover_rate": 0.53,
                    "turnover_rate_f": 0.48,
                    "volume_ratio": 1.25,
                    "pe": 35.5,
                    "pe_ttm": 32.8,
                    "pb": 12.3,
                    "ps": 15.2,
                    "ps_ttm": 14.8,
                    "dv_ratio": 1.2,
                    "dv_ttm": 1.3,
                    "total_share": 1256000000,
                    "float_share": 1256000000,
                    "free_share": 1256000000,
                    "total_mv": 2325000000000.00,
                    "circ_mv": 2325000000000.00
                }
            ],
            "error": None
        }
    """
    api = self.get_api()
    if not api:
        return {
            "success": False,
            "data": None,
            "error": "Tushare API 未初始化，请检查 TUSHARE_API_TOKEN 环境变量",
        }

    try:
        # 设置默认日期
        if not trade_date:
            trade_date = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")

        # 构建参数
        params = {"trade_date": trade_date}
        if symbol:
            params["ts_code"] = self._normalize_stock_code(symbol)

        # 构建缓存键
        cache_key = f"daily_basic_{params.get('ts_code', 'all')}_{trade_date}"
        cached_data = self._get_from_cache(cache_key)
        if cached_data:
            return {"success": True, "data": cached_data, "error": None}

        # 调用 daily_basic 接口
        df = api.daily_basic(**params)

        if df is None or df.empty:
            return {
                "success": False,
                "data": None,
                "error": f"未找到每日指标数据: {symbol or '全市场'}",
            }

        # 转换为列表格式
        records = []
        for _, row in df.iterrows():
            records.append(
                {
                    "ts_code": row.get("ts_code", ""),
                    "trade_date": row.get("trade_date", ""),
                    "close": self._safe_float(row.get("close")),
                    "turnover_rate": self._safe_float(row.get("turnover_rate")),
                    "turnover_rate_f": self._safe_float(row.get("turnover_rate_f")),
                    "volume_ratio": self._safe_float(row.get("volume_ratio")),
                    "pe": self._safe_float(row.get("pe")),
                    "pe_ttm": self._safe_float(row.get("pe_ttm")),
                    "pb": self._safe_float(row.get("pb")),
                    "ps": self._safe_float(row.get("ps")),
                    "ps_ttm": self._safe_float(row.get("ps_ttm")),
                    "dv_ratio": self._safe_float(row.get("dv_ratio")),
                    "dv_ttm": self._safe_float(row.get("dv_ttm")),
                    "total_share": self._safe_float(row.get("total_share")),
                    "float_share": self._safe_float(row.get("float_share")),
                    "free_share": self._safe_float(row.get("free_share")),
                    "total_mv": self._safe_float(row.get("total_mv")),
                    "circ_mv": self._safe_float(row.get("circ_mv")),
                }
            )

        # 缓存数据
        self._set_cache(cache_key, records)

        return {
            "success": True,
            "data": records,
            "meta": {"trade_date": trade_date, "symbol": symbol, "count": len(records)},
            "error": None,
        }

    except Exception as e:
        error_msg = str(e).lower()
        if "points" in error_msg or "积分" in error_msg:
            return {
                "success": False,
                "data": None,
                "error": "积分不足，daily_basic 需要至少600积分",
            }
        return {"success": False, "data": None, "error": f"获取每日指标数据失败: {str(e)}"}


def get_north_money(self, start_date: str = None, end_date: str = None) -> dict[str, Any]:
    """
    获取沪深港通资金流向（北向资金）

    Args:
        start_date: 开始日期，格式 "YYYYMMDD"
        end_date: 结束日期，格式 "YYYYMMDD"

    Returns:
        北向资金数据字典：
        {
            "success": True/False,
            "data": [
                {
                    "trade_date": "20250314",
                    "ggt_ss": 250000000.00,      # 港股通（上海）
                    "ggt_sz": 180000000.00,      # 港股通（深圳）
                    "hgt": 420000000.00,         # 沪股通
                    "sgt": 380000000.00,         # 深股通
                    "north_money": 800000000.00, # 北向资金合计
                    "south_money": 430000000.00  # 南向资金合计
                }
            ],
            "error": None
        }
    """
    api = self.get_api()
    if not api:
        return {
            "success": False,
            "data": None,
            "error": "Tushare API 未初始化，请检查 TUSHARE_API_TOKEN 环境变量",
        }

    try:
        # 设置默认日期范围
        if not end_date:
            end_date = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
        if not start_date:
            start_dt = datetime.strptime(end_date, "%Y%m%d") - timedelta(days=30)
            start_date = start_dt.strftime("%Y%m%d")

        # 构建缓存键
        cache_key = f"north_money_{start_date}_{end_date}"
        cached_data = self._get_from_cache(cache_key)
        if cached_data:
            return {"success": True, "data": cached_data, "error": None}

        # 调用 moneyflow_hsgt 接口
        df = api.moneyflow_hsgt(start_date=start_date, end_date=end_date)

        if df is None or df.empty:
            return {"success": False, "data": None, "error": "未找到北向资金数据"}

        # 转换为列表格式
        records = []
        for _, row in df.iterrows():
            records.append(
                {
                    "trade_date": row.get("trade_date", ""),
                    "ggt_ss": self._safe_float(row.get("ggt_ss")),
                    "ggt_sz": self._safe_float(row.get("ggt_sz")),
                    "hgt": self._safe_float(row.get("hgt")),
                    "sgt": self._safe_float(row.get("sgt")),
                    "north_money": self._safe_float(row.get("north_money")),
                    "south_money": self._safe_float(row.get("south_money")),
                }
            )

        # 缓存数据
        self._set_cache(cache_key, records)

        return {
            "success": True,
            "data": records,
            "meta": {
                "start_date": start_date,
                "end_date": end_date,
                "count": len(records),
                "total_north": sum(r["north_money"] for r in records),
            },
            "error": None,
        }

    except Exception as e:
        return {"success": False, "data": None, "error": f"获取北向资金数据失败: {str(e)}"}


def get_margin(
    self, symbol: str = None, start_date: str = None, end_date: str = None
) -> dict[str, Any]:
    """
    获取融资融券数据

    Args:
        symbol: 股票代码，可选
        start_date: 开始日期，格式 "YYYYMMDD"
        end_date: 结束日期，格式 "YYYYMMDD"

    Returns:
        融资融券数据字典：
        {
            "success": True/False,
            "data": [
                {
                    "trade_date": "20250314",
                    "ts_code": "600519.SH",
                    "rzye": 1200000000.00,      # 融资余额
                    "rqye": 80000000.00,        # 融券余额
                    "rzrqye": 1280000000.00,    # 融资融券余额
                    "rzmre": 50000000.00,       # 融资买入额
                    "rqyl": 100000.00           # 融券余量
                }
            ],
            "error": None
        }
    """
    api = self.get_api()
    if not api:
        return {
            "success": False,
            "data": None,
            "error": "Tushare API 未初始化，请检查 TUSHARE_API_TOKEN 环境变量",
        }

    try:
        # 设置默认日期范围
        if not end_date:
            end_date = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
        if not start_date:
            start_dt = datetime.strptime(end_date, "%Y%m%d") - timedelta(days=30)
            start_date = start_dt.strftime("%Y%m%d")

        # 构建参数
        params = {"start_date": start_date, "end_date": end_date}
        if symbol:
            params["ts_code"] = self._normalize_stock_code(symbol)

        # 构建缓存键
        cache_key = f"margin_{params.get('ts_code', 'all')}_{start_date}_{end_date}"
        cached_data = self._get_from_cache(cache_key)
        if cached_data:
            return {"success": True, "data": cached_data, "error": None}

        # 调用 margin 接口
        df = api.margin(**params)

        if df is None or df.empty:
            return {
                "success": False,
                "data": None,
                "error": f"未找到融资融券数据: {symbol or '全市场'}",
            }

        # 转换为列表格式
        records = []
        for _, row in df.iterrows():
            records.append(
                {
                    "trade_date": row.get("trade_date", ""),
                    "ts_code": row.get("ts_code", ""),
                    "rzye": self._safe_float(row.get("rzye")),
                    "rqye": self._safe_float(row.get("rqye")),
                    "rzrqye": self._safe_float(row.get("rzrqye")),
                    "rzmre": self._safe_float(row.get("rzmre")),
                    "rqyl": self._safe_float(row.get("rqyl")),
                }
            )

        # 缓存数据
        self._set_cache(cache_key, records)

        return {
            "success": True,
            "data": records,
            "meta": {
                "symbol": symbol,
                "start_date": start_date,
                "end_date": end_date,
                "count": len(records),
            },
            "error": None,
        }

    except Exception as e:
        error_msg = str(e).lower()
        if "points" in error_msg or "积分" in error_msg:
            return {"success": False, "data": None, "error": "积分不足，margin 需要至少800积分"}
        return {"success": False, "data": None, "error": f"获取融资融券数据失败: {str(e)}"}


# 将新方法绑定到类
TushareClient.get_daily_basic = get_daily_basic
TushareClient.get_north_money = get_north_money
TushareClient.get_margin = get_margin


# ==================== 财务数据 API ====================


def get_income_statement(
    self, symbol: str, start_date: str = None, end_date: str = None
) -> dict[str, Any]:
    """
    获取利润表数据

    Args:
        symbol: 股票代码
        start_date: 开始日期，格式 "YYYYMMDD"
        end_date: 结束日期，格式 "YYYYMMDD"

    Returns:
        利润表数据字典
    """
    api = self.get_api()
    if not api:
        return {
            "success": False,
            "data": None,
            "error": "Tushare API 未初始化，请检查 TUSHARE_API_TOKEN 环境变量",
        }

    try:
        ts_code = self._normalize_stock_code(symbol)

        # 设置默认日期范围
        if not end_date:
            end_date = datetime.now().strftime("%Y%m%d")
        if not start_date:
            start_dt = datetime.strptime(end_date, "%Y%m%d") - timedelta(days=365 * 3)
            start_date = start_dt.strftime("%Y%m%d")

        # 构建缓存键
        cache_key = f"income_{ts_code}_{start_date}_{end_date}"
        cached_data = self._get_from_cache(cache_key)
        if cached_data:
            return {"success": True, "data": cached_data, "error": None}

        # 调用 income 接口
        df = api.income(ts_code=ts_code, start_date=start_date, end_date=end_date)

        if df is None or df.empty:
            return {"success": False, "data": None, "error": f"未找到利润表数据: {symbol}"}

        # 转换为列表格式
        records = []
        for _, row in df.iterrows():
            records.append(
                {
                    "ts_code": row.get("ts_code", ""),
                    "ann_date": row.get("ann_date", ""),
                    "f_ann_date": row.get("f_ann_date", ""),
                    "end_date": row.get("end_date", ""),
                    "comp_type": row.get("comp_type", ""),
                    "basic_eps": self._safe_float(row.get("basic_eps")),
                    "diluted_eps": self._safe_float(row.get("diluted_eps")),
                    "total_revenue": self._safe_float(row.get("total_revenue")),
                    "revenue": self._safe_float(row.get("revenue")),
                    "total_cogs": self._safe_float(row.get("total_cogs")),
                    "oper_cost": self._safe_float(row.get("oper_cost")),
                    "sell_exp": self._safe_float(row.get("sell_exp")),
                    "admin_exp": self._safe_float(row.get("admin_exp")),
                    "fin_exp": self._safe_float(row.get("fin_exp")),
                    "operate_profit": self._safe_float(row.get("operate_profit")),
                    "total_profit": self._safe_float(row.get("total_profit")),
                    "income_tax": self._safe_float(row.get("income_tax")),
                    "n_income": self._safe_float(row.get("n_income")),
                    "n_income_attr_p": self._safe_float(row.get("n_income_attr_p")),
                }
            )

        # 缓存数据
        self._set_cache(cache_key, records)

        return {
            "success": True,
            "data": records,
            "meta": {"symbol": ts_code, "count": len(records)},
            "error": None,
        }

    except Exception as e:
        error_msg = str(e).lower()
        if "points" in error_msg or "积分" in error_msg:
            return {"success": False, "data": None, "error": "积分不足，income 需要至少800积分"}
        return {"success": False, "data": None, "error": f"获取利润表数据失败: {str(e)}"}


def get_balance_sheet(
    self, symbol: str, start_date: str = None, end_date: str = None
) -> dict[str, Any]:
    """
    获取资产负债表数据

    Args:
        symbol: 股票代码
        start_date: 开始日期，格式 "YYYYMMDD"
        end_date: 结束日期，格式 "YYYYMMDD"

    Returns:
        资产负债表数据字典
    """
    api = self.get_api()
    if not api:
        return {
            "success": False,
            "data": None,
            "error": "Tushare API 未初始化，请检查 TUSHARE_API_TOKEN 环境变量",
        }

    try:
        ts_code = self._normalize_stock_code(symbol)

        # 设置默认日期范围
        if not end_date:
            end_date = datetime.now().strftime("%Y%m%d")
        if not start_date:
            start_dt = datetime.strptime(end_date, "%Y%m%d") - timedelta(days=365 * 3)
            start_date = start_dt.strftime("%Y%m%d")

        # 构建缓存键
        cache_key = f"balance_sheet_{ts_code}_{start_date}_{end_date}"
        cached_data = self._get_from_cache(cache_key)
        if cached_data:
            return {"success": True, "data": cached_data, "error": None}

        # 调用 balancesheet 接口
        df = api.balancesheet(ts_code=ts_code, start_date=start_date, end_date=end_date)

        if df is None or df.empty:
            return {"success": False, "data": None, "error": f"未找到资产负债表数据: {symbol}"}

        # 转换为列表格式
        records = []
        for _, row in df.iterrows():
            records.append(
                {
                    "ts_code": row.get("ts_code", ""),
                    "ann_date": row.get("ann_date", ""),
                    "f_ann_date": row.get("f_ann_date", ""),
                    "end_date": row.get("end_date", ""),
                    "comp_type": row.get("comp_type", ""),
                    "total_assets": self._safe_float(row.get("total_assets")),
                    "total_liab": self._safe_float(row.get("total_liab")),
                    "total_hldr_eqy_exc_min_int": self._safe_float(
                        row.get("total_hldr_eqy_exc_min_int")
                    ),
                    "total_hldr_eqy_inc_min_int": self._safe_float(
                        row.get("total_hldr_eqy_inc_min_int")
                    ),
                    "total_cur_assets": self._safe_float(row.get("total_cur_assets")),
                    "total_cur_liab": self._safe_float(row.get("total_cur_liab")),
                    "total_nca": self._safe_float(row.get("total_nca")),
                    "total_ncl": self._safe_float(row.get("total_ncl")),
                    "fix_assets": self._safe_float(row.get("fix_assets")),
                    "intan_assets": self._safe_float(row.get("intan_assets")),
                    "inventories": self._safe_float(row.get("inventories")),
                    "accounts_receiv": self._safe_float(row.get("accounts_receiv")),
                    "notes_receiv": self._safe_float(row.get("notes_receiv")),
                    "prepayment": self._safe_float(row.get("prepayment")),
                    "acct_payable": self._safe_float(row.get("acct_payable")),
                }
            )

        # 缓存数据
        self._set_cache(cache_key, records)

        return {
            "success": True,
            "data": records,
            "meta": {"symbol": ts_code, "count": len(records)},
            "error": None,
        }

    except Exception as e:
        error_msg = str(e).lower()
        if "points" in error_msg or "积分" in error_msg:
            return {
                "success": False,
                "data": None,
                "error": "积分不足，balance_sheet 需要至少800积分",
            }
        return {"success": False, "data": None, "error": f"获取资产负债表数据失败: {str(e)}"}


def get_cash_flow(
    self, symbol: str, start_date: str = None, end_date: str = None
) -> dict[str, Any]:
    """
    获取现金流量表数据

    Args:
        symbol: 股票代码
        start_date: 开始日期，格式 "YYYYMMDD"
        end_date: 结束日期，格式 "YYYYMMDD"

    Returns:
        现金流量表数据字典
    """
    api = self.get_api()
    if not api:
        return {
            "success": False,
            "data": None,
            "error": "Tushare API 未初始化，请检查 TUSHARE_API_TOKEN 环境变量",
        }

    try:
        ts_code = self._normalize_stock_code(symbol)

        # 设置默认日期范围
        if not end_date:
            end_date = datetime.now().strftime("%Y%m%d")
        if not start_date:
            start_dt = datetime.strptime(end_date, "%Y%m%d") - timedelta(days=365 * 3)
            start_date = start_dt.strftime("%Y%m%d")

        # 构建缓存键
        cache_key = f"cash_flow_{ts_code}_{start_date}_{end_date}"
        cached_data = self._get_from_cache(cache_key)
        if cached_data:
            return {"success": True, "data": cached_data, "error": None}

        # 调用 cashflow 接口
        df = api.cashflow(ts_code=ts_code, start_date=start_date, end_date=end_date)

        if df is None or df.empty:
            return {"success": False, "data": None, "error": f"未找到现金流量表数据: {symbol}"}

        # 转换为列表格式
        records = []
        for _, row in df.iterrows():
            records.append(
                {
                    "ts_code": row.get("ts_code", ""),
                    "ann_date": row.get("ann_date", ""),
                    "f_ann_date": row.get("f_ann_date", ""),
                    "end_date": row.get("end_date", ""),
                    "comp_type": row.get("comp_type", ""),
                    "n_cashflow_act": self._safe_float(row.get("n_cashflow_act")),
                    "c_inf_fr_operate_a": self._safe_float(row.get("c_inf_fr_operate_a")),
                    "c_paid_to_for_empl_a": self._safe_float(row.get("c_paid_to_for_empl_a")),
                    "c_paid_for_taxes": self._safe_float(row.get("c_paid_for_taxes")),
                    "n_cashflows_inv_act": self._safe_float(row.get("n_cashflows_inv_act")),
                    "c_recp_return_invest": self._safe_float(row.get("c_recp_return_invest")),
                    "c_invest_paid": self._safe_float(row.get("c_invest_paid")),
                    "n_cashflows_fnc_act": self._safe_float(row.get("n_cashflows_fnc_act")),
                    "c_recp_borrow": self._safe_float(row.get("c_recp_borrow")),
                    "c_prepay_amt_borr": self._safe_float(row.get("c_prepay_amt_borr")),
                    "c_pay_dist_dpcp_int_exp": self._safe_float(row.get("c_pay_dist_dpcp_int_exp")),
                    "free_cash_flow": self._safe_float(row.get("free_cash_flow")),
                }
            )

        # 缓存数据
        self._set_cache(cache_key, records)

        return {
            "success": True,
            "data": records,
            "meta": {"symbol": ts_code, "count": len(records)},
            "error": None,
        }

    except Exception as e:
        error_msg = str(e).lower()
        if "points" in error_msg or "积分" in error_msg:
            return {"success": False, "data": None, "error": "积分不足，cashflow 需要至少800积分"}
        return {"success": False, "data": None, "error": f"获取现金流量表数据失败: {str(e)}"}


def get_fina_indicator(
    self, symbol: str, start_date: str = None, end_date: str = None
) -> dict[str, Any]:
    """
    获取财务指标数据（一站式财务指标）

    Args:
        symbol: 股票代码
        start_date: 开始日期，格式 "YYYYMMDD"
        end_date: 结束日期，格式 "YYYYMMDD"

    Returns:
        财务指标数据字典
    """
    api = self.get_api()
    if not api:
        return {
            "success": False,
            "data": None,
            "error": "Tushare API 未初始化，请检查 TUSHARE_API_TOKEN 环境变量",
        }

    try:
        ts_code = self._normalize_stock_code(symbol)

        # 设置默认日期范围
        if not end_date:
            end_date = datetime.now().strftime("%Y%m%d")
        if not start_date:
            start_dt = datetime.strptime(end_date, "%Y%m%d") - timedelta(days=365 * 3)
            start_date = start_dt.strftime("%Y%m%d")

        # 构建缓存键
        cache_key = f"fina_indicator_{ts_code}_{start_date}_{end_date}"
        cached_data = self._get_from_cache(cache_key)
        if cached_data:
            return {"success": True, "data": cached_data, "error": None}

        # 调用 fina_indicator 接口
        df = api.fina_indicator(ts_code=ts_code, start_date=start_date, end_date=end_date)

        if df is None or df.empty:
            return {"success": False, "data": None, "error": f"未找到财务指标数据: {symbol}"}

        # 转换为列表格式
        records = []
        for _, row in df.iterrows():
            records.append(
                {
                    "ts_code": row.get("ts_code", ""),
                    "ann_date": row.get("ann_date", ""),
                    "end_date": row.get("end_date", ""),
                    "eps": self._safe_float(row.get("eps")),
                    "dt_eps": self._safe_float(row.get("dt_eps")),
                    "total_revenue_ps": self._safe_float(row.get("total_revenue_ps")),
                    "revenue_ps": self._safe_float(row.get("revenue_ps")),
                    "capital_rese_ps": self._safe_float(row.get("capital_rese_ps")),
                    "surplus_rese_ps": self._safe_float(row.get("surplus_rese_ps")),
                    "undist_profit_ps": self._safe_float(row.get("undist_profit_ps")),
                    "extra_item": self._safe_float(row.get("extra_item")),
                    "profit_dedt": self._safe_float(row.get("profit_dedt")),
                    "gross_margin": self._safe_float(row.get("gross_margin")),
                    "current_ratio": self._safe_float(row.get("current_ratio")),
                    "quick_ratio": self._safe_float(row.get("quick_ratio")),
                    "cash_ratio": self._safe_float(row.get("cash_ratio")),
                    "invturn_days": self._safe_float(row.get("invturn_days")),
                    "arturn_days": self._safe_float(row.get("arturn_days")),
                    "inv_turn": self._safe_float(row.get("inv_turn")),
                    "ar_turn": self._safe_float(row.get("ar_turn")),
                    "assets_turn": self._safe_float(row.get("assets_turn")),
                    "roe": self._safe_float(row.get("roe")),
                    "roe_waa": self._safe_float(row.get("roe_waa")),
                    "roe_dt": self._safe_float(row.get("roe_dt")),
                    "roa": self._safe_float(row.get("roa")),
                    "npta": self._safe_float(row.get("npta")),
                    "roic": self._safe_float(row.get("roic")),
                    "roe_yearly": self._safe_float(row.get("roe_yearly")),
                    "roa2_yearly": self._safe_float(row.get("roa2_yearly")),
                    "debt_to_assets": self._safe_float(row.get("debt_to_assets")),
                    "assets_to_eqt": self._safe_float(row.get("assets_to_eqt")),
                    "dp_assets_to_eqt": self._safe_float(row.get("dp_assets_to_eqt")),
                    "ca_to_assets": self._safe_float(row.get("ca_to_assets")),
                    "nca_to_assets": self._safe_float(row.get("nca_to_assets")),
                    "tbassets_to_totalassets": self._safe_float(row.get("tbassets_to_totalassets")),
                    "int_to_talcap": self._safe_float(row.get("int_to_talcap")),
                    "eqt_to_talcapital": self._safe_float(row.get("eqt_to_talcapital")),
                    "currentdebt_to_debt": self._safe_float(row.get("currentdebt_to_debt")),
                    "longdeb_to_debt": self._safe_float(row.get("longdeb_to_debt")),
                    "ocf_to_shortdebt": self._safe_float(row.get("ocf_to_shortdebt")),
                    "debt_to_eqt": self._safe_float(row.get("debt_to_eqt")),
                    "eqt_to_debt": self._safe_float(row.get("eqt_to_debt")),
                    "eqt_to_interestdebt": self._safe_float(row.get("eqt_to_interestdebt")),
                    "tangibleasset_to_debt": self._safe_float(row.get("tangibleasset_to_debt")),
                    "tangasset_to_intdebt": self._safe_float(row.get("tangasset_to_intdebt")),
                    "tangibleasset_to_netdebt": self._safe_float(
                        row.get("tangibleasset_to_netdebt")
                    ),
                    "ocf_to_debt": self._safe_float(row.get("ocf_to_debt")),
                    "ocf_to_interestdebt": self._safe_float(row.get("ocf_to_interestdebt")),
                    "ocf_to_netdebt": self._safe_float(row.get("ocf_to_netdebt")),
                    "ebit_to_interest": self._safe_float(row.get("ebit_to_interest")),
                    "longdebt_to_workingcapital": self._safe_float(
                        row.get("longdebt_to_workingcapital")
                    ),
                    "ebitda_to_debt": self._safe_float(row.get("ebitda_to_debt")),
                    "turn_days": self._safe_float(row.get("turn_days")),
                    "roa_yearly": self._safe_float(row.get("roa_yearly")),
                    "roa_dp": self._safe_float(row.get("roa_dp")),
                    "fixed_assets": self._safe_float(row.get("fixed_assets")),
                    "profit_prefin_exp": self._safe_float(row.get("profit_prefin_exp")),
                    "non_op_profit": self._safe_float(row.get("non_op_profit")),
                    "op_to_ebt": self._safe_float(row.get("op_to_ebt")),
                    "nop_to_ebt": self._safe_float(row.get("nop_to_ebt")),
                    "ocf_to_profit": self._safe_float(row.get("ocf_to_profit")),
                    "cash_to_liqdebt": self._safe_float(row.get("cash_to_liqdebt")),
                    "cash_to_liqdebt_withinterest": self._safe_float(
                        row.get("cash_to_liqdebt_withinterest")
                    ),
                    "op_to_liqdebt": self._safe_float(row.get("op_to_liqdebt")),
                    "op_to_debt": self._safe_float(row.get("op_to_debt")),
                    "roe_to_eqt": self._safe_float(row.get("roe_to_eqt")),
                    "saleexp_to_gr": self._safe_float(row.get("saleexp_to_gr")),
                    "adminexp_of_gr": self._safe_float(row.get("adminexp_of_gr")),
                    "finaexp_of_gr": self._safe_float(row.get("finaexp_of_gr")),
                    "impai_ttm": self._safe_float(row.get("impai_ttm")),
                    "op_of_gr": self._safe_float(row.get("op_of_gr")),
                    "ebit_of_gr": self._safe_float(row.get("ebit_of_gr")),
                    "roe_yoy": self._safe_float(row.get("roe_yoy")),
                    "dt_roe_yoy": self._safe_float(row.get("dt_roe_yoy")),
                    "op_yoy": self._safe_float(row.get("op_yoy")),
                    "ebt_yoy": self._safe_float(row.get("ebt_yoy")),
                    "netprofit_yoy": self._safe_float(row.get("netprofit_yoy")),
                    "dt_netprofit_yoy": self._safe_float(row.get("dt_netprofit_yoy")),
                    "ocf_yoy": self._safe_float(row.get("ocf_yoy")),
                    "roe_avg": self._safe_float(row.get("roe_avg")),
                    "q_sales_yoy": self._safe_float(row.get("q_sales_yoy")),
                    "q_sales_qoq": self._safe_float(row.get("q_sales_qoq")),
                    "q_op_yoy": self._safe_float(row.get("q_op_yoy")),
                    "q_op_qoq": self._safe_float(row.get("q_op_qoq")),
                    "q_profit_yoy": self._safe_float(row.get("q_profit_yoy")),
                    "q_profit_qoq": self._safe_float(row.get("q_profit_qoq")),
                    "q_netprofit_yoy": self._safe_float(row.get("q_netprofit_yoy")),
                    "q_netprofit_qoq": self._safe_float(row.get("q_netprofit_qoq")),
                    "equity_yoy": self._safe_float(row.get("equity_yoy")),
                    "rd_exp": self._safe_float(row.get("rd_exp")),
                }
            )

        # 缓存数据
        self._set_cache(cache_key, records)

        return {
            "success": True,
            "data": records,
            "meta": {"symbol": ts_code, "count": len(records)},
            "error": None,
        }

    except Exception as e:
        error_msg = str(e).lower()
        if "points" in error_msg or "积分" in error_msg:
            return {
                "success": False,
                "data": None,
                "error": "积分不足，fina_indicator 需要至少1200积分",
            }
        return {"success": False, "data": None, "error": f"获取财务指标数据失败: {str(e)}"}


# 绑定财务数据方法
TushareClient.get_income_statement = get_income_statement
TushareClient.get_balance_sheet = get_balance_sheet
TushareClient.get_cash_flow = get_cash_flow
TushareClient.get_fina_indicator = get_fina_indicator


# ==================== 行业概念 API ====================


def get_industry_list(self) -> dict[str, Any]:
    """
    获取行业分类列表

    Returns:
        行业分类数据字典
    """
    api = self.get_api()
    if not api:
        return {
            "success": False,
            "data": None,
            "error": "Tushare API 未初始化，请检查 TUSHARE_API_TOKEN 环境变量",
        }

    try:
        # 构建缓存键
        cache_key = "industry_list"
        cached_data = self._get_from_cache(cache_key)
        if cached_data:
            return {"success": True, "data": cached_data, "error": None}

        # 调用 stock_basic 接口获取行业信息
        df = api.stock_basic(fields="ts_code,name,industry")

        if df is None or df.empty:
            return {"success": False, "data": None, "error": "未找到行业数据"}

        # 提取唯一行业列表
        industries = df["industry"].dropna().unique().tolist()
        industries = [ind for ind in industries if ind]
        industries.sort()

        # 构建行业数据
        industry_data = []
        for ind in industries:
            count = len(df[df["industry"] == ind])
            industry_data.append({"name": ind, "stock_count": count})

        # 缓存数据
        self._set_cache(cache_key, industry_data)

        return {
            "success": True,
            "data": industry_data,
            "meta": {"count": len(industry_data)},
            "error": None,
        }

    except Exception as e:
        return {"success": False, "data": None, "error": f"获取行业列表失败: {str(e)}"}


def get_concept_list(self) -> dict[str, Any]:
    """
    获取概念分类列表

    Returns:
        概念分类数据字典
    """
    api = self.get_api()
    if not api:
        return {
            "success": False,
            "data": None,
            "error": "Tushare API 未初始化，请检查 TUSHARE_API_TOKEN 环境变量",
        }

    try:
        # 构建缓存键
        cache_key = "concept_list"
        cached_data = self._get_from_cache(cache_key)
        if cached_data:
            return {"success": True, "data": cached_data, "error": None}

        # 调用 concept 接口
        df = api.concept()

        if df is None or df.empty:
            return {"success": False, "data": None, "error": "未找到概念数据"}

        # 转换为列表格式
        records = []
        for _, row in df.iterrows():
            records.append(
                {
                    "code": row.get("code", ""),
                    "name": row.get("name", ""),
                    "src": row.get("src", ""),
                }
            )

        # 缓存数据
        self._set_cache(cache_key, records)

        return {"success": True, "data": records, "meta": {"count": len(records)}, "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": f"获取概念列表失败: {str(e)}"}


def get_concept_stocks(self, concept_code: str = None, concept_name: str = None) -> dict[str, Any]:
    """
    获取概念成分股

    Args:
        concept_code: 概念代码
        concept_name: 概念名称（可选，用于搜索）

    Returns:
        概念成分股数据字典
    """
    api = self.get_api()
    if not api:
        return {
            "success": False,
            "data": None,
            "error": "Tushare API 未初始化，请检查 TUSHARE_API_TOKEN 环境变量",
        }

    try:
        if not concept_code:
            # 如果提供了概念名称，先查找对应的代码
            if concept_name:
                concepts_df = api.concept()
                if concepts_df is not None and not concepts_df.empty:
                    match = concepts_df[concepts_df["name"].str.contains(concept_name, na=False)]
                    if not match.empty:
                        concept_code = match.iloc[0]["code"]
                    else:
                        return {
                            "success": False,
                            "data": None,
                            "error": f"未找到概念: {concept_name}",
                        }
            else:
                return {"success": False, "data": None, "error": "请提供概念代码或概念名称"}

        # 构建缓存键
        cache_key = f"concept_stocks_{concept_code}"
        cached_data = self._get_from_cache(cache_key)
        if cached_data:
            return {"success": True, "data": cached_data, "error": None}

        # 调用 concept_detail 接口
        df = api.concept_detail(id=concept_code)

        if df is None or df.empty:
            return {"success": False, "data": None, "error": f"未找到概念成分股: {concept_code}"}

        # 获取股票名称
        stock_names = {}
        try:
            ts_codes = df["ts_code"].tolist()
            basic_df = api.stock_basic(fields="ts_code,name")
            if basic_df is not None and not basic_df.empty:
                stock_names = dict(zip(basic_df["ts_code"], basic_df["name"]))
        except:
            pass

        # 转换为列表格式
        records = []
        for _, row in df.iterrows():
            ts_code = row.get("ts_code", "")
            records.append(
                {
                    "id": row.get("id", ""),
                    "concept_name": row.get("concept_name", ""),
                    "ts_code": ts_code,
                    "name": stock_names.get(ts_code, ""),
                    "in_date": row.get("in_date", ""),
                    "out_date": row.get("out_date", ""),
                }
            )

        # 缓存数据
        self._set_cache(cache_key, records)

        return {
            "success": True,
            "data": records,
            "meta": {"concept_code": concept_code, "count": len(records)},
            "error": None,
        }

    except Exception as e:
        return {"success": False, "data": None, "error": f"获取概念成分股失败: {str(e)}"}


# 绑定行业概念方法
TushareClient.get_industry_list = get_industry_list
TushareClient.get_concept_list = get_concept_list
TushareClient.get_concept_stocks = get_concept_stocks


# ==================== 行业深度分析 API ====================


def compare_industry_metrics(
    self, industries: list[str] = None, metric: str = "roe"
) -> dict[str, Any]:
    """
    对比不同行业的财务指标

    Args:
        industries: 行业列表，如 ['白酒', '银行', '医药']，不传则对比所有行业
        metric: 对比指标，可选 roe, gross_margin, net_margin, debt_ratio

    Returns:
        行业对比数据字典
    """
    api = self.get_api()
    if not api:
        return {
            "success": False,
            "data": None,
            "error": "Tushare API 未初始化，请检查 TUSHARE_API_TOKEN 环境变量",
        }

    try:
        # 获取所有股票基本信息
        df = api.stock_basic(fields="ts_code,name,industry")
        if df is None or df.empty:
            return {"success": False, "data": None, "error": "无法获取股票基本信息"}

        # 过滤指定行业
        if industries:
            df = df[df["industry"].isin(industries)]

        # 获取财务指标数据
        fina_df = api.fina_indicator(
            fields="ts_code,roe,grossprofit_margin,netprofit_margin,debt_to_assets"
        )
        if fina_df is None or fina_df.empty:
            return {"success": False, "data": None, "error": "无法获取财务指标数据"}

        # 合并数据
        merged = df.merge(fina_df, on="ts_code", how="inner")

        # 按行业聚合计算平均值
        metric_map = {
            "roe": "roe",
            "gross_margin": "grossprofit_margin",
            "net_margin": "netprofit_margin",
            "debt_ratio": "debt_to_assets",
        }
        metric_col = metric_map.get(metric, "roe")

        industry_stats = (
            merged.groupby("industry").agg({metric_col: "mean", "ts_code": "count"}).reset_index()
        )

        industry_stats.columns = ["industry", "avg_value", "stock_count"]
        industry_stats = industry_stats.sort_values("avg_value", ascending=False)

        # 转换为列表
        records = []
        for _, row in industry_stats.iterrows():
            records.append(
                {
                    "industry": row["industry"],
                    "avg_value": round(float(row["avg_value"]), 2),
                    "stock_count": int(row["stock_count"]),
                }
            )

        return {
            "success": True,
            "data": records,
            "meta": {
                "metric": metric,
                "metric_name": {
                    "roe": "净资产收益率",
                    "gross_margin": "毛利率",
                    "net_margin": "净利率",
                    "debt_ratio": "资产负债率",
                }.get(metric, metric),
                "count": len(records),
            },
            "error": None,
        }

    except Exception as e:
        return {"success": False, "data": None, "error": f"行业指标对比失败: {str(e)}"}


def compare_industry_valuation(self, industries: list[str] = None) -> dict[str, Any]:
    """
    对比不同行业的估值水平

    Args:
        industries: 行业列表，不传则对比所有行业

    Returns:
        行业估值对比数据字典
    """
    api = self.get_api()
    if not api:
        return {
            "success": False,
            "data": None,
            "error": "Tushare API 未初始化，请检查 TUSHARE_API_TOKEN 环境变量",
        }

    try:
        # 获取最近交易日
        trade_date = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")

        # 获取每日指标数据
        daily_df = api.daily_basic(trade_date=trade_date, fields="ts_code,pe_ttm,pb,ps_ttm")
        if daily_df is None or daily_df.empty:
            return {"success": False, "data": None, "error": "无法获取估值数据"}

        # 获取股票行业信息
        stock_df = api.stock_basic(fields="ts_code,industry")
        if stock_df is None or stock_df.empty:
            return {"success": False, "data": None, "error": "无法获取股票信息"}

        # 合并数据
        merged = daily_df.merge(stock_df, on="ts_code", how="inner")

        # 过滤指定行业
        if industries:
            merged = merged[merged["industry"].isin(industries)]

        # 过滤有效数据
        merged = merged[(merged["pe_ttm"] > 0) & (merged["pe_ttm"] < 1000)]  # 排除异常值
        merged = merged[(merged["pb"] > 0) & (merged["pb"] < 100)]

        # 按行业聚合
        industry_stats = (
            merged.groupby("industry")
            .agg({"pe_ttm": "median", "pb": "median", "ps_ttm": "median", "ts_code": "count"})
            .reset_index()
        )

        industry_stats.columns = ["industry", "pe_ttm", "pb", "ps_ttm", "stock_count"]
        industry_stats = industry_stats.sort_values("pe_ttm")

        # 转换为列表
        records = []
        for _, row in industry_stats.iterrows():
            records.append(
                {
                    "industry": row["industry"],
                    "pe_ttm": round(float(row["pe_ttm"]), 2) if pd.notna(row["pe_ttm"]) else None,
                    "pb": round(float(row["pb"]), 2) if pd.notna(row["pb"]) else None,
                    "ps_ttm": round(float(row["ps_ttm"]), 2) if pd.notna(row["ps_ttm"]) else None,
                    "stock_count": int(row["stock_count"]),
                }
            )

        return {
            "success": True,
            "data": records,
            "meta": {"trade_date": trade_date, "count": len(records)},
            "error": None,
        }

    except Exception as e:
        return {"success": False, "data": None, "error": f"行业估值对比失败: {str(e)}"}


def get_industry_performance(self, period: str = "1d") -> dict[str, Any]:
    """
    获取行业涨跌幅排名

    Args:
        period: 周期，可选 1d(日), 5d(周), 20d(月)

    Returns:
        行业涨跌幅排名数据
    """
    api = self.get_api()
    if not api:
        return {
            "success": False,
            "data": None,
            "error": "Tushare API 未初始化，请检查 TUSHARE_API_TOKEN 环境变量",
        }

    try:
        # 计算日期范围
        end_date = datetime.now()
        if period == "1d":
            start_date = end_date - timedelta(days=3)  # 最近1个交易日
        elif period == "5d":
            start_date = end_date - timedelta(days=7)
        elif period == "20d":
            start_date = end_date - timedelta(days=30)
        else:
            start_date = end_date - timedelta(days=3)

        # 获取股票行情数据
        df = api.daily(
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
            fields="ts_code,close,pct_chg",
        )

        if df is None or df.empty:
            return {"success": False, "data": None, "error": "无法获取行情数据"}

        # 获取股票行业信息
        stock_df = api.stock_basic(fields="ts_code,industry")
        if stock_df is None or stock_df.empty:
            return {"success": False, "data": None, "error": "无法获取股票信息"}

        # 合并数据
        merged = df.merge(stock_df, on="ts_code", how="inner")

        # 按行业计算平均涨跌幅
        industry_perf = (
            merged.groupby("industry").agg({"pct_chg": "mean", "ts_code": "count"}).reset_index()
        )

        industry_perf.columns = ["industry", "avg_change", "stock_count"]
        industry_perf = industry_perf.sort_values("avg_change", ascending=False)

        # 转换为列表
        records = []
        for _, row in industry_perf.iterrows():
            records.append(
                {
                    "industry": row["industry"],
                    "avg_change": round(float(row["avg_change"]), 2),
                    "stock_count": int(row["stock_count"]),
                }
            )

        return {
            "success": True,
            "data": records,
            "meta": {"period": period, "count": len(records)},
            "error": None,
        }

    except Exception as e:
        return {"success": False, "data": None, "error": f"获取行业涨跌幅失败: {str(e)}"}


def get_industry_leaders(self, industry: str, by: str = "market_cap") -> dict[str, Any]:
    """
    获取行业龙头股

    Args:
        industry: 行业名称
        by: 排序依据，可选 market_cap(市值), revenue(营收), profit(利润)

    Returns:
        行业龙头股数据
    """
    api = self.get_api()
    if not api:
        return {
            "success": False,
            "data": None,
            "error": "Tushare API 未初始化，请检查 TUSHARE_API_TOKEN 环境变量",
        }

    try:
        # 获取行业内的股票
        stock_df = api.stock_basic(fields="ts_code,name,industry")
        if stock_df is None or stock_df.empty:
            return {"success": False, "data": None, "error": "无法获取股票信息"}

        industry_stocks = stock_df[stock_df["industry"] == industry]
        if industry_stocks.empty:
            return {"success": False, "data": None, "error": f"未找到行业: {industry}"}

        ts_codes = industry_stocks["ts_code"].tolist()

        # 获取市值数据
        daily_df = api.daily_basic(fields="ts_code,total_mv")
        if daily_df is not None and not daily_df.empty:
            industry_stocks = industry_stocks.merge(daily_df, on="ts_code", how="left")

        # 获取财务数据 - 使用income接口批量获取最近一期营收数据
        try:
            income_df = api.income(
                ts_code=",".join(ts_codes[:100]), fields="ts_code,total_revenue,n_income,end_date"
            )
            if income_df is not None and not income_df.empty:
                # 取最新一期
                income_df = income_df.sort_values(["ts_code", "end_date"], ascending=[True, False])
                income_df = income_df.drop_duplicates(subset=["ts_code"], keep="first")
                industry_stocks = industry_stocks.merge(
                    income_df[["ts_code", "total_revenue", "n_income"]], on="ts_code", how="left"
                )
        except Exception:
            # 如果批量获取失败，继续执行（部分数据缺失不影响整体结果）
            pass

        # 按指定指标排序
        sort_map = {"market_cap": "total_mv", "revenue": "total_revenue", "profit": "n_income"}
        sort_col = sort_map.get(by, "total_mv")

        if sort_col in industry_stocks.columns:
            industry_stocks = industry_stocks.sort_values(sort_col, ascending=False)

        # 取前10名
        top_stocks = industry_stocks.head(10)

        # 转换为列表
        records = []
        for _, row in top_stocks.iterrows():
            records.append(
                {
                    "ts_code": row["ts_code"],
                    "name": row["name"],
                    "total_mv": self._safe_float(row.get("total_mv")),
                    "total_revenue": self._safe_float(row.get("total_revenue")),
                    "n_income": self._safe_float(row.get("n_income")),
                }
            )

        return {
            "success": True,
            "data": records,
            "meta": {"industry": industry, "sort_by": by, "count": len(records)},
            "error": None,
        }

    except Exception as e:
        return {"success": False, "data": None, "error": f"获取行业龙头股失败: {str(e)}"}


# 绑定行业深度分析方法
TushareClient.compare_industry_metrics = compare_industry_metrics
TushareClient.compare_industry_valuation = compare_industry_valuation
TushareClient.get_industry_performance = get_industry_performance
TushareClient.get_industry_leaders = get_industry_leaders


class MockTushareAPI:
    """
    Mock Tushare Pro API 接口

    模拟 ts.pro_api() 返回的对象，拦截所有 API 调用并路由到 MockTushareService。
    返回的 DataFrame 格式与真实 Tushare API 完全一致。
    """

    def __init__(self, mock_service):
        """
        初始化 Mock API

        Args:
            mock_service: MockTushareService 实例
        """
        self._service = mock_service
        self._logger = logging.getLogger(__name__)

    def daily(
        self,
        ts_code: str = None,
        trade_date: str = None,
        start_date: str = None,
        end_date: str = None,
        **kwargs,
    ):
        """
        获取日K线数据（模拟 daily 接口）

        Args:
            ts_code: 股票代码，如 "600519.SH"
            trade_date: 交易日期（与 start_date/end_date 互斥）
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            DataFrame，格式与 Tushare daily 接口一致
        """
        try:
            import asyncio

            # 处理参数逻辑
            if trade_date:
                # 指定单日
                start_date = trade_date
                end_date = trade_date
            elif not start_date or not end_date:
                # 默认返回最近30天
                if not end_date:
                    end_date = datetime.now().strftime("%Y%m%d")
                if not start_date:
                    start_dt = datetime.strptime(end_date, "%Y%m%d") - timedelta(days=30)
                    start_date = start_dt.strftime("%Y%m%d")

            # 标准化股票代码
            if ts_code:  # noqa: SIM108 — comment-on-else clarifies default
                ts_code = self._normalize_code(ts_code)
            else:
                # 默认返回茅台数据
                ts_code = "600519.SH"

            # 调用 Mock 服务
            self._logger.info(f"[Mock] daily({ts_code}, {start_date}, {end_date})")
            df = asyncio.run(self._service.generate_daily_data(ts_code, start_date, end_date))

            # 如果指定了 trade_date，只返回该日期的数据
            if trade_date and not df.empty:
                df = df[df["trade_date"] == trade_date]

            return df

        except Exception as e:
            self._logger.error(f"[Mock] daily 调用失败: {e}")
            # 返回空 DataFrame
            return pd.DataFrame(
                columns=[
                    "ts_code",
                    "trade_date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "pre_close",
                    "change",
                    "pct_chg",
                    "vol",
                    "amount",
                ]
            )

    def daily_basic(self, ts_code: str = None, trade_date: str = None, **kwargs):
        """
        获取每日指标数据（模拟 daily_basic 接口）

        Args:
            ts_code: 股票代码
            trade_date: 交易日期

        Returns:
            DataFrame，格式与 Tushare daily_basic 接口一致
        """
        try:
            import asyncio

            if ts_code:
                ts_code = self._normalize_code(ts_code)

            self._logger.info(f"[Mock] daily_basic({ts_code}, {trade_date})")
            df = asyncio.run(self._service.generate_daily_basic(ts_code, trade_date))

            return df

        except Exception as e:
            self._logger.error(f"[Mock] daily_basic 调用失败: {e}")
            return pd.DataFrame(
                columns=[
                    "ts_code",
                    "trade_date",
                    "close",
                    "turnover_rate",
                    "pe",
                    "pe_ttm",
                    "pb",
                    "total_mv",
                    "circ_mv",
                ]
            )

    def stock_basic(
        self, exchange: str = None, list_status: str = "L", fields: str = None, **kwargs
    ):
        """
        获取股票基础信息（模拟 stock_basic 接口）

        Args:
            exchange: 交易所，SSE/SZE/BSE
            list_status: 上市状态 L/D/P
            fields: 返回字段列表

        Returns:
            DataFrame，格式与 Tushare stock_basic 接口一致
        """
        try:
            import asyncio

            self._logger.info(f"[Mock] stock_basic({exchange}, {list_status})")
            df = asyncio.run(self._service.generate_stock_basic(exchange, list_status))

            # 如果指定了 fields，只返回指定字段
            if fields and not df.empty:
                field_list = [f.strip() for f in fields.split(",")]
                available_fields = [f for f in field_list if f in df.columns]
                if available_fields:
                    df = df[available_fields]

            return df

        except Exception as e:
            self._logger.error(f"[Mock] stock_basic 调用失败: {e}")
            return pd.DataFrame(
                columns=[
                    "ts_code",
                    "symbol",
                    "name",
                    "area",
                    "industry",
                    "market",
                    "exchange",
                    "list_status",
                    "list_date",
                ]
            )

    def fina_indicator(
        self,
        ts_code: str = None,
        period: str = None,
        start_date: str = None,
        end_date: str = None,
        **kwargs,
    ):
        """
        获取财务指标数据（模拟 fina_indicator 接口）

        Args:
            ts_code: 股票代码
            period: 报告期，如 "20241231"
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            DataFrame，格式与 Tushare fina_indicator 接口一致
        """
        try:
            import asyncio

            if ts_code:
                ts_code = self._normalize_code(ts_code)

            self._logger.info(f"[Mock] fina_indicator({ts_code}, {period})")
            df = asyncio.run(self._service.generate_fina_indicator(ts_code, period))
            return df

        except Exception as e:
            self._logger.error(f"[Mock] fina_indicator 调用失败: {e}")
            return pd.DataFrame(
                columns=[
                    "ts_code",
                    "ann_date",
                    "end_date",
                    "eps",
                    "dt_eps",
                    "revenue_ps",
                    "gross_margin",
                    "current_ratio",
                    "quick_ratio",
                    "cash_ratio",
                    "invturn_days",
                    "arturn_days",
                    "inv_turn",
                    "ar_turn",
                    "ca_turn",
                    "fa_turn",
                    "assets_turn",
                    "op_income",
                    "profit_dedt",
                    "netprofit_margin",
                    "bps",
                    "ocfps",
                    "roe",
                    "rd_exp",
                ]
            )

    def income(
        self,
        ts_code: str = None,
        start_date: str = None,
        end_date: str = None,
        period: str = None,
        **kwargs,
    ):
        """
        获取利润表数据（模拟 income 接口）

        Args:
            ts_code: 股票代码
            start_date: 开始日期
            end_date: 结束日期
            period: 报告期

        Returns:
            DataFrame，格式与 Tushare income 接口一致
        """
        try:
            import asyncio

            if ts_code:
                ts_code = self._normalize_code(ts_code)

            self._logger.info(f"[Mock] income({ts_code}, {period})")
            df = asyncio.run(self._service.generate_income(ts_code, period))
            return df

        except Exception as e:
            self._logger.error(f"[Mock] income 调用失败: {e}")
            return pd.DataFrame(
                columns=[
                    "ts_code",
                    "ann_date",
                    "f_ann_date",
                    "end_date",
                    "report_type",
                    "comp_type",
                    "basic_eps",
                    "diluted_eps",
                    "total_revenue",
                    "revenue",
                    "total_cogs",
                    "oper_cost",
                    "operate_profit",
                    "non_oper_income",
                    "non_oper_exp",
                    "total_profit",
                    "income_tax",
                    "n_income",
                    "ebit",
                    "ebitda",
                ]
            )

    def balancesheet(
        self,
        ts_code: str = None,
        start_date: str = None,
        end_date: str = None,
        period: str = None,
        **kwargs,
    ):
        """
        获取资产负债表数据（模拟 balancesheet 接口）

        Args:
            ts_code: 股票代码
            start_date: 开始日期
            end_date: 结束日期
            period: 报告期

        Returns:
            DataFrame，格式与 Tushare balancesheet 接口一致
        """
        try:
            import asyncio

            if ts_code:
                ts_code = self._normalize_code(ts_code)

            self._logger.info(f"[Mock] balancesheet({ts_code}, {period})")
            df = asyncio.run(self._service.generate_balance_sheet(ts_code, period))
            return df

        except Exception as e:
            self._logger.error(f"[Mock] balancesheet 调用失败: {e}")
            return pd.DataFrame(
                columns=[
                    "ts_code",
                    "ann_date",
                    "f_ann_date",
                    "end_date",
                    "report_type",
                    "comp_type",
                    "total_share",
                    "cap_rese",
                    "undistr_porfit",
                    "surplus_rese",
                    "special_rese",
                    "money_cap",
                    "trad_asset",
                    "notes_receiv",
                    "accounts_receiv",
                    "oth_receiv",
                    "prepayment",
                    "inventories",
                    "total_cur_assets",
                    "fa_avail_for_sale",
                    "lt_eqt_invest",
                    "fix_assets",
                    "intan_assets",
                    "rd",
                    "goodwill",
                    "total_nca",
                    "total_assets",
                    "lt_borr",
                    "st_borr",
                    "notes_payable",
                    "acct_payable",
                    "adv_receipts",
                    "taxes_payable",
                    "total_cur_liab",
                    "lt_payable",
                    "total_ncl",
                    "total_liab_eqt",
                ]
            )

    def cashflow(
        self,
        ts_code: str = None,
        start_date: str = None,
        end_date: str = None,
        period: str = None,
        **kwargs,
    ):
        """
        获取现金流量表数据（模拟 cashflow 接口）

        Args:
            ts_code: 股票代码
            start_date: 开始日期
            end_date: 结束日期
            period: 报告期

        Returns:
            DataFrame，格式与 Tushare cashflow 接口一致
        """
        try:
            import asyncio

            if ts_code:
                ts_code = self._normalize_code(ts_code)

            self._logger.info(f"[Mock] cashflow({ts_code}, {period})")
            df = asyncio.run(self._service.generate_cash_flow(ts_code, period))
            return df

        except Exception as e:
            self._logger.error(f"[Mock] cashflow 调用失败: {e}")
            return pd.DataFrame(
                columns=[
                    "ts_code",
                    "ann_date",
                    "f_ann_date",
                    "end_date",
                    "comp_type",
                    "report_type",
                    "net_profit",
                    "finan_exp",
                    "c_fr_sale_sg",
                    "recp_tax_rends",
                    "c_inf_fr_operate_a",
                    "c_paid_goods_s",
                    "c_paid_to_for_empl",
                    "c_paid_for_taxes",
                    "st_cash_out_act",
                    "n_cashflow_act",
                    "c_disp_withdrwl_invest",
                    "stot_cash_inflow_inv_act",
                    "c_pay_acq_const_fiolta",
                    "stot_cash_outflow_inv_act",
                    "n_cashflow_inv_act",
                    "c_recp_borrow",
                    "stot_cash_inflow_fnc_act",
                    "c_prepay_debt",
                    "stot_cash_outflow_fnc_act",
                    "n_cashflow_fnc_act",
                    "eff_fx_flu_cash",
                    "c_cash_equ_beg_period",
                    "c_cash_equ_end_period",
                ]
            )

    def moneyflow(
        self,
        ts_code: str = None,
        trade_date: str = None,
        start_date: str = None,
        end_date: str = None,
        **kwargs,
    ):
        """
        获取个股资金流向数据（模拟 moneyflow 接口）

        Args:
            ts_code: 股票代码
            trade_date: 交易日期
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            DataFrame，格式与 Tushare moneyflow 接口一致
        """
        try:
            import asyncio

            ts_code = self._normalize_code(ts_code) if ts_code else "600519.SH"

            self._logger.info(f"[Mock] moneyflow({ts_code}, {trade_date})")
            df = asyncio.run(self._service.generate_money_flow(ts_code, trade_date))
            return df

        except Exception as e:
            self._logger.error(f"[Mock] moneyflow 调用失败: {e}")
            return pd.DataFrame(
                columns=[
                    "ts_code",
                    "trade_date",
                    "buy_sm_vol",
                    "buy_sm_amount",
                    "sell_sm_vol",
                    "sell_sm_amount",
                    "buy_md_vol",
                    "buy_md_amount",
                    "sell_md_vol",
                    "sell_md_amount",
                    "buy_lg_vol",
                    "buy_lg_amount",
                    "sell_lg_vol",
                    "sell_lg_amount",
                    "buy_elg_vol",
                    "buy_elg_amount",
                    "sell_elg_vol",
                    "sell_elg_amount",
                    "net_mf_vol",
                    "net_mf_amount",
                    "trade_count",
                ]
            )

    def top_list(self, trade_date: str = None, **kwargs):
        """
        获取龙虎榜每日明细（模拟 top_list 接口）

        Args:
            trade_date: 交易日期

        Returns:
            DataFrame，格式与 Tushare top_list 接口一致
        """
        try:
            import asyncio

            self._logger.info(f"[Mock] top_list({trade_date})")
            df = asyncio.run(self._service.generate_top_list(trade_date))
            return df

        except Exception as e:
            self._logger.error(f"[Mock] top_list 调用失败: {e}")
            return pd.DataFrame(
                columns=[
                    "trade_date",
                    "ts_code",
                    "name",
                    "close",
                    "pct_chg",
                    "turnover_rate",
                    "amount",
                    "l_buy",
                    "l_sell",
                    "net_amount",
                    "net_rate",
                    "amount_rate",
                    "reason",
                ]
            )

    def limit_list(self, trade_date: str = None, limit_type: str = None, **kwargs):
        """
        获取每日涨跌停名单（模拟 limit_list 接口）

        Args:
            trade_date: 交易日期
            limit_type: 涨停/跌停类型

        Returns:
            DataFrame，格式与 Tushare limit_list 接口一致
        """
        try:
            import asyncio

            self._logger.info(f"[Mock] limit_list({trade_date}, {limit_type})")
            df = asyncio.run(self._service.generate_limit_list(trade_date, limit_type))
            return df

        except Exception as e:
            self._logger.error(f"[Mock] limit_list 调用失败: {e}")
            return pd.DataFrame(
                columns=[
                    "trade_date",
                    "ts_code",
                    "name",
                    "industry",
                    "close",
                    "pct_chg",
                    "amount",
                    "limit_amount",
                    "float_mv",
                    "total_mv",
                    "turnover_ratio",
                    "fd_amount",
                    "first_time",
                    "last_time",
                    "open_times",
                    "up_stat",
                    "limit_type",
                ]
            )

    def margin(
        self,
        ts_code: str = None,
        trade_date: str = None,
        start_date: str = None,
        end_date: str = None,
        **kwargs,
    ):
        """
        获取融资融券数据（模拟 margin 接口）

        Args:
            ts_code: 股票代码
            trade_date: 交易日期
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            DataFrame，格式与 Tushare margin 接口一致
        """
        try:
            import asyncio

            ts_code = self._normalize_code(ts_code) if ts_code else "600519.SH"

            self._logger.info(f"[Mock] margin({ts_code}, {trade_date})")
            df = asyncio.run(self._service.generate_margin(ts_code, trade_date))
            return df

        except Exception as e:
            self._logger.error(f"[Mock] margin 调用失败: {e}")
            return pd.DataFrame(
                columns=[
                    "trade_date",
                    "ts_code",
                    "rzye",
                    "rqyl",
                    "rzmre",
                    "rqylc",
                    "rzche",
                    "rqchl",
                    "rqmcl",
                    "szrje",
                    "xzrje",
                    "szrkje",
                    "xzrkje",
                    "rzrqye",
                    "rzrqylc",
                ]
            )

    def moneyflow_hsgt(
        self, start_date: str = None, end_date: str = None, trade_date: str = None, **kwargs
    ):
        """
        获取沪深港通资金流向数据（模拟 moneyflow_hsgt 接口）

        Args:
            start_date: 开始日期
            end_date: 结束日期
            trade_date: 交易日期

        Returns:
            DataFrame，格式与 Tushare moneyflow_hsgt 接口一致
        """
        try:
            import asyncio

            if trade_date:
                start_date = trade_date
                end_date = trade_date

            self._logger.info(f"[Mock] moneyflow_hsgt({start_date}, {end_date})")
            df = asyncio.run(self._service.generate_money_flow_hsgt(start_date, end_date))
            return df

        except Exception as e:
            self._logger.error(f"[Mock] moneyflow_hsgt 调用失败: {e}")
            return pd.DataFrame(
                columns=[
                    "trade_date",
                    "ggt_ss",
                    "ggt_sz",
                    "hgt_ltg",
                    "hgt_cgtes",
                    "hgt_cgtes_l",
                    "sgt_ltg",
                    "sgt_cgtes",
                    "sgt_cgtes_l",
                    "north_money",
                    "south_money",
                ]
            )

    def concept(self, src: str = None, **kwargs):
        """
        获取概念分类列表（模拟 concept 接口）

        Args:
            src: 来源

        Returns:
            DataFrame，格式与 Tushare concept 接口一致
        """
        try:
            import asyncio

            self._logger.info(f"[Mock] concept({src})")
            df = asyncio.run(self._service.generate_concept())
            return df

        except Exception as e:
            self._logger.error(f"[Mock] concept 调用失败: {e}")
            return pd.DataFrame(columns=["code", "name", "src"])

    def concept_detail(self, id: str = None, concept_name: str = None, **kwargs):
        """
        获取概念成分明细（模拟 concept_detail 接口）

        Args:
            id: 概念ID
            concept_name: 概念名称

        Returns:
            DataFrame，格式与 Tushare concept_detail 接口一致
        """
        try:
            import asyncio

            concept_code = id or concept_name
            self._logger.info(f"[Mock] concept_detail({concept_code})")
            df = asyncio.run(self._service.generate_concept_detail(concept_code))
            return df

        except Exception as e:
            self._logger.error(f"[Mock] concept_detail 调用失败: {e}")
            return pd.DataFrame(
                columns=["id", "concept_name", "ts_code", "name", "in_date", "out_date"]
            )

    def stock_company(self, ts_code: str = None, exchange: str = None, **kwargs):
        """
        获取上市公司基本信息（模拟 stock_company 接口）

        Args:
            ts_code: 股票代码
            exchange: 交易所代码

        Returns:
            DataFrame，格式与 Tushare stock_company 接口一致
        """
        try:
            import asyncio

            ts_code = self._normalize_code(ts_code) if ts_code else "600519.SH"

            self._logger.info(f"[Mock] stock_company({ts_code})")
            df = asyncio.run(self._service.generate_stock_company(ts_code))
            return df

        except Exception as e:
            self._logger.error(f"[Mock] stock_company 调用失败: {e}")
            return pd.DataFrame(
                columns=[
                    "ts_code",
                    "exchange",
                    "chairman",
                    "manager",
                    "secretary",
                    "reg_capital",
                    "setup_date",
                    "province",
                    "city",
                    "introduction",
                    "website",
                    "email",
                    "office",
                    "employees",
                    "main_business",
                    "business_scope",
                ]
            )

    def weekly(self, ts_code: str = None, start_date: str = None, end_date: str = None, **kwargs):
        """获取周K线数据（模拟 weekly 接口）"""
        self._logger.info(f"[Mock] weekly({ts_code}) - 使用 daily 数据聚合")
        # 复用 daily 数据，简单模拟
        df = self.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
        if not df.empty:
            # 按周聚合（简化处理，直接返回日数据）
            df = df.head(10)  # 只返回前10条模拟周数据
        return df

    def monthly(self, ts_code: str = None, start_date: str = None, end_date: str = None, **kwargs):
        """获取月K线数据（模拟 monthly 接口）"""
        self._logger.info(f"[Mock] monthly({ts_code}) - 使用 daily 数据聚合")
        df = self.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
        if not df.empty:
            df = df.head(5)  # 只返回前5条模拟月数据
        return df

    def user(self, **kwargs):
        """
        获取用户信息（模拟 user 接口）

        Returns:
            DataFrame，包含 mock 用户信息
        """
        self._logger.info("[Mock] user()")
        # 返回 mock 用户信息，模拟无限积分
        data = {"points": [999999], "vip_level": ["mock"], "valid_until": ["2099-12-31"]}
        return pd.DataFrame(data)

    def query(self, api_name: str, params: dict = None, fields: str = ""):
        """
        通用查询接口（模拟 query 方法）

        Args:
            api_name: API 名称
            params: 查询参数
            fields: 返回字段

        Returns:
            DataFrame
        """
        self._logger.info(f"[Mock] query({api_name}, {params})")

        # 路由到对应的 mock 方法
        if params is None:
            params = {}

        if api_name == "daily":
            return self.daily(**params)
        elif api_name == "daily_basic":
            return self.daily_basic(**params)
        elif api_name == "stock_basic":
            return self.stock_basic(**params)
        elif api_name == "fina_indicator":
            return self.fina_indicator(**params)
        elif api_name == "income":
            return self.income(**params)
        elif api_name == "balancesheet":
            return self.balancesheet(**params)
        elif api_name == "cashflow":
            return self.cashflow(**params)
        elif api_name == "moneyflow":
            return self.moneyflow(**params)
        elif api_name == "top_list":
            return self.top_list(**params)
        elif api_name == "limit_list":
            return self.limit_list(**params)
        elif api_name == "margin":
            return self.margin(**params)
        elif api_name == "moneyflow_hsgt":
            return self.moneyflow_hsgt(**params)
        elif api_name == "concept":
            return self.concept(**params)
        elif api_name == "concept_detail":
            return self.concept_detail(**params)
        elif api_name == "stock_company":
            return self.stock_company(**params)
        elif api_name == "weekly":
            return self.weekly(**params)
        elif api_name == "monthly":
            return self.monthly(**params)
        else:
            self._logger.warning(f"[Mock] 未实现的 API: {api_name}")
            return pd.DataFrame()

    def _normalize_code(self, symbol: str) -> str:
        """标准化股票代码为 Tushare 格式"""
        symbol = symbol.strip().upper()

        # 如果已经是 Tushare 格式，直接返回
        if "." in symbol:
            return symbol

        # 去除市场前缀（如 sh600519 -> 600519）
        if symbol.startswith("SH") or symbol.startswith("SZ") or symbol.startswith("BJ"):
            code = symbol[2:]
            market = symbol[:2]
            return f"{code}.{market}"

        # 纯数字，根据规则判断市场
        if len(symbol) == 6:
            if symbol.startswith("6") or symbol.startswith("9"):
                return f"{symbol}.SH"
            elif symbol.startswith("0") or symbol.startswith("3") or symbol.startswith("2"):
                return f"{symbol}.SZ"
            elif symbol.startswith("4") or symbol.startswith("8"):
                return f"{symbol}.BJ"

        return symbol

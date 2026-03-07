# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""Tushare API 封装客户端"""
import os
import time
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from threading import Lock
import tushare as ts


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

    _instance: Optional['TushareClient'] = None
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
        """初始化客户端"""
        # 避免重复初始化
        if hasattr(self, '_initialized'):
            return

        # 从环境变量读取 Token
        self.token = os.getenv("TUSHARE_API_TOKEN", "")
        # 从环境变量读取自定义 API URL
        self.api_url = os.getenv("TUSHARE_API_URL", "https://api.tushare.pro")

        if not self.token:
            print("警告: TUSHARE_API_TOKEN 环境变量未设置")
            self.api = None
        else:
            try:
                ts.set_token(self.token)
                # 创建 pro_api 实例
                self.api = ts.pro_api()
                # 设置自定义 API URL（如果指定了非默认 URL）
                if self.api_url and self.api_url != "https://api.tushare.pro":
                    self.api._DataApi__token = self.token
                    self.api._DataApi__http_url = self.api_url
                    print(f"使用自定义 Tushare API URL: {self.api_url}")
            except Exception as e:
                print(f"警告: Tushare API 初始化失败: {e}")
                self.api = None

        # 缓存存储: {ts_code: (data, timestamp)}
        self._cache: Dict[str, tuple[Dict[str, Any], float]] = {}
        self._cache_lock = Lock()

        # 用户积分（延迟加载）
        self._user_points: Optional[int] = None
        self._points_checked = False

        self._initialized = True

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

    def _get_from_cache(self, ts_code: str) -> Optional[Dict[str, Any]]:
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

    def _set_cache(self, ts_code: str, data: Dict[str, Any]):
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
                key for key, (_, timestamp) in self._cache.items()
                if current_time - timestamp >= self.CACHE_TTL
            ]
            for key in expired_keys:
                del self._cache[key]

    def get_user_points(self) -> Optional[int]:
        """
        获取用户积分

        Returns:
            用户积分，如果无法获取返回 None
        """
        if self._points_checked:
            return self._user_points

        if not self.api:
            self._points_checked = True
            return None

        try:
            # 调用 user 接口获取用户信息
            user_info = self.api.user()
            if user_info is not None and not user_info.empty:
                # user() 返回 DataFrame，取第一行的 points 字段
                self._user_points = int(user_info.iloc[0].get('points', 0))
                print(f"Tushare 账号积分: {self._user_points}")
            else:
                print("警告: 无法获取 Tushare 用户积分信息")
                self._user_points = None
        except Exception as e:
            print(f"警告: 获取 Tushare 用户积分失败: {e}")
            self._user_points = None

        self._points_checked = True
        return self._user_points

    def get_stock_basic(self, symbol: str) -> Dict[str, Any]:
        """
        获取股票基本信息（低积分可用接口）

        Args:
            symbol: 股票代码

        Returns:
            格式化的股票基本信息字典
        """
        if not self.api:
            return {
                "success": False,
                "data": None,
                "error": "Tushare API 未初始化，请检查 TUSHARE_API_TOKEN 环境变量"
            }

        try:
            # 标准化股票代码
            ts_code = self._normalize_stock_code(symbol)

            # 调用 stock_basic 接口获取基本信息
            df = self.api.stock_basic(
                ts_code=ts_code,
                fields='ts_code,symbol,name,area,industry,list_date'
            )

            if df is None or df.empty:
                raise TushareInvalidCodeError(f"未找到股票: {symbol}")

            # 获取第一条记录
            stock_info = df.iloc[0]

            # 构造返回数据
            stock_data = {
                "ts_code": stock_info['ts_code'],
                "symbol": stock_info['symbol'],
                "name": stock_info['name'],
                "area": stock_info.get('area', ''),
                "industry": stock_info.get('industry', ''),
                "list_date": stock_info.get('list_date', '')
            }

            return {
                "success": True,
                "data": stock_data,
                "error": None
            }

        except TushareInvalidCodeError as e:
            return {
                "success": False,
                "data": None,
                "error": f"无效股票代码: {str(e)}"
            }
        except Exception as e:
            return {
                "success": False,
                "data": None,
                "error": f"获取股票基本信息失败: {str(e)}"
            }

    def get_quote(self, symbol: str) -> Dict[str, Any]:
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
        if not self.api:
            return {
                "success": False,
                "data": None,
                "error": "Tushare API 未初始化，请检查 TUSHARE_API_TOKEN 环境变量"
            }

        try:
            # 标准化股票代码
            ts_code = self._normalize_stock_code(symbol)

            # 尝试从缓存获取
            cached_data = self._get_from_cache(ts_code)
            if cached_data:
                return {
                    "success": True,
                    "data": cached_data,
                    "error": None
                }

            # 检查用户积分
            points = self.get_user_points()

            # 积分 < 200 时使用低积分替代方案
            if points is not None and points < 200:
                print(f"积分不足 ({points} < 200)，使用 stock_basic 接口获取基本信息")

                # 获取股票基本信息
                basic_result = self.get_stock_basic(symbol)
                if not basic_result['success']:
                    return basic_result

                basic_data = basic_result['data']

                # 构造简化数据（仅基本信息，无价格数据）
                stock_data = {
                    "gid": self._to_legacy_code(ts_code),
                    "ts_code": basic_data['ts_code'],
                    "name": basic_data['name'],
                    "area": basic_data.get('area', ''),
                    "industry": basic_data.get('industry', ''),
                    "list_date": basic_data.get('list_date', ''),
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
                    "update_time": datetime.now().strftime('%Y-%m-%d'),
                    "_low_points_mode": True  # 标记为低积分模式
                }

                # 缓存数据
                self._set_cache(ts_code, stock_data)

                return {
                    "success": True,
                    "data": stock_data,
                    "error": None,
                    "warning": f"账号积分 {points} < 200，仅返回基本信息"
                }

            # 积分 >= 200 或无法获取积分时，使用 daily 接口获取完整数据
            # 调用 Tushare API 获取实时行情
            # 使用 daily 接口获取最新交易日数据
            df = self.api.daily(
                ts_code=ts_code,
                start_date=(datetime.now() - timedelta(days=7)).strftime('%Y%m%d'),
                end_date=datetime.now().strftime('%Y%m%d')
            )

            if df is None or df.empty:
                raise TushareInvalidCodeError(f"未找到股票数据: {symbol}")

            # 获取最新一条数据
            latest = df.iloc[0]

            # 获取股票基本信息（股票名称）
            stock_basic = self.api.stock_basic(
                ts_code=ts_code,
                fields='ts_code,symbol,name'
            )

            stock_name = "未知"
            if stock_basic is not None and not stock_basic.empty:
                stock_name = stock_basic.iloc[0]['name']

            # 计算涨跌额和涨跌幅
            close_price = float(latest['close'])
            pre_close = float(latest['pre_close'])
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
                "update_time": latest['trade_date']
            }

            # 缓存数据
            self._set_cache(ts_code, stock_data)

            # 定期清理过期缓存
            self._clear_expired_cache()

            return {
                "success": True,
                "data": stock_data,
                "error": None
            }

        except TushareInvalidCodeError as e:
            return {
                "success": False,
                "data": None,
                "error": f"无效股票代码: {str(e)}"
            }
        except Exception as e:
            error_msg = str(e).lower()

            # 判断错误类型
            if "rate limit" in error_msg or "too many requests" in error_msg:
                return {
                    "success": False,
                    "data": None,
                    "error": "API 调用频率超限，请稍后再试"
                }
            elif "network" in error_msg or "timeout" in error_msg or "connection" in error_msg:
                return {
                    "success": False,
                    "data": None,
                    "error": f"网络异常: {str(e)}"
                }
            else:
                return {
                    "success": False,
                    "data": None,
                    "error": f"获取股票数据失败: {str(e)}"
                }

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

    def get_cache_info(self) -> Dict[str, Any]:
        """
        获取缓存信息

        Returns:
            缓存统计信息
        """
        with self._cache_lock:
            current_time = time.time()
            valid_count = sum(
                1 for _, timestamp in self._cache.values()
                if current_time - timestamp < self.CACHE_TTL
            )

            return {
                "total_cached": len(self._cache),
                "valid_cached": valid_count,
                "cache_ttl": self.CACHE_TTL
            }


# 单例获取函数
_client_instance: Optional[TushareClient] = None


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

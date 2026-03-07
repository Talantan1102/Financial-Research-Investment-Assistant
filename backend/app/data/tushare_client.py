# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""Tushare API 封装客户端"""
import os
import time
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from threading import Lock
import tushare as ts
import pandas as pd


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

    def get_history(self, symbol: str, period: str = "daily", 
                    start_date: str = None, end_date: str = None, 
                    limit: int = 100) -> Dict[str, Any]:
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
        if not self.api:
            return {
                "success": False,
                "data": None,
                "error": "Tushare API 未初始化，请检查 TUSHARE_API_TOKEN 环境变量"
            }

        try:
            # 标准化股票代码
            ts_code = self._normalize_stock_code(symbol)

            # 构建缓存键
            cache_key = f"history_{ts_code}_{period}_{start_date}_{end_date}"
            cached_data = self._get_from_cache(cache_key)
            if cached_data:
                return {
                    "success": True,
                    "data": cached_data,
                    "error": None
                }

            # 设置默认日期范围
            if not end_date:
                end_date = datetime.now().strftime('%Y%m%d')
            if not start_date:
                start_dt = datetime.strptime(end_date, '%Y%m%d') - timedelta(days=limit)
                start_date = start_dt.strftime('%Y%m%d')

            # 根据周期选择API
            api_func_map = {
                "daily": self.api.daily,
                "weekly": self.api.weekly,
                "monthly": self.api.monthly
            }

            if period not in api_func_map:
                return {
                    "success": False,
                    "data": None,
                    "error": f"不支持的周期类型: {period}，可选: daily, weekly, monthly"
                }

            api_func = api_func_map[period]

            # 调用API
            df = api_func(
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date
            )

            if df is None or df.empty:
                return {
                    "success": False,
                    "data": None,
                    "error": f"未找到历史数据: {symbol}"
                }

            # 转换为列表格式
            records = []
            for _, row in df.iterrows():
                records.append({
                    "trade_date": row['trade_date'],
                    "open": float(row['open']),
                    "high": float(row['high']),
                    "low": float(row['low']),
                    "close": float(row['close']),
                    "pre_close": float(row['pre_close']),
                    "change": float(row['change']),
                    "pct_chg": float(row['pct_chg']),
                    "vol": float(row['vol']),
                    "amount": float(row['amount'])
                })

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
                    "start_date": records[-1]['trade_date'] if records else None,
                    "end_date": records[0]['trade_date'] if records else None
                },
                "error": None
            }

        except Exception as e:
            return {
                "success": False,
                "data": None,
                "error": f"获取历史数据失败: {str(e)}"
            }

    def get_top_list(self, trade_date: str = None, limit: int = 50) -> Dict[str, Any]:
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
        if not self.api:
            return {
                "success": False,
                "data": None,
                "error": "Tushare API 未初始化，请检查 TUSHARE_API_TOKEN 环境变量"
            }

        try:
            # 设置默认日期为最近交易日
            if not trade_date:
                trade_date = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')

            # 构建缓存键
            cache_key = f"top_list_{trade_date}"
            cached_data = self._get_from_cache(cache_key)
            if cached_data:
                return {
                    "success": True,
                    "data": cached_data,
                    "error": None
                }

            # 调用top_list接口
            df = self.api.top_list(trade_date=trade_date)

            if df is None or df.empty:
                return {
                    "success": False,
                    "data": None,
                    "error": f"未找到龙虎榜数据: {trade_date}"
                }

            # 获取股票名称映射
            stock_names = {}
            try:
                basic_df = self.api.stock_basic(fields='ts_code,name')
                if basic_df is not None and not basic_df.empty:
                    stock_names = dict(zip(basic_df['ts_code'], basic_df['name']))
            except:
                pass

            # 转换为列表格式
            records = []
            for _, row in df.head(limit).iterrows():
                ts_code = row['ts_code']
                records.append({
                    "trade_date": row['trade_date'],
                    "ts_code": ts_code,
                    "name": stock_names.get(ts_code, ""),
                    "close": float(row.get('close', 0)),
                    "pct_chg": float(row.get('pct_chg', 0)),
                    "turnover_rate": float(row.get('turnover_rate', 0)),
                    "amount": float(row.get('amount', 0)),
                    "l_buy": float(row.get('l_buy', 0)),
                    "l_sell": float(row.get('l_sell', 0)),
                    "net_amount": float(row.get('l_buy', 0)) - float(row.get('l_sell', 0)),
                    "reason": row.get('reason', '')
                })

            # 缓存数据
            self._set_cache(cache_key, records)

            return {
                "success": True,
                "data": records,
                "meta": {
                    "trade_date": trade_date,
                    "count": len(records)
                },
                "error": None
            }

        except Exception as e:
            error_msg = str(e).lower()
            if "points" in error_msg or "积分" in error_msg:
                return {
                    "success": False,
                    "data": None,
                    "error": "积分不足，龙虎榜数据需要至少5000积分"
                }
            return {
                "success": False,
                "data": None,
                "error": f"获取龙虎榜数据失败: {str(e)}"
            }

    def get_money_flow(self, symbol: str, trade_date: str = None, 
                       start_date: str = None, end_date: str = None) -> Dict[str, Any]:
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
        if not self.api:
            return {
                "success": False,
                "data": None,
                "error": "Tushare API 未初始化，请检查 TUSHARE_API_TOKEN 环境变量"
            }

        try:
            # 标准化股票代码
            ts_code = self._normalize_stock_code(symbol)

            # 构建缓存键
            date_key = trade_date or f"{start_date}_{end_date}"
            cache_key = f"money_flow_{ts_code}_{date_key}"
            cached_data = self._get_from_cache(cache_key)
            if cached_data:
                return {
                    "success": True,
                    "data": cached_data,
                    "error": None
                }

            # 构建参数
            params = {"ts_code": ts_code}
            if trade_date:
                params["trade_date"] = trade_date
            if start_date:
                params["start_date"] = start_date
            if end_date:
                params["end_date"] = end_date

            # 调用moneyflow接口
            df = self.api.moneyflow(**params)

            if df is None or df.empty:
                return {
                    "success": False,
                    "data": None,
                    "error": f"未找到资金流向数据: {symbol}"
                }

            # 获取股票名称
            stock_name = ""
            try:
                basic_df = self.api.stock_basic(ts_code=ts_code, fields='name')
                if basic_df is not None and not basic_df.empty:
                    stock_name = basic_df.iloc[0]['name']
            except:
                pass

            # 转换为列表格式
            records = []
            for _, row in df.iterrows():
                records.append({
                    "trade_date": row['trade_date'],
                    "ts_code": ts_code,
                    "name": stock_name,
                    "buy_sm_amount": float(row.get('buy_sm_amount', 0)),
                    "sell_sm_amount": float(row.get('sell_sm_amount', 0)),
                    "buy_md_amount": float(row.get('buy_md_amount', 0)),
                    "sell_md_amount": float(row.get('sell_md_amount', 0)),
                    "buy_lg_amount": float(row.get('buy_lg_amount', 0)),
                    "sell_lg_amount": float(row.get('sell_lg_amount', 0)),
                    "buy_elg_amount": float(row.get('buy_elg_amount', 0)),
                    "sell_elg_amount": float(row.get('sell_elg_amount', 0)),
                    "net_mf_amount": float(row.get('net_mf_amount', 0)),
                    "trade_count": int(row.get('trade_count', 0))
                })

            # 缓存数据
            self._set_cache(cache_key, records)

            return {
                "success": True,
                "data": records,
                "meta": {
                    "symbol": ts_code,
                    "count": len(records)
                },
                "error": None
            }

        except Exception as e:
            return {
                "success": False,
                "data": None,
                "error": f"获取资金流向数据失败: {str(e)}"
            }

    def get_limit_list(self, trade_date: str = None, limit_type: str = None) -> Dict[str, Any]:
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
        if not self.api:
            return {
                "success": False,
                "data": None,
                "error": "Tushare API 未初始化，请检查 TUSHARE_API_TOKEN 环境变量"
            }

        try:
            # 设置默认日期
            if not trade_date:
                trade_date = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')

            # 构建缓存键
            cache_key = f"limit_list_{trade_date}_{limit_type or 'all'}"
            cached_data = self._get_from_cache(cache_key)
            if cached_data:
                return {
                    "success": True,
                    "data": cached_data,
                    "error": None
                }

            # 构建参数
            params = {"trade_date": trade_date}
            if limit_type:
                params["limit_type"] = limit_type

            # 调用limit_list接口
            df = self.api.limit_list(**params)

            if df is None or df.empty:
                return {
                    "success": False,
                    "data": None,
                    "error": f"未找到涨跌停数据: {trade_date}"
                }

            # 获取股票名称映射
            stock_names = {}
            try:
                ts_codes = df['ts_code'].tolist()
                basic_df = self.api.stock_basic(fields='ts_code,name')
                if basic_df is not None and not basic_df.empty:
                    stock_names = dict(zip(basic_df['ts_code'], basic_df['name']))
            except:
                pass

            # 转换为列表格式
            records = []
            for _, row in df.iterrows():
                ts_code = row['ts_code']
                record = {
                    "trade_date": row['trade_date'],
                    "ts_code": ts_code,
                    "name": stock_names.get(ts_code, ""),
                    "close": float(row.get('close', 0)),
                    "pre_close": float(row.get('pre_close', 0)),
                    "pct_chg": float(row.get('pct_chg', 0)),
                    "amount": float(row.get('amount', 0)),
                    "limit_amount": float(row.get('limit_amount', 0)),
                    "float_mv": float(row.get('float_mv', 0)),
                    "total_mv": float(row.get('total_mv', 0)),
                    "turnover_ratio": float(row.get('turnover_ratio', 0)),
                    "fd_amount": float(row.get('fd_amount', 0)),
                    "first_time": row.get('first_time', ''),
                    "last_time": row.get('last_time', ''),
                    "open_times": int(row.get('open_times', 0)),
                    "up_stat": row.get('up_stat', ''),
                    "limit_type": row.get('limit_type', '')
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
                    "limit_up_count": sum(1 for r in records if r['up_stat'] == 'U'),
                    "limit_down_count": sum(1 for r in records if r['up_stat'] == 'D')
                },
                "error": None
            }

        except Exception as e:
            return {
                "success": False,
                "data": None,
                "error": f"获取涨跌停数据失败: {str(e)}"
            }

    def get_stock_company_info(self, symbol: str) -> Dict[str, Any]:
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
        if not self.api:
            return {
                "success": False,
                "data": None,
                "error": "Tushare API 未初始化，请检查 TUSHARE_API_TOKEN 环境变量"
            }

        try:
            # 标准化股票代码
            ts_code = self._normalize_stock_code(symbol)

            # 构建缓存键
            cache_key = f"company_info_{ts_code}"
            cached_data = self._get_from_cache(cache_key)
            if cached_data:
                return {
                    "success": True,
                    "data": cached_data,
                    "error": None
                }

            # 调用stock_company接口获取详细信息
            df = self.api.stock_company(ts_code=ts_code)

            if df is None or df.empty:
                return {
                    "success": False,
                    "data": None,
                    "error": f"未找到公司信息: {symbol}"
                }

            # 获取基础信息补充
            basic_df = self.api.stock_basic(ts_code=ts_code)
            basic_info = {}
            if basic_df is not None and not basic_df.empty:
                basic_row = basic_df.iloc[0]
                basic_info = {
                    "area": basic_row.get('area', ''),
                    "industry": basic_row.get('industry', ''),
                    "list_date": basic_row.get('list_date', '')
                }

            # 构造返回数据
            row = df.iloc[0]
            company_data = {
                "ts_code": ts_code,
                "symbol": row.get('symbol', ''),
                "name": row.get('name', ''),
                "fullname": row.get('fullname', ''),
                "enname": row.get('enname', ''),
                "exchange": row.get('exchange', ''),
                "curr_type": row.get('curr_type', ''),
                "list_status": row.get('list_status', ''),
                "list_date": basic_info.get('list_date', row.get('list_date', '')),
                "delist_date": row.get('delist_date') if pd.notna(row.get('delist_date')) else None,
                "is_hs": row.get('is_hs', ''),
                "area": basic_info.get('area', row.get('area', '')),
                "industry": basic_info.get('industry', row.get('industry', '')),
                "province": row.get('province', ''),
                "city": row.get('city', ''),
                "introduction": row.get('introduction', ''),
                "website": row.get('website', ''),
                "email": row.get('email', ''),
                "office": row.get('office', '')
            }

            # 缓存数据
            self._set_cache(cache_key, company_data)

            return {
                "success": True,
                "data": company_data,
                "error": None
            }

        except Exception as e:
            return {
                "success": False,
                "data": None,
                "error": f"获取公司信息失败: {str(e)}"
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

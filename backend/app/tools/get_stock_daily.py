"""GetStockDailyTool —— 按区间取个股日线收盘序列。

填补:get_stock_quote 只给最新一日;算涨幅/回撤/波动需要区间收盘序列。本工具薄包
TushareService.get_daily(ts_code, start, end),返回升序的 {trade_date, close} 列表,
让模型自己用 run_python 算指标(守"取数/算分离"红线)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from app.tools.base import Tool, ToolError

if TYPE_CHECKING:
    from app.services.tushare_service import TushareService


class GetStockDailyArgs(BaseModel):
    ts_code: str
    start_date: str  # YYYYMMDD
    end_date: str  # YYYYMMDD


class GetStockDailyTool(Tool):
    """Return the daily closing-price series for an A-share over [start_date, end_date]."""

    name = "get_stock_daily"
    description = (
        "取某只 A 股在 [start_date, end_date] 区间的日线序列(升序),每项含 "
        "close(收盘价)与 pct_chg(当日涨跌幅 %)。用于自行计算涨幅/回撤/CAGR(用 close)"
        "与波动率/相关性(用 pct_chg)——本工具只返回原始数据,不替你算。"
        "ts_code 如 '000938.SZ';日期格式 YYYYMMDD。"
    )
    args_schema = GetStockDailyArgs

    def __init__(self, tushare: TushareService | None = None) -> None:
        self._tushare = tushare

    async def run(self, args: BaseModel) -> dict[str, Any]:
        v = GetStockDailyArgs.model_validate(args.model_dump())
        if self._tushare is None:
            raise ToolError("tushare not configured — cannot fetch daily data")
        try:
            df = await self._tushare.get_daily(ts_code=v.ts_code, start=v.start_date, end=v.end_date)
        except Exception as exc:  # noqa: BLE001 — 转成工具层错误
            raise ToolError(f"get_daily failed: {exc}") from exc
        if df is None or df.empty:
            raise ToolError(f"No daily data for ts_code={v.ts_code!r} in [{v.start_date},{v.end_date}]")
        ordered = df.sort_values("trade_date")
        _has_pct = "pct_chg" in ordered.columns

        def _pct(r: Any) -> float | None:
            if not _has_pct:
                return None
            val = r["pct_chg"]
            return float(val) if val == val else None  # NaN → None

        # close(算涨幅/回撤/CAGR)+ pct_chg(算波动/相关,与 Path A MCP get_daily 对齐:
        # 这两个指标 gold 走 tushare pct_chg/100 而非 close 比值,缺 pct_chg 会逼模型用
        # close 比值 → 拆股/分红系统性偏差)。
        closes = [
            {
                "trade_date": str(r["trade_date"]),
                "close": float(r["close"]),
                "pct_chg": _pct(r),
            }
            for _, r in ordered.iterrows()
        ]
        return {"ts_code": v.ts_code, "closes": closes}


__all__ = ["GetStockDailyTool", "GetStockDailyArgs"]

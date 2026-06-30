"""Tool: get_stock_quote — fetch latest daily quote for a single A-share."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from app.tools.base import Tool, ToolError

if TYPE_CHECKING:
    from app.services.tushare_service import TushareService


class StockQuoteArgs(BaseModel):
    ts_code: str
    as_of: str | None = None  # YYYYMMDD;基准日(否则用今天)。固定它→历史题目可复现、不随训练日漂移。


class StockQuoteTool(Tool):
    """Return the latest daily price/volume snapshot for a given A-share.

    Data source: TushareService.get_daily (daily K-line).
    The most recent row is extracted and mapped to a compact quote dict.
    """

    name = "get_stock_quote"
    description = (
        "Return the latest daily closing price, price-change %, "
        "and trading volume for the given A-share (ts_code, e.g. '600519.SH')."
    )
    args_schema = StockQuoteArgs

    def __init__(self, tushare: TushareService | None = None) -> None:
        self._tushare = tushare

    async def run(self, args: BaseModel) -> dict[str, Any]:
        # Narrow type: registry always validates against args_schema first
        validated = StockQuoteArgs.model_validate(args.model_dump())

        if self._tushare is None:
            raise ToolError("tushare not configured — cannot fetch daily data")

        # C54: use a 5-day window so weekends/holidays always yield at least one trading day.
        # The comment originally said "last 3 days" but start=today,end=today was a zero-width
        # window on non-trading days.  sort_values + iloc[0] below picks the most recent row.
        ref = datetime.strptime(validated.as_of, "%Y%m%d") if validated.as_of else datetime.now()
        start = (ref - timedelta(days=5)).strftime("%Y%m%d")
        end = ref.strftime("%Y%m%d")
        try:
            df = await self._tushare.get_daily(
                ts_code=validated.ts_code,
                start=start,
                end=end,
            )
        except Exception as exc:
            raise ToolError(f"get_daily failed: {exc}") from exc

        if df.empty:
            raise ToolError(f"No daily data returned for ts_code={validated.ts_code!r}")

        # Take the latest row (most recent trade_date)
        row = df.sort_values("trade_date", ascending=False).iloc[0]

        return {
            "ts_code": str(row.get("ts_code", validated.ts_code)),
            "price": float(row.get("close", 0.0)),
            "change_pct": float(row.get("pct_chg", 0.0)),
            "volume": float(row.get("vol", 0.0)),
        }

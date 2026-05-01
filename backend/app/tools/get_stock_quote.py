"""Tool: get_stock_quote — fetch latest daily quote for a single A-share."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from app.tools.base import Tool, ToolError

if TYPE_CHECKING:
    from app.service.mock_tushare_service import MockTushareService


class StockQuoteArgs(BaseModel):
    ts_code: str


class StockQuoteTool(Tool):
    """Return the latest daily price/volume snapshot for a given A-share.

    Data source: MockTushareService.generate_daily_data (daily K-line).
    The most recent row is extracted and mapped to a compact quote dict.
    """

    name = "get_stock_quote"
    description = (
        "Return the latest daily closing price, price-change %, "
        "and trading volume for the given A-share (ts_code, e.g. '600519.SH')."
    )
    args_schema = StockQuoteArgs

    def __init__(self, mock_tushare: MockTushareService) -> None:
        self._mock_tushare = mock_tushare

    async def run(self, args: BaseModel) -> dict[str, Any]:
        # Narrow type: registry always validates against args_schema first
        validated = StockQuoteArgs.model_validate(args.model_dump())

        today = datetime.now().strftime("%Y%m%d")
        # Fetch last 3 days to ensure at least one trading day is included
        try:
            df = await self._mock_tushare.generate_daily_data(
                ts_code=validated.ts_code,
                start_date=today,
                end_date=today,
            )
        except Exception as exc:
            raise ToolError(f"generate_daily_data failed: {exc}") from exc

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

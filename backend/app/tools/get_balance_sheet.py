"""GetBalanceSheetTool — 资产负债 + 派生偿债指标 (v0.8.5)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from app.tools.base import Tool

if TYPE_CHECKING:
    from app.services.tushare_service import TushareService


class BalanceSheetArgs(BaseModel):
    ts_code: str
    end_date: str | None = None


class GetBalanceSheetTool(Tool):
    """Return key balance-sheet items + derived solvency ratios.

    Derived fields (computed in Python so the LLM consumes structured signals):
      - asset_liability_ratio = total_liab / max(total_assets, 1.0)
      - current_ratio = total_cur_assets / max(total_cur_liab, 1.0)
    """

    name = "get_balance_sheet"
    description = (
        "Return total_assets, total_liab, total_cur_assets, total_cur_liab "
        "and derived asset_liability_ratio + current_ratio for an A-share."
    )
    args_schema = BalanceSheetArgs

    def __init__(self, tushare: TushareService | None = None) -> None:
        if tushare is None:
            from app.services.tushare_factory import build_tushare_service

            tushare = build_tushare_service()
        self._tushare = tushare

    async def run(self, args: BaseModel) -> dict[str, Any]:
        a = BalanceSheetArgs.model_validate(args.model_dump())
        df = await self._tushare.get_balance_sheet(ts_code=a.ts_code, end_date=a.end_date)
        if df.empty:
            return {"ts_code": a.ts_code, "error": "no data"}
        # Pick latest end_date if multiple rows present
        if "end_date" in df.columns and len(df) > 1:
            df = df.sort_values("end_date", ascending=False)
        row = df.iloc[0]
        total_assets = float(row["total_assets"])
        total_liab = float(row["total_liab"])
        total_cur_assets = float(row["total_cur_assets"])
        total_cur_liab = float(row["total_cur_liab"])
        return {
            "ts_code": a.ts_code,
            "end_date": str(row.get("end_date", "")),
            "total_assets": total_assets,
            "total_liab": total_liab,
            "total_cur_assets": total_cur_assets,
            "total_cur_liab": total_cur_liab,
            "asset_liability_ratio": total_liab / max(total_assets, 1.0),
            "current_ratio": total_cur_assets / max(total_cur_liab, 1.0),
        }

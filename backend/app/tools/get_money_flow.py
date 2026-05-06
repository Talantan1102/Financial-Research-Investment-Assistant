"""GetMoneyFlowTool — 资金流向 + 派生大单净流向信号 (v0.8.5)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel

from app.tools.base import Tool

if TYPE_CHECKING:
    from app.services.tushare_service import TushareService


class MoneyFlowArgs(BaseModel):
    ts_code: str
    start_date: str
    end_date: str


NetLgSignal = Literal["inflow", "outflow"]


class GetMoneyFlowTool(Tool):
    """Return money-flow buckets + derived large-order net signal.

    Derived field:
      - net_lg_signal: 'inflow' if buy_lg_amount > sell_lg_amount else 'outflow'.
        Indicates whether large-order (institutional) money is net-flowing in.
    """

    name = "get_money_flow"
    description = (
        "Return buy_lg / sell_lg / buy_md / sell_md amounts and a derived "
        "net_lg_signal (inflow/outflow) for an A-share."
    )
    args_schema = MoneyFlowArgs

    def __init__(self, tushare: TushareService | None = None) -> None:
        if tushare is None:
            from app.services.tushare_factory import build_tushare_service

            tushare = build_tushare_service()
        self._tushare = tushare

    async def run(self, args: BaseModel) -> dict[str, Any]:
        a = MoneyFlowArgs.model_validate(args.model_dump())
        df = await self._tushare.get_money_flow(
            ts_code=a.ts_code, start_date=a.start_date, end_date=a.end_date
        )
        if df.empty:
            return {"ts_code": a.ts_code, "error": "no data"}
        # Sum across the date range (mock returns 1 row but real may return many)
        buy_lg = float(df["buy_lg_amount"].sum()) if "buy_lg_amount" in df.columns else 0.0
        sell_lg = float(df["sell_lg_amount"].sum()) if "sell_lg_amount" in df.columns else 0.0
        buy_md = float(df["buy_md_amount"].sum()) if "buy_md_amount" in df.columns else 0.0
        sell_md = float(df["sell_md_amount"].sum()) if "sell_md_amount" in df.columns else 0.0
        net_lg_signal: NetLgSignal = "inflow" if buy_lg > sell_lg else "outflow"
        return {
            "ts_code": a.ts_code,
            "start_date": a.start_date,
            "end_date": a.end_date,
            "buy_lg_amount": buy_lg,
            "sell_lg_amount": sell_lg,
            "buy_md_amount": buy_md,
            "sell_md_amount": sell_md,
            "net_lg_signal": net_lg_signal,
        }

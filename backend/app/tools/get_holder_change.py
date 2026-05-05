"""GetHolderChangeTool — 股东户数变化 + 派生筹码趋势 (v0.8.5)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from app.tools.base import Tool

if TYPE_CHECKING:
    from app.services.tushare_service import TushareService


class HolderChangeArgs(BaseModel):
    ts_code: str
    years_back: int = Field(default=2, ge=1, le=5)


HolderTrend = Literal["concentration", "dispersion", "stable"]


def _classify_holder_trend(latest: float, earliest: float) -> HolderTrend:
    """股东户数变化趋势:

    - 户数减少 5%+ → 'concentration' (筹码向少数人集中, 多见于机构持仓增加)
    - 户数增加 5%+ → 'dispersion' (筹码散户化)
    - |变化| < 5% → 'stable'
    """
    if earliest <= 0:
        return "stable"
    delta_ratio = (latest - earliest) / earliest
    # Inclusive thresholds — docstring 说"户数减少 5%+" / "增加 5%+",
    # -5.0% / +5.0% 临界值归 concentration / dispersion (而非 stable).
    if delta_ratio <= -0.05:
        return "concentration"
    if delta_ratio >= 0.05:
        return "dispersion"
    return "stable"


class GetHolderChangeTool(Tool):
    """Return recent shareholder-count snapshots + derived trend signal.

    Derived field:
      - trend: 'concentration' (户数显著减少 → 机构集中) /
               'dispersion' (户数显著增加 → 散户化) /
               'stable' (变化 < 5%).
    """

    name = "get_holder_change"
    description = (
        "Return recent_holder_nums (list of {end_date, holder_num}) and a "
        "derived trend (concentration/dispersion/stable) for an A-share."
    )
    args_schema = HolderChangeArgs

    def __init__(self, tushare: TushareService | None = None) -> None:
        if tushare is None:
            from app.services.tushare_factory import build_tushare_service

            tushare = build_tushare_service()
        self._tushare = tushare

    async def run(self, args: BaseModel) -> dict[str, Any]:
        a = HolderChangeArgs.model_validate(args.model_dump())
        df = await self._tushare.get_holder_change(ts_code=a.ts_code, years_back=a.years_back)
        if df.empty:
            return {"ts_code": a.ts_code, "error": "no data"}

        # Sort by end_date ascending so [0]=earliest, [-1]=latest
        if "end_date" in df.columns:
            df = df.sort_values("end_date", ascending=True)

        recent: list[dict[str, Any]] = []
        holder_nums: list[float] = []
        for _, row in df.iterrows():
            hn = float(row.get("holder_num", 0.0) or 0.0)
            recent.append(
                {
                    "end_date": str(row.get("end_date", "")),
                    "holder_num": hn,
                }
            )
            holder_nums.append(hn)

        if len(holder_nums) >= 2:
            trend: HolderTrend = _classify_holder_trend(
                latest=holder_nums[-1], earliest=holder_nums[0]
            )
        else:
            trend = "stable"

        return {
            "ts_code": a.ts_code,
            "recent_holder_nums": recent,
            "trend": trend,
        }

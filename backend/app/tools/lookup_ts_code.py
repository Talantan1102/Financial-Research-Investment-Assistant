"""LookupTsCodeTool —— 股票名 → ts_code(薄包 TushareService.get_stock_basic)。

填缺口:数据集题面是股票名,数据工具要 ts_code。解锁多股题(组合/估值)让模型先查代码。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from app.tools.base import Tool, ToolError

if TYPE_CHECKING:
    from app.services.tushare_service import TushareService


class LookupTsCodeArgs(BaseModel):
    name: str  # 股票简称,如 "贝达药业"


class LookupTsCodeTool(Tool):
    """按股票简称查 ts_code(A 股)。多股题先用它把名换成代码再调数据工具。"""

    name = "lookup_ts_code"
    description = "按股票简称查 ts_code(如 '贝达药业' → '300558.SZ')。多股题先查代码再取数。"
    args_schema = LookupTsCodeArgs

    def __init__(self, tushare: TushareService | None = None) -> None:
        self._tushare = tushare

    async def run(self, args: BaseModel) -> dict[str, Any]:
        v = LookupTsCodeArgs.model_validate(args.model_dump())
        if self._tushare is None:
            raise ToolError("tushare not configured")
        try:
            df = await self._tushare.get_stock_basic()
        except Exception as exc:  # noqa: BLE001
            raise ToolError(f"get_stock_basic failed: {exc}") from exc
        if df is None or df.empty or "name" not in df.columns:
            raise ToolError("stock_basic 无数据")
        hit = df[df["name"] == v.name]
        if hit.empty:
            raise ToolError(f"未找到股票简称 {v.name!r} 对应的 ts_code")
        return {"name": v.name, "ts_code": str(hit.iloc[0]["ts_code"])}


__all__ = ["LookupTsCodeTool", "LookupTsCodeArgs"]

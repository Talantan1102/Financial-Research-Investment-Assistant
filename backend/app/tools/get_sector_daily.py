"""GetSectorDailyTool — 个股行业归属 + 板块当日涨跌。

实现步骤:
  1. 接收个股 ts_code;
  2. 调 get_stock_basic 取 industry 字段;
  3. 用内置 _INDUSTRY_TO_SW 映射行业名 → 申万行业指数代码;
  4. 调 get_sw_index_daily 取该行业指数当日 pct_chg;
  5. 若行业未在映射表内,返回 {industry, pct_chg: None} + note。

注:申万行业指数代码格式 xxxxxx.SI。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandas as pd
from pydantic import BaseModel

from app.tools.base import Tool

if TYPE_CHECKING:
    from app.services.tushare_service import TushareService

# ---------------------------------------------------------------------------
# 申万行业名 → 申万一级行业指数代码(常见覆盖)
# 申万指数代码以 .SI 结尾(Shenwan Industry)
# ---------------------------------------------------------------------------

_INDUSTRY_TO_SW: dict[str, str] = {
    "白酒": "801120.SI",       # 食品饮料(白酒归属)
    "食品饮料": "801120.SI",
    "银行": "801780.SI",
    "新能源": "801200.SI",     # 电力设备(含新能源)
    "电力设备": "801200.SI",
    "半导体": "801080.SI",     # 电子
    "电子": "801080.SI",
    "医药": "801150.SI",       # 医药生物
    "医药生物": "801150.SI",
    "生物医药": "801150.SI",
    "汽车": "801880.SI",
    "计算机": "801750.SI",
    "传媒": "801760.SI",
    "通信": "801770.SI",
    "军工": "801740.SI",       # 国防军工
    "国防军工": "801740.SI",
    "钢铁": "801040.SI",
    "煤炭": "801050.SI",
    "有色金属": "801020.SI",
    "化工": "801030.SI",       # 基础化工
    "基础化工": "801030.SI",
    "建筑材料": "801710.SI",
    "建筑装饰": "801720.SI",
    "房地产": "801180.SI",
    "商业贸易": "801200.SI",   # 商贸零售
    "商贸零售": "801200.SI",
    "家用电器": "801110.SI",
    "纺织服装": "801130.SI",
    "农林牧渔": "801010.SI",
    "非银金融": "801790.SI",
    "证券": "801790.SI",
    "保险": "801790.SI",
    "交通运输": "801170.SI",
    "机械设备": "801890.SI",
    "电气设备": "801730.SI",
    "公用事业": "801160.SI",
    "轻工制造": "801140.SI",
    "石油石化": "801020.SI",
    "环保": "801210.SI",
    "社会服务": "801230.SI",
    "综合": "801230.SI",
}


class SectorDailyArgs(BaseModel):
    ts_code: str         # 个股代码,如 "600519.SH"
    trade_date: str      # YYYYMMDD,查询当日


def _format_sector(
    industry: str,
    index_code: str | None,
    pct_chg: float | None,
) -> dict[str, Any]:
    """DataFrame → 结构化 dict(纯函数,可单测,不碰网络/LLM)。"""
    result: dict[str, Any] = {
        "industry": industry,
        "index_code": index_code,
        "pct_chg": pct_chg,
    }
    if index_code is None:
        result["note"] = "该行业指数未配置"
    return result


class GetSectorDailyTool(Tool):
    name = "get_sector_daily"
    description = (
        "查个股所属行业 + 该板块当日涨跌幅(申万一级行业指数)。"
        "持仓监控里看某只股票所在板块今日表现时用。"
    )
    args_schema = SectorDailyArgs

    def __init__(self, tushare: TushareService | None = None) -> None:
        if tushare is None:
            from app.services.tushare_factory import build_tushare_service
            tushare = build_tushare_service()
        self._tushare = tushare

    async def run(self, args: BaseModel) -> dict[str, Any]:
        a = SectorDailyArgs.model_validate(args.model_dump())

        # 1. 取个股行业
        basic = await self._tushare.get_stock_basic(ts_code=a.ts_code)
        if basic is None or basic.empty:
            return _format_sector("未知", None, None)
        industry = str(basic.iloc[0]["industry"])

        # 2. 映射行业 → 申万指数代码
        index_code = _INDUSTRY_TO_SW.get(industry)
        if index_code is None:
            return _format_sector(industry, None, None)

        # 3. 取行业指数当日涨跌
        df = await self._tushare.get_sw_index_daily(
            index_code=index_code, trade_date=a.trade_date
        )
        if df is None or df.empty:
            return _format_sector(industry, index_code, None)

        pct_chg = float(df.iloc[0]["pct_chg"])
        return _format_sector(industry, index_code, pct_chg)

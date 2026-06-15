"""GetSectorDailyTool — 个股行业归属 + 板块当日涨跌。

实现步骤:
  1. 接收个股 ts_code;
  2. 调 get_stock_basic 取 industry 字段;
  3. 用内置 _INDUSTRY_TO_SW 映射行业名 → 申万一级行业指数代码;
  4. 调 get_sw_index_daily 取该行业指数当日 pct_change;
  5. 若行业未在映射表内,返回 {industry, pct_chg: None} + note。

注:申万行业指数代码格式 xxxxxx.SI。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from app.tools.base import Tool

if TYPE_CHECKING:
    from app.services.tushare_service import TushareService

# ---------------------------------------------------------------------------
# tushare stock_basic.industry(tushare 自有行业分类,共 110 类)→ 申万一级行业指数代码。
# 申万一级代码经真 tushare index_classify(level=L1, SW2021)核对;110 个 key 来自
# 真 tushare stock_basic 全市场 distinct industry(2026-06 拉取,覆盖 5500+ 股)。
# 申万指数代码以 .SI 结尾(Shenwan Industry)。少数归类为判断(电器仪表/运输设备/
# 日用化工/航空/广告包装等),取最接近的申万一级。
# ---------------------------------------------------------------------------

_INDUSTRY_TO_SW: dict[str, str] = {
    # 农林牧渔 801010
    "农业综合": "801010.SI",
    "种植业": "801010.SI",
    "饲料": "801010.SI",
    "渔业": "801010.SI",
    "林业": "801010.SI",
    # 基础化工 801030
    "化工原料": "801030.SI",
    "塑料": "801030.SI",
    "农药化肥": "801030.SI",
    "染料涂料": "801030.SI",
    "化纤": "801030.SI",
    "橡胶": "801030.SI",
    # 钢铁 801040
    "普钢": "801040.SI",
    "钢加工": "801040.SI",
    "特种钢": "801040.SI",
    # 有色金属 801050
    "小金属": "801050.SI",
    "铝": "801050.SI",
    "铜": "801050.SI",
    "铅锌": "801050.SI",
    "黄金": "801050.SI",
    # 电子 801080
    "元器件": "801080.SI",
    "半导体": "801080.SI",
    # 家用电器 801110
    "家用电器": "801110.SI",
    # 食品饮料 801120
    "食品": "801120.SI",
    "乳制品": "801120.SI",
    "白酒": "801120.SI",
    "软饮料": "801120.SI",
    "红黄酒": "801120.SI",
    "啤酒": "801120.SI",
    # 纺织服饰 801130
    "服饰": "801130.SI",
    "纺织": "801130.SI",
    # 轻工制造 801140
    "家居用品": "801140.SI",
    "广告包装": "801140.SI",
    "造纸": "801140.SI",
    # 医药生物 801150
    "医疗保健": "801150.SI",
    "化学制药": "801150.SI",
    "生物制药": "801150.SI",
    "中成药": "801150.SI",
    "医药商业": "801150.SI",
    # 公用事业 801160
    "供气供热": "801160.SI",
    "火力发电": "801160.SI",
    "新型电力": "801160.SI",
    "水力发电": "801160.SI",
    "水务": "801160.SI",
    # 交通运输 801170
    "仓储物流": "801170.SI",
    "水运": "801170.SI",
    "港口": "801170.SI",
    "空运": "801170.SI",
    "铁路": "801170.SI",
    "公共交通": "801170.SI",
    "机场": "801170.SI",
    "公路": "801170.SI",
    # 房地产 801180
    "区域地产": "801180.SI",
    "全国地产": "801180.SI",
    "园区开发": "801180.SI",
    "房产服务": "801180.SI",
    # 商贸零售 801200
    "百货": "801200.SI",
    "商贸代理": "801200.SI",
    "其他商业": "801200.SI",
    "超市连锁": "801200.SI",
    "批发业": "801200.SI",
    "商品城": "801200.SI",
    "电器连锁": "801200.SI",
    # 社会服务 801210
    "文教休闲": "801210.SI",
    "旅游景点": "801210.SI",
    "酒店餐饮": "801210.SI",
    "旅游服务": "801210.SI",
    # 综合 801230
    "综合类": "801230.SI",
    # 建筑材料 801710
    "矿物制品": "801710.SI",
    "其他建材": "801710.SI",
    "玻璃": "801710.SI",
    "水泥": "801710.SI",
    "陶瓷": "801710.SI",
    # 建筑装饰 801720
    "建筑工程": "801720.SI",
    "装修装饰": "801720.SI",
    "路桥": "801720.SI",
    # 电力设备 801730
    "电气设备": "801730.SI",
    "电器仪表": "801730.SI",
    # 国防军工 801740
    "航空": "801740.SI",
    "船舶": "801740.SI",
    # 计算机 801750
    "软件服务": "801750.SI",
    "IT设备": "801750.SI",
    "互联网": "801750.SI",
    # 传媒 801760
    "影视音像": "801760.SI",
    "出版业": "801760.SI",
    # 通信 801770
    "通信设备": "801770.SI",
    "电信运营": "801770.SI",
    # 银行 801780
    "银行": "801780.SI",
    # 非银金融 801790
    "证券": "801790.SI",
    "多元金融": "801790.SI",
    "保险": "801790.SI",
    # 汽车 801880
    "汽车配件": "801880.SI",
    "汽车整车": "801880.SI",
    "摩托车": "801880.SI",
    "汽车服务": "801880.SI",
    # 机械设备 801890
    "专用机械": "801890.SI",
    "机械基件": "801890.SI",
    "工程机械": "801890.SI",
    "机床制造": "801890.SI",
    "农用机械": "801890.SI",
    "化工机械": "801890.SI",
    "纺织机械": "801890.SI",
    "轻工机械": "801890.SI",
    "运输设备": "801890.SI",
    # 煤炭 801950
    "煤炭开采": "801950.SI",
    "焦炭加工": "801950.SI",
    # 石油石化 801960
    "石油开采": "801960.SI",
    "石油加工": "801960.SI",
    "石油贸易": "801960.SI",
    # 环保 801970
    "环境保护": "801970.SI",
    # 美容护理 801980
    "日用化工": "801980.SI",
}


class SectorDailyArgs(BaseModel):
    ts_code: str  # 个股代码,如 "600519.SH"
    trade_date: str  # YYYYMMDD,查询当日


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
        df = await self._tushare.get_sw_index_daily(index_code=index_code, trade_date=a.trade_date)
        if df is None or df.empty:
            return _format_sector(industry, index_code, None)

        # 申万 sw_daily 涨跌幅列名是 pct_change(不是 pct_chg)
        col = "pct_change" if "pct_change" in df.columns else "pct_chg"
        pct_chg = float(df.iloc[0][col])
        return _format_sector(industry, index_code, pct_chg)

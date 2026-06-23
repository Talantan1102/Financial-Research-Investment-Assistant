"""出题机主循环:意图 × 股票 × 指标 × 窗口 → 取真数据算 canonical gold → ComputationCase。

spec: docs/superpowers/specs/2026-06-17-question-gen-mvp-design.md
- 窗口由 trade_cal 的 window 动作确定化(与 agent 取同一段交易日 → 口径对齐 method B 的前提);
- gold 用真 tushare 数据 + indicator_oracle(经 operators)算;%-指标 gold 存成百分数(×100,与 agent 答法一致);
- 真实性闸:合法配对矩阵 + 同板块相关配对 + 复杂档只 ≥3 板块(闸①②;闸③留后期)。
离线跑一次:`python -m eval.question_gen.generator`(需 TUSHARE_MODE=real + .env)。
"""

from __future__ import annotations

import asyncio
import itertools
import json
import statistics
from pathlib import Path

from app.agents.valuation_helpers.exceptions import InsufficientDataForModelError
from app.agents.valuation_helpers.pb import compute_pb_value
from app.agents.valuation_helpers.pe import compute_pe_value
from app.services.portfolio_analytics import (
    DailySnap,
    HoldingDaily,
    compute_daily_attribution,
    compute_twr,
)

from eval.question_gen import case, intents, legality, operators, stock_pool

_AS_OF_DEFAULT = (
    "20260612"  # 钉到已落定的历史交易日(非"今天"):窗口不含移动/未回填的近端 bar → gold 可复现
)
_OUT_DEFAULT = Path(__file__).resolve().parent / "data" / "computation_cases.jsonl"

# 容差(承 caliber-freeze;gold 存百分数,故对百分数比)
_TOL = {
    # 涨幅/CAGR 可能接近零 → rel_mult(比"价格变成几倍",接近零不被相对误差放大)
    "涨幅": {"kind": "rel_mult", "value": 0.005},
    "回撤": {"kind": "rel", "value": 0.005},
    "波动": {"kind": "rel", "value": 0.02},
    "相关": {"kind": "abs", "value": 0.01},
    "CAGR": {"kind": "rel_mult", "value": 0.01},
}
_TOL_DUAL = {"kind": "rel", "value": 0.02}  # 双指标(回撤+波动)统一取较松的
_WINDOW_YEARS = {"3m": 0.25, "1y": 1.0, "3y": 3.0}
_PCT_INDICATORS = {"涨幅", "回撤", "波动", "CAGR"}  # gold ×100 存百分数

_SNAPSHOT_INDICATORS = ("PE", "PB", "换手率", "股息率")
_SNAPSHOT_TOL = {
    "PE": {"kind": "rel", "value": 0.01},
    "PB": {"kind": "rel", "value": 0.01},
    "换手率": {"kind": "rel", "value": 0.02},
    "股息率": {"kind": "rel", "value": 0.02},
}
_SNAPSHOT_COLS = ("pe", "pb", "turnover_rate", "dv_ratio")

_FINANCIAL_INDICATORS = ("ROE", "资产负债率", "毛利率", "营收", "净利")
_FINANCIAL_TOL = {ind: {"kind": "rel", "value": 0.01} for ind in _FINANCIAL_INDICATORS}
_FINA_COLS = ("roe", "debt_to_assets", "grossprofit_margin", "q_sales_yoy", "netprofit_yoy")
_INCOME_COLS = ("revenue", "n_income")

# 财报核对:只核对金额类(营收/净利),容差 ±1%
_VERIFY_INDICATORS = ("营收", "净利")
_VERIFY_TOL = {"kind": "rel", "value": 0.01}

# 异动信号(同比增速):营收/净利同比,gold 直取预算字段(%),容差 ±1%
_TREND_INDICATORS = ("营收同比", "净利同比")
_TREND_TOL = {"kind": "rel", "value": 0.01}


async def _resolve_window(as_of: str, code: str) -> tuple[str, str]:
    """调 trade_cal 的 window 动作把周期码解析成确定的 (start, end)。"""
    from app.mcp_server.tools.trade_cal import handle

    out = await handle({"action": "window", "anchor": as_of, "lookback": code})
    payload = json.loads(out[0].text)
    if "error" in payload:
        raise RuntimeError(f"window 解析失败 {code}: {payload['error']}")
    return payload["start"], payload["end"]


async def _fetch(tushare, ts_code: str, start: str, end: str) -> dict:
    """取真 tushare 日线 → {close, dates, pct_chg}(按 trade_date 升序)。"""
    df = await tushare.get_daily(ts_code=ts_code, start=start, end=end)
    df = df.sort_values("trade_date")
    return {
        "close": [float(x) for x in df["close"].tolist()],
        "dates": [str(x) for x in df["trade_date"].tolist()],
        "pct_chg": [float(x) for x in df["pct_chg"].tolist()],
    }


def _scale(indicator: str, value: float) -> float:
    """%-指标 ×100 存成百分数(与 agent 答法一致);相关不变。"""
    return value * 100.0 if indicator in _PCT_INDICATORS else value


async def _fetch_snapshot(tushare, ts_code: str, trade_date: str) -> dict:
    """取真 tushare daily_basic 的某交易日一行 → {pe, pb, turnover_rate, dv_ratio}(值可能为 None/NaN)。"""
    df = await tushare.get_daily_basic(ts_code=ts_code, trade_date=trade_date)
    if len(df) == 0:
        raise RuntimeError(f"daily_basic 无数据:{ts_code} @ {trade_date}")
    row = df.iloc[0]
    return {col: row[col] for col in _SNAPSHOT_COLS}


async def build_snapshot_cases(
    tushare,
    as_of: str,
    cid,
    pool: tuple[stock_pool.Stock, ...] = stock_pool.POOL,
) -> list[case.ComputationCase]:
    """行情快照取数(简单档,无窗口):每只股取 as_of 当日 daily_basic → 4 个直取指标。

    tushare 依赖注入(可塞 stub 单测);cid 是 case_id 生成器 callable。
    gold = 直取字段值(换手率/股息率 tushare 已是百分数,不 scale)。
    pool 默认全局 POOL，可注入子集。
    """
    out: list[case.ComputationCase] = []
    for st in pool:
        snap = await _fetch_snapshot(tushare, st.ts_code, as_of)
        for ind in _SNAPSHOT_INDICATORS:
            gold = operators.snapshot_lookup(ind, snap)
            if gold is None:  # 该股该指标无值(如亏损股无 PE),跳过
                continue
            out.append(
                case.ComputationCase(
                    case_id=cid(f"快照{ind}-{st.ts_code}"),
                    intent=intents.INTENT_SNAPSHOT,
                    difficulty="简单",
                    question=intents.q_snapshot(st.name, ind, as_of),
                    stocks=[st.ts_code],
                    indicator=ind,
                    window="snapshot",
                    gold=gold,
                    gold_shape="scalar",
                    tolerance=_SNAPSHOT_TOL[ind],
                    meta={"trade_date": as_of, "as_of": as_of},
                )
            )
    return out


def _select_period_row(df, end_date: str):
    """从多期历史 DataFrame 里选 end_date 匹配的那一行;无则 None。"""
    if len(df) == 0 or "end_date" not in df.columns:
        return None
    rows = df[df["end_date"].astype(str) == end_date]
    return None if len(rows) == 0 else rows.iloc[0]


async def _fetch_financial(tushare, ts_code: str, query_date: str, period_end: str) -> dict:
    """取 fina_indicator + income(用 query_date 查,确保目标期已披露),按 period_end 选行。"""
    fi = await tushare.get_fina_indicator(ts_code=ts_code, end_date=query_date)
    inc = await tushare.get_income(ts_code=ts_code, end_date=query_date)
    snap: dict = {}
    frow = _select_period_row(fi, period_end)
    if frow is not None:
        for c in _FINA_COLS:
            snap[c] = frow[c] if c in fi.columns else None
    irow = _select_period_row(inc, period_end)
    if irow is not None:
        for c in _INCOME_COLS:
            snap[c] = irow[c] if c in inc.columns else None
    return snap


async def build_financial_cases(
    tushare,
    as_of: str,
    period_end: str,
    period_label: str,
    cid,
    pool: tuple[stock_pool.Stock, ...] = stock_pool.POOL,
) -> list[case.ComputationCase]:
    """财报取数(简单档):用 as_of 查询(确保目标期已披露),取 period_end 期的 5 个直取指标。

    tushare 依赖注入;空值/缺期指标跳过。营收/净利 gold 已是亿元。
    pool 默认全局 POOL，可注入子集。
    """
    out: list[case.ComputationCase] = []
    for st in pool:
        snap = await _fetch_financial(tushare, st.ts_code, as_of, period_end)
        for ind in _FINANCIAL_INDICATORS:
            gold = operators.financial_lookup(ind, snap)
            if gold is None:
                continue
            out.append(
                case.ComputationCase(
                    case_id=cid(f"财报{ind}-{st.ts_code}"),
                    intent=intents.INTENT_FINANCIAL,
                    difficulty="简单",
                    question=intents.q_financial(st.name, ind, period_label),
                    stocks=[st.ts_code],
                    indicator=ind,
                    window=period_label,
                    gold=gold,
                    gold_shape="scalar",
                    tolerance=_FINANCIAL_TOL[ind],
                    meta={"period_end": period_end, "period_label": period_label},
                )
            )
    return out


async def build_verify_cases(
    tushare,
    as_of: str,
    period_end: str,
    period_label: str,
    cid,
    pool: tuple[stock_pool.Stock, ...] = stock_pool.POOL,
) -> list[case.ComputationCase]:
    """财报核对(简单档):题面嵌一个声称值(真值×1.05),gold=tushare 真实营收/净利(亿)。

    结构同 build_financial_cases:取 income(按 period_end 选行),仅核对金额类(营收/净利)。
    tushare 依赖注入;空值/缺期指标跳过。gold 是真值(不是声称值),容差 ±1%。
    pool 默认全局 POOL,可注入子集。
    """
    out: list[case.ComputationCase] = []
    for st in pool:
        snap = await _fetch_financial(tushare, st.ts_code, as_of, period_end)
        for ind in _VERIFY_INDICATORS:
            gold = operators.financial_verify_real(ind, snap)
            if gold is None:
                continue
            claimed = round(gold * 1.05, 2)  # 真值 ±5% 扰动(此处偏高 5%)
            out.append(
                case.ComputationCase(
                    case_id=cid(f"核对{ind}-{st.ts_code}"),
                    intent=intents.INTENT_FINANCIAL_VERIFY,
                    difficulty="简单",
                    question=intents.q_verify(
                        st.name, intents._VERIFY_LABELS[ind], claimed, period_label
                    ),
                    stocks=[st.ts_code],
                    indicator=ind,
                    window=period_label,
                    gold=gold,
                    gold_shape="scalar",
                    tolerance=_VERIFY_TOL,
                    meta={
                        "period_end": period_end,
                        "period_label": period_label,
                        "claimed": claimed,
                    },
                )
            )
    return out


async def build_trend_cases(
    tushare,
    as_of: str,
    period_end: str,
    period_label: str,
    cid,
    pool: tuple[stock_pool.Stock, ...] = stock_pool.POOL,
) -> list[case.ComputationCase]:
    """异动信号(中等档):营收同比 + 净利同比,gold 直取 fina_indicator 预算字段(%)。

    结构同 build_financial_cases:复用 _fetch_financial 取 fina_indicator 行
    (q_sales_yoy/netprofit_yoy 已并入 _FINA_COLS,一并落进 snap);按 period_end 选行。
    tushare 依赖注入;空值/缺期指标跳过。gold 已是百分数,容差 ±1%。
    pool 默认全局 POOL,可注入子集。
    """
    out: list[case.ComputationCase] = []
    for st in pool:
        snap = await _fetch_financial(tushare, st.ts_code, as_of, period_end)
        for ind in _TREND_INDICATORS:
            gold = operators.trend_lookup(ind, snap)
            if gold is None:
                continue
            out.append(
                case.ComputationCase(
                    case_id=cid(f"异动{ind}-{st.ts_code}"),
                    intent=intents.INTENT_TREND_SIGNAL,
                    difficulty="中等",
                    question=intents.q_trend(st.name, intents._TREND_LABELS[ind], period_label),
                    stocks=[st.ts_code],
                    indicator=ind,
                    window=period_label,
                    gold=gold,
                    gold_shape="scalar",
                    tolerance=_TREND_TOL,
                    meta={"period_end": period_end, "period_label": period_label},
                )
            )
    return out


_POSITION_TOL = {"kind": "rel", "value": 0.005}


async def _fetch_close(tushare, ts_code: str, trade_date: str) -> float | None:
    """取 daily_basic 某交易日收盘价;无/空 则 None。"""
    df = await tushare.get_daily_basic(ts_code=ts_code, trade_date=trade_date)
    if len(df) == 0 or "close" not in df.columns:
        return None
    val = df.iloc[0]["close"]
    if val is None or (isinstance(val, float) and val != val):
        return None
    return float(val)


async def build_position_cases(
    tushare,
    as_of: str,
    cid,
    pool: tuple[stock_pool.Stock, ...] = stock_pool.POOL,
) -> list[case.ComputationCase]:
    """单仓持仓量(简单档):合成 qty/cost(确定性)+ 真收盘价。close 缺则跳过该股。

    pool 默认全局 POOL，可注入子集。
    """
    out: list[case.ComputationCase] = []
    for i, st in enumerate(pool):
        close = await _fetch_close(tushare, st.ts_code, as_of)
        if close is None:
            continue
        qty = 100 * (i + 1)
        cost = round(close * 0.85, 2)
        out.append(
            case.ComputationCase(
                case_id=cid(f"市值-{st.ts_code}"),
                intent=intents.INTENT_POSITION,
                difficulty="简单",
                question=intents.q_position_value(st.name, qty, as_of),
                stocks=[st.ts_code],
                indicator="单仓市值",
                window="snapshot",
                gold=round(operators.position_market_value(qty, close), 2),
                gold_shape="scalar",
                tolerance=_POSITION_TOL,
                meta={"trade_date": as_of, "qty": qty, "close": close},
            )
        )
        out.append(
            case.ComputationCase(
                case_id=cid(f"浮盈-{st.ts_code}"),
                intent=intents.INTENT_POSITION,
                difficulty="简单",
                question=intents.q_position_pnl(st.name, qty, cost, as_of),
                stocks=[st.ts_code],
                indicator="单仓浮盈",
                window="snapshot",
                gold=round(operators.position_pnl(qty, close, cost), 2),
                gold_shape="scalar",
                tolerance=_POSITION_TOL,
                meta={"trade_date": as_of, "qty": qty, "cost": cost, "close": close},
            )
        )
    return out


async def build_portfolio_cases(
    tushare,
    as_of: str,
    cid,
    pool: tuple[stock_pool.Stock, ...] = stock_pool.POOL,
) -> list[case.ComputationCase]:
    """组合权重 + HHI(中等档):按板块构造合成篮子(qty 100,200,...)+ 真收盘价。

    任一成员 close 缺则跳过该板块(保权重口径一致)。
    pool 默认全局 POOL，可注入子集。
    """
    out: list[case.ComputationCase] = []
    for sector, members in stock_pool.by_sector(pool).items():
        if len(members) < 2:
            continue
        mvs: list[float] = []
        descs: list[str] = []
        ok = True
        for j, m in enumerate(members):
            close = await _fetch_close(tushare, m.ts_code, as_of)
            if close is None:
                ok = False
                break
            qty = 100 * (j + 1)
            mvs.append(qty * close)
            descs.append(f"{m.name}{qty}股")
        if not ok or len(mvs) < 2:
            continue
        weights = operators.portfolio_weights(mvs)
        basket = "、".join(descs)
        out.append(
            case.ComputationCase(
                case_id=cid(f"权重-{sector}"),
                intent=intents.INTENT_PORTFOLIO,
                difficulty="中等",
                question=intents.q_portfolio_weight(basket, members[0].name, as_of),
                stocks=[m.ts_code for m in members],
                indicator="持仓权重",
                window="snapshot",
                gold=round(weights[0] * 100, 4),
                gold_shape="scalar",
                tolerance={"kind": "rel", "value": 0.01},
                meta={"trade_date": as_of, "板块": sector},
            )
        )
        out.append(
            case.ComputationCase(
                case_id=cid(f"HHI-{sector}"),
                intent=intents.INTENT_PORTFOLIO,
                difficulty="中等",
                question=intents.q_portfolio_hhi(basket, as_of),
                stocks=[m.ts_code for m in members],
                indicator="HHI",
                window="snapshot",
                gold=round(operators.portfolio_hhi(weights), 4),
                gold_shape="scalar",
                tolerance={"kind": "rel", "value": 0.02},
                meta={"trade_date": as_of, "板块": sector},
            )
        )
    return out


# 难档 portfolio_calc(TWR + 三层归因):统计/链式量,容差给稍宽 ±2%
_PORTFOLIO_ADV_TOL = {"kind": "rel", "value": 0.02}
# 取最近 3 连续交易日:复用 generate() 已解析/缓存的 3m 窗口码(避免新增 lookback 码),
# 取该窗口日线的末 3 根 bar 即可(无需精确"近 N 交易日"窗口)。
_TWR_LOOKBACK = "3m"
_TWR_DAYS = 3


async def _fetch_recent_bars(
    tushare, ts_code: str, start: str, end: str, n: int
) -> list[tuple[str, float, float]]:
    """取 [start, end] 窗口内日线,返回末 n 根 (trade_date, close, pct_chg)(升序)。

    复用 _fetch(get_daily,按 trade_date 升序);不足 n 根则原样返回(调用方判长度)。
    """
    d = await _fetch(tushare, ts_code, start, end)
    dates, closes, pcts = d["dates"], d["close"], d["pct_chg"]
    rows = list(zip(dates, closes, pcts))
    return rows[-n:]


async def build_portfolio_advanced_cases(
    tushare,
    as_of: str,
    cid,
    pool: tuple[stock_pool.Stock, ...] = stock_pool.POOL,
) -> list[case.ComputationCase]:
    """账户真实收益 TWR(按板块) + 赚钱来源三层归因(跨板块,难档,复杂,requires_run_python)。

      (A) TWR:对每个 ≥2 成员的板块合成一篮(qty 第 j 只 = 100*(j+1)),取各股最近 3 连续
          交易日 close,qty 全程不变(无加减仓 → 纯市场 TWR);
          gold = compute_twr(snaps)["cumulative"]*100(百分数),scalar。
      (B) 三层归因(单道,跨板块):从前 2 个「≥2 成员」板块各取前 2 只凑一篮(≤4 仓),
          这样三层都非平凡——market_pct = 全篮等权、各 sector_pct = 各自板块对内等权
          (≠ market → 行业超额非 0)、idio = 个股 − 所属板块。
          today_pct = as_of 当日 pct_chg;基准冻进题面避免引指数接口;
          gold = compute_daily_attribution(holdings).stock_breakdown(三标签),multi_scalar。
          凑不出「≥2 板块 × ≥2 成员」则跳过归因题(只出 TWR,不报错)。

    任一成员取价不足 3 根 / 无数据则跳过该板块(保口径一致)。
    pool 默认全局 POOL,可注入子集。
    """
    start, end = await _resolve_window(as_of, _TWR_LOOKBACK)
    out: list[case.ComputationCase] = []
    by_sec = stock_pool.by_sector(pool)
    # 跨板块归因篮子:按板块出现顺序收集「≥2 成员」板块,取前 2 个、各前 2 只。
    attr_basket: list[stock_pool.Stock] = []

    for sector, members in by_sec.items():
        if len(members) < 2:
            continue
        # 每只股的末 3 根 bar(date, close, pct_chg)
        bars: dict[str, list[tuple[str, float, float]]] = {}
        qty_of: dict[str, int] = {}
        descs: list[str] = []
        ok = True
        for j, m in enumerate(members):
            rows = await _fetch_recent_bars(tushare, m.ts_code, start, end, _TWR_DAYS)
            if len(rows) < _TWR_DAYS:
                ok = False
                break
            bars[m.ts_code] = rows
            qty_of[m.ts_code] = 100 * (j + 1)
            descs.append(f"{m.name}{qty_of[m.ts_code]}股")
        if not ok:
            continue
        basket = "、".join(descs)
        # 3 连续交易日端点(各股窗口对齐,取首只的日期序列即可)
        ref_dates = [r[0] for r in bars[members[0].ts_code]]
        d0, d2 = ref_dates[0], ref_dates[-1]

        # ---- (A) TWR(按板块) ----
        snaps = [
            DailySnap(
                date=ref_dates[i],
                holdings={m.ts_code: (qty_of[m.ts_code], bars[m.ts_code][i][1]) for m in members},
            )
            for i in range(_TWR_DAYS)
        ]
        twr_gold = round(compute_twr(snaps)["cumulative"] * 100, 6)
        out.append(
            case.ComputationCase(
                case_id=cid(f"TWR-{sector}"),
                intent=intents.INTENT_PORTFOLIO,
                difficulty="复杂",
                question=intents.q_portfolio_twr(basket, d0, d2),
                stocks=[m.ts_code for m in members],
                indicator="账户TWR",
                window=f"{d0}~{d2}",
                gold=twr_gold,
                gold_shape="scalar",
                tolerance=_PORTFOLIO_ADV_TOL,
                meta={"板块": sector, "window_dates": [d0, d2], "as_of": as_of},
                requires_run_python=True,
            )
        )

        # 攒跨板块归因篮子:前 2 个「≥2 成员」板块,各前 2 只成员。
        if len(attr_basket) < 4:
            attr_basket.extend(members[:2])

    # ---- (B) 三层归因(单道,跨板块) ----
    attr_sectors = {st.sector for st in attr_basket}
    if len(attr_sectors) >= 2:
        # 篮内 qty 按全局顺序 100*(j+1);末日 close + 当日 pct_chg 取该股的末根 bar。
        member_bars: dict[str, list[tuple[str, float, float]]] = {}
        ok = True
        for st in attr_basket:
            rows = await _fetch_recent_bars(tushare, st.ts_code, start, end, _TWR_DAYS)
            if len(rows) < _TWR_DAYS:
                ok = False
                break
            member_bars[st.ts_code] = rows
        if ok:
            qty_of2 = {st.ts_code: 100 * (j + 1) for j, st in enumerate(attr_basket)}
            today_pct = {st.ts_code: member_bars[st.ts_code][-1][2] for st in attr_basket}
            last_close = {st.ts_code: member_bars[st.ts_code][-1][1] for st in attr_basket}
            descs2 = [f"{st.name}{qty_of2[st.ts_code]}股" for st in attr_basket]
            basket2 = "、".join(descs2)
            # market_pct = 全篮等权;sector_pct = 各自板块内成员等权(跨板块 → 二者不等)。
            market_pct = statistics.mean(today_pct.values())
            sector_pct_of: dict[str, float] = {}
            for sec in attr_sectors:
                vals = [today_pct[st.ts_code] for st in attr_basket if st.sector == sec]
                sector_pct_of[sec] = statistics.mean(vals)
            holdings = [
                HoldingDaily(
                    ts_code=st.ts_code,
                    asset_class="stock",
                    market_value=qty_of2[st.ts_code] * last_close[st.ts_code],
                    today_pct=today_pct[st.ts_code],
                    sector=st.sector,
                    sector_pct=sector_pct_of[st.sector],
                    market_pct=market_pct,
                )
                for st in attr_basket
            ]
            attr_gold = compute_daily_attribution(holdings).stock_breakdown
            out.append(
                case.ComputationCase(
                    case_id=cid("归因-跨板块"),
                    intent=intents.INTENT_PORTFOLIO,
                    difficulty="复杂",
                    question=intents.q_portfolio_attribution(basket2, as_of),
                    stocks=[st.ts_code for st in attr_basket],
                    indicator="收益归因",
                    window="snapshot",
                    gold=attr_gold,
                    gold_shape="multi_scalar",
                    tolerance=_PORTFOLIO_ADV_TOL,
                    meta={
                        "板块": sorted(attr_sectors),
                        "trade_date": as_of,
                        "as_of": as_of,
                    },
                    requires_run_python=True,
                )
            )
    return out


_VALUATION_TOL = {"kind": "rel", "value": 0.01}


def _finite_positive(val) -> float | None:
    """None/NaN/<=0 -> None;否则 float。"""
    if val is None:
        return None
    f = float(val)
    if f != f or f <= 0:  # NaN 或 <=0
        return None
    return f


async def build_valuation_cases(
    tushare,
    as_of: str,
    period_end: str,
    period_label: str,
    cid,
    pool: tuple[stock_pool.Stock, ...] = stock_pool.POOL,
) -> list[case.ComputationCase]:
    """估值算式(中等档):板块同行聚合 PE/PB(avg+median)+ 个股 eps/bps -> 理论价。

    题面明示可比篮子;eps/bps 缺或 compute 抛 InsufficientDataForModelError -> 跳过。
    pool 默认全局 POOL，可注入子集。
    """
    out: list[case.ComputationCase] = []
    for sector, members in stock_pool.by_sector(pool).items():
        if len(members) < 2:
            continue
        pes: list[float] = []
        pbs: list[float] = []
        info: dict = {}
        for m in members:
            db = await tushare.get_daily_basic(ts_code=m.ts_code, trade_date=as_of)
            fi = await tushare.get_fina_indicator(ts_code=m.ts_code, end_date=as_of)
            frow = _select_period_row(fi, period_end)
            pe = _finite_positive(db.iloc[0]["pe"]) if len(db) and "pe" in db.columns else None
            pb = _finite_positive(db.iloc[0]["pb"]) if len(db) and "pb" in db.columns else None
            eps = None
            bps = None
            if frow is not None:
                eps = (
                    float(frow["eps"]) if "eps" in fi.columns and frow["eps"] is not None else None
                )
                bps = (
                    float(frow["bps"]) if "bps" in fi.columns and frow["bps"] is not None else None
                )
            info[m.ts_code] = {"name": m.name, "eps": eps, "bps": bps}
            if pe is not None:
                pes.append(pe)
            if pb is not None:
                pbs.append(pb)
        peer_names = "、".join(m.name for m in members)
        pe_avg = statistics.mean(pes) if len(pes) >= 2 else None
        pe_med = statistics.median(pes) if len(pes) >= 2 else None
        pb_avg = statistics.mean(pbs) if len(pbs) >= 2 else None
        pb_med = statistics.median(pbs) if len(pbs) >= 2 else None
        for m in members:
            d = info[m.ts_code]
            # PE 理论价
            if (
                pe_avg is not None
                and pe_med is not None
                and d["eps"] is not None
                and d["eps"] == d["eps"]
            ):
                try:
                    gold = compute_pe_value(
                        eps=d["eps"], industry_pe_avg=pe_avg, industry_pe_median=pe_med
                    )
                    out.append(
                        case.ComputationCase(
                            case_id=cid(f"PE理论价-{m.ts_code}"),
                            intent=intents.INTENT_VALUATION,
                            difficulty="中等",
                            question=intents.q_valuation(
                                m.name, "PE理论价", sector, peer_names, period_label
                            ),
                            stocks=[m.ts_code],
                            indicator="PE理论价",
                            window=period_label,
                            gold=round(gold, 4),
                            gold_shape="scalar",
                            tolerance=_VALUATION_TOL,
                            meta={"板块": sector, "period_end": period_end},
                        )
                    )
                except InsufficientDataForModelError:
                    pass
            # PB 理论价
            if (
                pb_avg is not None
                and pb_med is not None
                and d["bps"] is not None
                and d["bps"] == d["bps"]
            ):
                try:
                    gold = compute_pb_value(
                        book_value_per_share=d["bps"],
                        industry_pb_avg=pb_avg,
                        industry_pb_median=pb_med,
                    )
                    out.append(
                        case.ComputationCase(
                            case_id=cid(f"PB理论价-{m.ts_code}"),
                            intent=intents.INTENT_VALUATION,
                            difficulty="中等",
                            question=intents.q_valuation(
                                m.name, "PB理论价", sector, peer_names, period_label
                            ),
                            stocks=[m.ts_code],
                            indicator="PB理论价",
                            window=period_label,
                            gold=round(gold, 4),
                            gold_shape="scalar",
                            tolerance=_VALUATION_TOL,
                            meta={"板块": sector, "period_end": period_end},
                        )
                    )
                except InsufficientDataForModelError:
                    pass
    return out


# PE 历史分位(难档):分位是统计量,容差给稍宽 ±2%
_PERCENTILE_TOL = {"kind": "rel", "value": 0.02}
_PERCENTILE_WINDOW = "3y"
_PERCENTILE_WINDOW_CN = "三年"


async def _fetch_pe_history(tushare, ts_code: str, start: str, end: str) -> list[float]:
    """取 [start, end] 窗口内 daily_basic.pe 序列(按 trade_date 升序,去 None/NaN)。

    daily_basic 原生支持 start_date/end_date 区间(get_pe_history 内部即用此口径)。
    """
    df = await tushare.get_daily_basic(ts_code=ts_code, start_date=start, end_date=end)
    if len(df) == 0 or "pe" not in df.columns:
        return []
    if "trade_date" in df.columns:
        df = df.sort_values("trade_date")
    out: list[float] = []
    for v in df["pe"].tolist():
        if v is None or (isinstance(v, float) and v != v):  # None 或 NaN
            continue
        out.append(float(v))
    return out


async def build_percentile_cases(
    tushare,
    as_of: str,
    cid,
    pool: tuple[stock_pool.Stock, ...] = stock_pool.POOL,
) -> list[case.ComputationCase]:
    """PE 历史分位(难档,复杂,requires_run_python):现在的 PE 在最近三年历史里第几分位。

    history = 3 年窗 daily_basic.pe 序列;current = as_of 当日 pe;
    gold = operators.pe_percentile_lookup(history, current)(= oracle.pe_percentile×100)。
    序列为空 / 当日 pe 缺 → 跳过该股。答案应由 agent 写代码算 → requires_run_python=True。
    pool 默认全局 POOL,可注入子集。
    """
    start, end = await _resolve_window(as_of, _PERCENTILE_WINDOW)
    out: list[case.ComputationCase] = []
    for st in pool:
        history = await _fetch_pe_history(tushare, st.ts_code, start, end)
        if not history:
            continue
        snap = await _fetch_snapshot(tushare, st.ts_code, as_of)
        current = operators.snapshot_lookup("PE", snap)
        if current is None:
            continue
        gold = operators.pe_percentile_lookup(history, current)
        out.append(
            case.ComputationCase(
                case_id=cid(f"PE分位-{st.ts_code}"),
                intent=intents.INTENT_VALUATION_PERCENTILE,
                difficulty="复杂",
                question=intents.q_percentile(st.name, _PERCENTILE_WINDOW_CN),
                stocks=[st.ts_code],
                indicator="PE历史分位",
                window=_PERCENTILE_WINDOW,
                gold=gold,
                gold_shape="scalar",
                tolerance=_PERCENTILE_TOL,
                meta={
                    "window_dates": [start, end],
                    "as_of": as_of,
                    "current_pe": current,
                    "n_history": len(history),
                },
                requires_run_python=True,
            )
        )
    return out


async def generate(
    as_of: str = _AS_OF_DEFAULT,
    out_path: Path = _OUT_DEFAULT,
    pool: tuple[stock_pool.Stock, ...] = stock_pool.POOL,
    tushare=None,
) -> list[case.ComputationCase]:
    """完整出题管线。

    pool 默认全局 POOL，可注入子集（build_datasets 分 train/val/test 用）。
    tushare 可注入（测试用）；不传则从工厂构建。
    """
    if tushare is None:
        from app.services.tushare_factory import build_tushare_service

        tushare = build_tushare_service()
    cases: list[case.ComputationCase] = []
    seq = itertools.count(1)

    # 窗口端点 + 每 (股, 窗口) 数据缓存(去重取数)
    win: dict[str, tuple[str, str]] = {c: await _resolve_window(as_of, c) for c in legality.WINDOWS}
    cache: dict[tuple[str, str], dict] = {}

    async def data(ts_code: str, window: str) -> dict:
        key = (ts_code, window)
        if key not in cache:
            s, e = win[window]
            cache[key] = await _fetch(tushare, ts_code, s, e)
        return cache[key]

    def cid(tag: str) -> str:
        return f"qg-{tag}-{next(seq):03d}"

    def meta(window: str, sector: str | None = None) -> dict:
        m = {"window_dates": list(win[window]), "as_of": as_of}
        if sector:
            m["板块"] = sector
        return m

    # ---- 简单档(scalar)----
    for st in pool:
        wcn = legality.window_cn
        # 涨幅 × 3 窗口
        for w in ("3m", "1y", "3y"):
            d = await data(st.ts_code, w)
            gold = _scale("涨幅", operators.single("涨幅", d))
            cases.append(
                case.ComputationCase(
                    case_id=cid(f"涨幅-{st.ts_code}-{w}"),
                    intent=intents.INTENT,
                    difficulty="简单",
                    question=intents.q_single("涨幅", st.name, wcn(w)),
                    stocks=[st.ts_code],
                    indicator="涨幅",
                    window=w,
                    gold=gold,
                    gold_shape="scalar",
                    tolerance=_TOL["涨幅"],
                    meta=meta(w),
                )
            )
        # 回撤 / 波动 × 1y
        for ind in ("回撤", "波动"):
            d = await data(st.ts_code, "1y")
            gold = _scale(ind, operators.single(ind, d))
            cases.append(
                case.ComputationCase(
                    case_id=cid(f"{ind}-{st.ts_code}-1y"),
                    intent=intents.INTENT,
                    difficulty="简单",
                    question=intents.q_single(ind, st.name, wcn("1y")),
                    stocks=[st.ts_code],
                    indicator=ind,
                    window="1y",
                    gold=gold,
                    gold_shape="scalar",
                    tolerance=_TOL[ind],
                    meta=meta("1y"),
                )
            )
        # CAGR × 3y
        d = await data(st.ts_code, "3y")
        gold = _scale("CAGR", operators.single("CAGR", d, years=_WINDOW_YEARS["3y"]))
        cases.append(
            case.ComputationCase(
                case_id=cid(f"CAGR-{st.ts_code}-3y"),
                intent=intents.INTENT,
                difficulty="简单",
                question=intents.q_single("CAGR", st.name, wcn("3y")),
                stocks=[st.ts_code],
                indicator="CAGR",
                window="3y",
                gold=gold,
                gold_shape="scalar",
                tolerance=_TOL["CAGR"],
                meta=meta("3y"),
            )
        )

    # ---- 行情快照取数(简单档,无窗口)----
    cases.extend(await build_snapshot_cases(tushare, as_of, cid, pool=pool))

    # ---- 财报取数(简单档,2024 年年报;用 as_of 查询确保已披露)----
    cases.extend(
        await build_financial_cases(tushare, as_of, "20241231", "2024年年报", cid, pool=pool)
    )

    # ---- 财报核对(简单档,2024 年年报;题面嵌声称值,gold 取真实营收/净利)----
    cases.extend(await build_verify_cases(tushare, as_of, "20241231", "2024年年报", cid, pool=pool))

    # ---- 异动信号(中等档,2024 年年报;营收/净利同比,gold 取预算 yoy 字段)----
    cases.extend(await build_trend_cases(tushare, as_of, "20241231", "2024年年报", cid, pool=pool))

    # ---- 单仓持仓量(简单档)----
    cases.extend(await build_position_cases(tushare, as_of, cid, pool=pool))

    # ---- 组合权重 + HHI(中等档)----
    cases.extend(await build_portfolio_cases(tushare, as_of, cid, pool=pool))

    # ---- 账户 TWR + 三层归因(难档,复杂,requires_run_python)----
    cases.extend(await build_portfolio_advanced_cases(tushare, as_of, cid, pool=pool))

    # ---- 估值算式 PE/PB 理论价(中等档,2024 年报 + 板块同行可比)----
    cases.extend(
        await build_valuation_cases(tushare, as_of, "20241231", "2024年年报", cid, pool=pool)
    )

    # ---- PE 历史分位(难档,复杂,requires_run_python;现在算便宜还是贵)----
    cases.extend(await build_percentile_cases(tushare, as_of, cid, pool=pool))

    # ---- 中等档 ----
    for st in pool:
        # 双指标(回撤+波动) × 1y → multi_scalar
        d = await data(st.ts_code, "1y")
        gold_dual: dict[str, float] = {
            "回撤": _scale("回撤", operators.single("回撤", d)),
            "波动": _scale("波动", operators.single("波动", d)),
        }
        cases.append(
            case.ComputationCase(
                case_id=cid(f"双指标-{st.ts_code}-1y"),
                intent=intents.INTENT,
                difficulty="中等",
                question=intents.q_dual(st.name, legality.window_cn("1y")),
                stocks=[st.ts_code],
                indicator="回撤+波动",
                window="1y",
                gold=gold_dual,
                gold_shape="multi_scalar",
                tolerance=_TOL_DUAL,
                meta=meta("1y"),
            )
        )
    # 相关(同板块两两) × 1y
    for sector, members in stock_pool.by_sector(pool).items():
        for a, b in itertools.combinations(members, 2):
            da, db = await data(a.ts_code, "1y"), await data(b.ts_code, "1y")
            gold = operators.correlation_pair(da, db)
            cases.append(
                case.ComputationCase(
                    case_id=cid(f"相关-{a.ts_code}-{b.ts_code}-1y"),
                    intent=intents.INTENT,
                    difficulty="中等",
                    question=intents.q_corr(a.name, b.name, legality.window_cn("1y")),
                    stocks=[a.ts_code, b.ts_code],
                    indicator="相关",
                    window="1y",
                    gold=gold,
                    gold_shape="scalar",
                    tolerance=_TOL["相关"],
                    meta=meta("1y", sector),
                )
            )

    # ---- 复杂档(ranking / set)----
    by_sec = stock_pool.by_sector(pool)
    for sector in stock_pool.sectors_with_at_least(3, pool=pool):
        members = by_sec[sector]
        names = [m.name for m in members]
        for w in ("3m", "1y", "3y"):
            per_stock = {m.ts_code: await data(m.ts_code, w) for m in members}
            # 排序:涨幅前三
            ranked = operators.rank_by("涨幅", per_stock, top_k=3, descending=True)
            code_to_name = {m.ts_code: m.name for m in members}
            gold_rank = [[code_to_name[c], _scale("涨幅", v)] for c, v in ranked]
            cases.append(
                case.ComputationCase(
                    case_id=cid(f"排序-{sector}-{w}"),
                    intent=intents.INTENT,
                    difficulty="复杂",
                    question=intents.q_rank(sector, names, legality.window_cn(w)),
                    stocks=[m.ts_code for m in members],
                    indicator="涨幅",
                    window=w,
                    gold=gold_rank,
                    gold_shape="ranking",
                    tolerance={},
                    meta=meta(w, sector),
                )
            )
            # 筛选:涨幅>0 且 回撤<0.20(注:operators 用分数,涨幅>0 / 回撤<0.20)
            sel = operators.filter_by(per_stock, [("涨幅", ">", 0.0), ("回撤", "<", 0.20)])
            gold_set = sorted(code_to_name[c] for c in sel)
            cases.append(
                case.ComputationCase(
                    case_id=cid(f"筛选-{sector}-{w}"),
                    intent=intents.INTENT,
                    difficulty="复杂",
                    question=intents.q_filter(names, legality.window_cn(w)),
                    stocks=[m.ts_code for m in members],
                    indicator="涨幅+回撤",
                    window=w,
                    gold=gold_set,
                    gold_shape="set",
                    tolerance={},
                    meta=meta(w, sector),
                )
            )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    case.dump_jsonl(cases, out_path)
    return cases


def _summary(cases: list[case.ComputationCase]) -> str:
    from collections import Counter

    by_diff = Counter(c.difficulty for c in cases)
    by_ind = Counter(c.indicator for c in cases)
    return f"共 {len(cases)} 道 | 档:{dict(by_diff)} | 指标:{dict(by_ind)}"


if __name__ == "__main__":
    cs = asyncio.run(generate())
    print(_summary(cs))
    print(f"落盘:{_OUT_DEFAULT}")

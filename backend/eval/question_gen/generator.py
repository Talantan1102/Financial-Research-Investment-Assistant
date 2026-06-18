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
from pathlib import Path

from eval.question_gen import case, intents, legality, operators, stock_pool

_AS_OF_DEFAULT = "20260612"  # 钉到已落定的历史交易日(非"今天"):窗口不含移动/未回填的近端 bar → gold 可复现
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
_FINA_COLS = ("roe", "debt_to_assets", "grossprofit_margin")
_INCOME_COLS = ("revenue", "n_income")


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


async def build_snapshot_cases(tushare, as_of: str, cid) -> list[case.ComputationCase]:
    """行情快照取数(简单档,无窗口):每只股取 as_of 当日 daily_basic → 4 个直取指标。

    tushare 依赖注入(可塞 stub 单测);cid 是 case_id 生成器 callable。
    gold = 直取字段值(换手率/股息率 tushare 已是百分数,不 scale)。
    """
    out: list[case.ComputationCase] = []
    for st in stock_pool.POOL:
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


async def build_financial_cases(tushare, as_of: str, period_end: str, period_label: str, cid) -> list[case.ComputationCase]:
    """财报取数(简单档):用 as_of 查询(确保目标期已披露),取 period_end 期的 5 个直取指标。

    tushare 依赖注入;空值/缺期指标跳过。营收/净利 gold 已是亿元。
    """
    out: list[case.ComputationCase] = []
    for st in stock_pool.POOL:
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


async def build_position_cases(tushare, as_of: str, cid) -> list[case.ComputationCase]:
    """单仓持仓量(简单档):合成 qty/cost(确定性)+ 真收盘价。close 缺则跳过该股。"""
    out: list[case.ComputationCase] = []
    for i, st in enumerate(stock_pool.POOL):
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


async def generate(
    as_of: str = _AS_OF_DEFAULT, out_path: Path = _OUT_DEFAULT
) -> list[case.ComputationCase]:
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
    for st in stock_pool.POOL:
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
    cases.extend(await build_snapshot_cases(tushare, as_of, cid))

    # ---- 财报取数(简单档,2024 年年报;用 as_of 查询确保已披露)----
    cases.extend(await build_financial_cases(tushare, as_of, "20241231", "2024年年报", cid))

    # ---- 单仓持仓量(简单档)----
    cases.extend(await build_position_cases(tushare, as_of, cid))

    # ---- 中等档 ----
    for st in stock_pool.POOL:
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
    for sector, members in stock_pool.by_sector().items():
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
    by_sec = stock_pool.by_sector()
    for sector in stock_pool.sectors_with_at_least(3):
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

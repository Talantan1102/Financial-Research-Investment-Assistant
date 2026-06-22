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

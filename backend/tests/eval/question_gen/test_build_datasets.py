"""build_datasets 单测：mock 小 universe，不打真 tushare。"""

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from eval.question_gen.build_datasets import build_datasets


# ---- Mock _resolve_window so tests don't need trade_cal / DB ----
async def _mock_resolve_window(as_of: str, code: str) -> tuple[str, str]:
    windows = {
        "3m": ("20260312", "20260612"),
        "1y": ("20250612", "20260612"),
        "3y": ("20230612", "20260612"),
    }
    return windows[code]


# ---- Mock tushare covering ALL methods used by generator ----
class _MockTushare:
    """Comprehensive mock for build_datasets integration test."""

    def __init__(self, constituents: list[dict]):
        self._constituents = constituents  # list of {ts_code, name, sector, list_date?}

    async def get_index_weight(
        self,
        *,
        index_code,
        trade_date=None,
        start_date=None,
        end_date=None,
    ):
        ref_date = trade_date or end_date or "20260612"
        return pd.DataFrame(
            {
                "index_code": [index_code] * len(self._constituents),
                "con_code": [c["ts_code"] for c in self._constituents],
                "trade_date": [ref_date] * len(self._constituents),
            }
        )

    async def get_stock_basic(self, *, ts_code=None):
        if ts_code is None:
            # Bulk fetch: return all constituents
            rows = [
                {
                    "ts_code": c["ts_code"],
                    "name": c["name"],
                    "industry": c["sector"],
                    "list_date": c.get("list_date", "20010101"),
                }
                for c in self._constituents
            ]
            return pd.DataFrame(rows) if rows else pd.DataFrame()
        for c in self._constituents:
            if c["ts_code"] == ts_code:
                return pd.DataFrame(
                    [
                        {
                            "ts_code": ts_code,
                            "name": c["name"],
                            "industry": c["sector"],
                            "list_date": c.get("list_date", "20010101"),
                        }
                    ]
                )
        return pd.DataFrame()

    async def get_daily_basic(self, *, ts_code, trade_date=None, start_date=None, end_date=None):
        # 区间查(start_date/end_date):多行 PE 历史序列(build_percentile_cases 用)。
        if start_date is not None or end_date is not None:
            return pd.DataFrame(
                {
                    "ts_code": [ts_code] * 4,
                    "trade_date": ["20230101", "20230401", "20230701", "20231001"],
                    "pe": [10.0, 20.0, 30.0, 40.0],
                }
            )
        return pd.DataFrame(
            [
                {
                    "ts_code": ts_code,
                    "trade_date": trade_date or "20260612",
                    "pe": 25.0,
                    "pb": 8.0,
                    "turnover_rate": 1.5,
                    "dv_ratio": 2.0,
                    "close": 100.0,
                }
            ]
        )

    async def get_fina_indicator(self, *, ts_code, end_date=None):
        return pd.DataFrame(
            [
                {
                    "end_date": "20241231",
                    "roe": 0.25,
                    "debt_to_assets": 0.35,
                    "grossprofit_margin": 0.90,
                    "eps": 5.0,
                    "bps": 35.0,
                }
            ]
        )

    async def get_income(self, *, ts_code, end_date=None):
        return pd.DataFrame([{"end_date": "20241231", "revenue": 1.5e11, "n_income": 7e10}])

    async def get_daily(self, *, ts_code, start, end):
        # return a few rows of fake daily data
        return pd.DataFrame(
            [
                {"trade_date": "20250612", "close": 100.0, "pct_chg": 1.0},
                {"trade_date": "20260612", "close": 110.0, "pct_chg": 0.5},
            ]
        )

    async def get_trade_cal(self, *, start, end):
        from app.services.trade_calendar import build_calendar_df

        return build_calendar_df(start, end)


# Build a mock universe with enough stocks across sectors for splitting
def _make_universe(n_per_sector: dict[str, int]) -> list[dict]:
    result: list[dict] = []
    for sector, n in n_per_sector.items():
        for i in range(n):
            ts_code = f"6{len(result):05d}.SH"
            result.append(
                {
                    "ts_code": ts_code,
                    "name": f"{sector}股{i}",
                    "sector": sector,
                    "list_date": "20010101",  # > 3y before any as_of we use
                }
            )
    return result


# 10 per sector: round(10*0.8)=8 train, round(10*0.1)=1 val, test=10-8-1=1 → each split non-empty
_MOCK_UNIVERSE = _make_universe({"白酒": 10, "银行": 10, "新能源": 10})


def test_three_files_produced():
    mock = _MockTushare(_MOCK_UNIVERSE)
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir)
        with patch("eval.question_gen.generator._resolve_window", side_effect=_mock_resolve_window):
            paths = asyncio.run(
                build_datasets(
                    mock,
                    as_of="20260612",
                    out_dir=out_dir,
                    train_sample=3,
                    val_sample=2,
                    test_sample=2,
                    seed=42,
                )
            )
        assert set(paths.keys()) == {"train", "val", "test"}
        for name, path in paths.items():
            assert path.exists(), f"{name}.jsonl not created"
            assert path.stat().st_size > 0, f"{name}.jsonl is empty"


def test_case_ids_unique():
    mock = _MockTushare(_MOCK_UNIVERSE)
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir)
        with patch("eval.question_gen.generator._resolve_window", side_effect=_mock_resolve_window):
            paths = asyncio.run(
                build_datasets(
                    mock,
                    as_of="20260612",
                    out_dir=out_dir,
                    train_sample=3,
                    val_sample=2,
                    test_sample=2,
                    seed=42,
                )
            )
        all_ids = []
        for path in paths.values():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    case = json.loads(line)
                    all_ids.append(case["case_id"])
        # case_ids must be unique across all splits
        assert len(all_ids) == len(set(all_ids)), "Duplicate case_ids found"


def test_train_test_stocks_disjoint():
    """The hard red line: train stocks ∩ test stocks == ∅."""
    mock = _MockTushare(_MOCK_UNIVERSE)
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir)
        with patch("eval.question_gen.generator._resolve_window", side_effect=_mock_resolve_window):
            paths = asyncio.run(
                build_datasets(
                    mock,
                    as_of="20260612",
                    out_dir=out_dir,
                    train_sample=3,
                    val_sample=2,
                    test_sample=2,
                    seed=42,
                )
            )

        def get_stocks(path: Path) -> set[str]:
            codes = set()
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    case = json.loads(line)
                    codes.update(case.get("stocks", []))
            return codes

        train_stocks = get_stocks(paths["train"])
        test_stocks = get_stocks(paths["test"])
        assert train_stocks & test_stocks == set(), (
            f"train ∩ test stocks not empty: {train_stocks & test_stocks}"
        )


# 行业保量抽样回归用 universe:贴近真实中证800 的行业长尾(一个大行业 + 几个小行业)。
# split(0.8/0.1/0.1)后 val/test 每份只剩 3~4 只、分散到 2~3 个行业,且只有"其他"
# 这一个行业凑得到 2 只。纯随机下采样(sample=2)会把这唯一的 ≥2 行业拆成 1+1
# → 估值题(build_valuation_cases)/组合题(build_portfolio_cases,均要求同板块 ≥2 只)
# 在 val/test 直接为 0。balanced 抽样须优先把同行业 ≥2 只整组保住。
_BALANCED_UNIVERSE = _make_universe({"白酒": 6, "银行": 4, "医药": 3, "电子": 2, "其他": 20})


def _intents_in(path: Path) -> set[str]:
    intents: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            intents.add(json.loads(line)["intent"])
    return intents


def test_valuation_and_portfolio_in_val_test():
    """行业保量抽样:val/test 下采样后仍含 ≥2 成员行业 → 估值/组合题不为 0。

    估值题(build_valuation_cases)与组合题(build_portfolio_cases)都要求同板块 ≥2 只;
    纯随机抽样(旧 _sample)在此 universe+seed 下把唯一的 ≥2 行业拆散 → 两类意图在
    val/test 缺席(本测试在修复前 FAIL)。balanced 抽样把 ≥2 行业整组保住后必过。
    """
    mock = _MockTushare(_BALANCED_UNIVERSE)
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir)
        with patch("eval.question_gen.generator._resolve_window", side_effect=_mock_resolve_window):
            paths = asyncio.run(
                build_datasets(
                    mock,
                    as_of="20260612",
                    out_dir=out_dir,
                    train_sample=30,
                    val_sample=2,
                    test_sample=2,
                    seed=42,
                )
            )
        for split in ("val", "test"):
            intents = _intents_in(paths[split])
            assert "valuation_calc" in intents, (
                f"{split}.jsonl 缺 valuation_calc 意图 (抽样未保同行业 ≥2): {sorted(intents)}"
            )
            assert "portfolio_calc" in intents, (
                f"{split}.jsonl 缺 portfolio_calc 意图 (抽样未保同行业 ≥2): {sorted(intents)}"
            )


def test_sample_balanced_keeps_ge3_and_ge2_sectors():
    """_sample_balanced 单元测试:有 ≥3 行业 + ≥2 行业时,二者都进入抽样结果。

    直接验证抽样函数:池含 A(4 只,≥3)+ B(2 只,≥2)+ 长尾单只行业。
    n=8 足以容纳 3+2+补足;结果须含某行业 ≥3 只 + 另一行业 ≥2 只,且确定性。
    """
    import random as _random
    from collections import Counter

    from eval.question_gen.build_datasets import _sample_balanced
    from eval.question_gen.stock_pool import Stock

    pool = [
        Stock("A0.SH", "A0", "甲"),
        Stock("A1.SH", "A1", "甲"),
        Stock("A2.SH", "A2", "甲"),
        Stock("A3.SH", "A3", "甲"),
        Stock("B0.SH", "B0", "乙"),
        Stock("B1.SH", "B1", "乙"),
        Stock("C0.SH", "C0", "丙"),
        Stock("D0.SH", "D0", "丁"),
        Stock("E0.SH", "E0", "戊"),
    ]
    picked = _sample_balanced(pool, 8, _random.Random(42))
    assert len(picked) == 8
    counts = sorted(Counter(s.sector for s in picked).values(), reverse=True)
    assert counts[0] >= 3, f"无 ≥3 成员行业: {counts}"
    assert counts[1] >= 2, f"无第二个 ≥2 成员行业: {counts}"
    # 确定性:同 seed 同结果
    again = _sample_balanced(pool, 8, _random.Random(42))
    assert [s.ts_code for s in picked] == [s.ts_code for s in again]

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

    async def get_daily_basic(self, *, ts_code, trade_date=None):
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

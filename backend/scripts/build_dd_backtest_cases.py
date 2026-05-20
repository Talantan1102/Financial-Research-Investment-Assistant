"""Build golden case JSONL for DD report backtest.

spec § 4.4 决策 4 — 8 公司 × 4 backtest 时点 + 8 sanity case

用法:
    uv run python -m backend.scripts.build_dd_backtest_cases
    输出: backend/eval/dd_report/golden/backtest_cases.jsonl  (40 行)
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

COMPANIES: list[dict[str, str]] = [
    {"ts_code": "600519.SH", "name": "贵州茅台", "type": "blue_chip"},
    {"ts_code": "300750.SZ", "name": "宁德时代", "type": "growth_leader"},
    {"ts_code": "601088.SH", "name": "中国神华", "type": "cyclical"},
    {"ts_code": "600221.SH", "name": "海航控股", "type": "distressed_turnaround"},
    {"ts_code": "600518.SH", "name": "康美药业", "type": "fraud_delisted"},
    {"ts_code": "600036.SH", "name": "招商银行", "type": "bank"},
    {"ts_code": "600276.SH", "name": "恒瑞医药", "type": "pharma"},
    {"ts_code": "002415.SZ", "name": "海康威视", "type": "tech_sanctioned"},
]

BACKTEST_CUT_OFFS: list[date] = [
    date(2024, 6, 30),
    date(2024, 12, 31),
    date(2025, 6, 30),
    date(2025, 12, 31),
]

SANITY_CUT_OFF: date = date(2026, 4, 30)


def build_cases() -> list[dict[str, str]]:
    out: list[dict[str, str]] = []

    for co in BACKTEST_CUT_OFFS:
        for c in COMPANIES:
            out.append(
                {
                    "case_id": f"bt-{c['ts_code']}-{co.strftime('%Y%m%d')}",
                    "ts_code": c["ts_code"],
                    "target_name": c["name"],
                    "cut_off_date": co.isoformat(),
                    "case_type": "backtest",
                    "company_type": c["type"],
                }
            )

    for c in COMPANIES:
        out.append(
            {
                "case_id": f"sn-{c['ts_code']}-{SANITY_CUT_OFF.strftime('%Y%m%d')}",
                "ts_code": c["ts_code"],
                "target_name": c["name"],
                "cut_off_date": SANITY_CUT_OFF.isoformat(),
                "case_type": "sanity",
                "company_type": c["type"],
            }
        )

    return out


def main() -> None:
    out_path = Path(__file__).parents[1] / "eval" / "dd_report" / "golden" / "backtest_cases.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cases = build_cases()
    with out_path.open("w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    print(f"wrote {len(cases)} cases to {out_path}")


if __name__ == "__main__":
    main()

"""M2 NumericalMetric — extraction numerical accuracy (spec § 4.2).

简化 v0 — 支持 4 类指标 (其余 skip):
  - 营业收入  -> tushare income.revenue (单位 元)
  - 净利润    -> tushare income.n_income (单位 元)
  - 资产负债率 -> v0 简化 routes through fetch_income; 真值字段在 balancesheet
                  (T2.11 dogfood 撞实后 sediment + 拉到 fetch_balancesheet)
  - ROE       -> v0 简化 routes through fetch_income; 真值在 fina_indicator endpoint
                  (T2.11 dogfood 撞实后 sediment + 加 fina_indicator 适配)

容差 ±1% (spec § 4.2)。

NOTE: 无单位数字 (parse_chinese_number("150") 默认 = 150 元), 不算亿; LLM output 应带
单位。若 claim 无单位 vs. tushare 元值, 会触发 tolerance miss → wrong_values 入 log。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from eval.dd_report.metrics.base import MetricInputs, MetricResult

_NUM_PATTERN = re.compile(r"(-?\d+(?:\.\d+)?)")


def parse_chinese_number(text: str | None) -> float | None:
    """把 '150 亿元' / '12.5%' / '8000 万元' 归一为基础单位 (元 / 0-1 比例).

    Returns None 当无法 parse。
    """
    if not text:
        return None
    s = text.strip()
    m = _NUM_PATTERN.search(s)
    if not m:
        return None
    n = float(m.group(1))
    rest = s[m.end() :].strip()
    if "亿" in rest:
        return n * 1e8
    if "万" in rest and "亿" not in rest:
        return n * 1e4
    if "%" in rest or "百分" in rest:
        return n / 100.0
    return n


# Metric name -> (tushare adapter method, tushare row key, expected unit normalization)
_KNOWN_METRICS: dict[str, dict[str, Any]] = {
    "营业收入": {"fetch": "fetch_income", "row_key": "revenue", "unit": "yuan"},
    "净利润": {"fetch": "fetch_income", "row_key": "n_income", "unit": "yuan"},
    "ROE": {
        "fetch": "fetch_income",
        "row_key": "roe",
        "unit": "percent",
    },  # 简化:实际 ROE 在 fina_indicator
    "资产负债率": {"fetch": "fetch_income", "row_key": "_debt_ratio", "unit": "percent"},
}


@dataclass
class NumericalMetric:
    name: str = "m2_numerical"
    tolerance: float = 0.01  # ±1%
    sections_with_metrics: tuple[str, ...] = ("financial_analysis",)

    def compute(self, inputs: MetricInputs) -> MetricResult:
        if inputs.tushare_adapter is None:
            raise ValueError("NumericalMetric requires tushare_adapter")
        ts_code = inputs.case_meta.ts_code

        total = 0
        correct = 0
        wrong: list[dict[str, Any]] = []
        skipped: list[str] = []

        for sec_path in self.sections_with_metrics:
            sec = inputs.report.get(sec_path)
            if not isinstance(sec, dict):
                continue
            for item in sec.get("key_metrics", []) or []:
                if not isinstance(item, dict):
                    continue
                metric_name = item.get("name", "")
                if metric_name not in _KNOWN_METRICS:
                    skipped.append(metric_name)
                    continue
                claimed = parse_chinese_number(item.get("value"))
                if claimed is None:
                    skipped.append(f"{metric_name}:unparseable")
                    continue
                real = self._lookup_real_value(
                    metric_name, ts_code, item.get("period", ""), inputs.tushare_adapter
                )
                if real is None:
                    skipped.append(f"{metric_name}:no_tushare")
                    continue
                total += 1
                if abs(claimed - real) / max(abs(real), 1e-9) <= self.tolerance:
                    correct += 1
                else:
                    wrong.append(
                        {
                            "metric_name": metric_name,
                            "claimed": claimed,
                            "real": real,
                            "period": item.get("period", ""),
                        }
                    )

        accuracy = correct / total if total else 1.0
        return MetricResult(
            name=self.name,
            value=accuracy,
            details={
                "total": total,
                "correct": correct,
                "wrong_values": wrong[:10],
                "skipped": skipped[:20],
            },
        )

    def _lookup_real_value(
        self, metric_name: str, ts_code: str, period: str, adapter: Any
    ) -> float | None:
        spec = _KNOWN_METRICS[metric_name]
        method = getattr(adapter, spec["fetch"], None)
        if method is None:
            return None
        rows = method(ts_code=ts_code)
        if not rows:
            return None
        # Defensive sort — TushareBacktestAdapter applies ann_date filter but no sort; tushare
        # typically returns descending by ann_date for financial statements but the adapter
        # contract is silent. Explicit sort makes "rows[0] = latest reporting period before cut_off"
        # guaranteed regardless of inner client behavior. cf. T2.1 GroundTruthLoader kline sort fix.
        rows = sorted(rows, key=lambda r: r.get("ann_date", ""), reverse=True)
        row = rows[0]
        if spec["row_key"] == "_debt_ratio":
            total_liab = row.get("total_liab")
            total_assets = row.get("total_assets")
            if total_liab is None or total_assets is None or total_assets == 0:
                return None
            return float(total_liab) / float(total_assets)
        val = row.get(spec["row_key"])
        if val is None:
            return None
        return float(val) / 100.0 if spec["unit"] == "percent" else float(val)

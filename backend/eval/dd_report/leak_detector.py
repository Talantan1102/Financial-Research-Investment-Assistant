"""LeakDetector — backtest 模式下的数据 leakage 检测工具.

spec § 4.5 决策 5 / § 7.4

用法:
    detector = LeakDetector(cut_off=date(2024, 6, 30))
    leaks = detector.scan_tushare_rows(rows)
    leaks += detector.scan_chunks(chunks)
    leaks += detector.scan_prompt_text(prompt_str, source="agent:writer")
    detector.assert_no_leaks(leaks)   # raise AssertionError if any leak
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

# 匹配 YYYY-MM-DD / YYYYMMDD / YYYY/MM/DD 三种常见日期格式
_DATE_PATTERN = re.compile(r"\b(20\d{2})[-/年.]?(\d{1,2})[-/月.]?(\d{1,2})\b")


@dataclass(frozen=True)
class LeakRecord:
    """单条 leakage 证据."""

    source: str
    value: str


@dataclass
class LeakDetector:
    """跑 backtest 时审查所有数据来源, 识别 cut_off 之后的内容."""

    cut_off: date

    @property
    def _cut_off_compact(self) -> str:
        return self.cut_off.strftime("%Y%m%d")

    def scan_tushare_rows(self, rows: list[dict[str, Any]]) -> list[LeakRecord]:
        """检查 tushare 返回行中 ann_date / trade_date / f_ann_date / end_date."""
        out: list[LeakRecord] = []
        for r in rows:
            for field_name in ("ann_date", "trade_date", "f_ann_date", "end_date"):
                v = r.get(field_name)
                if isinstance(v, str) and len(v) == 8 and v > self._cut_off_compact:
                    out.append(
                        LeakRecord(
                            source=f"tushare:{r.get('source', 'unknown')}",
                            value=v,
                        )
                    )
        return out

    def scan_chunks(self, chunks: list[Any]) -> list[LeakRecord]:
        """检查 KB chunk publish_date."""
        out: list[LeakRecord] = []
        for c in chunks:
            cid = c.get("chunk_id") if isinstance(c, dict) else getattr(c, "chunk_id", "?")
            pd = c.get("publish_date") if isinstance(c, dict) else getattr(c, "publish_date", None)
            if isinstance(pd, date) and pd > self.cut_off:
                out.append(LeakRecord(source=f"kb:{cid}", value=pd.isoformat()))
        return out

    def scan_prompt_text(self, text: str, source: str) -> list[LeakRecord]:
        """扫描 prompt / agent 输出文本中出现的日期, 识别 cut_off 之后的."""
        out: list[LeakRecord] = []
        for m in _DATE_PATTERN.finditer(text):
            y, mo, d = m.group(1), m.group(2), m.group(3)
            try:
                found = date(int(y), int(mo), int(d))
            except ValueError:
                continue
            if found > self.cut_off:
                out.append(
                    LeakRecord(
                        source=source,
                        value=f"{y}-{int(mo):02d}-{int(d):02d}",
                    )
                )
        return out

    def assert_no_leaks(self, leaks: list[LeakRecord]) -> None:
        if leaks:
            details = "; ".join(f"{le.source}:{le.value}" for le in leaks[:10])
            raise AssertionError(f"data leakage detected ({len(leaks)} record(s)): {details}")

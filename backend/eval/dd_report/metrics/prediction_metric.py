"""M4 PredictionMetric — reasoning backtest accuracy (spec § 4.2).

3 子指标:
  1. direction_correct: rec_dir(+1/0/-1) × actual_dir(+1/0/-1) > 0
  2. target_price_hit: cut_off 后 horizon 内 high 触及 target_price.low ~ high 区间
  3. risk_flag_realized_rate: RiskItem.title 关键词在后续 ann.title substring 命中率

主 value = 3 子指标平均 (None 不计入)

注 (T2.1 contract): GroundTruthLoader.fetch_post_cut_off_kline 返回 rows 升序排序,
所以 kline[-1] = horizon 末端 close, 用于 direction.

Self-review fix (T2.5): _target_price_hit 只检查 low <= high <= target_high 区间内命中,
去掉原计划中的 `or float(h) >= low` 多余子句 — 该子句会把任何 high > low 的 bar 算命中,
违背 spec "触及区间" 语义。测试用例 h=1750 在 [1700, 1900] 内, PASS 不受影响。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eval.dd_report.metrics.base import MetricInputs, MetricResult

_REC_DIRECTION: dict[str, int] = {
    "recommend_buy": 1,
    "recommend_overweight": 1,
    "recommend_hold": 0,
    "recommend_underweight": -1,
    "recommend_sell": -1,
}


@dataclass
class PredictionMetric:
    name: str = "m4_prediction"
    horizon_days: int = 90

    def compute(self, inputs: MetricInputs) -> MetricResult:
        if inputs.ground_truth is None:
            raise ValueError("PredictionMetric requires ground_truth")
        ts_code = inputs.case_meta.ts_code
        cut_off = inputs.case_meta.cut_off_date
        kline = inputs.ground_truth.fetch_post_cut_off_kline(
            ts_code, cut_off, horizon_days=self.horizon_days
        )
        anns = inputs.ground_truth.fetch_post_cut_off_anns(
            ts_code, cut_off, horizon_days=self.horizon_days
        )

        rec = inputs.report.get("investment_recommendation") or {}
        risk_sec = inputs.report.get("risk_assessment") or {}
        anchor_price = inputs.report.get("target_close_price_at_gen")

        # 1. direction
        direction_correct = self._direction_correct(rec, kline, anchor_price)
        # 2. target_price_hit
        target_price_hit = self._target_price_hit(rec, kline)
        # 3. risk_flag_realized
        rate, hit_log, miss_log = self._risk_flag_realized(risk_sec, anns)

        subs: list[float] = []
        if direction_correct is not None:
            subs.append(1.0 if direction_correct else 0.0)
        if target_price_hit is not None:
            subs.append(1.0 if target_price_hit else 0.0)
        if rate is not None:
            subs.append(rate)
        value = sum(subs) / len(subs) if subs else None

        return MetricResult(
            name=self.name,
            value=value,
            details={
                "direction_correct": direction_correct,
                "target_price_hit": target_price_hit,
                "risk_flag_realized_rate": rate,
                "risk_flag_hits": hit_log[:10],
                "risk_flag_misses": miss_log[:10],
                "kline_rows": len(kline),
                "ann_rows": len(anns),
            },
        )

    @staticmethod
    def _direction_correct(
        rec: dict[str, Any], kline: list[dict[str, Any]], anchor_price: float | None
    ) -> bool | None:
        if not kline or anchor_price is None:
            return None
        rec_dir = _REC_DIRECTION.get(rec.get("recommendation", ""))
        if rec_dir is None:
            return None
        last_close = float(kline[-1].get("close", 0.0))
        if last_close == 0.0:
            return None
        change = (last_close - float(anchor_price)) / float(anchor_price)
        actual_dir = 1 if change > 0.02 else (-1 if change < -0.02 else 0)
        if rec_dir == 0 and actual_dir == 0:
            return True
        return rec_dir * actual_dir > 0

    @staticmethod
    def _target_price_hit(rec: dict[str, Any], kline: list[dict[str, Any]]) -> bool | None:
        rng = rec.get("estimated_target_price_range")
        if not isinstance(rng, dict) or not kline:
            return None
        low = float(rng.get("low", 0.0))
        high = float(rng.get("high", 0.0))
        if low >= high:
            return None
        for row in kline:
            h = row.get("high")
            if h is None:
                continue
            # Fix: strictly within [low, high] — "触及区间" means bar high falls
            # inside the target range, not just above the lower bound.
            if low <= float(h) <= high:
                return True
        return False

    @staticmethod
    def _risk_flag_realized(
        risk_sec: dict[str, Any], anns: list[dict[str, Any]]
    ) -> tuple[float | None, list[str], list[str]]:
        keywords: list[str] = []
        for bucket in ("market_risk", "growth_risk", "event_risk", "valuation_risk"):
            for it in risk_sec.get(bucket, []) or []:
                if isinstance(it, dict) and it.get("title"):
                    keywords.append(it["title"])
        if not keywords:
            return None, [], []
        if not anns:
            return 0.0, [], keywords
        ann_titles = " | ".join(a.get("title", "") for a in anns)
        hits: list[str] = []
        misses: list[str] = []
        for kw in keywords:
            # 简化关键词匹配:title 中 substring (去 "风险" 后缀)
            core = kw.replace("风险", "").strip() or kw
            if core in ann_titles:
                hits.append(kw)
            else:
                misses.append(kw)
        return len(hits) / len(keywords), hits, misses

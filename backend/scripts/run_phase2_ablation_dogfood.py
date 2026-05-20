"""Phase 2 末完整 ablation L2 dogfood — spec § 4.7 决策 7.

跑 4 variant (V0/V1/V2/V3) × 8 sanity case (cut_off=2026-04-30) × 1 evaluator_llm
(deepseek-v4-flash) = 32 backtest_runs.

成本: ~28 RMB (per spec § 5.3). 单次 dogfood, 不在 CI 跑。

输出:
  - backend/data/eval_phase2_dogfood.db (新 sqlite)
  - 控制台 4×5 metric 矩阵
  - sediment 卡片需 user 手动 paste 真实数字

前置:
  - DASHSCOPE_API_KEY 在 backend/.env
  - unset all_proxy https_proxy http_proxy
  - tushare client 接通

使用:
  uv run python backend/scripts/run_phase2_ablation_dogfood.py
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any


def main() -> int:
    if not os.environ.get("DASHSCOPE_API_KEY"):
        print("ERROR: DASHSCOPE_API_KEY not set in env. dogfood requires real LLM access.")
        print("       Hint: source backend/.env or export DASHSCOPE_API_KEY=...")
        return 1

    db_path = Path("backend/data/eval_phase2_dogfood.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Lazy import (heavy)
    from app.eval.dd_report_production_factory import (
        build_dd_report_production_factory,
        build_pairing_judge,
        build_supports_judge,
    )
    from app.services.eval_recorder import EvalRecorder
    from eval.dd_report.ablation.runner import AblationRunner
    from eval.dd_report.ablation.variants import AblationVariant
    from eval.dd_report.golden.ground_truth_loader import GroundTruthLoader
    from eval.dd_report.llm_swapper import LLMSwapper
    from eval.dd_report.metrics.base import MetricRegistry
    from eval.dd_report.metrics.citation_metric import CitationMetric
    from eval.dd_report.metrics.composite_judge_metric import CompositeJudgeMetric
    from eval.dd_report.metrics.numerical_metric import NumericalMetric
    from eval.dd_report.metrics.prediction_metric import PredictionMetric
    from eval.dd_report.metrics.risk_pairing_metric import RiskPairingMetric

    EvalRecorder(db_path).init_schema()

    cases_path = Path("backend/eval/dd_report/golden/backtest_cases.jsonl")
    sanity_cases = [
        _row_to_case(json.loads(line))
        for line in cases_path.read_text().splitlines()
        if json.loads(line).get("case_type") == "sanity"
    ]
    assert len(sanity_cases) == 8, f"expected 8 sanity cases, got {len(sanity_cases)}"

    swapper = LLMSwapper()
    eval_client = swapper.get_client("deepseek-v4-flash")

    # Try to wire tushare + KB; if either fails, fall back gracefully so the dogfood
    # still produces a partial run (M1/M2/M3/M4 may degrade).
    try:
        tushare_inner: Any = _build_tushare_client()
    except Exception as e:
        print(f"WARN: TushareClient unavailable ({e}); M2/M4 will skip.")
        tushare_inner = _stub_tushare()
    try:
        kb_inner = _build_kb_client()
        kb_lookup = _build_kb_lookup()
    except Exception as e:
        print(f"WARN: KB client unavailable ({e}); M1 lookup will degrade.")
        kb_inner = _stub_kb()

        def kb_lookup(_cid: Any) -> Any:  # noqa: ANN401 — stub for deferred KB wire
            return None

    gtl = GroundTruthLoader(inner=tushare_inner)
    metric_registry = MetricRegistry(
        [
            CitationMetric(judge=build_supports_judge(eval_client)),
            NumericalMetric(),
            RiskPairingMetric(judge=build_pairing_judge(eval_client)),
            PredictionMetric(),
            CompositeJudgeMetric(),
        ]
    )

    production_factory = build_dd_report_production_factory()
    git_sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"]).decode().strip()

    runner = AblationRunner(
        swapper=swapper,
        tushare_inner=tushare_inner,
        kb_inner=kb_inner,
        db_path=db_path,
        production_factory=production_factory,
        metric_registry=metric_registry,
        ground_truth_loader=gtl,
        kb_lookup=kb_lookup,
        enable_leak_detection=True,
    )

    print(f"Phase 2 末 ablation dogfood — 4 variant × 8 sanity case (git_sha={git_sha})")
    results = runner.run_ablation(
        cases=sanity_cases,
        variants=list(AblationVariant),
        evaluator_llm="deepseek-v4-flash",
        git_sha=git_sha,
        case_type="sanity",
    )

    print("\n=== Ablation 4x5 矩阵 ===")
    _print_ablation_matrix(db_path, git_sha)

    failed = [r for r in results if r.status == "failed"]
    if failed:
        print(f"\nWARN: {len(failed)} run failed:")
        for f in failed:
            print(f"  {f.variant} / {f.case_id}: {f.error}")

    return 0


def _row_to_case(d: dict[str, Any]) -> Any:
    from eval.dd_report.backtest_runner import BacktestCase

    return BacktestCase(
        case_id=d["case_id"],
        ts_code=d["ts_code"],
        target_name=d["target_name"],
        cut_off_date=date.fromisoformat(d["cut_off_date"]),
    )


def _print_ablation_matrix(db: Path, git_sha: str) -> None:
    with sqlite3.connect(db) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT ablation_variant, metric_summary_json FROM backtest_runs "
            "WHERE git_sha = ? AND status = 'completed'",
            (git_sha,),
        ).fetchall()
    by_variant: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if not r["metric_summary_json"]:
            continue
        m = json.loads(r["metric_summary_json"])
        for k, v in m.items():
            if v is not None:
                by_variant[r["ablation_variant"]][k].append(float(v))
    header = ["Variant", "M1", "M2", "M3", "M4", "M5"]
    print(
        f"{header[0]:<20} | {header[1]:>6} | {header[2]:>6} | "
        f"{header[3]:>6} | {header[4]:>6} | {header[5]:>6}"
    )
    for v in ("V0_baseline", "V1_no_rag", "V2_no_multi_agent", "V3_no_critic"):
        _scores = by_variant.get(v, {})
        print(
            f"{v:<20} | {_avg(_scores, 'm1_citation'):>6} | {_avg(_scores, 'm2_numerical'):>6} | "
            f"{_avg(_scores, 'm3_risk_pairing'):>6} | {_avg(_scores, 'm4_prediction'):>6} | "
            f"{_avg(_scores, 'm5_composite'):>6}"
        )


def _avg(scores: dict[str, list[float]], k: str) -> str:
    """Average a list of float scores; return 'N/A' if empty."""
    vs = scores.get(k, [])
    return f"{sum(vs) / len(vs):.2f}" if vs else "N/A"


def _build_tushare_client() -> Any:
    """Build sync tushare client suitable for TushareBacktestAdapter.inner.

    TushareBacktestAdapter.inner needs sync methods: income / daily / balancesheet /
    cashflow / anns (each returns list[dict]).

    The tushare Pro SDK (tushare.pro_api) provides a sync DataApi.query() call.
    We wrap it here as a thin adapter exposing the 5 sync methods.
    """
    import tushare as ts

    token = os.environ.get("TUSHARE_TOKEN", "")
    if not token:
        raise ValueError("TUSHARE_TOKEN not set in env")
    base_url = os.environ.get("TUSHARE_BASE_URL", "http://api.tushare.pro")
    api = ts.pro_api(token)
    # Monkey-patch base_url if override provided
    if base_url != "http://api.tushare.pro":
        api._DataApi__url = base_url  # noqa: SLF001

    class _SyncTushareClient:
        """Sync wrapper around tushare Pro SDK DataApi for TushareBacktestAdapter."""

        @staticmethod
        def _query_to_list(api_name: str, **kwargs: Any) -> list[dict[str, Any]]:
            df = api.query(api_name, **kwargs)
            if df is None or df.empty:
                return []
            return df.to_dict(orient="records")

        def income(self, **kwargs: Any) -> list[dict[str, Any]]:
            return self._query_to_list("income", **kwargs)

        def daily(self, **kwargs: Any) -> list[dict[str, Any]]:
            return self._query_to_list("daily", **kwargs)

        def balancesheet(self, **kwargs: Any) -> list[dict[str, Any]]:
            return self._query_to_list("balancesheet", **kwargs)

        def cashflow(self, **kwargs: Any) -> list[dict[str, Any]]:
            return self._query_to_list("cashflow", **kwargs)

        def anns(self, **kwargs: Any) -> list[dict[str, Any]]:
            # tushare Pro announcement api
            return self._query_to_list("anns_d", **kwargs)

    return _SyncTushareClient()


def _stub_tushare() -> Any:
    """Stub tushare client for degraded dogfood paths."""

    class _Stub:
        def income(self, **kw: Any) -> list[Any]:
            return []

        def daily(self, **kw: Any) -> list[Any]:
            return []

        def balancesheet(self, **kw: Any) -> list[Any]:
            return []

        def cashflow(self, **kw: Any) -> list[Any]:
            return []

        def anns(self, **kw: Any) -> list[Any]:
            return []

    return _Stub()


def _stub_kb() -> Any:
    class _Stub:
        def search(self, query: str = "", k: int = 10, **kw: Any) -> list[Any]:
            return []

    return _Stub()


def _build_kb_client() -> Any:
    """Build production KB client from env (KB_MODE=real → Milvus; otherwise mock).

    If KB_MODE is not set to 'real' or Milvus is unavailable, raises Exception
    and dogfood falls back to stub.
    """
    kb_mode = os.environ.get("KB_MODE", "mock")
    if kb_mode != "real":
        raise ValueError(f"KB_MODE={kb_mode!r}; set KB_MODE=real + MILVUS_HOST to enable real KB.")
    from app.services.kb_factory import build_kb_search_service_from_env

    return build_kb_search_service_from_env()


def _build_kb_lookup() -> Any:
    """Build chunk_id -> chunk dict callable.

    Real Milvus chunk lookup by ID is complex (requires get_by_ids). For now return
    a passthrough None callable — M1's total_cited > 0 requires actual lookup but
    framework still runs; lookup_failures counter increments.

    Deferred: implement get_by_chunk_id via MilvusKbClient when M1 real citation
    scoring is needed beyond framework smoke.
    """
    return lambda cid: None


if __name__ == "__main__":
    sys.exit(main())

"""BacktestRunner — orchestrator (Phase 1 skeleton → Phase 2 wire).

spec § 4.1 / § 5.1 / § 5.3

Phase 1 形态:
  - 接受 BacktestCase + cut_off + evaluator_llm + ablation_variant + git_sha
  - 装配 TushareBacktestAdapter + KBBacktestAdapter + EvaluatorClient
  - 调 pipeline.run(...) 并捕获 output
  - 写一行到 backtest_runs 表

Phase 2 扩展:
  - 接 MetricRegistry, 跑 5 个 metric
  - 写 metric_summary_json 字段
  - 写 eval_results 表(per case)
  - 接 LeakDetector, 可选扫报告 narrative 中 > cut_off 的日期
"""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Literal, Protocol
from uuid import uuid4

from app.services.eval_models import BacktestRun, EvalResult, JudgeScores
from app.services.eval_recorder import EvalRecorder
from sqlalchemy.orm import Session

from eval.dd_report.kb_backtest_adapter import KBBacktestAdapter
from eval.dd_report.leak_detector import LeakDetector
from eval.dd_report.llm_swapper import BACKTEST_EVALUATOR_MODELS, LLMSwapper
from eval.dd_report.metric_scores import BacktestMetricScores
from eval.dd_report.metrics.base import (
    CaseMeta,
    MetricInputs,
    MetricRegistry,
    MetricResult,
)
from eval.dd_report.tushare_backtest_adapter import TushareBacktestAdapter

CaseType = Literal["backtest", "sanity", "financebench", "cross_llm"]


@dataclass(frozen=True)
class BacktestCase:
    """单个 backtest case 的元数据."""

    case_id: str
    ts_code: str
    target_name: str
    cut_off_date: date


class PipelineProtocol(Protocol):
    """需 InvestmentDueDiligenceReport 生产 pipeline 实现的 protocol.

    Phase 1: 用 mock 满足即可。Phase 2/3: 接生产 ResearchAgent / chat path。
    """

    def run(
        self,
        *,
        target_name: str,
        ts_code: str,
        tushare_adapter: TushareBacktestAdapter,
        kb_adapter: KBBacktestAdapter,
        evaluator_client: Any,
    ) -> dict[str, Any]: ...


class BacktestRunner:
    """Orchestrator: 装配 backtest 数据控制层 + LLM swap + 调 pipeline + 跑 metric."""

    def __init__(
        self,
        swapper: LLMSwapper,
        tushare_inner: Any,
        kb_inner: Any,
        session_factory: Callable[[], AbstractContextManager[Session]],
        pipeline: PipelineProtocol | None = None,
        metric_registry: MetricRegistry | None = None,
        kb_lookup: Any | None = None,
        enable_leak_detection: bool = False,
    ) -> None:
        self._swapper = swapper
        self._tushare_inner = tushare_inner
        self._kb_inner = kb_inner
        self._pipeline = pipeline
        self._metric_registry = metric_registry or MetricRegistry([])
        self._kb_lookup = kb_lookup
        self._enable_leak_detection = enable_leak_detection
        self._recorder = EvalRecorder(session_factory)

    def run_one(
        self,
        case: BacktestCase,
        evaluator_llm: str,
        ablation_variant: str,
        git_sha: str,
        case_type: CaseType = "backtest",
    ) -> str:
        """跑一个 case: pipeline → leak detect → 5 metric → 写 eval_results +
        backtest_runs。返回 run_id.

        spec § 4.5 leak detection: 可选 (enable_leak_detection=True) — 默认不跑以保
        Phase 1 test 兼容。开后扫报告 narrative 中 > cut_off 的日期, raise AssertionError
        并把 run 标 status='failed'.
        """
        run_id = f"bt-run-{uuid4().hex[:12]}"
        created_at = datetime.now(UTC).isoformat()

        tushare_adapter = TushareBacktestAdapter(
            inner=self._tushare_inner, cut_off=case.cut_off_date
        )
        kb_adapter = KBBacktestAdapter(inner=self._kb_inner, cut_off=case.cut_off_date)
        evaluator_client = self._swapper.get_client(evaluator_llm)

        # 装配 3 evaluator clients (M5 需要)
        m5_clients = {m: self._swapper.get_client(m) for m in BACKTEST_EVALUATOR_MODELS}

        status = "completed"
        report: dict[str, Any] = {}
        metric_results: list[MetricResult] = []
        try:
            if self._pipeline is not None:
                report = self._pipeline.run(
                    target_name=case.target_name,
                    ts_code=case.ts_code,
                    tushare_adapter=tushare_adapter,
                    kb_adapter=kb_adapter,
                    evaluator_client=evaluator_client,
                )
            if self._enable_leak_detection:
                self._run_leak_detection(report, case)
            if self._metric_registry.metrics and not report:
                raise RuntimeError(
                    f"MetricRegistry has {len(self._metric_registry.metrics)} metric(s) "
                    "but pipeline produced empty report; cannot compute metrics"
                )
            if self._metric_registry.metrics and report:
                case_meta = CaseMeta(
                    case_id=case.case_id,
                    ts_code=case.ts_code,
                    target_name=case.target_name,
                    cut_off_date=case.cut_off_date,
                )
                inputs = MetricInputs(
                    report=report,
                    case_meta=case_meta,
                    tushare_adapter=tushare_adapter,
                    kb_lookup=self._kb_lookup,
                    evaluator_clients=m5_clients,
                )
                metric_results = self._metric_registry.compute_all(inputs)
                self._write_eval_result(
                    run_id=run_id,
                    case=case,
                    evaluator_llm=evaluator_llm,
                    case_type=case_type,
                    metric_results=metric_results,
                )
        except Exception:
            status = "failed"
            raise
        finally:
            self._write_run_row(
                run_id=run_id,
                created_at=created_at,
                case_count=1,
                status=status,
                git_sha=git_sha,
                ablation_variant=ablation_variant,
                llm_model=evaluator_llm,
                metric_summary_json=_aggregate_summary_json(metric_results),
            )
        return run_id

    def _run_leak_detection(self, report: dict[str, Any], case: BacktestCase) -> None:
        detector = LeakDetector(cut_off=case.cut_off_date)
        leaks: list = []
        # 扫报告所有 section 的 narrative 中的日期 (adapter 已做 row-level 防御, 这里
        # 兜底扫 prompt-level / agent-output 中可能 hallucinate 出的 future 日期)
        for sec_path in (
            "target_overview",
            "legal_qualification",
            "financial_analysis",
            "industry_analysis",
            "risk_assessment",
            "investment_recommendation",
        ):
            sec = report.get(sec_path)
            if isinstance(sec, dict):
                leaks += detector.scan_prompt_text(
                    sec.get("narrative", ""), source=f"report:{sec_path}"
                )
        detector.assert_no_leaks(leaks)

    def _write_eval_result(
        self,
        *,
        run_id: str,
        case: BacktestCase,
        evaluator_llm: str,
        case_type: CaseType,
        metric_results: list[MetricResult],
    ) -> None:
        bscores = _to_backtest_metric_scores(metric_results)
        eval_id = f"ev-{uuid4().hex[:12]}"
        request_id = case.case_id  # backtest 模式: 1 case = 1 eval, request_id 复用 case_id
        # backtest 模式 JudgeScores stub (满足 EvalResult schema 非空)
        stub_judge = JudgeScores(
            factuality=0,
            factuality_evidence="N/A backtest 模式",
            tool_correctness=None,
            tool_correctness_evidence="N/A backtest 模式",
            coverage=0,
            coverage_evidence="N/A backtest 模式",
            structure=0,
            structure_evidence="N/A backtest 模式",
        )
        result = EvalResult(
            eval_id=eval_id,
            request_id=request_id,
            case_id=case.case_id,
            scores=stub_judge,
            judge_model=f"backtest:{evaluator_llm}",
            judge_cost_cny=0.0,
            judge_latency_ms=0,
            timestamp=datetime.now(UTC),
            backtest_run_id=run_id,
            cut_off_date=case.cut_off_date.isoformat(),
            evaluator_llm=evaluator_llm,
            case_type=case_type,
            metric_scores_json=bscores.model_dump_json(),
        )
        self._recorder.write(result)

    def _write_run_row(
        self,
        *,
        run_id: str,
        created_at: str,
        case_count: int,
        status: str,
        git_sha: str,
        ablation_variant: str,
        llm_model: str,
        metric_summary_json: str | None,
    ) -> None:
        self._recorder.write_backtest_run(
            BacktestRun(
                run_id=run_id,
                created_at=created_at,
                case_count=case_count,
                metric_summary_json=metric_summary_json,
                status=status,
                git_sha=git_sha,
                ablation_variant=ablation_variant,
                llm_model=llm_model,
            )
        )


def _aggregate_summary_json(results: list[MetricResult]) -> str | None:
    """Aggregate per-metric value to {name: value} JSON; None values serialized as null."""
    if not results:
        return None
    return json.dumps({r.name: r.value for r in results})


def _to_backtest_metric_scores(results: list[MetricResult]) -> BacktestMetricScores:
    """从 MetricResult list 拼出 BacktestMetricScores. 缺失 metric 用安全默认.

    关键设计 (T2.2 / T2.5 review sediment):
      - M1 details key 是 "citation_coverage", 不是 "recall" (T2.2 rename); schema
        field name 仍是 m1_citation_recall 保 spec 一致
      - M2/M3/M5 value 可能是 0.0 (legitimate zero); 用 explicit `is None` check
        而非 `or` short-circuit (`0.0 or 1.0 == 1.0` 会 silently inflate)
      - 去推荐改造(2026-06-04):预测回测(原 M4)已下线
    """
    by_name = {r.name: r for r in results}
    m1 = by_name.get("m1_citation")
    m2 = by_name.get("m2_numerical")
    m3 = by_name.get("m3_risk_pairing")
    m5 = by_name.get("m5_composite")
    return BacktestMetricScores(
        m1_citation_precision=(m1.details.get("precision", 1.0) if m1 else 1.0),
        m1_citation_recall=(m1.details.get("citation_coverage", 1.0) if m1 else 1.0),
        m2_numerical_accuracy=(m2.value if m2 and m2.value is not None else 1.0),
        m2_numerical_total=(m2.details.get("total", 0) if m2 else 0),
        m2_numerical_correct=(m2.details.get("correct", 0) if m2 else 0),
        m3_risk_pairing_score=(m3.value if m3 and m3.value is not None else 1.0),
        # M5: prefer details["mean"] (set by CompositeJudgeMetric); fall back to
        # m5.value so stub/const metrics used in tests still map correctly.
        m5_composite_mean=(
            m5.details.get("mean", m5.value if m5.value is not None else 0.0) if m5 else 0.0
        ),
        m5_composite_majority=(m5.details.get("majority", 0.0) if m5 else 0.0),
        m5_composite_disagreement_max=(m5.details.get("disagreement_max", 0.0) if m5 else 0.0),
        details_json={r.name: r.details for r in results},
    )

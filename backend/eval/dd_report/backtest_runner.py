"""BacktestRunner — orchestrator skeleton (Phase 1).

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
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from eval.dd_report.kb_backtest_adapter import KBBacktestAdapter
from eval.dd_report.llm_swapper import LLMSwapper
from eval.dd_report.tushare_backtest_adapter import TushareBacktestAdapter


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
    """Orchestrator: 装配 backtest 数据控制层 + LLM swap + 调 pipeline."""

    def __init__(
        self,
        swapper: LLMSwapper,
        tushare_inner: Any,
        kb_inner: Any,
        db_path: Path,
        pipeline: PipelineProtocol | None = None,
    ) -> None:
        self._swapper = swapper
        self._tushare_inner = tushare_inner
        self._kb_inner = kb_inner
        self._db_path = db_path
        self._pipeline = pipeline

    def run_one(
        self,
        case: BacktestCase,
        evaluator_llm: str,
        ablation_variant: str,
        git_sha: str,
    ) -> str:
        """跑一个 case,写 backtest_runs 表,返回 run_id."""
        run_id = f"bt-run-{uuid4().hex[:12]}"
        created_at = datetime.now(UTC).isoformat()

        tushare_adapter = TushareBacktestAdapter(
            inner=self._tushare_inner, cut_off=case.cut_off_date
        )
        kb_adapter = KBBacktestAdapter(inner=self._kb_inner, cut_off=case.cut_off_date)
        evaluator_client = self._swapper.get_client(evaluator_llm)

        status = "completed"
        try:
            if self._pipeline is not None:
                _ = self._pipeline.run(
                    target_name=case.target_name,
                    ts_code=case.ts_code,
                    tushare_adapter=tushare_adapter,
                    kb_adapter=kb_adapter,
                    evaluator_client=evaluator_client,
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
            )

        return run_id

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
    ) -> None:
        with sqlite3.connect(self._db_path) as con:
            con.execute(
                "INSERT INTO backtest_runs "
                "(run_id, created_at, case_count, metric_summary_json, status, "
                "git_sha, ablation_variant, llm_model) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    created_at,
                    case_count,
                    None,
                    status,
                    git_sha,
                    ablation_variant,
                    llm_model,
                ),
            )

"""AblationRunner — 跑 4 variant × case 子集 + 写 ablation_variant 字段."""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from eval.dd_report.ablation.runner import AblationRunner
from eval.dd_report.ablation.variants import AblationVariant
from eval.dd_report.backtest_runner import BacktestCase


def _make_runner(db: Path) -> AblationRunner:
    """AblationRunner 接受 production_factory + BacktestRunner deps."""
    from app.services.eval_recorder import EvalRecorder
    from eval.dd_report.metrics.base import MetricRegistry

    EvalRecorder(db).init_schema()

    class _Tushare:
        def income(self, **kw: Any) -> list[dict[str, Any]]:
            return []

        def daily(self, **kw: Any) -> list[dict[str, Any]]:
            return []

        def balancesheet(self, **kw: Any) -> list[dict[str, Any]]:
            return []

        def cashflow(self, **kw: Any) -> list[dict[str, Any]]:
            return []

        def anns(self, **kw: Any) -> list[dict[str, Any]]:
            return []

    class _KB:
        def search(self, q: str, k: int = 10, **kw: Any) -> list[Any]:
            return []

    class _DummySwapper:
        def get_client(self, m: str) -> Any:
            c = MagicMock()
            c.chat.return_value = '{"score": 7, "reasoning": "ok"}'
            return c

    def production_factory(
        *,
        tushare_adapter: Any,
        kb_adapter: Any,
        evaluator_client: Any,
        disable_critic: bool = False,
    ) -> Any:
        from app.agents.investment_dd_schema import (
            DEFAULT_DISCLAIMER,
            FinancialAnalysis,
            IndustryAnalysis,
            InvestmentDueDiligenceReport,
            InvestmentRecommendation,
            LegalQualification,
            PriceRange,
            RiskAssessment,
            TargetOverview,
            ValuationAnalysis,
        )

        def runner(target_name: str, target_ts_code: str) -> InvestmentDueDiligenceReport:
            return InvestmentDueDiligenceReport(
                target_name=target_name,
                target_ts_code=target_ts_code,
                request_id="prod-test",
                generated_at=datetime.now(UTC),
                target_overview=TargetOverview(narrative="...", main_business="X"),
                legal_qualification=LegalQualification(
                    narrative="...",
                    legal_status="ok",
                    business_qualifications=[],
                    adverse_records=[],
                ),
                financial_analysis=FinancialAnalysis(
                    narrative="...",
                    key_metrics=[],
                    profitability_analysis="...",
                    growth_analysis="...",
                    return_analysis="...",
                    cash_flow_analysis="...",
                    valuation_analysis=ValuationAnalysis(narrative="..."),
                ),
                industry_analysis=IndustryAnalysis(
                    narrative="...",
                    industry_name="X",
                    industry_outlook="...",
                    competitive_position="...",
                    key_competitors=[],
                    policy_impact="...",
                ),
                risk_assessment=RiskAssessment(
                    narrative="...",
                    market_risk=[],
                    growth_risk=[],
                    event_risk=[],
                    valuation_risk=[],
                    overall_risk_level="medium",
                ),
                investment_recommendation=InvestmentRecommendation(
                    narrative="...",
                    recommendation="recommend_hold",
                    recommended_position_size_pct=5.0,
                    recommended_holding_period="medium_term",
                    recommended_entry_price_range=PriceRange(low=1400, high=1500),
                    recommended_stop_loss_price=1300,
                    estimated_target_price_range=PriceRange(low=1600, high=1700),
                    position_management_conditions=[],
                ),
                disclaimer=DEFAULT_DISCLAIMER,
            )

        return runner

    return AblationRunner(
        swapper=_DummySwapper(),  # type: ignore[arg-type]
        tushare_inner=_Tushare(),
        kb_inner=_KB(),
        db_path=db,
        production_factory=production_factory,
        metric_registry=MetricRegistry([]),  # 空 registry, 只验调度
    )


def test_run_4_variants_x_2_cases_writes_8_runs(tmp_path) -> None:
    runner = _make_runner(tmp_path / "ev.db")
    cases = [
        BacktestCase("c1", "600519.SH", "茅台", date(2024, 6, 30)),
        BacktestCase("c2", "300750.SZ", "宁德", date(2024, 6, 30)),
    ]
    results = runner.run_ablation(
        cases=cases,
        variants=list(AblationVariant),
        evaluator_llm="deepseek-v4-flash",
        git_sha="testsha",
    )
    assert len(results) == 4 * 2
    with sqlite3.connect(tmp_path / "ev.db") as con:
        n = con.execute(
            "SELECT COUNT(*) FROM backtest_runs WHERE git_sha = ?", ("testsha",)
        ).fetchone()[0]
    assert n == 8


def test_single_case_failure_does_not_abort_remaining_runs(tmp_path) -> None:
    """Fail-soft contract: AblationRunner.except Exception ensures 1 failed (variant,
    case) doesn't abort remaining. T2.11 ablation 32 case run with 1 auth error
    must still produce 31 success entries + 1 failure entry.

    V2 does NOT call production_factory (uses SingleAgentPipeline directly), so
    call_count increments only for V0/V1/V3 = 3 variants × 2 cases = 6 invocations.
    First call (V0×c1) fails → 1 failed; remaining 7 complete → 7 completed.
    """
    from app.services.eval_recorder import EvalRecorder
    from eval.dd_report.metrics.base import MetricRegistry

    EvalRecorder(tmp_path / "ev.db").init_schema()

    class _Tushare:
        def income(self, **kw: Any) -> list[dict[str, Any]]:
            return []

        def daily(self, **kw: Any) -> list[dict[str, Any]]:
            return []

        def balancesheet(self, **kw: Any) -> list[dict[str, Any]]:
            return []

        def cashflow(self, **kw: Any) -> list[dict[str, Any]]:
            return []

        def anns(self, **kw: Any) -> list[dict[str, Any]]:
            return []

    class _KB:
        def search(self, q: str, k: int = 10, **kw: Any) -> list[Any]:
            return []

    class _DummySwapper:
        def get_client(self, m: str) -> Any:
            c = MagicMock()
            c.chat.return_value = '{"score": 7}'
            return c

    call_count = 0

    def failing_then_passing_factory(
        *,
        tushare_adapter: Any,
        kb_adapter: Any,
        evaluator_client: Any,
        disable_critic: bool = False,
    ) -> Any:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("simulated auth error on first invocation")
        from datetime import UTC, datetime

        from app.agents.investment_dd_schema import (
            DEFAULT_DISCLAIMER,
            FinancialAnalysis,
            IndustryAnalysis,
            InvestmentDueDiligenceReport,
            InvestmentRecommendation,
            LegalQualification,
            PriceRange,
            RiskAssessment,
            TargetOverview,
            ValuationAnalysis,
        )

        def runner(target_name: str, target_ts_code: str) -> InvestmentDueDiligenceReport:
            return InvestmentDueDiligenceReport(
                target_name=target_name,
                target_ts_code=target_ts_code,
                request_id="prod-test",
                generated_at=datetime.now(UTC),
                target_overview=TargetOverview(narrative="...", main_business="X"),
                legal_qualification=LegalQualification(
                    narrative="...",
                    legal_status="ok",
                    business_qualifications=[],
                    adverse_records=[],
                ),
                financial_analysis=FinancialAnalysis(
                    narrative="...",
                    key_metrics=[],
                    profitability_analysis="...",
                    growth_analysis="...",
                    return_analysis="...",
                    cash_flow_analysis="...",
                    valuation_analysis=ValuationAnalysis(narrative="..."),
                ),
                industry_analysis=IndustryAnalysis(
                    narrative="...",
                    industry_name="X",
                    industry_outlook="...",
                    competitive_position="...",
                    key_competitors=[],
                    policy_impact="...",
                ),
                risk_assessment=RiskAssessment(
                    narrative="...",
                    market_risk=[],
                    growth_risk=[],
                    event_risk=[],
                    valuation_risk=[],
                    overall_risk_level="medium",
                ),
                investment_recommendation=InvestmentRecommendation(
                    narrative="...",
                    recommendation="recommend_hold",
                    recommended_position_size_pct=5.0,
                    recommended_holding_period="medium_term",
                    recommended_entry_price_range=PriceRange(low=1400, high=1500),
                    recommended_stop_loss_price=1300,
                    estimated_target_price_range=PriceRange(low=1600, high=1700),
                    position_management_conditions=[],
                ),
                disclaimer=DEFAULT_DISCLAIMER,
            )

        return runner

    runner = AblationRunner(
        swapper=_DummySwapper(),  # type: ignore[arg-type]
        tushare_inner=_Tushare(),
        kb_inner=_KB(),
        db_path=tmp_path / "ev.db",
        production_factory=failing_then_passing_factory,
        metric_registry=MetricRegistry([]),
    )
    cases = [
        BacktestCase("c1", "600519.SH", "茅台", date(2024, 6, 30)),
        BacktestCase("c2", "300750.SZ", "宁德", date(2024, 6, 30)),
    ]
    results = runner.run_ablation(
        cases=cases,
        variants=list(AblationVariant),  # 4 variants × 2 cases = 8 total
        evaluator_llm="deepseek-v4-flash",
        git_sha="testsha-failsoft",
    )

    # 4 variants × 2 cases = 8 total — fail-soft must not abort early
    assert len(results) == 8
    failed = [r for r in results if r.status == "failed"]
    completed = [r for r in results if r.status == "completed"]
    # V0×c1 should have failed (call_count=1 raises); remaining 7 complete
    assert len(failed) >= 1, "first factory call should have failed"
    assert len(completed) >= 1, "subsequent calls should complete (fail-soft)"
    assert failed[0].error is not None
    assert "auth error" in failed[0].error.lower()

    # BacktestRunner.finally writes status row even on failure — DB count must match
    with sqlite3.connect(tmp_path / "ev.db") as con:
        n = con.execute(
            "SELECT COUNT(*) FROM backtest_runs WHERE git_sha = ?",
            ("testsha-failsoft",),
        ).fetchone()[0]
    assert n == 8


def test_ablation_variant_field_set_per_run(tmp_path) -> None:
    runner = _make_runner(tmp_path / "ev.db")
    cases = [BacktestCase("c1", "600519.SH", "茅台", date(2024, 6, 30))]
    runner.run_ablation(
        cases=cases,
        variants=[AblationVariant.V0_BASELINE, AblationVariant.V1_NO_RAG],
        evaluator_llm="deepseek-v4-flash",
        git_sha="testsha2",
    )
    with sqlite3.connect(tmp_path / "ev.db") as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT ablation_variant FROM backtest_runs WHERE git_sha = ?", ("testsha2",)
        ).fetchall()
    variants_written = sorted(r["ablation_variant"] for r in rows)
    assert variants_written == ["V0_baseline", "V1_no_rag"]

"""Unit tests — Writer post_process_writer_output (v0.8.5).

Verify deterministic Python override of recommendation + position_size_pct
fields. The LLM-emitted values are intentionally overridden by skill-bundle
helpers (classify_recommendation + compute_position_size_pct).

spec ref: docs/superpowers/specs/2026-05-04-v0.8.5-constrained-router-design.md § Task 5
"""

from __future__ import annotations

from datetime import datetime

from app.agents.investment_dd_schema import (
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
from app.agents.schemas import ResearchState
from app.agents.writer import (
    _extract_metrics_from_llm_report,
    build_investment_dd_prompt,
    post_process_writer_output,
)


def _make_state(**kwargs: object) -> ResearchState:
    defaults: dict[str, object] = {
        "user_id": "test",
        "session_id": "sess-1",
        "user_message": "请对贵州茅台进行投资尽调。",
        "request_id": "req-1",
        "target_ts_code": "600519.SH",
        "client_total_aum": 10_000_000.0,
        "investment_objective": "balanced",
        "investment_horizon": "medium_term",
        "risk_tolerance": "moderate",
    }
    defaults.update(kwargs)
    return ResearchState(**defaults)  # type: ignore[arg-type]


def _make_dd_report(
    *,
    recommendation: str = "recommend_buy",
    position_size_pct: float = 18.0,
    market_cap: float | None = 1_000_000_000_000.0,
) -> InvestmentDueDiligenceReport:
    """Build a minimal InvestmentDueDiligenceReport with controllable § 6 values."""
    return InvestmentDueDiligenceReport(
        target_name="贵州茅台",
        target_ts_code="600519.SH",
        request_id="req-1",
        generated_at=datetime(2026, 5, 5, 10, 0, 0),
        target_overview=TargetOverview(
            narrative="标的综述",
            main_business="白酒生产销售",
            current_market_cap=market_cap,
        ),
        legal_qualification=LegalQualification(
            narrative="资质综述",
            legal_status="合规",
            business_qualifications=[],
            adverse_records=[],
        ),
        financial_analysis=FinancialAnalysis(
            narrative="财务综述",
            key_metrics=[],
            profitability_analysis="盈利分析",
            growth_analysis="成长分析",
            return_analysis="回报分析",
            cash_flow_analysis="现金流分析",
            valuation_analysis=ValuationAnalysis(narrative="估值综述"),
        ),
        industry_analysis=IndustryAnalysis(
            narrative="行业综述",
            industry_name="白酒",
            industry_outlook="景气",
            competitive_position="龙头",
            key_competitors=[],
            policy_impact="无重大影响",
        ),
        risk_assessment=RiskAssessment(
            narrative="风险综述",
            market_risk=[],
            growth_risk=[],
            event_risk=[],
            valuation_risk=[],
            overall_risk_level="medium",
        ),
        investment_recommendation=InvestmentRecommendation(
            narrative="LLM 给出的建议综述(将被 post_process 覆盖)",
            recommendation=recommendation,  # type: ignore[arg-type]
            recommended_position_size_pct=position_size_pct,
            recommended_holding_period="medium_term",
            recommended_entry_price_range=PriceRange(low=1500.0, high=1800.0),
            recommended_stop_loss_price=1400.0,
            estimated_target_price_range=PriceRange(low=2000.0, high=2200.0),
            position_management_conditions=["分批建仓"],
        ),
    )


def test_writer_post_process_overrides_recommendation_and_size() -> None:
    """LLM 输出 recommend_buy + 18% — post_process 必须根据 metrics 重新分类。

    LLM-driven report carries the schema fields used by the schema (no `roe` /
    `revenue_yoy` numeric extras) so classify_recommendation falls through to
    the recommend_hold fallback rule. compute_position_size_pct(hold, moderate,
    1T) = 5.0 * 1.0 * 1.0 = 5.0%. Both values must override the LLM's
    optimistic 18% / recommend_buy.
    """
    state = _make_state(risk_tolerance="moderate")
    llm_report = _make_dd_report(
        recommendation="recommend_buy",
        position_size_pct=18.0,
        market_cap=1_000_000_000_000.0,
    )
    out = post_process_writer_output(state, llm_report)
    # LLM 的 recommend_buy 被覆盖为 fallback recommend_hold
    assert out.investment_recommendation.recommendation == "recommend_hold"
    # 仓位也由 deterministic 公式重算 — 不再是 LLM 的 18.0
    assert out.investment_recommendation.recommended_position_size_pct == 5.0


def test_writer_post_process_deterministic() -> None:
    """同 (state, llm_report) 多次调用必须产生一致输出 (idempotent)。"""
    state = _make_state(risk_tolerance="aggressive")
    llm_report = _make_dd_report(recommendation="recommend_overweight", position_size_pct=10.0)
    out1 = post_process_writer_output(state, llm_report)
    out2 = post_process_writer_output(state, llm_report)
    assert out1.investment_recommendation.recommendation == (
        out2.investment_recommendation.recommendation
    )
    assert out1.investment_recommendation.recommended_position_size_pct == (
        out2.investment_recommendation.recommended_position_size_pct
    )


def test_writer_post_process_preserves_other_fields() -> None:
    """post_process 改 recommendation + size + narrative footer,其它字段必须保持原样。

    v0.8.5 forward concern 2: post_process now also appends a deterministic
    narrative footer announcing the Python override. The original LLM-authored
    narrative prefix must still be preserved as the leading text.
    """
    state = _make_state()
    llm_report = _make_dd_report(recommendation="recommend_buy", position_size_pct=18.0)
    out = post_process_writer_output(state, llm_report)
    # narrative 的 LLM 部分必须保留 (作为前缀); footer 是新增内容
    out_narr = out.investment_recommendation.narrative
    src_narr = llm_report.investment_recommendation.narrative
    assert out_narr.startswith(src_narr.rstrip()), (
        f"LLM-authored narrative must remain as prefix; got {out_narr!r}"
    )
    assert "Python 决定论修正" in out_narr, "footer must be appended"
    assert (
        out.investment_recommendation.recommended_holding_period
        == llm_report.investment_recommendation.recommended_holding_period
    )
    assert (
        out.investment_recommendation.recommended_entry_price_range
        == llm_report.investment_recommendation.recommended_entry_price_range
    )
    assert (
        out.investment_recommendation.recommended_stop_loss_price
        == llm_report.investment_recommendation.recommended_stop_loss_price
    )
    # 其它 section 完全不动
    assert out.target_overview == llm_report.target_overview
    assert out.financial_analysis == llm_report.financial_analysis
    assert out.industry_analysis == llm_report.industry_analysis


def test_writer_post_process_narrative_footer_idempotent() -> None:
    """v0.8.5 forward concern 2 — re-running post_process must not stack footers.

    Footer marker '`Python 决定论修正`' is detected via substring; second pass
    finds it and skips appending so narrative stays exactly one footer long.
    """
    state = _make_state()
    llm_report = _make_dd_report(recommendation="recommend_buy", position_size_pct=18.0)
    out1 = post_process_writer_output(state, llm_report)
    out2 = post_process_writer_output(state, out1)
    assert out1.investment_recommendation.narrative == out2.investment_recommendation.narrative
    # Exactly one occurrence of the footer marker
    assert out1.investment_recommendation.narrative.count("Python 决定论修正") == 1


def test_writer_post_process_footer_idempotent_when_llm_quotes_marker_text() -> None:
    """v0.8.5 — LLM 在 narrative 引用可见文字 'Python 决定论修正' 不能让 footer 误 skip.

    sentinel 是 HTML 注释 _FOOTER_SENTINEL ('<!-- v0.8.5-pyoverride-v1 -->'),
    markdown 渲染不可见; 旧版 bare-substring 检测 'Python 决定论修正' 会被 LLM
    narrative 中的同名文字触发 false-positive skip, 导致 footer 不被追加 →
    Python 决定论失效但用户看不到提示.
    """
    state = _make_state()
    base = _make_dd_report(recommendation="recommend_buy", position_size_pct=18.0)
    # 模拟 LLM narrative 引用了可见 marker text 但没有真 sentinel
    quoting_narrative = (
        "本次基于多维分析给出 recommend_buy。(注:最终 Python 决定论修正会在下方追加,以本部分为准。)"
    )
    base_with_quote = base.model_copy(
        update={
            "investment_recommendation": base.investment_recommendation.model_copy(
                update={"narrative": quoting_narrative}
            )
        }
    )
    out = post_process_writer_output(state, base_with_quote)
    out_narr = out.investment_recommendation.narrative
    # 原 LLM 引用文字保留 (作为 prefix)
    assert quoting_narrative.rstrip() in out_narr, (
        f"LLM-quoted 'Python 决定论修正' 文字必须保留为 prefix; got {out_narr!r}"
    )
    # sentinel HTML 注释必须真 append (不被 quote 误 skip)
    assert "<!-- v0.8.5-pyoverride-v1 -->" in out_narr, (
        f"sentinel 必须 append; LLM quote 不能误 skip footer; got {out_narr!r}"
    )
    # 第二次 post_process 应识别 sentinel 并 skip — 真 idempotent
    out2 = post_process_writer_output(state, out)
    assert out.investment_recommendation.narrative == out2.investment_recommendation.narrative
    assert out2.investment_recommendation.narrative.count("<!-- v0.8.5-pyoverride-v1 -->") == 1


def test_writer_post_process_uses_state_risk_tolerance() -> None:
    """风险容忍度 conservative vs aggressive 应得出不同仓位。"""
    llm_report = _make_dd_report(
        recommendation="recommend_buy",
        position_size_pct=10.0,
        market_cap=1_000_000_000_000.0,
    )
    state_cons = _make_state(risk_tolerance="conservative")
    state_aggr = _make_state(risk_tolerance="aggressive")
    out_cons = post_process_writer_output(state_cons, llm_report)
    out_aggr = post_process_writer_output(state_aggr, llm_report)
    # 二者 recommendation 都会 fallback 到 recommend_hold (默认 metric 不足),
    # 但 compute_position_size_pct(hold, conservative=0.5x) < (hold, aggressive=1.6x)
    pct_cons = out_cons.investment_recommendation.recommended_position_size_pct
    pct_aggr = out_aggr.investment_recommendation.recommended_position_size_pct
    assert pct_cons < pct_aggr, f"conservative 仓位 ({pct_cons}) 应小于 aggressive ({pct_aggr})"


def test_extract_metrics_handles_missing_fields() -> None:
    """_extract_metrics_from_llm_report 在缺字段时不报错,返回默认。"""
    metrics = _extract_metrics_from_llm_report({})
    assert metrics["pe_percentile"] == 0.5
    assert metrics["roe"] == 0.0
    assert metrics["forecast_signal"] == "neutral"
    assert metrics["asset_liability_warning"] is False


def test_extract_metrics_uses_numeric_pe_percentile_when_present() -> None:
    """v0.8.5 forward concern 1 — numeric field takes precedence over str."""
    report = {
        "financial_analysis": {
            "valuation_analysis": {
                # Both fields present; numeric wins.
                "pe_historical_percentile": "近 5 年 80 分位",
                "pe_historical_percentile_value": 0.30,
            }
        }
    }
    metrics = _extract_metrics_from_llm_report(report)
    assert metrics["pe_percentile"] == 0.30, (
        "numeric pe_historical_percentile_value must take precedence over str"
    )


def test_extract_metrics_falls_back_to_regex_parse_of_str_percentile() -> None:
    """v0.8.5 forward concern 1 — regex parses '近 5 年 30 分位' → 0.30."""
    report = {
        "financial_analysis": {
            "valuation_analysis": {
                "pe_historical_percentile": "近 5 年 30 分位",
                # numeric field absent → regex fallback.
            }
        }
    }
    metrics = _extract_metrics_from_llm_report(report)
    assert metrics["pe_percentile"] == 0.30, (
        f"regex fallback should parse '30 分位' → 0.30, got {metrics['pe_percentile']}"
    )


def test_extract_metrics_rejects_bool_pe_value() -> None:
    """v0.8.5 — bool 是 int subclass, 必须显式 reject 防 True/False 误触发 red-line.

    isinstance(True, int) == True 在 Python 是 True, 没有 not-bool guard
    pe_historical_percentile_value=True 会通过 0.0<=float(True)=1.0<=1.0 拿 1.0
    触发 sell red-line — silent misroute. 这里 fixture 不提供 str pe →
    fallback 到 0.5 mid-cap default.
    """
    for bad in [True, False]:
        report = {
            "financial_analysis": {
                "valuation_analysis": {
                    "pe_historical_percentile_value": bad,
                }
            }
        }
        metrics = _extract_metrics_from_llm_report(report)
        assert metrics["pe_percentile"] == 0.5, (
            f"bool {bad!r} must be rejected, fall through to 0.5 default; "
            f"got {metrics['pe_percentile']}"
        )


def test_extract_metrics_falls_back_to_default_on_unparseable_string() -> None:
    """v0.8.5 forward concern 1 — bad str → 0.5 mid-cap default."""
    report = {
        "financial_analysis": {
            "valuation_analysis": {
                "pe_historical_percentile": "估值合理(未给具体百分位)",
            }
        }
    }
    metrics = _extract_metrics_from_llm_report(report)
    assert metrics["pe_percentile"] == 0.5


def test_extract_metrics_debt_ratio_assessment_warning_red_line() -> None:
    """v0.8.5 forward concern 3 — debt_ratio_assessment 字段 wired (was dead code)."""
    # 警戒 → True
    report_warn = {
        "financial_analysis": {"debt_ratio_assessment": "警戒"},
    }
    assert _extract_metrics_from_llm_report(report_warn)["asset_liability_warning"] is True

    # 高风险 → True
    report_risk = {
        "financial_analysis": {"debt_ratio_assessment": "高风险"},
    }
    assert _extract_metrics_from_llm_report(report_risk)["asset_liability_warning"] is True

    # 健康 → False
    report_ok = {
        "financial_analysis": {"debt_ratio_assessment": "健康"},
    }
    assert _extract_metrics_from_llm_report(report_ok)["asset_liability_warning"] is False


def test_writer_prompt_contains_sop_section() -> None:
    """v0.8.5 — Writer prompt 必须含 SOP 11 维度方法论 section。"""
    state = _make_state()
    prompt = build_investment_dd_prompt(state)
    assert "投资研究员 SOP" in prompt or "11 维度方法论" in prompt
    # 至少 11 关键词中的代表性几个出现
    for kw in [
        "偿债",
        "盈利",
        "成长",
        "现金流",
        "估值",
        "行业",
        "股东",
        "资金流",
        "事件",
        "风险",
        "决策",
    ]:
        assert kw in prompt, f"writer prompt missing SOP keyword: {kw}"

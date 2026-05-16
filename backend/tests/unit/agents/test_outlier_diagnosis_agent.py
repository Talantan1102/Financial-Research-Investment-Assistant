"""L0 — OutlierDiagnosisAgent (LLM call only on severe divergence; sync API)."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.agents.investment_dd_schema import OutlierDiagnosis, ValuationModel
from app.services.llm_response import LLMResponse


def _mock_llm_returning_diagnosis() -> MagicMock:
    """mock LLMService.chat 返回 LLMResponse.parsed = OutlierDiagnosis 实例."""
    diagnosis = OutlierDiagnosis(
        outlier_model=ValuationModel.DCF,
        likely_cause="DCF 永续增长率假设 5% 偏离行业 2.5%, terminal value 飘高",
        confidence="high",
        recommended_action="trust_consensus",
        narrative="DCF 给 5000, PE 给 1500. DCF 永续增长率应调到 2.5% 行业标准。",
    )
    response = LLMResponse(
        content=diagnosis.model_dump_json(),
        parsed=diagnosis,
        model="qwen-test",
        tier="balanced",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        cost_cny=0.0,
        latency_ms=100,
    )

    llm = MagicMock()
    llm.chat = MagicMock(return_value=response)
    return llm


def test_diagnose_returns_outlier_diagnosis() -> None:
    from app.agents.outlier_diagnosis_agent import OutlierDiagnosisAgent

    llm = _mock_llm_returning_diagnosis()
    agent = OutlierDiagnosisAgent(llm=llm)

    result = agent.diagnose(
        valuations={"pe": 1500.0, "dcf_base": 5000.0},
        assumptions={"dcf": {"terminal_growth": 0.05, "wacc": 0.08}},
        company_narrative="贵州茅台,白酒龙头",
    )

    assert result is not None
    assert result.outlier_model == ValuationModel.DCF
    assert result.confidence == "high"
    assert "永续" in result.likely_cause or "terminal" in result.likely_cause.lower()


def test_diagnose_returns_none_on_llm_failure() -> None:
    """LLM raises → return None (不 retry, 不 propagate)."""
    from app.agents.outlier_diagnosis_agent import OutlierDiagnosisAgent

    llm = MagicMock()
    llm.chat = MagicMock(side_effect=RuntimeError("LLM timeout"))
    agent = OutlierDiagnosisAgent(llm=llm)

    result = agent.diagnose(
        valuations={"pe": 1500.0, "dcf_base": 5000.0},
        assumptions={},
        company_narrative="test",
    )
    assert result is None


def test_diagnose_prompt_includes_valuations_and_assumptions() -> None:
    """verify prompt 包含数字和关键假设(便于 LLM 真诊断)"""
    from app.agents.outlier_diagnosis_agent import OutlierDiagnosisAgent

    llm = _mock_llm_returning_diagnosis()
    agent = OutlierDiagnosisAgent(llm=llm)

    agent.diagnose(
        valuations={"pe": 1500.0, "dcf_base": 5000.0},
        assumptions={"dcf": {"terminal_growth": 0.05, "wacc": 0.08}},
        company_narrative="贵州茅台",
    )

    # llm.chat called once
    assert llm.chat.call_count == 1
    call_kwargs = llm.chat.call_args.kwargs
    prompt = call_kwargs["prompt"]
    assert "1500" in prompt
    assert "5000" in prompt
    assert "terminal_growth" in prompt or "永续" in prompt
    assert "贵州茅台" in prompt


def test_diagnose_uses_schema_constrained_call() -> None:
    """schema=OutlierDiagnosis 必须传入,确保 LLM 返回结构化."""
    from app.agents.outlier_diagnosis_agent import OutlierDiagnosisAgent

    llm = _mock_llm_returning_diagnosis()
    agent = OutlierDiagnosisAgent(llm=llm)
    agent.diagnose(
        valuations={"pe": 1500.0, "dcf_base": 5000.0},
        assumptions={},
        company_narrative="test",
    )

    call_kwargs = llm.chat.call_args.kwargs
    assert call_kwargs.get("schema") == OutlierDiagnosis
    # tier 用 "balanced"(spec: 诊断 task complexity 中等)
    assert call_kwargs.get("tier") == "balanced"


def test_diagnose_returns_none_when_parsed_not_outlier_diagnosis() -> None:
    """若 LLM 返回 LLMResponse.parsed 是 None / 不是 OutlierDiagnosis(异常路径)→ fallback try content,
    parse 失败也 → None."""
    from app.agents.outlier_diagnosis_agent import OutlierDiagnosisAgent

    response = LLMResponse(
        content="not valid OutlierDiagnosis json blob",
        parsed=None,
        model="qwen-test",
        tier="balanced",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        cost_cny=0.0,
        latency_ms=100,
    )
    llm = MagicMock()
    llm.chat = MagicMock(return_value=response)

    agent = OutlierDiagnosisAgent(llm=llm)
    result = agent.diagnose(
        valuations={"pe": 1500.0},
        assumptions={},
        company_narrative="test",
    )
    assert result is None

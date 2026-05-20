"""L0 — BearAdvocate single-round LLM call + AdvocateOutput parse."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.agents.debate_schemas import AdvocateOutput
from app.services.llm_response import LLMResponse


def _mock_llm_with_advocate_output() -> MagicMock:
    out = AdvocateOutput(
        arguments=[
            "PE 30x 接近历史 80% 分位 (贵)",
            "反腐 + 八项规定影响高端消费",
            "年轻一代不喝白酒 20-30 年隐忧",
        ],
        strongest_argument="估值接近历史高位",
        confidence="medium",
    )
    response = LLMResponse(
        content=out.model_dump_json(),
        parsed=out,
        model="qwen-turbo",
        tier="fast",
        prompt_tokens=200,
        completion_tokens=100,
        total_tokens=300,
        cost_cny=0.001,
        latency_ms=300,
    )
    llm = MagicMock()
    llm.chat = MagicMock(return_value=response)
    return llm


def test_bear_advocate_round_1_returns_advocate_output() -> None:
    from app.agents.bear_advocate import BearAdvocate
    from app.agents.schemas import ResearchState

    llm = _mock_llm_with_advocate_output()
    advocate = BearAdvocate(llm=llm)
    state = ResearchState(
        user_id="u",
        session_id="s",
        user_message="尽调贵州茅台 600519.SH",
        request_id="r",
        target_ts_code="600519.SH",
    )
    result = advocate.advocate_round_1(state)
    assert result is not None
    assert isinstance(result, AdvocateOutput)


def test_bear_advocate_returns_none_on_llm_failure() -> None:
    from app.agents.bear_advocate import BearAdvocate
    from app.agents.schemas import ResearchState

    llm = MagicMock()
    llm.chat = MagicMock(side_effect=RuntimeError("timeout"))
    advocate = BearAdvocate(llm=llm)
    state = ResearchState(user_id="u", session_id="s", user_message="m", request_id="r")
    assert advocate.advocate_round_1(state) is None


def test_bear_advocate_uses_fast_tier() -> None:
    from app.agents.bear_advocate import BearAdvocate
    from app.agents.schemas import ResearchState

    llm = _mock_llm_with_advocate_output()
    advocate = BearAdvocate(llm=llm)
    state = ResearchState(user_id="u", session_id="s", user_message="m", request_id="r")
    advocate.advocate_round_1(state)
    call_kwargs = llm.chat.call_args.kwargs
    assert call_kwargs.get("tier") == "fast"
    assert call_kwargs.get("schema") == AdvocateOutput


def test_bear_advocate_prompt_includes_dcf_bear_outlier() -> None:
    """Bear 引 dcf_bear (看空价格) + outlier_diagnosis (打架信号)."""
    from app.agents.bear_advocate import BearAdvocate
    from app.agents.investment_dd_schema import (
        OutlierDiagnosis,
        ValuationAnalysis,
        ValuationModel,
    )
    from app.agents.schemas import ResearchState

    diagnosis = OutlierDiagnosis(
        outlier_model=ValuationModel.DCF,
        likely_cause="永续增长率假设过乐观",
        confidence="high",
        recommended_action="trust_consensus",
        narrative="DCF 5000 偏离 PE 1500, 主因永续增长率假设过乐观。",
    )
    va = ValuationAnalysis(
        narrative="cross-check",
        active_models=[ValuationModel.PE, ValuationModel.DCF],
        pe_value=1500.0,
        dcf_base=5000.0,
        dcf_bear=2500.0,
        valuation_consistency="severe",
        outlier_diagnosis=diagnosis,
    )
    llm = _mock_llm_with_advocate_output()
    advocate = BearAdvocate(llm=llm)
    state = ResearchState(
        user_id="u",
        session_id="s",
        user_message="m",
        request_id="r",
        valuation_analysis=va,
    )
    advocate.advocate_round_1(state)
    prompt = llm.chat.call_args.kwargs["prompt"]
    assert "2500" in prompt or "DCF bear" in prompt
    assert "永续增长率假设过乐观" in prompt or "outlier" in prompt.lower()


def test_bear_advocate_round_2_includes_bull_v1() -> None:
    """round 2 prompt 必须含 bull_v1 让 BearAdvocate 反驳."""
    from app.agents.bear_advocate import BearAdvocate
    from app.agents.schemas import ResearchState

    bull_v1 = AdvocateOutput(
        arguments=["品牌护城河 30 年", "ROE 30% 稳定", "提价权 5-10%"],
        strongest_argument="提价权 + 品牌 = 长期复利",
        confidence="high",
    )
    llm = _mock_llm_with_advocate_output()
    advocate = BearAdvocate(llm=llm)
    state = ResearchState(user_id="u", session_id="s", user_message="m", request_id="r")
    advocate.advocate_round_2(state, bull_v1)
    prompt = llm.chat.call_args.kwargs["prompt"]
    assert "品牌护城河 30 年" in prompt or "提价权 + 品牌" in prompt


def test_bear_advocate_round_2_returns_none_on_failure() -> None:
    from app.agents.bear_advocate import BearAdvocate
    from app.agents.schemas import ResearchState

    bull_v1 = AdvocateOutput(arguments=["1", "2", "3"], strongest_argument="x", confidence="low")
    llm = MagicMock()
    llm.chat = MagicMock(side_effect=RuntimeError("timeout"))
    advocate = BearAdvocate(llm=llm)
    state = ResearchState(user_id="u", session_id="s", user_message="m", request_id="r")
    assert advocate.advocate_round_2(state, bull_v1) is None

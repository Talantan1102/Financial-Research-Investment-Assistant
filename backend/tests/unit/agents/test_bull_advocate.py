"""L0 — BullAdvocate single-round LLM call + AdvocateOutput parse."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.agents.debate_schemas import AdvocateOutput
from app.services.llm_response import LLMResponse


def _mock_llm_with_advocate_output() -> MagicMock:
    """mock LLMService.chat 返 LLMResponse(parsed=AdvocateOutput)."""
    out = AdvocateOutput(
        arguments=[
            "茅台品牌护城河 30 年, 同业不可超越",
            "ROE 长期 30%+, 业绩稳定",
            "提价权强, 年提价 5-10% 客户照买",
        ],
        strongest_argument="提价权 + 品牌 = 长期复利公司",
        confidence="high",
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


def test_bull_advocate_round_1_returns_advocate_output() -> None:
    from app.agents.bull_advocate import BullAdvocate
    from app.agents.schemas import ResearchState

    llm = _mock_llm_with_advocate_output()
    advocate = BullAdvocate(llm=llm)

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
    assert len(result.arguments) >= 3
    assert result.confidence in {"high", "medium", "low"}


def test_bull_advocate_returns_none_on_llm_failure() -> None:
    from app.agents.bull_advocate import BullAdvocate
    from app.agents.schemas import ResearchState

    llm = MagicMock()
    llm.chat = MagicMock(side_effect=RuntimeError("LLM timeout"))
    advocate = BullAdvocate(llm=llm)

    state = ResearchState(user_id="u", session_id="s", user_message="m", request_id="r")
    result = advocate.advocate_round_1(state)
    assert result is None


def test_bull_advocate_uses_fast_tier() -> None:
    """advocate 走 fast tier (low-complexity task), 跟 v0.8.5 TierRouter 范式一致."""
    from app.agents.bull_advocate import BullAdvocate
    from app.agents.schemas import ResearchState

    llm = _mock_llm_with_advocate_output()
    advocate = BullAdvocate(llm=llm)
    state = ResearchState(user_id="u", session_id="s", user_message="m", request_id="r")
    advocate.advocate_round_1(state)

    call_kwargs = llm.chat.call_args.kwargs
    assert call_kwargs.get("tier") == "fast"
    assert call_kwargs.get("schema") == AdvocateOutput


def test_bull_advocate_prompt_includes_valuation_analysis_when_available() -> None:
    """如果 state.valuation_analysis 不 None, prompt 应引用 PE / DCF / outlier."""
    from app.agents.bull_advocate import BullAdvocate
    from app.agents.investment_dd_schema import ValuationAnalysis, ValuationModel
    from app.agents.schemas import ResearchState

    va = ValuationAnalysis(
        narrative="cross-check",
        active_models=[ValuationModel.PE, ValuationModel.DCF],
        pe_value=1500.0,
        dcf_base=1800.0,
        dcf_bull=2200.0,
        dcf_bear=1500.0,
        valuation_consistency="consistent",
    )
    llm = _mock_llm_with_advocate_output()
    advocate = BullAdvocate(llm=llm)
    state = ResearchState(
        user_id="u",
        session_id="s",
        user_message="尽调茅台",
        request_id="r",
        valuation_analysis=va,
    )
    advocate.advocate_round_1(state)

    prompt = llm.chat.call_args.kwargs["prompt"]
    # Bull 引 dcf_bull(看多)
    assert "2200" in prompt or "DCF bull" in prompt
    # PE 也露在 prompt
    assert "1500" in prompt or "PE" in prompt


def test_bull_advocate_round_2_includes_bear_v1() -> None:
    """round 2 prompt 必须含 bear_v1 arguments 让 BullAdvocate 反驳."""
    from app.agents.bull_advocate import BullAdvocate
    from app.agents.schemas import ResearchState

    bear_v1 = AdvocateOutput(
        arguments=[
            "PE 30x 接近历史 80% 分位 (贵)",
            "反腐 + 八项规定影响高端消费",
            "年轻一代不喝白酒 20-30 年隐忧",
        ],
        strongest_argument="估值接近历史高位",
        confidence="medium",
    )
    llm = _mock_llm_with_advocate_output()
    advocate = BullAdvocate(llm=llm)
    state = ResearchState(user_id="u", session_id="s", user_message="m", request_id="r")
    advocate.advocate_round_2(state, bear_v1)

    prompt = llm.chat.call_args.kwargs["prompt"]
    assert "PE 30x 接近历史 80% 分位" in prompt or "估值接近历史高位" in prompt


def test_bull_advocate_round_2_returns_none_on_failure() -> None:
    from app.agents.bull_advocate import BullAdvocate
    from app.agents.schemas import ResearchState

    bear_v1 = AdvocateOutput(arguments=["1", "2", "3"], strongest_argument="x", confidence="low")
    llm = MagicMock()
    llm.chat = MagicMock(side_effect=RuntimeError("timeout"))
    advocate = BullAdvocate(llm=llm)
    state = ResearchState(user_id="u", session_id="s", user_message="m", request_id="r")
    result = advocate.advocate_round_2(state, bear_v1)
    assert result is None

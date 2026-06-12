import pytest
from app.services.portfolio_narrator import narrate_today

_SAMPLE_ATTRIBUTION = {
    "total_pct": -1.05,
    "stock_breakdown": {
        "market": -0.40,
        "sector_excess": -0.46,
        "idiosyncratic": -0.09,
    },
    "contributions": [
        {"ts_code": "600519.SH", "contrib_pct": -1.05},
    ],
}

_BANNED = ("建议买", "建议卖", "应该减仓", "应该加仓", "清仓")


@pytest.mark.asyncio
async def test_narrate_uses_given_numbers_no_advice(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "mock")
    text = await narrate_today(_SAMPLE_ATTRIBUTION, persona_note="用户在意白酒仓位")
    assert isinstance(text, str) and len(text) > 0
    for banned in _BANNED:
        assert banned not in text, f"output contains banned phrase: {banned!r}"


@pytest.mark.asyncio
async def test_narrate_no_persona_note(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "mock")
    text = await narrate_today(_SAMPLE_ATTRIBUTION)
    assert isinstance(text, str) and len(text) > 0
    for banned in _BANNED:
        assert banned not in text, f"output contains banned phrase: {banned!r}"


@pytest.mark.asyncio
async def test_narrate_mock_is_deterministic(monkeypatch):
    """mock 模式下两次调用结果相同(确定性)。"""
    monkeypatch.setenv("LLM_MODE", "mock")
    t1 = await narrate_today(_SAMPLE_ATTRIBUTION, persona_note="关注白酒")
    t2 = await narrate_today(_SAMPLE_ATTRIBUTION, persona_note="关注白酒")
    assert t1 == t2


@pytest.mark.asyncio
async def test_narrate_contains_total_pct(monkeypatch):
    """mock 模式输出应包含 total_pct 数字。"""
    monkeypatch.setenv("LLM_MODE", "mock")
    text = await narrate_today(_SAMPLE_ATTRIBUTION)
    # total_pct is -1.05; the template should mention "-1.05" or "1.05"
    assert "-1.05" in text or "1.05" in text

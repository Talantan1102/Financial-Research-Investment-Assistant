"""LLMSwapper unit tests — Phase 1 Task 1.2.

spec § 4.1 决策 1 / § 5.3 LLM swap 机制
"""

from __future__ import annotations

import pytest


def test_llm_swapper_init_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLMSwapper init 时读 OPENROUTER_API_KEY env."""
    from eval.dd_report.llm_swapper import LLMSwapper

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-123")
    swapper = LLMSwapper()
    assert swapper.api_key == "test-key-123"


def test_llm_swapper_init_explicit_key() -> None:
    """LLMSwapper 接受显式 api_key 覆盖 env."""
    from eval.dd_report.llm_swapper import LLMSwapper

    swapper = LLMSwapper(api_key="explicit-key")
    assert swapper.api_key == "explicit-key"


def test_llm_swapper_get_client_for_known_models() -> None:
    """LLMSwapper.get_client 对每个 backtest evaluator model 返回 client."""
    from eval.dd_report.llm_swapper import EVALUATOR_MODELS, LLMSwapper

    swapper = LLMSwapper(api_key="test-key")

    # spec § 4.1 决策 1 — 3 个 backtest evaluator LLM
    expected = {"gpt-4o-2024-05-13", "qwen2.5-72b-instruct", "deepseek-v3"}
    assert expected.issubset(set(EVALUATOR_MODELS))

    for model_id in expected:
        client = swapper.get_client(model_id)
        assert client.model == model_id
        assert client.api_key == "test-key"


def test_llm_swapper_unknown_model_raises() -> None:
    """LLMSwapper.get_client 对未知 model raise."""
    from eval.dd_report.llm_swapper import LLMSwapper

    swapper = LLMSwapper(api_key="test-key")
    with pytest.raises(ValueError, match="unknown evaluator model"):
        swapper.get_client("not-a-real-model")


def test_evaluator_client_repr_hides_api_key() -> None:
    """I2 regression: api_key 不能出现在 repr 中, 防 log 泄露 credential."""
    from eval.dd_report.llm_swapper import LLMSwapper

    swapper = LLMSwapper(api_key="secret-token-xyz")
    client = swapper.get_client("gpt-4o-2024-05-13")

    rep = repr(client)
    assert "secret-token-xyz" not in rep, f"api_key leaked in repr: {rep!r}"
    # model 仍应该在 repr 中显示, 便于 debug
    assert "gpt-4o-2024-05-13" in rep

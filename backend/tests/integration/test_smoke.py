"""Smoke test: pytest discovers L1 integration layer and LLM_MODE=mock."""

import os


def test_integration_layer_llm_mode_mock():
    assert os.environ["LLM_MODE"] == "mock"

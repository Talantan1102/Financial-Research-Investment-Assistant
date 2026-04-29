"""Smoke test: pytest discovers L0 unit layer and LLM_MODE=none."""

import os


def test_unit_layer_llm_mode_none():
    assert os.environ["LLM_MODE"] == "none"

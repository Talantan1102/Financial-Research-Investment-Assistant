"""Smoke test: pytest discovers L3 eval layer and LLM_MODE=live."""

import os

import pytest


@pytest.mark.live_only
def test_eval_layer_llm_mode_live():
    assert os.environ["LLM_MODE"] == "live"

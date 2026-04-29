"""Smoke test: pytest discovers L2 e2e layer and LLM_MODE=cassette."""

import os


def test_e2e_layer_llm_mode_cassette():
    assert os.environ["LLM_MODE"] == "cassette"

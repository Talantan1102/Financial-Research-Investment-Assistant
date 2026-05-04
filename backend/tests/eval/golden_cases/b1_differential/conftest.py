"""Conftest for B-1 differential golden case tests (v0.8.4).

These tests are L2-style cassette tests (not live LLM) that verify:
  1. The 6-field prompt conditioning produces differential outputs
  2. The InputContextAppropriatenessScorer scores ≥ 8.5 for each case

VCR cassettes are stored per-module in:
  backend/tests/fixtures/cassettes/b1_differential/<module_stem>/<cassette>.yaml

To record cassettes (first time or re-record):
  unset all_proxy https_proxy http_proxy
  uv run pytest backend/tests/eval/golden_cases/b1_differential/ --record-mode=once -v
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

# Load backend/.env for DASHSCOPE_API_KEY (needed during cassette recording)
try:
    from dotenv import load_dotenv as _load_dotenv

    _load_dotenv(Path(__file__).parents[4] / ".env")
except ImportError:
    pass


FIXTURES_DIR = Path(__file__).parents[3] / "fixtures"


@pytest.fixture(scope="module")
def vcr_cassette_dir(request: pytest.FixtureRequest) -> str:
    """Override cassette directory: all differential cassettes go under b1_differential/.

    Uses module stem (e.g. "test_b1_diff_capital_preservation") as sub-directory
    so each test module has its own cassette directory.
    """
    module_stem = request.module.__name__.rsplit(".", 1)[-1]
    cassette_dir = FIXTURES_DIR / "cassettes" / "b1_differential" / module_stem
    cassette_dir.mkdir(parents=True, exist_ok=True)
    return str(cassette_dir)


@pytest.fixture(scope="module")
def vcr_config() -> dict[str, Any]:
    """VCR config for differential cassettes.

    Same as e2e conftest: drop body from match criteria because agent prompts
    contain dynamic values (timestamps, request_ids, chunk_ids).
    """

    def _strip_dashscope_response_headers(response: dict[str, Any]) -> dict[str, Any]:
        headers = response.get("headers", {})
        response["headers"] = {k: v for k, v in headers.items() if "dashscope" not in k.lower()}
        return response

    return {
        "filter_headers": [
            "authorization",
            "x-dashscope-api-key",
            "x-api-key",
            "openai-organization",
        ],
        "filter_post_data_parameters": [],
        "decode_compressed_response": True,
        "record_mode": os.environ.get("VCR_RECORD_MODE", "once"),
        "match_on": ["method", "scheme", "host", "port", "path"],
        "before_record_response": _strip_dashscope_response_headers,
    }


@pytest.fixture(autouse=True)
def _unset_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip proxy env vars — identical to e2e conftest."""
    for var in (
        "all_proxy",
        "ALL_PROXY",
        "https_proxy",
        "HTTPS_PROXY",
        "http_proxy",
        "HTTP_PROXY",
    ):
        monkeypatch.delenv(var, raising=False)

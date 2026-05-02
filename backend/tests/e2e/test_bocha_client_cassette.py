"""L2 cassette — BochaClient with real Bocha API, recorded via VCR.

Records one real Bocha API call (~¥0.001), replays offline in CI.
The cassette is committed to git; subsequent runs are pure replay (no network cost).

VCR config note:
  - Authorization header is filtered (→ REDACTED) before recording.
  - match_on excludes body: the query is stable, but body matching would fail
    if httpx serialises JSON keys in a different order on replay.
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from app.services.bocha_client import BochaClient

# ---------------------------------------------------------------------------
# VCR config (module-scoped, overrides the global vcr_config in conftest.py)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def vcr_config() -> dict[str, Any]:
    """VCR config tailored for Bocha httpx calls.

    - filter_headers strips the Bearer token before any cassette write.
    - match_on: method + scheme + host + port + path (no body — avoids
      JSON key-ordering sensitivity between record and replay runs).
    - record_mode controlled by VCR_RECORD_MODE env var (default "none").
    """
    return {
        "filter_headers": [
            "authorization",
            "x-api-key",
        ],
        "decode_compressed_response": True,
        "record_mode": os.environ.get("VCR_RECORD_MODE", "none"),
        "match_on": ["method", "scheme", "host", "port", "path"],
    }


# ---------------------------------------------------------------------------
# Cassette test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.vcr
async def test_bocha_client_search_maotai() -> None:
    """1 real Bocha API call. Records once, replays offline.

    During replay (VCR_RECORD_MODE unset / "none") a dummy key is used because
    VCR intercepts the HTTP call before any network traffic occurs, so the real
    key is never needed. During recording (VCR_RECORD_MODE=once) the real key
    must be present; the test skips if it is missing.
    """
    record_mode = os.environ.get("VCR_RECORD_MODE", "none")
    api_key = os.environ.get("BOCHA_API_KEY", "")
    if record_mode != "none" and not api_key:
        pytest.skip("BOCHA_API_KEY not set; skipping cassette record")
    # In replay mode use a dummy key (VCR intercepts before network)
    api_key = api_key or "fake-for-replay"

    client = BochaClient(api_key=api_key)
    result = await client.search(query="贵州茅台 600519", count=3)
    n = len(result["items"])
    assert n >= 1
    item = result["items"][0]
    assert "title" in item
    assert "url" in item
    await client.aclose()

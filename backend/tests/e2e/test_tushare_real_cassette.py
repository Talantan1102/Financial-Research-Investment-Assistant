"""E2E cassette test — real tushare API replays for 8 endpoints × 5 ts_codes.

Recording: VCR_RECORD_MODE=new_episodes TUSHARE_MODE=real
  - Hits proxy at TUSHARE_BASE_URL, rewrites URL to api.tushare.pro before saving
  - Strips real token from request body (replaced with REDACTED)
  - Rewrites proxy IP from any response body leakage

Replay (CI): default (record_mode=none), no env vars needed.

Path D (proxy URL scrub):
  - Record-time URL: http://47.109.59.144:8989/dataapi
  - Cassette URL:    http://api.tushare.pro  (after before_record_request rewrite)
  - Replay-time URL: http://api.tushare.pro  (TushareClient default base_url)
  - match_on: method + path + token_stripped_body
    → matches by api_name+params, ignoring token
"""

from __future__ import annotations

import contextlib
import json
import os
import re
from pathlib import Path
from typing import Any

import pytest
from app.services.rate_limiter import RateLimiter
from app.services.tushare_cache import TushareCache
from app.services.tushare_client import TushareClient
from app.services.tushare_service import RealTushareService

# ---------------------------------------------------------------------------
# Sample ts_codes — 5 well-known A-share stocks covering different exchanges
# ---------------------------------------------------------------------------

SAMPLE_TS_CODES = [
    "600519.SH",  # 贵州茅台
    "601398.SH",  # 工商银行
    "000001.SZ",  # 平安银行
    "000063.SZ",  # 中兴通讯
    "002594.SZ",  # 比亚迪
]

# ---------------------------------------------------------------------------
# Sensitive strings to scrub (proxy IP prefix + token prefix)
# ---------------------------------------------------------------------------

_PROXY_IP_PATTERN = re.compile(r"47\.109\.59\.144", re.IGNORECASE)
_PROXY_URL_PATTERN = re.compile(r"http://47\.109\.59\.144:[0-9]+[^\s\"']*")
_TOKEN_BODY_PATTERN = re.compile(
    r'"token"\s*:\s*"[^"]{8,}"',  # token value ≥8 chars
)
_REDACTED_TOKEN = '"token": "REDACTED"'


# ---------------------------------------------------------------------------
# VCR hooks
# ---------------------------------------------------------------------------


def _before_record_request(request: Any) -> Any:
    """Rewrite proxy URL → api.tushare.pro; strip real token from body."""
    # 1. Rewrite the URI to canonical api.tushare.pro/
    #    Recording hits: http://47.109.59.144:8989/dataapi
    #    Cassette saves: http://api.tushare.pro/  (trailing slash so path="/" is consistent)
    if request.uri and ("47.109.59.144" in request.uri or "/dataapi" in request.uri):
        request.uri = "http://api.tushare.pro/"

    # 2. Rewrite Host header if present
    if hasattr(request, "headers") and request.headers:
        host = request.headers.get("Host", request.headers.get("host", ""))
        if host and "47.109.59.144" in host:
            # vcr.Request headers may be a dict-like; suppress errors silently
            with contextlib.suppress(TypeError, KeyError):
                request.headers["Host"] = "api.tushare.pro"

    # 3. Strip real token from JSON body
    if request.body:
        raw = request.body
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        try:
            body_dict = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            body_dict = None

        if isinstance(body_dict, dict) and "token" in body_dict:
            body_dict["token"] = "REDACTED"
            request.body = json.dumps(body_dict).encode("utf-8")
        elif isinstance(raw, str) and '"token"' in raw:
            # Fallback: regex replace if JSON parse failed
            scrubbed = _TOKEN_BODY_PATTERN.sub(_REDACTED_TOKEN, raw)
            request.body = scrubbed.encode("utf-8")

    return request


def _before_record_response(response: Any) -> Any:
    """Defensive: scan response body for any proxy IP or token leakage."""
    body_obj = response.get("body", {})
    raw = body_obj.get("string", b"")
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)

    changed = False

    # Scrub proxy URL patterns first (more specific)
    scrubbed = _PROXY_URL_PATTERN.sub("http://api.tushare.pro", text)
    if scrubbed != text:
        changed = True
        text = scrubbed

    # Scrub any remaining IP occurrences
    scrubbed2 = _PROXY_IP_PATTERN.sub("api.tushare.pro", text)
    if scrubbed2 != text:
        changed = True
        text = scrubbed2

    if changed:
        response["body"]["string"] = text.encode("utf-8")

    return response


# ---------------------------------------------------------------------------
# VCR config (module-scoped, overrides the global vcr_config in conftest.py)
# token_stripped_body matcher registered in e2e/conftest.py pytest_recording_configure
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def vcr_config() -> dict[str, Any]:
    """VCR config for tushare cassettes.

    - before_record_request: scrub proxy URL + strip token
    - before_record_response: scrub any proxy IP leakage from response
    - match_on: method + path + token_stripped_body
      (path = "/" after URL rewrite; body discriminates by api_name+params)
    - record_mode: new_episodes when VCR_RECORD_MODE=new_episodes, else none
    """
    return {
        "filter_headers": ["authorization"],
        "decode_compressed_response": True,
        "record_mode": os.environ.get("VCR_RECORD_MODE", "none"),
        "before_record_request": _before_record_request,
        "before_record_response": _before_record_response,
        "match_on": ["method", "path", "token_stripped_body"],
    }


@pytest.fixture(scope="module")
def vcr_cassette_dir() -> str:
    """Store tushare cassettes in their own subdirectory."""
    cassette_dir = (
        Path(__file__).resolve().parents[2]
        / "tests"
        / "fixtures"
        / "cassettes"
        / "test_tushare_real_cassette"
    )
    cassette_dir.mkdir(parents=True, exist_ok=True)
    return str(cassette_dir)


# ---------------------------------------------------------------------------
# RealTushareService fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def service(tmp_path: Path) -> RealTushareService:
    """Build a RealTushareService pointed at env-configured URL.

    During recording: TUSHARE_TOKEN + TUSHARE_BASE_URL from .env
    During replay: token placeholder (VCR intercepts before network)
    """
    token = os.environ.get("TUSHARE_TOKEN", "REDACTED")
    base_url = os.environ.get("TUSHARE_BASE_URL", "http://api.tushare.pro")
    return RealTushareService(
        client=TushareClient(token=token, base_url=base_url),
        cache=TushareCache(db_path=tmp_path / "tushare_cache.sqlite"),
        rate_limiter=RateLimiter(max_calls=100, window_s=60.0),
    )


# ---------------------------------------------------------------------------
# 8 endpoint tests × 5 ts_codes (= 40 cassette episodes)
# ---------------------------------------------------------------------------
# NOTE: test_get_disclosure_date_real is NOT parametrized (ts_code=None API).
# Total: 7 × 5 + 1 = 36 episodes — matching plan's "~36 cassette files".
# ---------------------------------------------------------------------------


@pytest.mark.vcr
@pytest.mark.parametrize("ts_code", SAMPLE_TS_CODES)
@pytest.mark.asyncio
async def test_get_daily_real(service: RealTushareService, ts_code: str) -> None:
    """Fetch daily OHLCV for 2024-03 to 2024-05."""
    df = await service.get_daily(ts_code=ts_code, start="20240301", end="20240501")
    assert not df.empty, f"get_daily returned empty DataFrame for {ts_code}"
    assert "close" in df.columns or "trade_date" in df.columns, (
        f"get_daily missing expected columns for {ts_code}: {list(df.columns)}"
    )


@pytest.mark.vcr
@pytest.mark.parametrize("ts_code", SAMPLE_TS_CODES)
@pytest.mark.asyncio
async def test_get_income_real(service: RealTushareService, ts_code: str) -> None:
    """Fetch income statement (latest periods)."""
    df = await service.get_income(ts_code=ts_code)
    assert not df.empty, f"get_income returned empty DataFrame for {ts_code}"


@pytest.mark.vcr
@pytest.mark.parametrize("ts_code", SAMPLE_TS_CODES)
@pytest.mark.asyncio
async def test_get_fina_indicator_real(service: RealTushareService, ts_code: str) -> None:
    """Fetch financial indicators (ROE, gross margin, etc.)."""
    df = await service.get_fina_indicator(ts_code=ts_code)
    assert not df.empty, f"get_fina_indicator returned empty DataFrame for {ts_code}"


@pytest.mark.vcr
@pytest.mark.parametrize("ts_code", SAMPLE_TS_CODES)
@pytest.mark.asyncio
async def test_get_balance_sheet_real(service: RealTushareService, ts_code: str) -> None:
    """Fetch balance sheet (latest periods)."""
    df = await service.get_balance_sheet(ts_code=ts_code)
    assert not df.empty, f"get_balance_sheet returned empty DataFrame for {ts_code}"


@pytest.mark.vcr
@pytest.mark.parametrize("ts_code", SAMPLE_TS_CODES)
@pytest.mark.asyncio
async def test_get_cashflow_real(service: RealTushareService, ts_code: str) -> None:
    """Fetch cash flow statement (latest periods)."""
    df = await service.get_cashflow(ts_code=ts_code)
    assert not df.empty, f"get_cashflow returned empty DataFrame for {ts_code}"


@pytest.mark.vcr
@pytest.mark.parametrize("ts_code", SAMPLE_TS_CODES)
@pytest.mark.asyncio
async def test_get_stk_holdernumber_real(service: RealTushareService, ts_code: str) -> None:
    """Fetch shareholder count data.

    Some stocks may not have disclosure data — allow empty but must not raise.
    """
    df = await service.get_stk_holdernumber(ts_code=ts_code)
    # stk_holdernumber may be empty for some stocks (no disclosure) — that's OK
    assert df is not None, f"get_stk_holdernumber raised for {ts_code}"


@pytest.mark.vcr
@pytest.mark.asyncio
async def test_get_disclosure_date_real(service: RealTushareService) -> None:
    """Fetch report disclosure dates (market-wide, ts_code=None) for 2024-03 to 2024-05."""
    df = await service.get_disclosure_date(ts_code=None, start="20240301", end="20240501")
    # May be empty if no disclosures in range, but must not raise
    assert df is not None, "get_disclosure_date raised unexpectedly"


@pytest.mark.vcr
@pytest.mark.parametrize("ts_code", SAMPLE_TS_CODES)
@pytest.mark.asyncio
async def test_get_anns_real(service: RealTushareService, ts_code: str) -> None:
    """Fetch announcements for 2024-03 to 2024-05.

    May be empty for some stocks — that's OK.
    """
    df = await service.get_anns(ts_code=ts_code, start="20240301", end="20240501")
    assert df is not None, f"get_anns raised for {ts_code}"

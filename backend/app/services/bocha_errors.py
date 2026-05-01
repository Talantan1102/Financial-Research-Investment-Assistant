"""Bocha API error hierarchy.

Each error class corresponds to a distinct retry / circuit-breaker / user-facing behavior:

| Class                   | HTTP / cause          | Retry?  | Notes                                  |
|-------------------------|-----------------------|---------|----------------------------------------|
| BochaNetworkError       | DNS / TCP / TLS / r/w | yes     | exponential backoff in caller         |
| BochaRateLimitError     | HTTP 429              | NO      | rate_limiter should have prevented     |
| BochaAuthError          | HTTP 401 / 403        | NO      | re-auth needed                         |
| BochaServerError        | HTTP 5xx              | yes     | exponential backoff                    |
| BochaClientError        | HTTP 4xx (other)      | NO      | request itself is malformed            |
"""

from __future__ import annotations


class BochaError(Exception):
    """Base for all BochaClient errors."""


class BochaNetworkError(BochaError):
    """Network failure: DNS / connection / TLS / read timeout."""


class BochaRateLimitError(BochaError):
    """HTTP 429 — rate limit exceeded.

    rate_limiter.acquire() should have prevented this; if hit, signal that
    the limiter and the server disagree on quota state. Caller should
    treat as breaker-failure event but not retry.
    """


class BochaAuthError(BochaError):
    """HTTP 401 / 403 — invalid or revoked credentials."""


class BochaServerError(BochaError):
    """HTTP 5xx — Bocha-side server error, likely transient."""


class BochaClientError(BochaError):
    """HTTP 4xx (other than 401 / 403 / 429) — request itself is malformed."""

"""build_email_notifier — env-driven mock/real switch.

10th application of Protocol+Real+Mock+factory pattern in this repo.

Env vars:
  EMAIL_MODE       mock (default) | real
  SMTP_HOST        required in real mode
  SMTP_PORT        required in real mode (int)
  SMTP_USER        required in real mode
  SMTP_PASSWORD    required in real mode  (NOT logged anywhere)
  SMTP_FROM        required in real mode
  SMTP_USE_TLS     optional, default "true"
"""

from __future__ import annotations

import os
from pathlib import Path

from app.services.monitoring.notifications.email_notifier import (
    EmailNotifier,
    RealEmailNotifier,
)
from app.services.monitoring.notifications.mock_email_notifier import (
    MockEmailNotifier,
)

# __file__: backend/app/services/monitoring/notifications/factory.py
# parents[0] = .../notifications/
# parents[1] = .../monitoring/
# parents[2] = .../services/
# parents[3] = .../app/
# parents[4] = backend/
# → backend/data/emails_mock.sqlite (cwd-independent)
_MOCK_DB_PATH = Path(__file__).resolve().parents[4] / "data" / "emails_mock.sqlite"

_REQUIRED_REAL_VARS = (
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USER",
    "SMTP_PASSWORD",
    "SMTP_FROM",
)


def build_email_notifier() -> EmailNotifier:
    """Return an EmailNotifier configured from environment variables."""
    mode = os.environ.get("EMAIL_MODE", "mock").lower()

    if mode == "mock":
        return MockEmailNotifier(db_path=_MOCK_DB_PATH)

    if mode == "real":
        for var in _REQUIRED_REAL_VARS:
            if var not in os.environ:
                raise KeyError(f"{var} required when EMAIL_MODE=real")
        use_tls = os.environ.get("SMTP_USE_TLS", "true").lower() not in ("false", "0", "no")
        return RealEmailNotifier(
            host=os.environ["SMTP_HOST"],
            port=int(os.environ["SMTP_PORT"]),
            user=os.environ["SMTP_USER"],
            password=os.environ["SMTP_PASSWORD"],
            from_addr=os.environ["SMTP_FROM"],
            use_tls=use_tls,
        )

    raise ValueError(f"EMAIL_MODE must be 'mock' or 'real', got {mode!r}")

"""SSOT for the test/dev Postgres password (C37).

Production code reads ``os.environ['POSTGRES_PASSWORD']`` with NO fallback (so an
unconfigured deploy fails fast instead of silently using a known password). Tests
and local dev legitimately use a fixed throwaway password — the literal lives here
ONLY, and conftests / the checkpointer L2 test import it instead of repeating it.
"""

from __future__ import annotations

PG_PASSWORD_DEFAULT = "postgres123"

"""C35: legacy text2sql path blocks PG file-read / privilege functions and all UNION.

These functions are SELECT-able, so a leading-SELECT allowlist is insufficient —
``SELECT pg_read_file('/etc/passwd')`` would otherwise pass. Guards the blocklist
hardening (the router is currently unmounted; this is defense-in-depth for re-enable).
"""

from __future__ import annotations


def test_text2sql_forbidden_keywords_cover_pg_file_and_union() -> None:
    from app.service.text2sql_service import Text2SQLService

    blocked = {kw.upper() for kw in Text2SQLService.FORBIDDEN_KEYWORDS}
    for kw in ("UNION", "COPY", "PG_READ_FILE", "PG_LS_DIR", "PG_SHADOW", "PG_AUTHID", "DBLINK"):
        assert kw in blocked, f"{kw!r} must be in FORBIDDEN_KEYWORDS (C35)"

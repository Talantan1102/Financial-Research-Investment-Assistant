"""EmailNotifier Protocol + RealEmailNotifier (SMTP).

Sanitizer note (Task 11 carryover from Task 9 review):
  RealEmailNotifier.send() calls _sanitize_body() before handing the body
  to smtplib.  The sanitizer strips:
    - The tushare proxy IP literal "47.109.59.144"
    - Any "http://47.109" prefix (broader URL match)
    - Truncates any remaining body beyond MAX_BODY_CHARS as a safety cap
  These are defence-in-depth: SignalDetector._safe() is the primary source
  of potentially exception-embedded sensitive URLs, but the email is the
  external boundary.
"""

from __future__ import annotations

import asyncio
import re
import smtplib
from email.message import EmailMessage
from typing import Protocol, runtime_checkable

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Sanitizer
# ---------------------------------------------------------------------------

_PROXY_IP_PATTERN = re.compile(r"47\.109\.59\.144")
_HTTP_PROXY_PATTERN = re.compile(r"http://47\.109[^\s]*")
MAX_BODY_CHARS = 50_000  # overall body cap


def _sanitize_body(s: str) -> str:
    """Strip sensitive substrings from email body before sending externally."""
    s = _HTTP_PROXY_PATTERN.sub("[REDACTED_URL]", s)
    s = _PROXY_IP_PATTERN.sub("[REDACTED_IP]", s)
    # Truncate extreme bodies (pathological exception messages)
    if len(s) > MAX_BODY_CHARS:
        s = s[:MAX_BODY_CHARS] + "\n...[truncated]"
    return s


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


class EmailSendResult(BaseModel):
    success: bool
    error: str | None = None


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class EmailNotifier(Protocol):
    async def send(
        self,
        to_addrs: list[str],
        subject: str,
        body_text: str,
        body_html: str | None = None,
    ) -> EmailSendResult: ...


# ---------------------------------------------------------------------------
# Real implementation
# ---------------------------------------------------------------------------


class RealEmailNotifier:
    """SMTP-backed notifier.  Runs smtplib in a thread via asyncio.to_thread."""

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        from_addr: str,
        use_tls: bool = True,
    ) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._from = from_addr
        self._use_tls = use_tls

    async def send(
        self,
        to_addrs: list[str],
        subject: str,
        body_text: str,
        body_html: str | None = None,
    ) -> EmailSendResult:
        # Sanitize before any external boundary
        clean_text = _sanitize_body(body_text)
        clean_html = _sanitize_body(body_html) if body_html else None

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self._from
        msg["To"] = ", ".join(to_addrs)
        msg.set_content(clean_text)
        if clean_html:
            msg.add_alternative(clean_html, subtype="html")

        def _send() -> None:
            if self._use_tls:
                with smtplib.SMTP_SSL(self._host, self._port) as smtp:
                    smtp.login(self._user, self._password)
                    smtp.send_message(msg)
            else:
                with smtplib.SMTP(self._host, self._port) as smtp:
                    # starttls() upgrades plain SMTP to TLS — required to avoid
                    # plaintext credentials.  Use smtplib.SMTP_SSL for implicit
                    # TLS (port 465).
                    smtp.starttls()
                    smtp.login(self._user, self._password)
                    smtp.send_message(msg)

        try:
            await asyncio.to_thread(_send)
            return EmailSendResult(success=True)
        except Exception as exc:
            # Do NOT include password in error; exc should not contain it
            return EmailSendResult(success=False, error=str(exc))

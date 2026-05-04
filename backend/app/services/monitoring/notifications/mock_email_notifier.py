"""MockEmailNotifier — records sent emails for test inspection.

Two modes:
  - db_path provided → persist to sqlite (useful for integration tests / dev dogfood)
  - db_path=None     → in-memory list only (lightweight unit tests)

Both modes expose `.sent_emails` list[dict] for test assertions and
`.list_recorded()` as the public API (mirrors sqlite mode).
"""

from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path

from app.services.monitoring.notifications.email_notifier import EmailSendResult

_logger = logging.getLogger(__name__)


class MockEmailNotifier:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path
        # In-memory copy always maintained (regardless of db_path)
        self.sent_emails: list[dict[str, str | None]] = []
        if db_path is not None:
            self._init_db()

    # ------------------------------------------------------------------
    # private helpers
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        assert self._db_path is not None
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS emails_mock (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    sent_at   REAL    NOT NULL,
                    to_addrs  TEXT    NOT NULL,
                    subject   TEXT    NOT NULL,
                    body_text TEXT    NOT NULL,
                    body_html TEXT
                )
                """
            )

    def _persist(
        self,
        to_addrs: list[str],
        subject: str,
        body_text: str,
        body_html: str | None,
    ) -> None:
        assert self._db_path is not None
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO emails_mock (sent_at, to_addrs, subject, body_text, body_html) "
                "VALUES (?, ?, ?, ?, ?)",
                (time.time(), ",".join(to_addrs), subject, body_text, body_html),
            )

    # ------------------------------------------------------------------
    # EmailNotifier Protocol
    # ------------------------------------------------------------------

    async def send(
        self,
        to_addrs: list[str],
        subject: str,
        body_text: str,
        body_html: str | None = None,
    ) -> EmailSendResult:
        record: dict[str, str | None] = {
            "to_addrs": ",".join(to_addrs),
            "subject": subject,
            "body_text": body_text,
            "body_html": body_html,
        }
        self.sent_emails.append(record)
        if self._db_path is not None:
            self._persist(to_addrs, subject, body_text, body_html)
        _logger.info("[mock email] to=%s subject=%r", to_addrs, subject)
        return EmailSendResult(success=True)

    # ------------------------------------------------------------------
    # Test inspection helpers
    # ------------------------------------------------------------------

    def list_recorded(self) -> list[dict[str, str | None]]:
        """Return all recorded emails.

        If db_path was provided, reads from sqlite (source of truth for
        multi-process scenarios).  Otherwise returns the in-memory list.
        """
        if self._db_path is not None:
            with sqlite3.connect(self._db_path) as conn:
                cur = conn.execute(
                    "SELECT to_addrs, subject, body_text, body_html FROM emails_mock ORDER BY id"
                )
                return [
                    {
                        "to_addrs": row[0],
                        "subject": row[1],
                        "body_text": row[2],
                        "body_html": row[3],
                    }
                    for row in cur.fetchall()
                ]
        return list(self.sent_emails)

    def clear(self) -> None:
        """Reset recorded state (useful between test cases)."""
        self.sent_emails.clear()
        if self._db_path is not None:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("DELETE FROM emails_mock")

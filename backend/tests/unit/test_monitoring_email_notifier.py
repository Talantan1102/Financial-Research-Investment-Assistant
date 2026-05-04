"""Unit tests for EmailNotifier (real + mock + factory).

Tests follow plan § Task 11 step 11.1 listings, plus the carryover
sanitizer test mandated by the Task 9 review.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from app.services.monitoring.notifications.email_notifier import (
    EmailNotifier,
    RealEmailNotifier,
    _sanitize_body,
)
from app.services.monitoring.notifications.factory import build_email_notifier
from app.services.monitoring.notifications.mock_email_notifier import (
    MockEmailNotifier,
)

# ---------------------------------------------------------------------------
# MockEmailNotifier — sqlite mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mock_records_to_sqlite(tmp_path: Path) -> None:
    notifier = MockEmailNotifier(db_path=tmp_path / "emails.sqlite")
    result = await notifier.send(
        to_addrs=["a@b.com"],
        subject="测试",
        body_text="hi",
    )
    assert result.success is True
    rows = notifier.list_recorded()
    assert len(rows) == 1
    assert rows[0]["subject"] == "测试"


@pytest.mark.asyncio
async def test_mock_in_memory_no_db_path() -> None:
    """When db_path=None, emails accumulate in sent_emails list only."""
    notifier = MockEmailNotifier()
    await notifier.send(to_addrs=["x@y.com"], subject="s1", body_text="b1")
    await notifier.send(to_addrs=["x@y.com"], subject="s2", body_text="b2")
    rows = notifier.list_recorded()
    assert len(rows) == 2
    assert rows[0]["subject"] == "s1"
    assert rows[1]["subject"] == "s2"


@pytest.mark.asyncio
async def test_mock_clear_resets_state() -> None:
    notifier = MockEmailNotifier()
    await notifier.send(to_addrs=["x@y.com"], subject="s", body_text="b")
    notifier.clear()
    assert notifier.list_recorded() == []


@pytest.mark.asyncio
async def test_mock_records_html(tmp_path: Path) -> None:
    notifier = MockEmailNotifier(db_path=tmp_path / "emails.sqlite")
    await notifier.send(
        to_addrs=["a@b.com"],
        subject="html_test",
        body_text="plain",
        body_html="<b>bold</b>",
    )
    rows = notifier.list_recorded()
    assert rows[0]["body_html"] == "<b>bold</b>"


# ---------------------------------------------------------------------------
# RealEmailNotifier — SMTP_SSL path (mocked)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_real_notifier_uses_smtp() -> None:
    fake_smtp = MagicMock()
    fake_smtp.__enter__ = MagicMock(return_value=fake_smtp)
    fake_smtp.__exit__ = MagicMock(return_value=False)
    fake_smtp.send_message = MagicMock()

    with patch("smtplib.SMTP_SSL", return_value=fake_smtp):
        n = RealEmailNotifier(
            host="smtp.test.com",
            port=465,
            user="u@t.com",
            password="x",
            from_addr="u@t.com",
        )
        result = await n.send(to_addrs=["a@b.com"], subject="s", body_text="hi")

    assert result.success
    fake_smtp.login.assert_called_once_with("u@t.com", "x")
    fake_smtp.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_real_notifier_no_tls_uses_smtp() -> None:
    """use_tls=False should branch to smtplib.SMTP instead of SMTP_SSL."""
    fake_smtp = MagicMock()
    fake_smtp.__enter__ = MagicMock(return_value=fake_smtp)
    fake_smtp.__exit__ = MagicMock(return_value=False)
    fake_smtp.send_message = MagicMock()

    with patch("smtplib.SMTP", return_value=fake_smtp):
        n = RealEmailNotifier(
            host="smtp.test.com",
            port=25,
            user="u@t.com",
            password="x",
            from_addr="u@t.com",
            use_tls=False,
        )
        result = await n.send(to_addrs=["a@b.com"], subject="s", body_text="hi")

    assert result.success
    fake_smtp.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_real_notifier_smtp_error_returns_failure() -> None:
    """SMTP connection error should not propagate; returns EmailSendResult(success=False)."""
    with patch("smtplib.SMTP_SSL", side_effect=ConnectionRefusedError("refused")):
        n = RealEmailNotifier(
            host="smtp.nowhere.invalid",
            port=465,
            user="u",
            password="p",
            from_addr="u@t.com",
        )
        result = await n.send(to_addrs=["a@b.com"], subject="s", body_text="body")

    assert result.success is False
    assert result.error is not None


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def test_factory_default_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EMAIL_MODE", raising=False)
    n = build_email_notifier()
    assert isinstance(n, MockEmailNotifier)


def test_factory_real_requires_smtp_envs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMAIL_MODE", "real")
    monkeypatch.delenv("SMTP_HOST", raising=False)
    with pytest.raises(KeyError):
        build_email_notifier()


def test_factory_real_with_envs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMAIL_MODE", "real")
    monkeypatch.setenv("SMTP_HOST", "smtp.test.com")
    monkeypatch.setenv("SMTP_PORT", "465")
    monkeypatch.setenv("SMTP_USER", "u@t.com")
    monkeypatch.setenv("SMTP_PASSWORD", "x")
    monkeypatch.setenv("SMTP_FROM", "u@t.com")
    n = build_email_notifier()
    assert isinstance(n, RealEmailNotifier)


def test_factory_invalid_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMAIL_MODE", "ftp")
    with pytest.raises(ValueError, match="EMAIL_MODE must be"):
        build_email_notifier()


def test_factory_mock_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMAIL_MODE", "mock")
    n = build_email_notifier()
    assert isinstance(n, MockEmailNotifier)


# ---------------------------------------------------------------------------
# Protocol runtime check
# ---------------------------------------------------------------------------


def test_protocol_runtime_check() -> None:
    assert hasattr(MockEmailNotifier, "send")
    assert hasattr(RealEmailNotifier, "send")
    assert EmailNotifier is not None


def test_mock_satisfies_protocol() -> None:
    """isinstance check against @runtime_checkable Protocol."""
    notifier = MockEmailNotifier()
    assert isinstance(notifier, EmailNotifier)


def test_real_satisfies_protocol() -> None:
    n = RealEmailNotifier(host="h", port=465, user="u", password="p", from_addr="f@f.com")
    assert isinstance(n, EmailNotifier)


# ---------------------------------------------------------------------------
# Sanitizer (carryover Task 9 review)
# ---------------------------------------------------------------------------


def test_sanitizer_redacts_proxy_ip() -> None:
    """_sanitize_body strips the tushare proxy IP from body text."""
    body = "error: 47.109.59.144 timeout connecting to tushare"
    result = _sanitize_body(body)
    assert "47.109.59.144" not in result
    assert "[REDACTED_IP]" in result


def test_sanitizer_redacts_http_proxy_url() -> None:
    """http://47.109.* URLs are stripped before the IP pattern."""
    body = "connection failed: http://47.109.59.144:8080/api/v2 401"
    result = _sanitize_body(body)
    assert "http://47.109" not in result
    assert "[REDACTED_URL]" in result
    # Plain IP portion may still be caught by IP pattern or already gone
    assert "47.109.59.144" not in result


def test_sanitizer_other_ips_preserved() -> None:
    """Non-tushare IPs must NOT be redacted."""
    body = "server at 192.168.1.1 responded OK"
    result = _sanitize_body(body)
    assert "192.168.1.1" in result


def test_sanitizer_truncates_long_body() -> None:
    """Bodies beyond MAX_BODY_CHARS are truncated."""
    from app.services.monitoring.notifications.email_notifier import MAX_BODY_CHARS

    long_body = "x" * (MAX_BODY_CHARS + 1000)
    result = _sanitize_body(long_body)
    assert len(result) < MAX_BODY_CHARS + 100
    assert "[truncated]" in result


def test_sanitizer_no_op_on_clean_body() -> None:
    """A normal body with no sensitive content is returned unchanged."""
    body = "季报已发布，ROE=12.5%，净利润同比增长 8%。"
    result = _sanitize_body(body)
    assert result == body


@pytest.mark.asyncio
async def test_real_notifier_sanitizes_before_smtp() -> None:
    """RealEmailNotifier must call sanitizer so proxy IP never reaches SMTP."""
    fake_smtp = MagicMock()
    fake_smtp.__enter__ = MagicMock(return_value=fake_smtp)
    fake_smtp.__exit__ = MagicMock(return_value=False)
    fake_smtp.send_message = MagicMock()

    sensitive_body = "error: 47.109.59.144 connection refused"

    with patch("smtplib.SMTP_SSL", return_value=fake_smtp):
        n = RealEmailNotifier(
            host="smtp.test.com",
            port=465,
            user="u@t.com",
            password="secret",
            from_addr="u@t.com",
        )
        await n.send(to_addrs=["a@b.com"], subject="alert", body_text=sensitive_body)

    # Inspect the EmailMessage passed to send_message
    sent_msg = fake_smtp.send_message.call_args[0][0]
    body_in_msg = sent_msg.get_body()
    assert body_in_msg is not None
    payload = body_in_msg.get_payload(decode=False)
    # The raw payload may be a string or bytes after encode; check as string
    payload_str = payload if isinstance(payload, str) else payload.decode()
    assert "47.109.59.144" not in payload_str

"""L0 — QuotaCounter SQLite-backed monthly counter."""

from datetime import UTC, datetime
from pathlib import Path

from app.services.quota_counter import QuotaCounter


def test_initial_count_zero(tmp_path: Path) -> None:
    counter = QuotaCounter(db_path=tmp_path / "quota.sqlite", name="test", monthly_limit=100)
    assert counter.used_this_month() == 0
    assert counter.remaining() == 100
    assert not counter.would_exceed()


def test_increment_persists(tmp_path: Path) -> None:
    db = tmp_path / "quota.sqlite"
    counter1 = QuotaCounter(db_path=db, name="test", monthly_limit=100)
    counter1.increment()
    counter1.increment()
    counter1.increment()

    # New instance, same file → state preserved
    counter2 = QuotaCounter(db_path=db, name="test", monthly_limit=100)
    assert counter2.used_this_month() == 3
    assert counter2.remaining() == 97


def test_separate_names_isolated(tmp_path: Path) -> None:
    db = tmp_path / "quota.sqlite"
    web = QuotaCounter(db_path=db, name="web_search", monthly_limit=100)
    news = QuotaCounter(db_path=db, name="get_news", monthly_limit=50)
    web.increment()
    web.increment()
    news.increment()

    assert web.used_this_month() == 2
    assert news.used_this_month() == 1


def test_would_exceed_at_limit(tmp_path: Path) -> None:
    counter = QuotaCounter(db_path=tmp_path / "quota.sqlite", name="t", monthly_limit=2)
    assert not counter.would_exceed()
    counter.increment()
    assert not counter.would_exceed()
    counter.increment()
    assert counter.would_exceed()  # at limit
    counter.increment()  # over
    assert counter.would_exceed()


def test_only_counts_current_month(tmp_path: Path) -> None:
    """Inserts a row from previous month directly; current_month query should not include it."""
    import sqlite3

    db = tmp_path / "quota.sqlite"
    counter = QuotaCounter(db_path=db, name="t", monthly_limit=100)
    counter.increment()  # initialize schema

    # Manually insert a stale row from 60 days ago
    stale_ts = int(datetime.now(UTC).timestamp() - 60 * 24 * 3600)
    with sqlite3.connect(str(db)) as conn:
        conn.execute(
            "INSERT INTO search_quota_log (name, ts) VALUES (?, ?)",
            ("t", stale_ts),
        )
        conn.commit()

    # current month count should still be 1 (the increment, not the stale row)
    assert counter.used_this_month() == 1

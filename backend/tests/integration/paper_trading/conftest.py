"""Paper-trading integration-test isolation guards."""

from __future__ import annotations

import threading
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine


@pytest.fixture(autouse=True)
def no_paper_trading_thread_or_connection_leaks(pg_test_engine: Engine) -> Iterator[None]:
    """Fail at the originating test instead of deadlocking the next TRUNCATE."""
    existing_threads = {thread.ident for thread in threading.enumerate()}

    yield

    leaked_threads = [
        thread
        for thread in threading.enumerate()
        if thread.ident not in existing_threads and thread.is_alive() and not thread.daemon
    ]
    for thread in leaked_threads:
        thread.join(timeout=1)
    still_alive = [thread.name for thread in leaked_threads if thread.is_alive()]
    assert still_alive == [], f"test leaked live threads: {still_alive}"

    checked_out = getattr(pg_test_engine.pool, "checkedout", lambda: 0)()
    assert checked_out == 0, f"test leaked {checked_out} PostgreSQL connection(s)"

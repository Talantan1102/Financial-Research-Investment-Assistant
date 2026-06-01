"""Unit tests for RedisCache — C36: logger.warning on Redis errors, not print."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import redis
from app.core.redis_client import RedisCache


@pytest.fixture
def fake_redis() -> MagicMock:
    """Return a MagicMock that raises ConnectionError on every Redis operation."""
    client = MagicMock(spec=redis.Redis)
    client.get.side_effect = redis.ConnectionError("connection refused")
    client.setex.side_effect = redis.ConnectionError("connection refused")
    client.delete.side_effect = redis.ConnectionError("connection refused")
    client.exists.side_effect = redis.ConnectionError("connection refused")
    client.lpush.side_effect = redis.ConnectionError("connection refused")
    client.ltrim.side_effect = redis.ConnectionError("connection refused")
    client.lrange.side_effect = redis.ConnectionError("connection refused")
    return client


@pytest.fixture
def cache_with_failing_redis(fake_redis: MagicMock) -> RedisCache:
    """RedisCache whose underlying client always raises ConnectionError."""
    rc = RedisCache.__new__(RedisCache)
    rc.client = fake_redis
    return rc


# ---------------------------------------------------------------------------
# C36: each method must return its sentinel AND emit a WARNING (with exc_info)
# ---------------------------------------------------------------------------


def test_get_returns_none_and_logs_on_error(
    cache_with_failing_redis: RedisCache, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("WARNING", logger="app.core.redis_client"):
        result = cache_with_failing_redis.get("some-key")
    assert result is None
    assert any("Redis get error" in r.message for r in caplog.records)
    # exc_info=True means the traceback is attached; levelname must be WARNING
    assert all(r.levelname == "WARNING" for r in caplog.records if "Redis get error" in r.message)
    assert any(r.exc_info is not None for r in caplog.records if "Redis get error" in r.message)


def test_set_returns_false_and_logs_on_error(
    cache_with_failing_redis: RedisCache, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("WARNING", logger="app.core.redis_client"):
        result = cache_with_failing_redis.set("k", {"x": 1})
    assert result is False
    assert any("Redis set error" in r.message for r in caplog.records)
    assert any(r.exc_info is not None for r in caplog.records if "Redis set error" in r.message)


def test_delete_returns_false_and_logs_on_error(
    cache_with_failing_redis: RedisCache, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("WARNING", logger="app.core.redis_client"):
        result = cache_with_failing_redis.delete("k")
    assert result is False
    assert any("Redis delete error" in r.message for r in caplog.records)
    assert any(r.exc_info is not None for r in caplog.records if "Redis delete error" in r.message)


def test_exists_returns_false_and_logs_on_error(
    cache_with_failing_redis: RedisCache, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("WARNING", logger="app.core.redis_client"):
        result = cache_with_failing_redis.exists("k")
    assert result is False
    assert any("Redis exists error" in r.message for r in caplog.records)
    assert any(r.exc_info is not None for r in caplog.records if "Redis exists error" in r.message)


def test_add_to_list_returns_false_and_logs_on_error(
    cache_with_failing_redis: RedisCache, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("WARNING", logger="app.core.redis_client"):
        result = cache_with_failing_redis.add_to_list("k", {"v": 1})
    assert result is False
    assert any("Redis add_to_list error" in r.message for r in caplog.records)
    assert any(
        r.exc_info is not None for r in caplog.records if "Redis add_to_list error" in r.message
    )


def test_get_list_returns_empty_and_logs_on_error(
    cache_with_failing_redis: RedisCache, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("WARNING", logger="app.core.redis_client"):
        result = cache_with_failing_redis.get_list("k")
    assert result == []
    assert any("Redis get_list error" in r.message for r in caplog.records)
    assert any(
        r.exc_info is not None for r in caplog.records if "Redis get_list error" in r.message
    )


# ---------------------------------------------------------------------------
# Regression: no print() output anywhere (would show up as stdout capture)
# ---------------------------------------------------------------------------


def test_no_print_on_error(
    cache_with_failing_redis: RedisCache, capsys: pytest.CaptureFixture
) -> None:
    """C36 regression: Redis errors must NOT reach stdout via print()."""
    cache_with_failing_redis.get("k")
    cache_with_failing_redis.set("k", 1)
    cache_with_failing_redis.delete("k")
    cache_with_failing_redis.exists("k")
    cache_with_failing_redis.add_to_list("k", 1)
    cache_with_failing_redis.get_list("k")
    captured = capsys.readouterr()
    assert "Redis" not in captured.out, "Redis errors must not be written to stdout"

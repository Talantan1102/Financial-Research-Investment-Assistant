"""POST /monitoring/refresh — 手动触发 detection cycle for current user."""

from __future__ import annotations

from unittest.mock import patch


def test_post_refresh_enqueues_detection_cycle(client, fake_auth):
    enqueued = []

    class _FakeResult:
        id = "task-id"

    def _fake_delay(user_filter=None, **kwargs):
        enqueued.append(user_filter)
        return _FakeResult()

    with patch("app.tasks.monitoring.detection_cycle.delay", side_effect=_fake_delay):
        r = client.post("/api/monitoring/refresh", headers=fake_auth["headers"])

    assert r.status_code == 202, r.text
    body = r.json()
    assert "task_id" in body
    assert enqueued == [fake_auth["user_id"]]


def test_post_refresh_unauthorized_401(client):
    r = client.post("/api/monitoring/refresh")
    assert r.status_code in (401, 403)

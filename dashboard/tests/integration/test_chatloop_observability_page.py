"""看板可观测性页 —— stub 后端聚合/逐日;渲染、降级、日历。"""

from __future__ import annotations

from starlette.testclient import TestClient

import dashboard.derive.observability as obs
from dashboard.server import app

_FAKE = {
    "window": "7d",
    "tool_latency": [
        {
            "tool_name": "get_quote",
            "calls": 12,
            "p50_ms": 300,
            "p95_ms": 8000,
            "max_ms": 9000,
            "success_rate": 0.9,
            "cache_hit_rate": 0.3,
        },
    ],
    "model_ms": 3000,
    "tool_ms": 8200,
    "model_share": 0.27,
    "cache_hit_rate": 0.8,
    "avg_cost_cny": 0.05,
    "avg_wall_ms": 12000,
    "avg_llm_calls": 3,
    "avg_tool_calls": 2,
    "turn_count": 5,
}

_DAILY = {
    "days": [
        {
            "date": "2026-06-10",
            "cost_cny": 0.04,
            "turns": 5,
            "model_calls": 12,
            "tool_calls": 8,
            "p95_ms": 4200,
            "cache_hit_rate": 0.7,
        },
    ]
}


def _stub_both(monkeypatch, agg=_FAKE, daily=_DAILY) -> None:
    monkeypatch.setattr(obs, "load_aggregates", lambda *a, **k: agg)
    monkeypatch.setattr(obs, "load_daily", lambda *a, **k: daily)


def test_page_renders_aggregates(monkeypatch) -> None:
    _stub_both(monkeypatch)
    resp = TestClient(app).get("/eval/chatloop-observability")
    assert resp.status_code == 200
    assert "get_quote" in resp.text
    assert "命中率" in resp.text


def test_page_degrades_when_backend_down(monkeypatch) -> None:
    def _boom(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(obs, "load_aggregates", _boom)
    monkeypatch.setattr(obs, "load_daily", _boom)
    resp = TestClient(app).get("/eval/chatloop-observability")
    assert resp.status_code == 200
    assert "未连接" in resp.text or "暂无数据" in resp.text


def test_page_no_500_when_all_p95_zero(monkeypatch) -> None:
    # 工具调用全是缓存/去重命中(p95_ms=0)时不得 div-by-zero 500。
    fake = {
        **_FAKE,
        "tool_latency": [{**_FAKE["tool_latency"][0], "p50_ms": 0, "p95_ms": 0, "max_ms": 0}],
    }
    _stub_both(monkeypatch, agg=fake)
    resp = TestClient(app).get("/eval/chatloop-observability")
    assert resp.status_code == 200
    assert "get_quote" in resp.text


def test_calendar_renders(monkeypatch) -> None:
    _stub_both(monkeypatch)
    resp = TestClient(app).get("/eval/chatloop-observability?metric=cost")
    assert resp.status_code == 200
    assert "obs-cal" in resp.text  # 日历容器
    assert "?from=" in resp.text  # 某格的选择链接
    assert "metric=cost" in resp.text


def test_today_shortcut_points_to_today(monkeypatch) -> None:
    from datetime import UTC, datetime

    _stub_both(monkeypatch)
    resp = TestClient(app).get("/eval/chatloop-observability")
    today = datetime.now(UTC).date().isoformat()
    # 「今天」快捷链接应指向当天,而不是当前选区的止日
    assert f"?from={today}&to={today}&metric=" in resp.text


def test_calendar_degrades_when_daily_down(monkeypatch) -> None:
    monkeypatch.setattr(obs, "load_aggregates", lambda *a, **k: _FAKE)

    def _boom(*a, **k):
        raise OSError("down")

    monkeypatch.setattr(obs, "load_daily", _boom)
    resp = TestClient(app).get("/eval/chatloop-observability")
    assert resp.status_code == 200  # 日历挂了也不崩

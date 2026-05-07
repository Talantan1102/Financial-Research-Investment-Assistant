from starlette.testclient import TestClient

from dashboard.server import app


def test_get_decisions_renders_cards() -> None:
    """/decisions 渲染决策卡 + active_view='decisions' tab。"""
    with TestClient(app) as client:
        r = client.get("/decisions")
        assert r.status_code == 200
        body = r.text
        assert 'class="decision-card"' in body
        # active class 在第三 tab(决策)上
        assert 'class="active">决策</a>' in body or 'active">决策' in body

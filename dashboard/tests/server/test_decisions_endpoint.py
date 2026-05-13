from starlette.testclient import TestClient

from dashboard.server import app


def test_get_decisions_renders_cards() -> None:
    """/decisions 渲染决策卡 + active_view='decisions' tab。"""
    with TestClient(app) as client:
        r = client.get("/decisions")
        assert r.status_code == 200
        body = r.text
        assert 'class="decision-card"' in body
        # active class 在 nav-rail decisions 项上(nav-item active)
        assert "nav-item active" in body or 'active" title="决策"' in body


def test_post_decision_note() -> None:
    """POST note → 写 decision_note 表 + 返回新 form HTML(details drawer)。"""
    with TestClient(app) as client:
        r = client.post(
            "/decisions/abc123def456/note",
            data={"note": "测试 note"},
        )
        assert r.status_code == 200
        body = r.text
        assert '<form class="decision-note"' in body
        # textarea contains the saved note
        assert "测试 note" in body


def test_delete_decision_note() -> None:
    """DELETE note → 清表 + 返回空 form HTML(details drawer)。"""
    with TestClient(app) as client:
        # seed
        client.post("/decisions/abc123def456/note", data={"note": "to be deleted"})
        # delete
        r = client.delete("/decisions/abc123def456/note")
        assert r.status_code == 200
        body = r.text
        assert '<form class="decision-note"' in body
        # empty note → summary shows "加 note"
        assert "加 note" in body

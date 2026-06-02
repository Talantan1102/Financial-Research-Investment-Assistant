"""/eval endpoint integration tests — Starlette TestClient。

eval_view 纯渲染 yaml,不碰 DB;仍隔离 DB_PATH 防 lifespan seed 污染 prod。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    from dashboard import server

    monkeypatch.setattr(server, "DB_PATH", tmp_path / "board.db")
    return TestClient(server.app)


def test_eval_page_renders_matrix(client: TestClient) -> None:
    resp = client.get("/eval")
    assert resp.status_code == 200
    body = resp.text
    # 标题 + tagline + 论文锚点
    assert "评估体系" in body
    assert "没有评估就没有优化" in body
    assert "§8" in body or "§ 08" in body
    # 覆盖率(36% for current yaml)出现
    assert "覆盖率" in body
    assert "36%" in body
    # 三态计数文案
    assert "有" in body and "部分" in body and "缺口" in body


def test_eval_page_lists_all_subsystems_and_layers(client: TestClient) -> None:
    body = client.get("/eval").text
    for name in [
        "知识库检索",
        "对话 Agent",
        "深度研报",
        "跨会话记忆",
        "持仓监控",
        "估值交叉验证",
        "多空辩论",
    ]:
        assert name in body, f"缺子系统行: {name}"
    for layer in ["组件级", "智能体级", "系统级", "回归监控"]:
        assert layer in body, f"缺层级列: {layer}"
    # 矩阵每格可点击 — htmx hx-get 指向 cell endpoint
    assert 'hx-get="/eval/cell/kb/component"' in body
    assert 'hx-target="#eval-detail"' in body
    # 底座小卡
    assert "评估底座" in body
    assert "EvalRunner" in body
    assert 'href="/m/verification"' in body


def test_eval_nav_active(client: TestClient) -> None:
    body = client.get("/eval").text
    # nav-rail 含 /eval 入口且 active
    assert 'href="/eval"' in body
    assert "nav-item active" in body


def test_eval_cell_expand_covered(client: TestClient) -> None:
    # memory.component 是 covered 格,有 methods + evidence
    resp = client.get("/eval/cell/memory/component")
    assert resp.status_code == 200
    body = resp.text
    assert "跨会话记忆" in body
    assert "组件级" in body
    assert "评估方法" in body
    assert "证据" in body
    # 一个真实 evidence 路径
    assert "backend/tests/unit/memory/test_extractor.py" in body


def test_eval_cell_expand_gap(client: TestClient) -> None:
    # valuation.system 是 gap 格 — 无 evidence,gap 文案非空
    resp = client.get("/eval/cell/valuation/system")
    assert resp.status_code == 200
    body = resp.text
    assert "估值交叉验证" in body
    assert "系统级" in body
    # gap 缺口说明出现
    assert "pytest.mark.skip" in body


def test_eval_cell_unknown_subsystem_404(client: TestClient) -> None:
    resp = client.get("/eval/cell/nope/component")
    assert resp.status_code == 404


def test_eval_cell_unknown_layer_404(client: TestClient) -> None:
    resp = client.get("/eval/cell/kb/nope")
    assert resp.status_code == 404

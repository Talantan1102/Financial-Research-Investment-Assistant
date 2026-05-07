"""Server tests autouse fixture — 隔离 dashboard.server.DB_PATH 到 tmp_path,
不污染 prod backend/data/board.db。"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_dashboard_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """每个 server test 用独立 sqlite。"""
    monkeypatch.setattr("dashboard.server.DB_PATH", tmp_path / "board.db")

"""lifespan seed ingest 集成测试 — spec § 2.5。"""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from dashboard.derive.deep_card_types import DeepCard
from dashboard.state.db import open_db
from dashboard.state.repositories import DeepCardRepo


@pytest.fixture(autouse=True)
def _disable_milvus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HARNESS_BOARD_MILVUS_HOST", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)


def test_lifespan_ingests_when_db_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """startup 时 db 空(0 < 35)→ insert-if-missing 跑;TestClient 上下文管理触发 lifespan。"""
    db = tmp_path / "board.db"
    monkeypatch.setattr("dashboard.server.DB_PATH", db)

    from dashboard.server import app

    with TestClient(app):  # ← `with` 触发 lifespan startup
        pass

    conn = open_db(db)
    try:
        cards = DeepCardRepo(conn).get_all()
    finally:
        conn.close()
    assert len(cards) >= 30  # seed jsonl 35 张,allow 一些 cap_id 不在 yaml


def test_lifespan_skips_when_db_already_full(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """db 已 ≥ seed 总数(40)→ lifespan no-op,不动 db。"""
    db = tmp_path / "board.db"
    monkeypatch.setattr("dashboard.server.DB_PATH", db)

    # 预先塞 40 张 marker card(用 yaml 中真实 id 范围内的一部分)
    from dashboard.derive.capability_resolver import load_capabilities

    PROJECT_ROOT = Path(__file__).resolve().parents[3]
    caps = load_capabilities(PROJECT_ROOT / "dashboard" / "config" / "capabilities.yaml")
    cap_ids = [c.id for c in caps][:40]  # 取前 40 个真实 id

    conn = open_db(db)
    try:
        repo = DeepCardRepo(conn)
        for cid in cap_ids:
            repo.upsert(DeepCard(cap_id=cid, what="MARKER"))
    finally:
        conn.close()

    from dashboard.server import app

    with TestClient(app):
        pass

    conn = open_db(db)
    try:
        survived = {c.cap_id: c.what for c in DeepCardRepo(conn).get_all()}
    finally:
        conn.close()
    # 所有 marker 仍是 MARKER(未被 seed 覆盖)
    for cid in cap_ids:
        assert survived.get(cid) == "MARKER", f"{cid} 被 lifespan 覆盖了"


def test_lifespan_does_not_overwrite_manual_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """underfilled 时跑 ingest,但已存在 cap_id 一律跳过(保护手动编辑)。"""
    db = tmp_path / "board.db"
    monkeypatch.setattr("dashboard.server.DB_PATH", db)

    # 塞 1 张已编辑 row(db count = 1 < 35,会触发 underfilled)
    conn = open_db(db)
    try:
        DeepCardRepo(conn).upsert(
            DeepCard(cap_id="memory.long_term_memory", what="USER_EDITED_VALUE")
        )
    finally:
        conn.close()

    from dashboard.server import app

    with TestClient(app):
        pass

    conn = open_db(db)
    try:
        survived = DeepCardRepo(conn).get("memory.long_term_memory")
    finally:
        conn.close()
    assert survived is not None
    assert survived.what == "USER_EDITED_VALUE"

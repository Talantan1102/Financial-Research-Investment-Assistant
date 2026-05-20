"""SeedIngestService L0 — insert-if-missing 语义 + 4 路径(underfilled / 已满 / 已编辑保护 / force upsert)。"""

from __future__ import annotations

import json
from pathlib import Path

from dashboard.derive.deep_card_types import DeepCard
from dashboard.derive.seed_ingest import SeedIngestResult, SeedIngestService
from dashboard.state.db import open_db
from dashboard.state.repositories import DeepCardRepo

PROJECT_ROOT = Path(__file__).resolve().parents[3]
REAL_CONFIG_DIR = PROJECT_ROOT / "dashboard" / "config"


def _write_seed_jsonl(p: Path, cap_ids: list[str]) -> None:
    """写一个 minimal 合法 seed jsonl(cap_id + what 足够过 Pydantic)。"""
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"cap_id": cid, "what": f"what for {cid}"}) for cid in cap_ids]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_run_once_if_underfilled_triggers_when_db_empty(tmp_path: Path) -> None:
    """db 中 DeepCard 数 < seed 总数(0 < 2)→ 跑 insert-if-missing。"""
    seed = tmp_path / "seed.jsonl"
    # 用 capabilities.yaml 中真实 cap_id(context.long_term_memory 一定存在)
    _write_seed_jsonl(seed, ["context.long_term_memory", "lifecycle.session_checkpoint"])
    db = tmp_path / "board.db"

    svc = SeedIngestService(seed_path=seed, db_path=db, config_dir=REAL_CONFIG_DIR)
    result = svc.run_once_if_underfilled()

    assert isinstance(result, SeedIngestResult)
    assert result.total_seed == 2
    assert result.inserted == 2
    assert result.skipped_existing == 0
    # cap_id 在 yaml 中 → 没有 skipped_invalid


def test_run_once_if_underfilled_skips_when_db_full(tmp_path: Path) -> None:
    """db 已 ≥ seed 总数 → no-op,返回 0 inserted。"""
    seed = tmp_path / "seed.jsonl"
    _write_seed_jsonl(seed, ["context.long_term_memory"])
    db = tmp_path / "board.db"

    # 预先塞 2 张 card(无论 cap_id 是否在 yaml,只看数量是否 underfilled)
    conn = open_db(db)
    try:
        DeepCardRepo(conn).upsert(DeepCard(cap_id="context.long_term_memory", what="manual edit"))
        DeepCardRepo(conn).upsert(DeepCard(cap_id="lifecycle.session_checkpoint"))
    finally:
        conn.close()

    svc = SeedIngestService(seed_path=seed, db_path=db, config_dir=REAL_CONFIG_DIR)
    result = svc.run_once_if_underfilled()
    assert result.inserted == 0
    # underfilled 检查命中 → 不读 seed,total_seed 可能为 0(no-op semantics)
    # 实现选定:no-op 返回全 0
    assert result.total_seed == 0


def test_run_does_not_overwrite_existing_when_not_forced(tmp_path: Path) -> None:
    """db 已有 card(模拟用户手动编辑)→ run(force=False) 跳过,skipped_existing+1。"""
    seed = tmp_path / "seed.jsonl"
    _write_seed_jsonl(seed, ["lifecycle.session_checkpoint"])
    db = tmp_path / "board.db"

    # 预先插入同 cap_id 的 card,模拟用户手动编辑
    conn = open_db(db)
    try:
        DeepCardRepo(conn).upsert(
            DeepCard(cap_id="lifecycle.session_checkpoint", what="user-edited content")
        )
    finally:
        conn.close()

    svc = SeedIngestService(seed_path=seed, db_path=db, config_dir=REAL_CONFIG_DIR)
    result = svc.run(force=False)

    assert result.total_seed == 1
    assert result.inserted == 0
    assert result.skipped_existing == 1
    assert result.overwritten == 0

    # 验证 db 中内容未被覆盖
    conn = open_db(db)
    try:
        card = DeepCardRepo(conn).get("lifecycle.session_checkpoint")
    finally:
        conn.close()
    assert card is not None
    assert card.what == "user-edited content"


def test_run_force_overwrites_existing(tmp_path: Path) -> None:
    """force=True 时 upsert 覆盖现有 card,overwritten+1。"""
    seed = tmp_path / "seed.jsonl"
    _write_seed_jsonl(seed, ["lifecycle.session_checkpoint"])
    db = tmp_path / "board.db"

    # 预先插入旧内容
    conn = open_db(db)
    try:
        DeepCardRepo(conn).upsert(
            DeepCard(cap_id="lifecycle.session_checkpoint", what="old content")
        )
    finally:
        conn.close()

    svc = SeedIngestService(seed_path=seed, db_path=db, config_dir=REAL_CONFIG_DIR)
    result = svc.run(force=True)

    assert result.total_seed == 1
    assert result.inserted == 0
    assert result.overwritten == 1
    assert result.skipped_existing == 0

    # 验证 db 中 what 已被 seed 内容覆盖
    conn = open_db(db)
    try:
        card = DeepCardRepo(conn).get("lifecycle.session_checkpoint")
    finally:
        conn.close()
    assert card is not None
    assert card.what == "what for lifecycle.session_checkpoint"


def test_run_skips_cap_id_not_in_yaml(tmp_path: Path) -> None:
    """seed 中 cap_id 不存在于 capabilities.yaml → skipped_invalid+1,不入库。"""
    seed = tmp_path / "seed.jsonl"
    _write_seed_jsonl(seed, ["nonexistent.fake_capability"])
    db = tmp_path / "board.db"

    svc = SeedIngestService(seed_path=seed, db_path=db, config_dir=REAL_CONFIG_DIR)
    result = svc.run(force=False)

    assert result.total_seed == 1
    assert result.skipped_invalid == 1
    assert result.inserted == 0

    # 验证 db 中无该 cap_id
    conn = open_db(db)
    try:
        card = DeepCardRepo(conn).get("nonexistent.fake_capability")
    finally:
        conn.close()
    assert card is None

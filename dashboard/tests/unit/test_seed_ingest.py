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
    # 用 capabilities.yaml 中真实 cap_id(memory.long_term_memory 一定存在)
    _write_seed_jsonl(seed, ["memory.long_term_memory", "memory.session_checkpoint"])
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
    _write_seed_jsonl(seed, ["memory.long_term_memory"])
    db = tmp_path / "board.db"

    # 预先塞 2 张 card(无论 cap_id 是否在 yaml,只看数量是否 underfilled)
    conn = open_db(db)
    try:
        DeepCardRepo(conn).upsert(DeepCard(cap_id="memory.long_term_memory", what="manual edit"))
        DeepCardRepo(conn).upsert(DeepCard(cap_id="memory.short_term_memory"))
    finally:
        conn.close()

    svc = SeedIngestService(seed_path=seed, db_path=db, config_dir=REAL_CONFIG_DIR)
    result = svc.run_once_if_underfilled()
    assert result.inserted == 0
    # underfilled 检查命中 → 不读 seed,total_seed 可能为 0(no-op semantics)
    # 实现选定:no-op 返回全 0
    assert result.total_seed == 0

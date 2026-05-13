"""RefreshPipeline L0 — 5 个 step 独立路径 + milvus 降级 4 种 + critical 错误。"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest

from dashboard.derive.refresh_pipeline import RefreshPipeline, StepEvent

PROJECT_ROOT = Path(__file__).resolve().parents[3]
REAL_CONFIG_DIR = PROJECT_ROOT / "dashboard" / "config"


@pytest.fixture
def pipeline(tmp_path: Path) -> RefreshPipeline:
    return RefreshPipeline(
        project_root=PROJECT_ROOT,
        config_dir=REAL_CONFIG_DIR,
        db_path=tmp_path / "board.db",
        seed_path=PROJECT_ROOT / "dashboard" / "data" / "deep_cards_seed.jsonl",
    )


def test_step_event_dataclass_shape() -> None:
    ev = StepEvent(step="chip_resolve", status="done", label="x", detail="y", duration_ms=5)
    assert ev.step == "chip_resolve"
    # status 只接受 4 个文字量(运行时不严格,但实现需 Literal 标注)
    valid: set[Literal["running", "done", "skip", "error"]] = {"running", "done", "skip", "error"}
    assert ev.status in valid


def test_chip_resolve_step_returns_done(pipeline: RefreshPipeline) -> None:
    ev = pipeline._chip_resolve_step()
    assert ev.step == "chip_resolve"
    assert ev.status == "done"
    assert "chip" in ev.detail.lower() or ev.detail  # 实现给出 detail
    assert ev.duration_ms >= 0

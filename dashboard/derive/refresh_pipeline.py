"""RefreshPipeline — POST /refresh SSE 5-step pipeline。spec § 2.6。

5 step:chip_resolve / seed_ingest / decision_extract / milvus_reindex / snapshot_finalize。
每个 step 返回 StepEvent;milvus_reindex 走 4 种 skip 降级矩阵(spec § 2.3)。
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

StepStatus = Literal["running", "done", "skip", "error"]


@dataclass(frozen=True)
class StepEvent:
    step: str
    status: StepStatus
    label: str
    detail: str = ""
    duration_ms: int = 0


# 步骤中文 label(SSE 面板显示)— spec § 2.1 范例
_LABELS: dict[str, str] = {
    "chip_resolve": "扫代码判断 chip 状态",
    "seed_ingest": "加载 DeepCard seed",
    "decision_extract": "重抽 spec/plan/memory 决策",
    "milvus_reindex": "向量重建",
    "snapshot_finalize": "整合 snapshot",
}


class RefreshPipeline:
    def __init__(
        self,
        *,
        project_root: Path,
        config_dir: Path,
        db_path: Path,
        seed_path: Path,
    ) -> None:
        self.project_root = project_root
        self.config_dir = config_dir
        self.db_path = db_path
        self.seed_path = seed_path

    # ---- 单 step 实现(下任务陆续补齐)----

    def _chip_resolve_step(self) -> StepEvent:
        """全量 resolve 62 cap;失败抛 → 上层包 status=error。"""
        from dashboard.derive.capability_resolver import load_capabilities, resolve_status

        t0 = time.perf_counter()
        caps = load_capabilities(self.config_dir / "capabilities.yaml")
        lit = wip = todo = 0
        for c in caps:
            s = resolve_status(c, self.project_root)
            if s == "lit":
                lit += 1
            elif s == "wip":
                wip += 1
            else:
                todo += 1
        dt = int((time.perf_counter() - t0) * 1000)
        return StepEvent(
            step="chip_resolve",
            status="done",
            label=_LABELS["chip_resolve"],
            detail=f"{len(caps)} chip · {lit} lit / {wip} wip / {todo} todo",
            duration_ms=dt,
        )

    async def stream(self) -> AsyncIterator[StepEvent]:
        """yield 5 个 step × (running, done|skip|error)。后续 task 完成。"""
        raise NotImplementedError("see Task 9")

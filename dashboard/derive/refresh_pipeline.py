"""RefreshPipeline — POST /refresh SSE 5-step pipeline。spec § 2.6。

5 step:chip_resolve / seed_ingest / decision_extract / milvus_reindex / snapshot_finalize。
每个 step 返回 StepEvent;milvus_reindex 走 4 种 skip 降级矩阵(spec § 2.3)。
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import AsyncIterator, Callable
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
        """全量 resolve 全部 cap;失败抛 → 上层包 status=error。

        附带漂移校验(fail-loud,反"虚假新鲜感"):统计 lit-但-无 DeepCard 的能力数 +
        DeepCard code_anchor 指向已不存在文件/越界行的数量,显示到 refresh 面板。
        """
        from dashboard.derive.capability_resolver import load_capabilities, resolve_status

        t0 = time.perf_counter()
        caps = load_capabilities(self.config_dir / "capabilities.yaml")
        lit = wip = todo = 0
        lit_ids: set[str] = set()
        for c in caps:
            s = resolve_status(c, self.project_root)
            if s == "lit":
                lit += 1
                lit_ids.add(c.id)
            elif s == "wip":
                wip += 1
            else:
                todo += 1
        drift = self._drift_suffix(lit_ids)
        dt = int((time.perf_counter() - t0) * 1000)
        return StepEvent(
            step="chip_resolve",
            status="done",
            label=_LABELS["chip_resolve"],
            detail=f"{len(caps)} chip · {lit} lit / {wip} wip / {todo} todo{drift}",
            duration_ms=dt,
        )

    def _drift_suffix(self, lit_ids: set[str]) -> str:
        """lit-无卡 数 + code_anchor 失效数 → ' · ⚠ N lit 无卡 · M 锚点漂移' 或 ' · ✓ 无漂移'。

        任何异常都吞成空串,不让漂移校验拖垮 critical 的 chip_resolve step。
        """
        try:
            from dashboard.state.db import open_db
            from dashboard.state.repositories import DeepCardRepo

            conn = open_db(self.db_path)
            try:
                cards = DeepCardRepo(conn).get_all()
            finally:
                conn.close()
            carded = {c.cap_id for c in cards}
            lit_no_card = len(lit_ids - carded)
            broken = 0
            for card in cards:
                for a in card.code_anchors:
                    p = self.project_root / a.file
                    # 短路:文件不存在就不 open(避免 open 缺失文件);存在则查行号越界
                    if not p.exists() or a.line > sum(1 for _ in p.open(errors="ignore")):
                        broken += 1
            parts = []
            if lit_no_card:
                parts.append(f"⚠ {lit_no_card} lit 无卡")
            if broken:
                parts.append(f"⚠ {broken} 锚点漂移")
            return " · " + " · ".join(parts) if parts else " · ✓ 无漂移"
        except Exception as e:  # noqa: BLE001
            logger.warning("drift check skipped: %s", e)
            return ""

    def _seed_ingest_step(self) -> StepEvent:
        from dashboard.derive.seed_ingest import SeedIngestService

        t0 = time.perf_counter()
        svc = SeedIngestService(
            seed_path=self.seed_path, db_path=self.db_path, config_dir=self.config_dir
        )
        # refresh 走 insert-if-missing(force=False),保护手动编辑;
        # 用户想 force 走 CLI --force 或后续 admin endpoint。
        result = svc.run(force=False)
        dt = int((time.perf_counter() - t0) * 1000)
        return StepEvent(
            step="seed_ingest",
            status="done",
            label=_LABELS["seed_ingest"],
            detail=(
                f"{result.total_seed} cards · {result.inserted} insert / "
                f"{result.skipped_existing} skip(existing) / "
                f"{result.skipped_invalid} skip(invalid)"
            ),
            duration_ms=dt,
        )

    def _decision_extract_step(self) -> StepEvent:
        from dashboard.derive.decision_extractor import extract_all

        t0 = time.perf_counter()
        decisions = extract_all()
        dt = int((time.perf_counter() - t0) * 1000)
        return StepEvent(
            step="decision_extract",
            status="done",
            label=_LABELS["decision_extract"],
            detail=f"{len(decisions)} entries",
            duration_ms=dt,
        )

    async def _milvus_reindex_step(self) -> StepEvent:
        """全量 reindex DeepCard → Milvus,4 种 skip 降级(spec § 2.3)。"""
        t0 = time.perf_counter()

        def _ev(status: StepStatus, detail: str) -> StepEvent:
            return StepEvent(
                step="milvus_reindex",
                status=status,
                label=_LABELS["milvus_reindex"],
                detail=detail,
                duration_ms=int((time.perf_counter() - t0) * 1000),
            )

        # 1. host 未设
        host = os.getenv("HARNESS_BOARD_MILVUS_HOST")
        if not host:
            return _ev("skip", "milvus disabled")

        # 2. embedding key 缺失(qwen mode 需 DASHSCOPE_API_KEY)
        mode = os.getenv("EMBEDDING_MODE", "qwen")
        if mode == "qwen" and not os.getenv("DASHSCOPE_API_KEY"):
            return _ev("skip", "embedding key missing")

        port = int(os.getenv("HARNESS_BOARD_MILVUS_PORT", "19530"))

        # 3. Milvus 不可达
        try:
            from dashboard.state.milvus_collection import DeepCardMilvusClient, embedding_text

            client = DeepCardMilvusClient(host=host, port=port)
            await client.ensure_collection()
        except ConnectionError as e:
            logger.warning("milvus_reindex skip (connection): %s", e)
            return _ev("skip", "milvus unreachable")
        except Exception as e:  # noqa: BLE001
            logger.warning("milvus_reindex skip (collection init): %s", e)
            return _ev("skip", f"milvus unreachable: {str(e)[:60]}")

        # 4. embedding 调用失败
        try:
            from app.services.embedding_factory import build_embedding_service_from_env

            from dashboard.derive.capability_resolver import load_capabilities
            from dashboard.state.db import open_db
            from dashboard.state.repositories import DeepCardRepo

            embedder = build_embedding_service_from_env()

            conn = open_db(self.db_path)
            try:
                cards = DeepCardRepo(conn).get_all()
            finally:
                conn.close()

            caps = load_capabilities(self.config_dir / "capabilities.yaml")
            name_by_id = {c.id: c.name_cn for c in caps}

            rows: list[dict[str, object]] = []
            texts: list[str] = []
            for card in cards:
                name_cn = name_by_id.get(card.cap_id, "")
                texts.append(embedding_text(card, name_cn=name_cn))
                rows.append(
                    {
                        "cap_id": card.cap_id,
                        "dimension": (card.cap_id.split(".", 1)[0] if "." in card.cap_id else ""),
                        "name_cn": name_cn,
                        "status": "lit",
                    }
                )
            if texts:
                vecs = await embedder.embed(texts)
                for r, v in zip(rows, vecs, strict=True):
                    r["embedding"] = v
                await client.upsert(rows)
            return _ev("done", f"{len(rows)} cards upserted")
        except Exception as e:  # noqa: BLE001
            logger.warning("milvus_reindex skip (embedding/upsert): %s", e)
            msg = str(e).replace("\n", " ")[:80]
            return _ev("skip", f"embedding error: {msg}")

    def _snapshot_finalize_step(self) -> StepEvent:
        from dashboard.derive.snapshot_builder import build_snapshot
        from dashboard.state.db import open_db
        from dashboard.state.repositories import OverrideRepo, SnapshotRepo

        t0 = time.perf_counter()
        conn = open_db(self.db_path)
        try:
            overrides = OverrideRepo(conn).get_all()
            snap_repo = SnapshotRepo(conn)
            snap_repo.invalidate()
            snapshot = build_snapshot(self.project_root, self.config_dir, overrides=overrides)
            snap_repo.save(snapshot.refreshed_at, snapshot.to_dict())
        finally:
            conn.close()
        dt = int((time.perf_counter() - t0) * 1000)
        return StepEvent(
            step="snapshot_finalize",
            status="done",
            label=_LABELS["snapshot_finalize"],
            detail=f"refreshed_at {snapshot.refreshed_at}",
            duration_ms=dt,
        )

    async def stream(self) -> AsyncIterator[StepEvent]:
        """yield 5 个 step × (running + done|skip|error)。

        协议:
        - 每个 step 先 yield 一个 status=running 占位 event
        - 再调对应 _xxx_step,把返回结果 yield 出去
        - critical step(chip_resolve / seed_ingest / decision_extract / snapshot_finalize)
          抛异常时 yield status=error 但**不取消**后续 step(spec § 2.4)
        - milvus_reindex 内部已封装 4 种 skip,不会向外抛
        """
        sync_steps: tuple[tuple[str, Callable[[], StepEvent]], ...] = (
            ("chip_resolve", self._chip_resolve_step),
            ("seed_ingest", self._seed_ingest_step),
            ("decision_extract", self._decision_extract_step),
        )

        for name, fn in sync_steps:
            yield StepEvent(step=name, status="running", label=_LABELS[name])
            try:
                yield fn()
            except Exception as e:  # noqa: BLE001
                logger.exception("step %s failed", name)
                yield StepEvent(
                    step=name,
                    status="error",
                    label=_LABELS[name],
                    detail=str(e)[:120],
                )

        # milvus_reindex(async)
        yield StepEvent(step="milvus_reindex", status="running", label=_LABELS["milvus_reindex"])
        try:
            yield await self._milvus_reindex_step()
        except Exception as e:  # noqa: BLE001
            logger.exception("milvus_reindex unexpectedly raised")
            yield StepEvent(
                step="milvus_reindex",
                status="skip",
                label=_LABELS["milvus_reindex"],
                detail=f"unexpected: {str(e)[:80]}",
            )

        # snapshot_finalize 始终最后跑
        yield StepEvent(
            step="snapshot_finalize", status="running", label=_LABELS["snapshot_finalize"]
        )
        try:
            yield self._snapshot_finalize_step()
        except Exception as e:  # noqa: BLE001
            logger.exception("snapshot_finalize failed")
            yield StepEvent(
                step="snapshot_finalize",
                status="error",
                label=_LABELS["snapshot_finalize"],
                detail=str(e)[:120],
            )

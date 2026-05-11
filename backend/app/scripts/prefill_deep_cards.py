"""DeepCard LLM prefill batch CLI。spec § 7.3 / Plan 1 Task 7。

Usage:
    uv run --project backend python -m app.scripts.prefill_deep_cards \\
        --caps 01.constrained_schema,02.tool_registry \\
        --db backend/data/board.db
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dashboard.derive.deep_card_types import DeepCard, FieldProvenance
from dashboard.derive.llm_prefill_prompt import (
    PrefillRequest,
    PrefillResponse,
    build_full_prefill_prompt,
)
from dashboard.derive.provenance import verify_quote_in_source
from dashboard.state.db import open_db
from dashboard.state.repositories import DeepCardRepo

if TYPE_CHECKING:
    from app.services.llm_service import LLMService

logger = logging.getLogger(__name__)
# project root = backend/app/scripts/prefill_deep_cards.py → ../../../ → project root
PROJECT_ROOT = Path(__file__).resolve().parents[3]

CONTENT_FIELDS = (
    "what",
    "why",
    "alternatives",
    "chosen_alternative",
    "tradeoff",
    "lessons_learned",
)


@dataclass(frozen=True)
class CapPrefillContext:
    cap_id: str
    cap_name_cn: str
    linked_specs: list[str]
    linked_memories: list[str]
    decisions_summary: list[tuple[str, str]]


@dataclass(frozen=True)
class PrefillResult:
    cap_id: str
    success_fields: int
    rejected_fields: int
    error: str | None = None


def _log_prefill(
    conn: sqlite3.Connection,
    cap_id: str,
    field_name: str,
    status: str,
    detail: str = "",
) -> None:
    """写 prefill_log。"""
    with conn:
        conn.execute(
            "INSERT INTO prefill_log (cap_id, field_name, status, detail, ran_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (cap_id, field_name, status, detail, datetime.now(UTC).isoformat()),
        )


def prefill_one_cap(
    *,
    ctx: CapPrefillContext,
    llm_service: LLMService,
    repo: DeepCardRepo,
    base_dir: Path,
) -> PrefillResult:
    """单个 cap 的 prefill — 调 LLM + provenance 校验 + 落库。"""
    req = PrefillRequest(
        cap_id=ctx.cap_id,
        cap_name_cn=ctx.cap_name_cn,
        linked_spec_paths=ctx.linked_specs,
        linked_memory_paths=ctx.linked_memories,
        decisions_summary=ctx.decisions_summary,
    )
    prompt = build_full_prefill_prompt(req)
    try:
        resp = llm_service.chat(prompt=prompt, tier="balanced", schema=PrefillResponse)
    except Exception as e:
        logger.exception("LLM prefill failed for %s", ctx.cap_id)
        _log_prefill(repo.conn, ctx.cap_id, "*", "llm_error", str(e))
        return PrefillResult(cap_id=ctx.cap_id, success_fields=0, rejected_fields=0, error=str(e))

    parsed_raw = getattr(resp, "parsed", None)
    parsed: PrefillResponse
    if isinstance(parsed_raw, PrefillResponse):
        parsed = parsed_raw
    else:
        # fallback: parse content
        parsed = PrefillResponse.model_validate_json(resp.content)

    success, rejected = _apply_response_to_card(
        parsed=parsed,
        ctx=ctx,
        repo=repo,
        base_dir=base_dir,
    )
    return PrefillResult(cap_id=ctx.cap_id, success_fields=success, rejected_fields=rejected)


def _apply_response_to_card(
    *,
    parsed: PrefillResponse,
    ctx: CapPrefillContext,
    repo: DeepCardRepo,
    base_dir: Path,
) -> tuple[int, int]:
    """逐字段 provenance 校验 → 失败 reject → 通过的字段写入新 DeepCard。"""
    existing = repo.get(ctx.cap_id) or DeepCard(cap_id=ctx.cap_id)
    new_data: dict[str, Any] = existing.model_dump()
    success = 0
    rejected = 0

    for field_name in CONTENT_FIELDS:
        value = getattr(parsed, field_name)
        prov: FieldProvenance | None = getattr(parsed, f"{field_name}_provenance", None)
        if value is None or (isinstance(value, list) and not value):
            _log_prefill(repo.conn, ctx.cap_id, field_name, "skipped", "LLM returned null")
            continue
        if prov is None or not prov.quote:
            rejected += 1
            _log_prefill(repo.conn, ctx.cap_id, field_name, "rejected_quote", "missing provenance")
            continue
        check = verify_quote_in_source(prov.quote, prov.source, base_dir=base_dir)
        if not check.ok:
            rejected += 1
            _log_prefill(repo.conn, ctx.cap_id, field_name, "rejected_quote", check.reason)
            continue
        # 落 value
        if isinstance(value, list):
            new_data[field_name] = [
                a.model_dump() if hasattr(a, "model_dump") else a for a in value
            ]
        else:
            new_data[field_name] = value
        # provenance 累计写入
        prov_dict = new_data.get("provenance") or {}
        prov_dict[field_name] = prov.model_dump()
        new_data["provenance"] = prov_dict
        success += 1
        _log_prefill(repo.conn, ctx.cap_id, field_name, "success", "")

    if success > 0:
        new_data["prefill_source"] = "llm"
        new_data["prefill_at"] = datetime.now(UTC).isoformat()
    # linked_specs / linked_memories 自动 dedupe(spec § 4.2)— provenance 内 value 是 dict
    prov_values = (new_data.get("provenance") or {}).values()
    spec_sources = {
        v["source"].split("#")[0]
        for v in prov_values
        if isinstance(v, dict) and isinstance(v.get("source"), str)
    }
    spec_paths = sorted(s for s in spec_sources if s.startswith("docs/"))
    memory_paths = sorted(
        s for s in spec_sources if "memory" in s.lower() or s.startswith("backend/data/memory")
    )
    if spec_paths:
        new_data["linked_specs"] = spec_paths
    if memory_paths:
        new_data["linked_memories"] = memory_paths

    if success > 0 or rejected > 0:
        repo.upsert(DeepCard.model_validate(new_data))

    return success, rejected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DeepCard LLM prefill batch")
    parser.add_argument("--caps", required=True, help="逗号分隔 cap_id list")
    parser.add_argument(
        "--db", default="backend/data/board.db", help="sqlite path (relative to project root)"
    )
    parser.add_argument("--base-dir", default=str(PROJECT_ROOT), help="project root for provenance")
    args = parser.parse_args(argv)

    # lazy import 避免 dashboard/derive/* L0 跑不动
    from app.services.openai_client import build_llm_service_from_env
    from dashboard.derive.capability_resolver import load_capabilities

    llm = build_llm_service_from_env()
    base_dir = Path(args.base_dir)
    db_path = base_dir / args.db
    conn = open_db(db_path)
    repo = DeepCardRepo(conn)

    caps_cfg = load_capabilities(base_dir / "dashboard" / "config" / "capabilities.yaml")
    cap_by_id = {c.id: c for c in caps_cfg}

    cap_ids = [c.strip() for c in args.caps.split(",") if c.strip()]
    total_success, total_rejected = 0, 0
    for cap_id in cap_ids:
        cfg = cap_by_id.get(cap_id)
        if not cfg:
            logger.warning("cap %s not in capabilities.yaml — skipping", cap_id)
            continue
        ctx = CapPrefillContext(
            cap_id=cap_id,
            cap_name_cn=cfg.name_cn,
            linked_specs=[],  # CLI 简化:空,可后续 enrich
            linked_memories=[],
            decisions_summary=[],
        )
        result = prefill_one_cap(ctx=ctx, llm_service=llm, repo=repo, base_dir=base_dir)
        logger.info(
            "cap=%s success=%d rejected=%d", cap_id, result.success_fields, result.rejected_fields
        )
        total_success += result.success_fields
        total_rejected += result.rejected_fields

    print(f"Prefill done. fields written: {total_success}, rejected: {total_rejected}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())

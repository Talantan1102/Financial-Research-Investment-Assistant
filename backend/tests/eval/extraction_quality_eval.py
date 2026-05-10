"""E9 — LLM extraction quality eval pipeline for EscalationPacket.

Ground truth source: EscalationRecord.user_edits (PG jsonb field, populated
when user clicks "edit" on a draft field in the EscalationConfirmDialog).

Metrics:
- field_accuracy = 1 - (n_fields_user_edited / n_fields_total)
- entity_recall = (n_entities_LLM_caught_correctly / n_entities_user_kept)
- entity_precision = (n_entities_LLM_caught_correctly / n_entities_LLM_extracted)
- preference_F1 = harmonic mean of preference recall+precision
- missing_field_quality = 1 if user filled the field LLM marked missing

Output: JSON report aggregating metrics across all EscalationRecord rows.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExtractionQualityReport:
    n_records: int
    field_accuracy_mean: float
    entity_recall_mean: float
    entity_precision_mean: float
    preference_f1_mean: float
    missing_field_quality_mean: float
    per_record: list[dict[str, Any]] = field(default_factory=list)


def flatten_paths(d: dict, prefix: str = "") -> set[str]:
    paths: set[str] = set()
    for k, v in d.items():
        p = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            paths |= flatten_paths(v, p)
        elif isinstance(v, list):
            for i, item in enumerate(v):
                if isinstance(item, dict):
                    paths |= flatten_paths(item, f"{p}[{i}]")
                else:
                    paths.add(f"{p}[{i}]")
        else:
            paths.add(p)
    return paths


def compute_field_accuracy(draft: dict, edits: list[dict]) -> float:
    total = len(flatten_paths(draft))
    if total == 0:
        return 1.0
    edited_paths = {e["field_path"] for e in edits}
    return 1.0 - (len(edited_paths) / total)


def _entity_set(packet: dict) -> set[tuple[str, str]]:
    return {
        (e["name"], e.get("ts_code") or "")
        for e in packet.get("chat_derived_signals", {}).get("entities", [])
    }


def compute_entity_metrics(draft: dict, confirmed: dict) -> tuple[float, float]:
    d, c = _entity_set(draft), _entity_set(confirmed)
    if not c:
        return 1.0, 1.0
    inter = d & c
    recall = len(inter) / len(c)
    precision = len(inter) / len(d) if d else 0.0
    return recall, precision


def _preference_set(packet: dict) -> set[str]:
    return {p["text"] for p in packet.get("chat_derived_signals", {}).get("preferences", [])}


def compute_preference_f1(draft: dict, confirmed: dict) -> float:
    d, c = _preference_set(draft), _preference_set(confirmed)
    if not c and not d:
        return 1.0
    inter = d & c
    p = len(inter) / len(d) if d else 0.0
    r = len(inter) / len(c) if c else 0.0
    if p + r == 0:
        return 0.0
    return 2 * p * r / (p + r)


def get_path(d: dict, path: str) -> Any:
    cur: Any = d
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def compute_missing_field_quality(packet_draft: dict, packet_confirmed: dict) -> float:
    hints = packet_draft.get("missing_field_hints", [])
    if not hints:
        return 1.0
    n_correct = 0
    for h in hints:
        path = h["field_path"]
        value = get_path(packet_confirmed, path)
        if value not in (None, "", [], {}):
            n_correct += 1
    return n_correct / len(hints)


async def run_extraction_quality_eval(
    database_url: str | None = None,
) -> ExtractionQualityReport:
    """Pull all EscalationRecord rows, compute metrics, return aggregated report."""
    try:
        import asyncpg
    except ImportError as exc:
        raise RuntimeError(
            "asyncpg is required to run the extraction quality eval pipeline. "
            "Install it with: uv add asyncpg"
        ) from exc

    dsn = database_url or os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL not set; cannot run extraction quality eval")
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            "SELECT id, packet_draft, packet_confirmed, user_edits FROM escalation_records "
            "WHERE status = 'completed'"
        )
    finally:
        await conn.close()

    accs, e_recalls, e_precisions, p_f1s, m_qualities = [], [], [], [], []
    per_record = []

    for row in rows:
        draft_raw = row["packet_draft"]
        confirmed_raw = row["packet_confirmed"]
        edits_raw = row["user_edits"]

        # asyncpg may return jsonb as str or already-parsed dict depending on type codec
        draft = json.loads(draft_raw) if isinstance(draft_raw, str) else draft_raw
        confirmed = json.loads(confirmed_raw) if isinstance(confirmed_raw, str) else confirmed_raw
        edits = json.loads(edits_raw) if isinstance(edits_raw, str) else (edits_raw or [])

        if not confirmed:
            continue

        acc = compute_field_accuracy(draft, edits)
        er, ep = compute_entity_metrics(draft, confirmed)
        pf1 = compute_preference_f1(draft, confirmed)
        mq = compute_missing_field_quality(draft, confirmed)

        accs.append(acc)
        e_recalls.append(er)
        e_precisions.append(ep)
        p_f1s.append(pf1)
        m_qualities.append(mq)
        per_record.append(
            {
                "record_id": str(row["id"]),
                "field_accuracy": acc,
                "entity_recall": er,
                "entity_precision": ep,
                "preference_f1": pf1,
                "missing_field_quality": mq,
            }
        )

    def _mean(xs: list[float]) -> float:
        return sum(xs) / len(xs) if xs else 0.0

    return ExtractionQualityReport(
        n_records=len(per_record),
        field_accuracy_mean=_mean(accs),
        entity_recall_mean=_mean(e_recalls),
        entity_precision_mean=_mean(e_precisions),
        preference_f1_mean=_mean(p_f1s),
        missing_field_quality_mean=_mean(m_qualities),
        per_record=per_record,
    )


if __name__ == "__main__":
    rep = asyncio.run(run_extraction_quality_eval())
    print(
        json.dumps(
            {
                "n_records": rep.n_records,
                "field_accuracy_mean": rep.field_accuracy_mean,
                "entity_recall_mean": rep.entity_recall_mean,
                "entity_precision_mean": rep.entity_precision_mean,
                "preference_f1_mean": rep.preference_f1_mean,
                "missing_field_quality_mean": rep.missing_field_quality_mean,
            },
            indent=2,
        )
    )

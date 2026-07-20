"""Read-only parity gate for legacy chat cutover."""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field


@dataclass
class CutoverEvidence:
    migration_report_hash: str
    source_counts: dict[str, int]
    target_counts: dict[str, int]
    active_chat_tasks: int
    frontend_singular_chat_urls: int
    has_run_session_routes: bool
    has_phase2_phase3_gates: bool
    backup_manifest_valid: bool = False


@dataclass
class CutoverResult:
    ok: bool
    failures: list[str] = field(default_factory=list)


def verify_cutover(evidence: CutoverEvidence) -> CutoverResult:
    failures: list[str] = []
    if not evidence.migration_report_hash or evidence.source_counts.get("chat_sessions", 0) != evidence.target_counts.get("run_sessions", 0) or evidence.source_counts.get("chat_messages", 0) != evidence.target_counts.get("run_messages", 0):
        failures.append("migration_counts")
    if evidence.active_chat_tasks:
        failures.append("active_chat_tasks")
    if evidence.frontend_singular_chat_urls:
        failures.append("legacy_frontend_urls")
    if not evidence.has_run_session_routes:
        failures.append("run_session_routes")
    if not evidence.has_phase2_phase3_gates:
        failures.append("phase2_phase3_done_cards")
    if not evidence.backup_manifest_valid:
        failures.append("backup_manifest")
    return CutoverResult(ok=not failures, failures=failures)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--migration-report", required=True)
    args = parser.parse_args()
    import json
    with open(args.migration_report, encoding="utf-8") as report_file:
        data = json.load(report_file)
    data.pop("report_hash", None)
    result = verify_cutover(CutoverEvidence(**data))
    print(json.dumps({"ok": result.ok, "failures": result.failures}))
    raise SystemExit(0 if result.ok else 1)


if __name__ == "__main__":
    main()

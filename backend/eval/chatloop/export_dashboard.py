"""Export evaluation history to the dashboard's PostgreSQL-free JSON source."""

from __future__ import annotations

import json
import os
import tempfile
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from eval.chatloop.artifact_store import ArtifactReference, read_verified_artifact
from eval.chatloop.business_reporting import derive_business_run_summary
from eval.chatloop.case_loader import CaseCatalog, load_catalog

_DEFAULT_OUT = (
    Path(__file__).resolve().parents[3] / "dashboard" / "data" / "chatloop_eval_history.json"
)

_RUN_COLS = (
    "run_id, created_at, git_sha, mode, dispatch, sut_model, judge_model, simulator_model, "
    "k, max_steps, max_turns, case_count, duration_ms, cost_cny, total_tokens, "
    "system_prompt_sha, sampling_json, thresholds_json, status, config_json"
)
_TRIAL_COLS = (
    "trial_id, run_id, case_id, trial_index, suite_type, trial_status, task_pass, "
    "task_score, failure_reason, artifact_path, artifact_sha256, created_at"
)


def export_history(
    out_path: Path = _DEFAULT_OUT,
    *,
    limit: int = 50,
    session_factory: Callable[[], Any] | None = None,
    catalog_loader: Callable[[], CaseCatalog] = load_catalog,
) -> dict[str, Any]:
    """Export recent runs, including honest business trial summaries."""
    from app.core.database import SessionLocal
    from sqlalchemy import text

    sf = session_factory or SessionLocal
    with sf() as session:
        session.execute(
            text("SELECT pg_advisory_lock(hashtextextended(:key, 0))"),
            {"key": "chatloop_eval_dashboard_export"},
        )
        try:
            runs = session.execute(
                text(
                    f"SELECT {_RUN_COLS} FROM chatloop_eval_runs "
                    "ORDER BY created_at DESC, run_id DESC LIMIT :n"
                ),
                {"n": limit},
            ).all()
            run_dicts = [dict(row._mapping) for row in runs]
            run_ids = [str(run["run_id"]) for run in run_dicts]
            metrics: list[Any] = []
            trials: list[Any] = []
            violations: list[Any] = []
            if run_ids:
                metrics = list(
                    session.execute(
                        text(
                            "SELECT run_id, behavior, metric, value, numerator, denominator "
                            "FROM chatloop_eval_metrics WHERE run_id = ANY(:ids)"
                        ),
                        {"ids": run_ids},
                    ).all()
                )
                trials = list(
                    session.execute(
                        text(
                            f"SELECT {_TRIAL_COLS} FROM chatloop_eval_trials "
                            "WHERE run_id = ANY(:ids) ORDER BY case_id, trial_index"
                        ),
                        {"ids": run_ids},
                    ).all()
                )
                violations = list(
                    session.execute(
                        text(
                            "SELECT t.run_id, v.trial_id, v.policy_id, v.severity, "
                            "v.triggered_escalations FROM chatloop_eval_violations v "
                            "JOIN chatloop_eval_trials t ON t.trial_id = v.trial_id "
                            "WHERE t.run_id = ANY(:ids)"
                        ),
                        {"ids": run_ids},
                    ).all()
                )
            data = _derive_history_data(
                run_dicts=run_dicts,
                metrics=metrics,
                trials=trials,
                violations=violations,
                catalog_loader=catalog_loader,
            )
            _atomic_write_json(out_path, data)
            return data
        finally:
            session.execute(
                text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"),
                {"key": "chatloop_eval_dashboard_export"},
            )


def _derive_history_data(
    *,
    run_dicts: list[dict[str, Any]],
    metrics: Sequence[Any],
    trials: Sequence[Any],
    violations: Sequence[Any],
    catalog_loader: Callable[[], CaseCatalog],
) -> dict[str, Any]:
    metrics_by_run: dict[str, dict[str, Any]] = defaultdict(dict)
    for metric in metrics:
        metrics_by_run[str(metric.run_id)][f"{metric.behavior}/{metric.metric}"] = {
            "value": metric.value,
            "num": metric.numerator,
            "den": metric.denominator,
        }

    trials_by_run = _rows_by_run(trials)
    violations_by_run = _rows_by_run(violations)
    catalog = catalog_loader() if any(run.get("mode") == "business" for run in run_dicts) else None
    for run in run_dicts:
        run_id = str(run["run_id"])
        run["metrics"] = metrics_by_run.get(run_id, {})
        if run.get("mode") != "business":
            continue
        assert catalog is not None
        run_trials = trials_by_run.get(run_id, [])
        artifacts = _load_artifacts(run_trials)
        run["business"] = derive_business_run_summary(
            run=run,
            trials=run_trials,
            violations=violations_by_run.get(run_id, []),
            catalog=catalog,
            artifacts=artifacts,
        )

    run_dicts.reverse()
    return {
        "schema_version": 2,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "latest": run_dicts[-1] if run_dicts else None,
        "runs": run_dicts,
    }


def _atomic_write_json(out_path: Path, data: Mapping[str, Any]) -> None:
    """Replace one complete snapshot while the database export lock is held."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=out_path.parent,
            prefix=f".{out_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.replace(temporary_name, out_path)
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def _rows_by_run(rows: Sequence[Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        mapped = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
        grouped[str(mapped["run_id"])].append(mapped)
    return grouped


def _load_artifacts(
    trials: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    artifacts: dict[str, Mapping[str, Any]] = {}
    for trial in trials:
        trial_id = str(trial["trial_id"])
        reference = ArtifactReference(
            path=Path(str(trial["artifact_path"])),
            sha256=str(trial["artifact_sha256"]),
        )
        try:
            artifacts[trial_id] = read_verified_artifact(reference)
        except Exception as exc:  # noqa: BLE001 - surface damaged evidence in the report
            artifacts[trial_id] = {
                "evaluation": {
                    "human_review_flags": [
                        {
                            "reason": "artifact_unavailable",
                            "assertion_id": "artifact_integrity",
                        }
                    ]
                },
                "artifact_error": f"{type(exc).__name__}: {exc}",
            }
    return artifacts


def main() -> int:
    data = export_history()
    print(f"导出 {len(data['runs'])} 次评估运行到 {_DEFAULT_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["export_history"]

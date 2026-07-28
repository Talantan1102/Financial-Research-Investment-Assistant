from __future__ import annotations

import json
from pathlib import Path

from starlette.testclient import TestClient

import dashboard.derive.chatloop_live as chatloop_live
from dashboard.derive.chatloop_live import (
    derive_chatloop_business_report,
    load_live,
)
from dashboard.server import app


def test_report_separates_validity_pass_and_diagnostic_score() -> None:
    report = derive_chatloop_business_report(_business_history())

    assert report is not None
    assert report["valid_trial_rate"] == 0.95
    assert report["task_pass_rate"] == 0.60
    assert report["diagnostic_score"] == 72.0
    # Capability 的诊断分不构成发布门槛，即使导出数据错误地给了 true。
    assert report["release_eligible"] is False


def test_report_completes_business_dimensions_and_preserves_review_evidence() -> None:
    report = derive_chatloop_business_report(_business_history())

    assert report is not None
    assert list(report["violations"]) == ["C0", "C1", "C2", "C3"]
    assert report["violations"] == {"C0": 1, "C1": 2, "C2": 0, "C3": 0}
    assert list(report["environment_coverage"]) == [f"E{i}" for i in range(1, 15)]
    assert report["environment_coverage"]["E1"] == 4
    assert report["environment_coverage"]["E14"] == 0
    assert list(report["task_groups"]) == [f"T{i}" for i in range(1, 10)]
    assert report["task_groups"]["T1"] == {"total": 8, "valid": 7, "passed": 4}
    assert report["task_groups"]["T9"] == {"total": 0, "valid": 0, "passed": 0}
    assert {item["reason"] for item in report["human_review"]} == {
        "C0",
        "C1",
        "judge_uncertain",
    }
    assert report["failure_reasons"] == [{"reason": "missing_evidence", "count": 2}]
    assert report["artifact_links"][0]["href"] == "/artifacts/trial-1.json"


def test_legacy_history_keeps_metric_trend_without_business_report(tmp_path: Path) -> None:
    history_path = tmp_path / "history.json"
    history_path.write_text(json.dumps(_legacy_history()), encoding="utf-8")

    scorecard = load_live(history_path)

    assert scorecard.business is None
    assert scorecard.metric_keys == ("routing_tool/RelAcc",)
    assert scorecard.cell(scorecard.latest, "routing_tool/RelAcc") == "80% (8/10)"


def test_chatloop_live_page_renders_business_evaluation_sections(monkeypatch) -> None:
    scorecard = chatloop_live.scorecard_from_history(_business_history())
    monkeypatch.setattr(chatloop_live, "load_live", lambda: scorecard)

    response = TestClient(app).get("/eval/chatloop-live")

    assert response.status_code == 200
    for label in (
        "有效试次率",
        "任务通过率",
        "诊断分",
        "违规分布",
        "环境覆盖",
        "任务组",
        "失败原因",
        "证据链接",
        "待人工复核",
    ):
        assert label in response.text
    assert "不能按平均分判定 Capability 通过" in response.text
    assert "judge_uncertain" in response.text
    assert "/artifacts/trial-1.json" in response.text


def _business_history() -> dict:
    business = {
        "total_trials": 20,
        "valid_trials": 19,
        "valid_trial_rate": 0.95,
        "task_passes": 12,
        "task_pass_rate": 0.60,
        "diagnostic_score": 72.0,
        "release_eligible": True,
        "violations": {"C0": 1, "C1": 2},
        "environment_coverage": {"E1": 4, "E7": 2},
        "task_groups": {"T1": {"total": 8, "valid": 7, "passed": 4}},
        "failure_reasons": [{"reason": "missing_evidence", "count": 2}],
        "human_review": [
            {
                "trial_id": "trial-1",
                "case_id": "B1-01",
                "reason": "C0",
                "artifact_path": "/artifacts/trial-1.json",
            },
            {
                "trial_id": "trial-2",
                "case_id": "B4-01",
                "reason": "C1",
                "artifact_path": "/artifacts/trial-2.json",
            },
            {
                "trial_id": "trial-3",
                "case_id": "B6-01",
                "reason": "judge_uncertain",
                "artifact_path": "/artifacts/trial-3.json",
            },
        ],
        "cases": [
            {
                "case_id": "B1-01",
                "suite_type": "Capability",
                "k": 3,
                "total_trials": 3,
                "valid_trials": 3,
                "pass_at_1": 1.0,
                "pass_power_k": True,
                "complete": True,
            }
        ],
        "artifact_links": [
            {
                "trial_id": "trial-1",
                "case_id": "B1-01",
                "path": "/artifacts/trial-1.json",
            }
        ],
    }
    run = {
        "run_id": "business-run-1",
        "created_at": "2026-07-28T10:30:00",
        "git_sha": "abcdef12",
        "mode": "business",
        "status": "completed",
        "case_count": 20,
        "duration_ms": 1200,
        "cost_cny": None,
        "total_tokens": 800,
        "system_prompt_sha": "prompt-sha",
        "business": business,
        "metrics": {},
    }
    return {"generated_at": "2026-07-28T10:31:00", "latest": run, "runs": [run]}


def _legacy_history() -> dict:
    run = {
        "created_at": "2026-07-27T09:00:00",
        "git_sha": "12345678",
        "mode": "ci",
        "metrics": {
            "routing_tool/RelAcc": {"value": 0.8, "num": 8, "den": 10},
        },
    }
    return {"generated_at": "2026-07-27T09:01:00", "latest": run, "runs": [run]}

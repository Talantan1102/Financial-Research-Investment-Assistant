"""读取 ChatLoop 评估历史，并派生实时成绩单所需的展示数据。

数据来自 ``dashboard/data/chatloop_eval_history.json``。后端负责导出事实，
本模块只做展示层归一化，因此 Dashboard 不需要直接连接 PostgreSQL。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_HISTORY = Path(__file__).resolve().parent.parent / "data" / "chatloop_eval_history.json"

# 趋势列固定顺序：出现的指标才展示，其余指标按字母顺序补在后面。
_KEY_METRICS: tuple[str, ...] = (
    "routing_tool/RelAcc",
    "abstain/IrrelAcc",
    "policy/disclaimer_compliance",
    "policy/advice_violations",
    "reliability/passk",
    "grounding/strict_faith",
    "grounding/lenient_faith_0.8",
    "multiturn/goal_met",
)

_LABELS: dict[str, str] = {
    "routing_tool/RelAcc": "RelAcc",
    "abstain/IrrelAcc": "IrrelAcc",
    "policy/disclaimer_compliance": "免责合规",
    "policy/advice_violations": "方向性违规",
    "reliability/passk": "pass^k",
    "grounding/strict_faith": "grounding 严格",
    "grounding/lenient_faith_0.8": "grounding 宽松",
    "multiturn/goal_met": "多轮目标达成",
}

_VIOLATION_LEVELS = tuple(f"C{i}" for i in range(4))
_ENVIRONMENT_AXES = tuple(f"E{i}" for i in range(1, 15))
_TASK_GROUPS = tuple(f"T{i}" for i in range(1, 10))


@dataclass(frozen=True)
class LiveScorecard:
    generated_at: str
    latest: dict[str, Any]
    runs: tuple[dict[str, Any], ...]
    metric_keys: tuple[str, ...]
    business: dict[str, Any] | None

    def label(self, key: str) -> str:
        return _LABELS.get(key, key)

    def cell(self, run: Mapping[str, Any], key: str) -> str:
        """把一个 legacy run 的指标格式化为趋势表单元格。"""
        metrics = run.get("metrics")
        metric = metrics.get(key) if isinstance(metrics, Mapping) else None
        if not isinstance(metric, Mapping) or metric.get("value") is None:
            return "—"
        value = float(metric["value"])
        if key.endswith("advice_violations"):
            return str(int(value))
        rendered = f"{value:.0%}"
        numerator, denominator = metric.get("num"), metric.get("den")
        if numerator is not None and denominator:
            rendered += f" ({numerator}/{denominator})"
        return rendered

    def short_time(self, run: Mapping[str, Any]) -> str:
        timestamp = str(run.get("created_at") or "")
        return timestamp.replace("T", " ")[5:16]  # MM-DD HH:MM


def derive_chatloop_business_report(history: Mapping[str, Any]) -> dict[str, Any] | None:
    """归一化最新一次 business run，不把诊断分解释成通过结论。"""
    latest = history.get("latest")
    if not isinstance(latest, Mapping):
        return None
    raw = latest.get("business")
    if not isinstance(raw, Mapping):
        return None

    total_trials = _as_int(raw.get("total_trials"))
    valid_trials = _as_int(raw.get("valid_trials"))
    task_passes = _as_int(raw.get("task_passes"))
    cases = _mapping_list(raw.get("cases"))
    suite_types = {str(case.get("suite_type") or "").casefold() for case in cases if case}
    for source in (raw, latest):
        suite = source.get("suite_type") or source.get("suite")
        if suite:
            suite_types.add(str(suite).casefold())
    is_capability = "capability" in suite_types

    violations_source = _mapping(raw.get("violations"))
    environment_source = _mapping(raw.get("environment_coverage"))
    task_source = _mapping(raw.get("task_groups"))

    violations = {
        severity: _as_int(violations_source.get(severity)) for severity in _VIOLATION_LEVELS
    }
    environment_coverage = {
        axis: _as_int(environment_source.get(axis)) for axis in _ENVIRONMENT_AXES
    }
    task_groups = {group: _task_bucket(task_source.get(group)) for group in _TASK_GROUPS}

    return {
        "total_trials": total_trials,
        "valid_trials": valid_trials,
        "valid_trial_rate": _as_rate(raw.get("valid_trial_rate"), valid_trials, total_trials),
        "task_passes": task_passes,
        "task_pass_rate": _as_rate(raw.get("task_pass_rate"), task_passes, valid_trials),
        "diagnostic_score": _as_optional_float(raw.get("diagnostic_score")),
        # Capability 是能力盘点，不设平均分发布线。即使上游误传 true，也必须关闭。
        "release_eligible": False if is_capability else bool(raw.get("release_eligible", False)),
        "is_capability": is_capability,
        "violations": violations,
        "environment_coverage": environment_coverage,
        "task_groups": task_groups,
        "failure_reasons": _count_items(raw.get("failure_reasons")),
        "human_review": _review_items(raw.get("human_review")),
        "cases": cases,
        "artifact_links": _artifact_links(raw.get("artifact_links")),
    }


def scorecard_from_history(data: Mapping[str, Any]) -> LiveScorecard:
    """从已解析 JSON 构建成绩单，供文件 loader 和页面测试共同使用。"""
    raw_runs = data.get("runs")
    runs = (
        tuple(dict(run) for run in raw_runs if isinstance(run, Mapping))
        if isinstance(raw_runs, Sequence) and not isinstance(raw_runs, (str, bytes))
        else ()
    )

    raw_latest = data.get("latest")
    latest = dict(raw_latest) if isinstance(raw_latest, Mapping) else (runs[-1] if runs else {})
    present: set[str] = set()
    for run in runs:
        metrics = run.get("metrics")
        if isinstance(metrics, Mapping):
            present.update(str(key) for key in metrics)
    keys = [key for key in _KEY_METRICS if key in present]
    keys.extend(sorted(present - set(_KEY_METRICS)))

    normalized_history = {**data, "latest": latest, "runs": runs}
    return LiveScorecard(
        generated_at=str(data.get("generated_at") or ""),
        latest=latest,
        runs=runs,
        metric_keys=tuple(keys),
        business=derive_chatloop_business_report(normalized_history),
    )


def load_live(path: Path = _HISTORY) -> LiveScorecard:
    if not path.exists():
        raise FileNotFoundError(f"ChatLoop 评估历史尚未生成：{path}。请先运行一次 run_eval。")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError("ChatLoop 评估历史的顶层必须是 JSON 对象")
    return scorecard_from_history(data)


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _mapping_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _as_int(value: object) -> int:
    if value is None:
        return 0
    return int(value)


def _as_optional_float(value: object) -> float | None:
    return None if value is None else float(value)


def _as_rate(value: object, numerator: int, denominator: int) -> float:
    if value is not None:
        return float(value)
    return numerator / denominator if denominator else 0.0


def _task_bucket(value: object) -> dict[str, int]:
    bucket = _mapping(value)
    return {
        "total": _as_int(bucket.get("total")),
        "valid": _as_int(bucket.get("valid")),
        "passed": _as_int(bucket.get("passed")),
    }


def _count_items(value: object) -> list[dict[str, Any]]:
    return [
        {"reason": str(item.get("reason") or ""), "count": _as_int(item.get("count"))}
        for item in _mapping_list(value)
    ]


def _review_items(value: object) -> list[dict[str, Any]]:
    items = _mapping_list(value)
    for item in items:
        item["href"] = str(item.get("artifact_path") or item.get("href") or "")
    return items


def _artifact_links(value: object) -> list[dict[str, Any]]:
    links = _mapping_list(value)
    for link in links:
        link["href"] = str(link.get("href") or link.get("url") or link.get("path") or "")
    return links


__all__ = [
    "LiveScorecard",
    "derive_chatloop_business_report",
    "load_live",
    "scorecard_from_history",
]

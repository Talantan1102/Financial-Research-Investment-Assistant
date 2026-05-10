"""C.5 Memory Eval Runner — 跑全套 metric 输出聚合报告.

spec § 10 跑频次:
    - 每 prompt 改动: run unit + integration (gates CI)
    - PR gate: run --strict 模式, threshold 不达 exit non-zero
    - nightly: real LLM judge + cassette replay

CLI:
    uv run python -m backend.eval.memory.eval_runner \
        --metric all --golden backend/eval/memory/c5_memory_golden.jsonl
    uv run python -m backend.eval.memory.eval_runner \
        --metric routing --report json --strict

Thresholds (spec § 10):
    recall_precision      ≥ 0.7
    temporal_correctness  ≥ 0.95
    faithful_answer       ≥ 0.85
    routing_accuracy      ≥ 0.85
    long_tail_p90_min_days ≥ 7
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from datetime import UTC
from pathlib import Path
from typing import Any

from backend.eval.memory.faithful_answer_metric import faithful_answer
from backend.eval.memory.long_tail_monitor import long_tail_recall_check
from backend.eval.memory.recall_precision_metric import recall_precision
from backend.eval.memory.routing_accuracy_metric import routing_accuracy
from backend.eval.memory.temporal_correctness_metric import temporal_correctness

METRIC_THRESHOLDS: dict[str, float] = {
    "recall_precision": 0.7,
    "temporal_correctness": 0.95,
    "faithful_answer": 0.85,
    "routing_accuracy": 0.85,
    "long_tail_p90_min_days": 7,
}


def load_golden_cases(golden_path: Path) -> list[dict[str, Any]]:
    """读 jsonl, 每行一 case."""
    cases = []
    for line in golden_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        cases.append(json.loads(line))
    return cases


async def run_all(
    golden_path: Path,
    judge: Any,
    planner: Any,
    retriever: Any,
) -> dict[str, Any]:
    """跑全套 metric, 输出聚合报告 dict.

    Args:
        golden_path: c5_memory_golden.jsonl path.
        judge: JudgeProtocol-shaped 对象 (eval / decompose_to_claims / is_grounded).
        planner: PlannerProtocol-shaped 对象 (.plan(query) -> Plan).
        retriever: 实现 archival_memory_search + generate_answer (live wiring).
    """
    cases = load_golden_cases(golden_path)
    by_cat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in cases:
        by_cat[c["category"]].append(c)

    results: dict[str, Any] = {
        "by_metric": {},
        "thresholds": METRIC_THRESHOLDS,
        "case_counts": {k: len(v) for k, v in by_cat.items()},
    }

    # === Metric 1: recall_precision ===
    rp_scores: list[float] = []
    for case in by_cat.get("retrieval", []):
        retrieved = await retriever.archival_memory_search(case["query"], k=5)
        score = await recall_precision(case["query"], retrieved, judge)
        rp_scores.append(score)
    results["by_metric"]["recall_precision"] = {
        "mean": (sum(rp_scores) / len(rp_scores)) if rp_scores else 0.0,
        "count": len(rp_scores),
    }

    # === Metric 2: temporal_correctness ===
    tc_scores: list[float] = []
    for case in by_cat.get("retrieval", []):
        rng = case.get("expected_time_range")
        if rng is None:
            continue
        retrieved = await retriever.archival_memory_search(case["query"], k=5)
        from datetime import datetime

        time_range = (
            datetime.fromisoformat(rng[0]).replace(tzinfo=UTC),
            datetime.fromisoformat(rng[1]).replace(tzinfo=UTC),
        )
        score = temporal_correctness(retrieved, time_range)
        tc_scores.append(score)
    results["by_metric"]["temporal_correctness"] = {
        "mean": (sum(tc_scores) / len(tc_scores)) if tc_scores else 1.0,
        "count": len(tc_scores),
    }

    # === Metric 3: faithful_answer (sub-sample 10 retrieval case) ===
    fa_scores: list[float] = []
    for case in by_cat.get("retrieval", [])[:10]:
        retrieved = await retriever.archival_memory_search(case["query"], k=5)
        answer = await retriever.generate_answer(case["query"], retrieved)
        score = await faithful_answer(answer, retrieved, judge)
        fa_scores.append(score)
    results["by_metric"]["faithful_answer"] = {
        "mean": (sum(fa_scores) / len(fa_scores)) if fa_scores else 1.0,
        "count": len(fa_scores),
    }

    # === Metric 4: routing_accuracy ===
    routing_cases = by_cat.get("routing", [])
    racc = await routing_accuracy(planner, routing_cases) if routing_cases else 0.0
    results["by_metric"]["routing_accuracy"] = {
        "value": racc,
        "count": len(routing_cases),
    }

    # === 长尾召回监控 ===
    sample_results = []
    for case in by_cat.get("retrieval", []):
        retrieved = await retriever.archival_memory_search(case["query"], k=5)
        sample_results.append({"query": case["query"], "top5_facts": retrieved})
    lt = long_tail_recall_check(
        sample_results, p90_floor_days=int(METRIC_THRESHOLDS["long_tail_p90_min_days"])
    )
    results["by_metric"]["long_tail"] = lt

    return results


def assert_thresholds(results: dict[str, Any]) -> list[str]:
    """对照 METRIC_THRESHOLDS 收集 failures."""
    failures: list[str] = []
    bm = results.get("by_metric", {})

    rp = bm.get("recall_precision", {}).get("mean", 0.0)
    if rp < METRIC_THRESHOLDS["recall_precision"]:
        failures.append(f"recall_precision {rp:.3f} < {METRIC_THRESHOLDS['recall_precision']}")

    tc = bm.get("temporal_correctness", {}).get("mean", 0.0)
    if tc < METRIC_THRESHOLDS["temporal_correctness"]:
        failures.append(
            f"temporal_correctness {tc:.3f} < {METRIC_THRESHOLDS['temporal_correctness']}"
        )

    fa = bm.get("faithful_answer", {}).get("mean", 0.0)
    if fa < METRIC_THRESHOLDS["faithful_answer"]:
        failures.append(f"faithful_answer {fa:.3f} < {METRIC_THRESHOLDS['faithful_answer']}")

    racc = bm.get("routing_accuracy", {}).get("value", 0.0)
    if racc < METRIC_THRESHOLDS["routing_accuracy"]:
        failures.append(f"routing_accuracy {racc:.3f} < {METRIC_THRESHOLDS['routing_accuracy']}")

    lt = bm.get("long_tail", {})
    if lt and lt.get("violated"):
        failures.append(
            f"long_tail p90={lt.get('p90_min_age_days')} < {lt.get('p90_floor_days')} days"
        )

    return failures


def format_text_report(results: dict[str, Any], failures: list[str]) -> str:
    lines = []
    lines.append("=" * 60)
    lines.append("C.5 Memory Eval Report")
    lines.append("=" * 60)
    lines.append(f"case_counts: {results.get('case_counts', {})}")
    lines.append("")
    for name, metric in results.get("by_metric", {}).items():
        lines.append(f"  {name}: {metric}")
    lines.append("")
    lines.append(f"Failures: {failures or 'none'}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="C.5 memory eval runner")
    parser.add_argument(
        "--golden",
        default="backend/eval/memory/c5_memory_golden.jsonl",
        help="path to golden jsonl",
    )
    parser.add_argument(
        "--metric",
        choices=["all", "recall", "temporal", "faithful", "routing", "long_tail"],
        default="all",
    )
    parser.add_argument("--report", choices=["json", "text"], default="text")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero if any threshold violated (PR gate mode)",
    )
    args = parser.parse_args(argv)

    # 真实 wiring 在 _runner_deps.py 内 — CLI 入口仅 nightly / dogfood 用.
    # L0/L1 测试直接调 metric 函数, 不经此 CLI.
    from backend.eval.memory._runner_deps import build_runtime_deps

    judge, planner, retriever = build_runtime_deps()

    results = asyncio.run(run_all(Path(args.golden), judge, planner, retriever))
    failures = assert_thresholds(results)

    if args.report == "json":
        print(json.dumps({"results": results, "failures": failures}, indent=2, default=str))
    else:
        print(format_text_report(results, failures))

    if args.strict and failures:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

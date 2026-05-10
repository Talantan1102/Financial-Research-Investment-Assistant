"""L0 — routing_accuracy_metric skeleton: input/output schema validation.

Plan 4 skeleton; Plan 8 fills 50 cases + threshold assertions.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add backend/ to sys.path so 'eval.memory.routing_accuracy_metric' resolves.
_BACKEND = Path(__file__).resolve().parents[3]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def test_routing_accuracy_metric_callable_with_no_cases() -> None:
    from eval.memory.routing_accuracy_metric import compute_routing_accuracy

    result = compute_routing_accuracy(cases=[])
    assert "total" in result
    assert "correct" in result
    assert "accuracy" in result
    assert "per_tool_recall" in result
    assert "errors" in result
    assert result["total"] == 0
    assert result["accuracy"] == 0.0


def test_routing_accuracy_metric_with_synthetic_case() -> None:
    from eval.memory.routing_accuracy_metric import compute_routing_accuracy

    cases = [
        {
            "query": "我的持仓",
            "expected_tool": "archival_memory_search",
            "predicted_tool": "archival_memory_search",
        },
        {
            "query": "茅台同行业的股",
            "expected_tool": "archival_memory_traverse",
            "predicted_tool": "archival_memory_search",
        },
    ]
    result = compute_routing_accuracy(cases=cases)
    assert result["total"] == 2
    assert result["correct"] == 1
    assert abs(result["accuracy"] - 0.5) < 1e-6
    # per_tool_recall must list all 6 memory tools
    assert set(result["per_tool_recall"].keys()) == {
        "core_memory_append",
        "core_memory_replace",
        "archival_memory_insert",
        "archival_memory_search",
        "archival_memory_traverse",
        "recall_memory_search",
    }
    assert result["per_tool_recall"]["archival_memory_search"] == 1.0
    assert result["per_tool_recall"]["archival_memory_traverse"] == 0.0
    assert len(result["errors"]) == 1
    assert result["errors"][0]["expected"] == "archival_memory_traverse"


def test_weekly_sql_file_exists() -> None:
    p = _BACKEND / "scripts" / "memory" / "weekly_tool_routing_report.sql"
    assert p.exists(), f"missing: {p}"
    content = p.read_text(encoding="utf-8")
    # 周报 SQL 必含字段
    assert "tool_name" in content
    assert "result_count" in content
    assert "latency_ms" in content
    assert "mcp_tool_call_log" in content

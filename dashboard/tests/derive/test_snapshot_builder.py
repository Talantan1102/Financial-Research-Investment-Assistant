# dashboard/tests/derive/test_snapshot_builder.py
from pathlib import Path

from dashboard.derive.snapshot_builder import build_snapshot

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
CONFIG_DIR = Path(__file__).parent.parent.parent / "config"


def test_snapshot_has_8_layers():
    snap = build_snapshot(PROJECT_ROOT, CONFIG_DIR)
    assert len(snap.layers) == 8
    assert {L.id for L in snap.layers} == {
        "prompt_context",
        "tools_function",
        "orchestration",
        "memory",
        "rag_knowledge",
        "guardrails",
        "eval_observability",
        "cost_routing",
    }


def test_snapshot_total_62():
    snap = build_snapshot(PROJECT_ROOT, CONFIG_DIR)
    assert snap.total == 62
    assert snap.total_lit + snap.total_wip + snap.total_todo == 62


def test_snapshot_lit_anchor_within_range():
    snap = build_snapshot(PROJECT_ROOT, CONFIG_DIR)
    assert 30 <= snap.total_lit <= 40, f"Lit {snap.total_lit} out of expected 35±5"


def test_snapshot_overrides_applied():
    snap = build_snapshot(PROJECT_ROOT, CONFIG_DIR, overrides={"memory.long_term_memory": "wip"})
    mem = next(L for L in snap.layers if L.id == "memory")
    target = next(c for c in mem.capabilities if c.id == "memory.long_term_memory")
    assert target.status == "wip"


def test_snapshot_to_dict_json_roundtrip():
    import json

    snap = build_snapshot(PROJECT_ROOT, CONFIG_DIR)
    d = snap.to_dict()
    s = json.dumps(d)
    assert json.loads(s)["total"] == 62

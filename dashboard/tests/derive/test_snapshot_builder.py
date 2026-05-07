# dashboard/tests/derive/test_snapshot_builder.py
from pathlib import Path

from dashboard.derive.snapshot_builder import build_snapshot

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
CONFIG_DIR = Path(__file__).parent.parent.parent / "config"


def test_snapshot_has_8_layers() -> None:
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


def test_snapshot_total_62() -> None:
    snap = build_snapshot(PROJECT_ROOT, CONFIG_DIR)
    assert snap.total == 62
    assert snap.total_lit + snap.total_wip + snap.total_todo == 62


def test_snapshot_lit_anchor_within_range() -> None:
    snap = build_snapshot(PROJECT_ROOT, CONFIG_DIR)
    assert 30 <= snap.total_lit <= 40, f"Lit {snap.total_lit} out of expected 35±5"


def test_snapshot_overrides_applied() -> None:
    snap = build_snapshot(PROJECT_ROOT, CONFIG_DIR, overrides={"memory.long_term_memory": "wip"})
    mem = next(L for L in snap.layers if L.id == "memory")
    target = next(c for c in mem.capabilities if c.id == "memory.long_term_memory")
    assert target.status == "wip"


def test_snapshot_to_dict_json_roundtrip() -> None:
    import json

    snap = build_snapshot(PROJECT_ROOT, CONFIG_DIR)
    d = snap.to_dict()
    s = json.dumps(d)
    assert json.loads(s)["total"] == 62


def test_snapshot_to_dict_satisfies_typed_dict() -> None:
    """to_dict 返回的字段必须满足 SnapshotDict 契约(verify 运行时形状)。"""
    from dashboard.derive.types import SnapshotDict

    snap = build_snapshot(PROJECT_ROOT, CONFIG_DIR)
    d: SnapshotDict = snap.to_dict()
    # 顶层字段
    assert set(d.keys()) >= {
        "refreshed_at",
        "layers",
        "total_lit",
        "total_wip",
        "total_todo",
        "total",
    }
    # 第一层 layer 字段
    L0 = d["layers"][0]
    assert set(L0.keys()) >= {
        "id",
        "number",
        "name_cn",
        "name_en",
        "lit",
        "wip",
        "todo",
        "total",
        "capabilities",
    }
    # 第一个 capability 字段(若存在)
    if L0["capabilities"]:
        c0 = L0["capabilities"][0]
        assert set(c0.keys()) >= {
            "id",
            "dimension",
            "name_cn",
            "name_en",
            "status",
            "derived_status",
        }

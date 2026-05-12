"""V3 cytoscape 节点/边 payload 构造。spec § 5.3。"""

from __future__ import annotations

from typing import Any

from dashboard.derive.deep_card_types import DeepCard
from dashboard.derive.types import Capability


def build_graph_payload(
    capabilities: list[Capability],
    deep_cards: list[DeepCard],
    *,
    filter_dimensions: set[str] | None = None,
    filter_statuses: set[str] | None = None,
    only_low_confidence: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    """构造 cytoscape JSON elements:{nodes: [...], edges: [...]}.

    spec § 5.3:
    - 节点 colour = dimension(前端 CSS)
    - 节点 size = code_anchors 数 + 1
    - 节点 border color = confidence(前端 CSS)
    - 边 = linked_capabilities,无向 dedupe + self-loop 去除
    """
    cards_by_id = {c.cap_id: c for c in deep_cards}

    # filter caps
    visible_caps: list[Capability] = []
    for cap in capabilities:
        if filter_dimensions and cap.dimension not in filter_dimensions:
            continue
        if filter_statuses and cap.status not in filter_statuses:
            continue
        if only_low_confidence:
            dc = cards_by_id.get(cap.id)
            if dc and dc.srs_state.confidence >= 3:
                continue
        visible_caps.append(cap)

    visible_ids = {c.id for c in visible_caps}

    nodes: list[dict[str, Any]] = []
    for cap in visible_caps:
        dc = cards_by_id.get(cap.id)
        size = (len(dc.code_anchors) + 1) if dc else 1
        confidence = dc.srs_state.confidence if dc else 0
        nodes.append(
            {
                "data": {
                    "id": cap.id,
                    "label": cap.name_cn,
                    "dimension": cap.dimension,
                    "status": cap.status,
                    "confidence": confidence,
                    "size": size,
                    "has_deep_card": dc is not None,
                }
            }
        )

    # edges — 无向 dedupe + self-loop 去
    edge_pairs: set[tuple[str, str]] = set()
    for dc in deep_cards:
        if dc.cap_id not in visible_ids:
            continue
        for other in dc.linked_capabilities:
            if other == dc.cap_id:  # self-loop
                continue
            if other not in visible_ids:
                continue
            pair = (
                (dc.cap_id, other) if dc.cap_id <= other else (other, dc.cap_id)
            )
            edge_pairs.add(pair)
    edges: list[dict[str, Any]] = [
        {"data": {"source": s, "target": t, "id": f"{s}__{t}"}}
        for s, t in sorted(edge_pairs)
    ]

    return {"nodes": nodes, "edges": edges}
